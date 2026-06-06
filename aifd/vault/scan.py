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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

# Per-line clip in scan_file. Lines longer than this are truncated to
# bound scan cost on pasted-file-in-one-line edge cases. Surfaced as a
# constant so the web renderer can warn "(line truncated)" when a match
# falls near the boundary.
_LINE_TRUNCATE = 16384

# Window of characters captured before / after the match in web mode.
# Wide enough to read a sentence around the leak; narrow enough that 1369
# findings * 2 windows * 200B ≈ 550KB stays cheap in memory.
_WEB_CONTEXT_WINDOW = 200


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
    path: Path, min_confidence: int = 1, capture_context: bool = False
) -> Iterable[SensitiveMatch]:
    """Yield SensitiveMatch rows for one jsonl file (or any text file).

    Reads line-by-line so we can attribute matches to a line number for
    later `aifd vault redact` lookup. Lines > `_LINE_TRUNCATE` (16 KiB)
    are clipped to bound scan cost on pasted-file-in-one-line edge cases;
    when `capture_context=True` and the line was clipped, every match
    from that line carries `line_truncated=True` so the web UI can warn.

    `min_confidence` is propagated to `_scan_line` so the entropy layer
    (which produces confidence 4-6 only) is skipped entirely when the
    caller will throw away anything below 7. This is the dominant
    perf win for the default `aifd vault scan` command (~16x faster).

    `capture_context=True` populates `context_before` / `match_full` /
    `context_after` / `raw_line` on each match. Off by default to
    preserve the "never persist secret" invariant for all non-web
    callers (table renderer, --json, library users).
    """
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return

    try:
        with f:
            for line_no, raw in enumerate(f, start=1):
                truncated = len(raw) > _LINE_TRUNCATE
                if truncated:
                    raw = raw[:_LINE_TRUNCATE]
                yield from _scan_line(
                    path, line_no, raw, min_confidence,
                    capture_context=capture_context,
                    line_truncated=truncated,
                )
    except OSError as exc:
        logger.warning("IO error reading %s: %s", path, exc)


def _scan_line(
    path: Path,
    line_no: int,
    line: str,
    min_confidence: int,
    *,
    capture_context: bool = False,
    line_truncated: bool = False,
) -> Iterable[SensitiveMatch]:
    """Detector pipeline for a single jsonl line.

    SEMI-PUBLIC API — called by:
      - aifd.vault.scan.scan_file (CLI `aifd vault scan`)
      - aifd.vault.watch.Daemon._scan_one (CLI `aifd vault watch daemon`,
        which then upserts into the v0.7 events DB and fans out webhook
        deliveries)
      - (planned) aifd MCP server

    The signature is part of our internal contract: any change here breaks
    the watch daemon's hot path and the events store ingestion. Stability
    over years > prettier API.
    """
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
                # For detectors with a capture group (bearer_token), the
                # secret is group(1) while the highlight span should
                # cover the full match (e.g. "Bearer sk-…"). For others
                # the secret IS the full match.
                if m.lastindex:
                    full = m.group(1)
                    span_start, span_end = m.span(1)
                else:
                    full = m.group(0)
                    span_start, span_end = m.span(0)
                if _is_suppressed(full, line, span_start, span_end):
                    continue
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
                    **_context_kwargs(
                        line, span_start, span_end, capture_context,
                        line_truncated,
                    ),
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
        span_start, span_end = m.span(0)
        if _is_suppressed(s, line, span_start, span_end):
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
            **_context_kwargs(
                line, span_start, span_end, capture_context, line_truncated,
            ),
        )


# ----- False-positive suppression -----
#
# Detectors are intentionally greedy (regex covers many fence cases, entropy
# floor catches unknowns). A small post-match suppression layer rejects
# matches that look right structurally but obviously come from code rather
# than real PII. Each rule has a name + reason for `aifd vault scan -vv`
# debug logging so users can verify a suppression was intentional.
#
# Add rules sparingly. False suppression silently drops real findings, which
# is worse than the FP noise it's solving. Quote the FP class you saw +
# rough frequency in the rule docstring.


@dataclass(frozen=True)
class _Suppressor:
    """One false-positive filter applied after a detector match.

    `check(match_full, line, span_start, span_end)` returns True to discard
    the match. Suppressors run in order and short-circuit on the first hit.
    """
    name: str
    reason: str
    check: Callable[[str, str, int, int], bool]


