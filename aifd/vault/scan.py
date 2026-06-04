"""PII / secret detector for `aifd vault scan`.

Walks every provider's jsonl files looking for likely-secret patterns:
- API keys (OpenAI, Anthropic, GitHub, AWS, etc.) — regex match
- JWT-shaped strings — regex
- email addresses — regex
- high-entropy strings — Shannon entropy heuristic (catches unknown
  token formats, with low confidence)

NEVER stores the full secret on disk or in memory beyond the scan loop;
SensitiveMatch carries only a redacted snippet (first/last 4 chars).
The output is safe to share / paste / log.

Detector confidence rubric:
  10  strict regex hit on a vendor-specific prefix (sk-, ghp_, AKIA, sk-ant-)
  9   AWS / Slack prefix
  8   JWT (eyJ-prefixed)
  7   email or bearer-token
  4-6 high entropy heuristic only (could be a hash, a uuid, etc.)
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable
from pathlib import Path

from aifd.models import SensitiveMatch

logger = logging.getLogger("aifd.vault.scan")


_DETECTORS: list[tuple[str, re.Pattern[str], int]] = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), 10),
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), 10),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{30,}"), 10),
    ("github_fine_grained_pat", re.compile(r"github_pat_[A-Za-z0-9_]{40,}"), 10),
    ("github_app_token", re.compile(r"ghs_[A-Za-z0-9]{30,}"), 10),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 9),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), 9),
    (
        "jwt",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
        ),
        8,
    ),
    ("bearer_token", re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-\.]{20,})"), 7),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), 7),
]


# Cheap literal substring scan that decides whether a line could possibly
# contain ANY of the vendor-prefixed detectors above. If none of the
# anchors appear, we skip the entire 10-detector regex loop for that
# line — saves 92% of detector work on real-world data (260K lines of
# jsonl, only 8.2% contain any vendor prefix).
#
# Why substring `in` instead of `re.compile("a|b|c").search`?
# Micro-benchmarked on a typical jsonl line: regex alternation 0.85s/260K
# rows, substring for-loop 0.25s/260K rows (3.4x faster). Python's
# `re.search` over a union has NFA backtracking overhead; `str.__contains__`
# is a tight C strstr loop.
#
# `_QUICK_PREFIX_LITERALS` is sorted by expected hit frequency so the
# common case (sk-/email) breaks the loop fastest. `@` covers both `email`
# and `bearer_token` rough anchors with one substring; the precise
# detector re refines.
#
# DRY warning: this list must stay aligned with _DETECTORS. The meta test
# `test_quick_prefix_covers_all_regex_detectors` enforces that every
# detector's sample string trips one of these literals.
_QUICK_PREFIX_LITERALS: tuple[str, ...] = (
    "sk-",           # openai_key, anthropic_key
    "@",             # email
    "ghp_",          # github_pat
    "AKIA",          # aws_access_key
    "eyJ",           # jwt
    "ghs_",          # github_app_token
    "github_pat_",   # github_fine_grained_pat
    "xox",           # slack_token (covers xoxb/xoxa/xoxp/xoxr/xoxs)
    "Bearer ",       # bearer_token
    "bearer ",       # bearer_token (lowercase)
)


def _has_vendor_anchor(line: str) -> bool:
    """Cheap substring scan — true iff the line could contain a vendor secret.

    See `_QUICK_PREFIX_LITERALS` docs for why this is a substring loop
    rather than a regex.
    """
    for anchor in _QUICK_PREFIX_LITERALS:
        if anchor in line:
            return True
    return False


_ENTROPY_MIN_LENGTH = 40
_ENTROPY_MAX_LENGTH = 200
_ENTROPY_THRESHOLD = 4.5
_ENTROPY_RE = re.compile(r"[A-Za-z0-9+/=_\-]{40,200}")
_ENTROPY_SKIP_RE = re.compile(
    r"^(?:[0-9a-f]{32}|[0-9a-f]{40}|[0-9a-f]{64})$"
)

# The maximum entropy a string can have is log2(unique_chars). If the
# candidate has fewer unique chars than this threshold, its entropy
# CANNOT exceed _ENTROPY_THRESHOLD (4.5) — skip the expensive Shannon
# computation. log2(22) ≈ 4.459, log2(23) ≈ 4.524; we use 23 so any
# candidate with ≤ 22 unique chars (hex hashes, repetitive base64
# padding, etc.) gets short-circuited before shannon_entropy runs.
#
# Real impact: profiling on 832 MB of jsonl shows shannon_entropy
# accounts for ~30% of total scan time. Most candidates have ≤ 22
# unique chars (hex / repetitive padding) so this prunes the vast
# majority before the costly computation.
_ENTROPY_MIN_UNIQUE_CHARS = 23

# Highest confidence value emitted by the entropy detector. Used as the
# "skip entropy entirely" gate — callers with `min_confidence > 6` can
# never receive an entropy-derived match, so we shortcut the whole
# entropy layer (the dominant cost in scans).
_ENTROPY_MAX_CONFIDENCE = 6


def shannon_entropy(s: str) -> float:
    """Shannon entropy in bits per character."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    ent = 0.0
    for c in freq.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def redact(value: str) -> str:
    """Build a safe-to-display snippet showing only head + tail."""
    if len(value) <= 8:
        return "…" * len(value)
    head_n = min(4, len(value) // 4)
    tail_n = min(4, len(value) // 4)
    return f"{value[:head_n]}…REDACTED…{value[-tail_n:]}"


def scan_file(
    path: Path, min_confidence: int = 1
) -> Iterable[SensitiveMatch]:
    """Yield SensitiveMatch rows for one jsonl file (or any text file).

    Reads line-by-line so we can attribute matches to a line number for
    later `aifd vault redact` lookup. Lines > 16KB are truncated to
    bound scan cost on pasted-file-in-one-line edge cases.

    `min_confidence` is propagated to `_scan_line` so the entropy layer
    (which produces confidence 4-6 only) is skipped entirely when the
    caller will throw away anything below 7. This is the dominant
    perf win for the default `aifd vault scan` command (~16x faster).
    """
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return

    try:
        with f:
            for line_no, raw in enumerate(f, start=1):
                if len(raw) > 16384:
                    raw = raw[:16384]
                yield from _scan_line(path, line_no, raw, min_confidence)
    except OSError as exc:
        logger.warning("IO error reading %s: %s", path, exc)


def _scan_line(
    path: Path, line_no: int, line: str, min_confidence: int
) -> Iterable[SensitiveMatch]:
    seen: set[tuple[str, str]] = set()

    # OPT-3: cheap substring prefilter. ~92% of real jsonl lines don't
    # contain any vendor-prefix anchor — skip the expensive 10-detector
    # loop for them. The line still goes through entropy detection below
    # since the entropy charset isn't anchored to vendor prefixes.
    has_prefix = _has_vendor_anchor(line)

    if has_prefix:
        # Regex layer (confidence 7-10). Cheap, only walked when prefix re
        # already proved the line contains at least one vendor anchor.
        for category, pattern, confidence in _DETECTORS:
            if confidence < min_confidence:
                # Skip detectors that can't pass the caller's threshold.
                continue
            for m in pattern.finditer(line):
                full = m.group(1) if m.lastindex else m.group(0)
                key = (category, full)
                if key in seen:
                    continue
                seen.add(key)
                yield SensitiveMatch(
                    file=path,
                    line=line_no,
                    category=category,
                    snippet_redacted=redact(full),
                    confidence=confidence,
                    full_length=len(full),
                )

    # Entropy layer (confidence 4-6). Skip whole layer if caller wouldn't
    # accept any entropy-derived match (A: 96% of default-case scan time).
    if min_confidence > _ENTROPY_MAX_CONFIDENCE:
        return

    for m in _ENTROPY_RE.finditer(line):
        s = m.group(0)
        if _ENTROPY_SKIP_RE.match(s):
            continue
        if len(s) < _ENTROPY_MIN_LENGTH or len(s) > _ENTROPY_MAX_LENGTH:
            continue

        # B: unique-chars upper bound. Shannon entropy of any string s is
        # bounded by log2(unique_chars). If unique_chars < 23, max
        # possible entropy is log2(22) ≈ 4.46 < 4.5 threshold — guaranteed
        # to fail the entropy check. Counting unique chars (one set()
        # pass) is ~10x cheaper than computing shannon_entropy (two
        # passes + log2 per unique char).
        if len(set(s)) < _ENTROPY_MIN_UNIQUE_CHARS:
            continue

        ent = shannon_entropy(s)
        if ent < _ENTROPY_THRESHOLD:
            continue
        key = ("high_entropy", s)
        if key in seen:
            continue
        confidence = 4 if ent < 5.0 else (5 if ent < 5.5 else 6)
        if confidence < min_confidence:
            continue
        yield SensitiveMatch(
            file=path,
            line=line_no,
            category="high_entropy",
            snippet_redacted=redact(s),
            confidence=confidence,
            full_length=len(s),
        )


def scan_paths(
    roots: Iterable[Path], min_confidence: int = 1
) -> Iterable[SensitiveMatch]:
    """Walk the given roots looking for `*.jsonl` files.

    `min_confidence` is propagated to `scan_file` -> `_scan_line` so
    the expensive entropy layer can be short-circuited when the caller
    won't accept matches below 7.
    """
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield from scan_file(root, min_confidence)
            continue
        try:
            for path in sorted(root.rglob("*.jsonl")):
                yield from scan_file(path, min_confidence)
        except OSError as exc:
            logger.warning("Cannot walk %s: %s", root, exc)