def _is_escape_prefix(
    match_full: str, line: str, span_start: int, span_end: int
) -> bool:
    """True when the match starts immediately after a literal backslash.

    The jsonl bytes the scanner reads are JSON-encoded: a newline inside
    a string is the two-char sequence `\\` + `n`. The email regex's `\\b`
    word boundary fires between `\\` (non-word) and `n` (word), letting
    patterns like `\\n@click.group` get caught as `n@click.group` (local
    `n`, domain `click`, TLD `group`). Same story for `\\n@router.post`,
    `\\n@pytest.fixture`, `\\t@nb.njit` and friends.

    Measured on a 50-file jsonl sample: 80.8% of email matches are this
    class. Real emails (preceded by whitespace, quote, or text) are not
    affected.
    """
    return span_start > 0 and line[span_start - 1] == "\\"


# RFC 2606 §3 — second-level domains reserved for examples and docs.
# Per spec, "the labels EXAMPLE.COM, EXAMPLE.ORG, and EXAMPLE.NET (and
# the labels that compose them) are reserved" — so subdomains like
# api.example.com and mail.example.org are also fake by definition.
_RFC2606_RESERVED_SLDS: frozenset[str] = frozenset({
    "example.com",
    "example.org",
    "example.net",
})

# RFC 2606 §2 — top-level domains reserved for testing and special-use.
# Any email whose domain ends with one of these is by definition a
# fake / synthetic address. The leading `.` is part of the suffix so
# `attest.com` doesn't get matched by `.test`.
_RFC2606_RESERVED_TLDS: tuple[str, ...] = (
    ".test",
    ".example",
    ".invalid",
    ".localhost",
)

# Precomputed suffix tuple for the `str.endswith` fast path.
# - `.example.com` / `.example.org` / `.example.net` catch subdomains of
#   the RFC 2606 §3 SLDs (`api.example.com`, `mail.example.org`, etc).
# - `.test` / `.example` / `.invalid` / `.localhost` are RFC 2606 §2 TLDs.
# The SLD-itself case (domain == "example.com" exactly) is handled by
# the `in _RFC2606_RESERVED_SLDS` check before falling through to this.
_RFC2606_RESERVED_SUFFIXES: tuple[str, ...] = tuple(
    f".{sld}" for sld in _RFC2606_RESERVED_SLDS
) + _RFC2606_RESERVED_TLDS

# Sender-only mailbox convention. RFC doesn't define this but every MTA
# treats these as send-only, never-accepts-mail addresses. They are not
# real PII for any individual — they're hardcoded service identities.
_NOREPLY_LOCAL_PARTS: frozenset[str] = frozenset({
    "noreply",
    "no-reply",
    "do-not-reply",
    "donotreply",
})

# Common documentation / UI placeholder domains. Not IANA-reserved like
# RFC 2606 — most of these are genuinely registered domains with real
# owners — but they're conventionally used as "replace with your own"
# placeholders in tutorials, error messages, and form mockups. The PII
# risk of suppressing them is the rare user who actually uses an
# `email.com` mailbox; conservative judgement says doc-placeholders
# outnumber that by orders of magnitude.
_PLACEHOLDER_EMAIL_DOMAINS: frozenset[str] = frozenset({
    "domain.com",       # literal "domain" — the canonical placeholder noun
    "email.com",        # literal "email" — common in form-field mockups
    "yourdomain.com",   # `your` + domain — explicit "fill in your own"
    "yoursite.com",     # `your` + site
    "mysite.com",       # `my` + site
})


def _is_reserved_email_domain(
    match_full: str, line: str, span_start: int, span_end: int
) -> bool:
    """RFC 2606 reserved domains and their subdomains (never real PII).

    §3 SLDs: example.com / example.org / example.net AND any subdomain
    (api.example.com, mail.example.org, www.example.net, …) since RFC
    2606 §3 reserves "the labels that compose them" too.
    §2 TLDs: .test / .example / .invalid / .localhost.
    Case-insensitive per DNS spec (RFC 1035 §2.3.3).

    Measured: 5.1% of remaining email matches on real data (and rising
    once subdomains like @api.example.com count, which earlier did not).
    """
    at = match_full.rfind("@")
    if at < 0:
        return False
    domain = match_full[at + 1:].lower()
    if domain in _RFC2606_RESERVED_SLDS:
        return True
    return domain.endswith(_RFC2606_RESERVED_SUFFIXES)


def _is_noreply_local_part(
    match_full: str, line: str, span_start: int, span_end: int
) -> bool:
    """Sender-only mailbox convention (`noreply@*` family).

    Variants: noreply, no-reply, do-not-reply, donotreply.
    Case-insensitive (most MTAs normalize local parts even though RFC
    5321 §4.1.2 makes them technically case-sensitive).

    Measured: 9.3% of remaining email matches on real data.
    """
    at = match_full.find("@")
    if at < 0:
        return False
    return match_full[:at].lower() in _NOREPLY_LOCAL_PARTS


def _is_placeholder_email_domain(
    match_full: str, line: str, span_start: int, span_end: int
) -> bool:
    """Common documentation / UI placeholder domains.

    Unlike `_is_reserved_email_domain` (which checks IANA-canonical
    RFC 2606 reservations), these domains are conventionally used as
    placeholders in tutorials and form mockups. They are technically
    registered with real owners, so there is a small nonzero risk of
    suppressing a real user's mailbox. Conservative judgement: doc
    placeholders dominate real `name@email.com` mail orders of
    magnitude in real-world history data.

    No subdomain match here (unlike RFC 2606): `api.domain.com` is
    likely a real internal service, not a placeholder.
    """
    at = match_full.rfind("@")
    if at < 0:
        return False
    return match_full[at + 1:].lower() in _PLACEHOLDER_EMAIL_DOMAINS


_SUPPRESSORS: tuple[_Suppressor, ...] = (
    _Suppressor(
        name="escape_prefix",
        reason="match starts after backslash; likely jsonl-escaped \\n + code decorator",
        check=_is_escape_prefix,
    ),
    _Suppressor(
        name="reserved_email_domain",
        reason="RFC 2606 reserved domain (example.com / .test / .invalid / etc); never real PII",
        check=_is_reserved_email_domain,
    ),
    _Suppressor(
        name="noreply_local_part",
        reason="noreply / no-reply / do-not-reply local part; sender-only mailbox convention",
        check=_is_noreply_local_part,
    ),
    _Suppressor(
        name="placeholder_email_domain",
        reason="common doc/UI placeholder domain (domain.com / email.com / yourdomain.com / etc)",
        check=_is_placeholder_email_domain,
    ),
)


def _is_suppressed(
    match_full: str, line: str, span_start: int, span_end: int
) -> bool:
    """Return True if any suppressor wants to drop this match.

    Suppressed matches never reach SensitiveMatch construction, so they
    are absent from --table, --json, and the --web HTML view alike.
    Run `aifd vault scan -vv` to see the suppressor name and reason on
    each drop.
    """
    for s in _SUPPRESSORS:
        if s.check(match_full, line, span_start, span_end):
            logger.debug(
                "scan suppressed [%s] at offset %d: %r (%s)",
                s.name, span_start, match_full, s.reason,
            )
            return True
    return False


def _context_kwargs(
    line: str,
    span_start: int,
    span_end: int,
    capture_context: bool,
    line_truncated: bool,
) -> dict[str, Any]:
    """Build the optional context fields for SensitiveMatch.

    Returns empty when `capture_context=False` so callers preserve the
    "redacted-only" invariant. When True, slices a ±_WEB_CONTEXT_WINDOW
    char window around the match plus the full raw line.

    Heterogeneous value types (str/bool) preclude a stricter dict
    annotation; the caller unpacks straight into the SensitiveMatch
    dataclass keyword args, which carry the precise per-field types.
    """
    if not capture_context:
        return {}
    return {
        "context_before": line[max(0, span_start - _WEB_CONTEXT_WINDOW):span_start],
        "match_full": line[span_start:span_end],
        "context_after": line[span_end:span_end + _WEB_CONTEXT_WINDOW],
        "raw_line": line,
        "line_truncated": line_truncated,
    }


def scan_paths(
    roots: Iterable[Path],
    min_confidence: int = 1,
    capture_context: bool = False,
) -> Iterable[SensitiveMatch]:
    """Walk the given roots looking for `*.jsonl` files.

    `min_confidence` is propagated to `scan_file` -> `_scan_line` so
    the expensive entropy layer can be short-circuited when the caller
    won't accept matches below 7.

    `capture_context=True` enables the --web mode payload (raw secret +
    surrounding text) on every emitted match. Default False keeps the
    invariant: only the redacted snippet lives on the dataclass.
    """
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            yield from scan_file(root, min_confidence, capture_context)
            continue
        try:
            for path in sorted(root.rglob("*.jsonl")):
                yield from scan_file(path, min_confidence, capture_context)
        except OSError as exc:
            logger.warning("Cannot walk %s: %s", root, exc)
