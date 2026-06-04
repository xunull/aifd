"""Tests for aifd.vault.scan (PII / secret detector)."""

from __future__ import annotations

from pathlib import Path

from aifd.vault.scan import (
    redact,
    scan_file,
    scan_paths,
    shannon_entropy,
)


def _write(p: Path, content: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ---------- helper functions ----------


def test_redact_short_string_shows_only_ellipses() -> None:
    # All ellipses, length-preserving, never leaks the original chars
    assert redact("abc") == "…" * 3
    assert redact("hi") == "…" * 2
    assert "abc" not in redact("abc")


def test_redact_long_string_shows_head_and_tail() -> None:
    r = redact("sk-proj-abc1234567890xyz")
    assert r.startswith("sk-p")
    assert r.endswith("0xyz")
    assert "REDACTED" in r


def test_shannon_entropy_uniform_high() -> None:
    # 26-char alphabet, each unique → max entropy
    assert shannon_entropy("abcdefghijklmnopqrstuvwxyz") > 4.5


def test_shannon_entropy_repeated_low() -> None:
    assert shannon_entropy("aaaaaaaaaa") == 0.0


# ---------- regex detectors ----------


def test_scan_finds_openai_key(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        'leaked: sk-proj-abc1234567890abcdef1234567890\n',
    )
    matches = list(scan_file(f))
    assert any(m.category == "openai_key" for m in matches)
    found = next(m for m in matches if m.category == "openai_key")
    assert found.confidence == 10
    # Snippet must not contain the full secret
    assert "abc1234567890abcdef" not in found.snippet_redacted
    assert "sk-p" in found.snippet_redacted


def test_scan_finds_anthropic_key(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        'oops: sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaa\n',
    )
    matches = list(scan_file(f))
    assert any(m.category == "anthropic_key" for m in matches)


def test_scan_finds_github_pat(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        "token=ghp_abcdef0123456789abcdef0123456789xyz\n",
    )
    cats = {m.category for m in scan_file(f)}
    assert "github_pat" in cats


def test_scan_finds_aws_access_key(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        "AWS_KEY = AKIAIOSFODNN7EXAMPLE\n",
    )
    cats = {m.category for m in scan_file(f)}
    assert "aws_access_key" in cats


def test_scan_finds_jwt(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        "auth: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3"
        "ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n",
    )
    cats = {m.category for m in scan_file(f)}
    assert "jwt" in cats


def test_scan_finds_email(tmp_path: Path) -> None:
    f = _write(tmp_path / "a.jsonl", 'user="quincy@example.com"\n')
    cats = {m.category for m in scan_file(f)}
    assert "email" in cats


# ---------- entropy + dedup ----------


def test_scan_high_entropy_low_confidence(tmp_path: Path) -> None:
    """40+ char random-looking base64 hits the entropy detector."""
    blob = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890"
    f = _write(tmp_path / "a.jsonl", f"data: {blob}\n")
    matches = [m for m in scan_file(f) if m.category == "high_entropy"]
    assert matches
    assert matches[0].confidence < 7  # always below the default cutoff


def test_scan_skips_sha256_hash(tmp_path: Path) -> None:
    """Known hash format (64 hex chars) is suppressed to reduce noise."""
    sha = "a" * 64  # not really random but matches the suppress regex
    f = _write(tmp_path / "a.jsonl", f"sha={sha}\n")
    matches = [m for m in scan_file(f) if m.category == "high_entropy"]
    assert not matches


def test_scan_dedupes_within_a_line(tmp_path: Path) -> None:
    """Same secret repeated on one line yields one match, not three."""
    secret = "sk-proj-abc1234567890abcdef1234567890"
    f = _write(tmp_path / "a.jsonl", f"{secret} {secret} {secret}\n")
    matches = [m for m in scan_file(f) if m.category == "openai_key"]
    assert len(matches) == 1


def test_scan_line_numbers_are_1_indexed(tmp_path: Path) -> None:
    f = _write(
        tmp_path / "a.jsonl",
        "no secret\n"  # line 1
        "no secret\n"  # line 2
        "sk-proj-abcdef0123456789abcdef0123456789\n",  # line 3
    )
    matches = list(scan_file(f))
    assert matches[0].line == 3


# ---------- scan_paths walker ----------


def test_scan_paths_walks_directory(tmp_path: Path) -> None:
    _write(tmp_path / "sub" / "a.jsonl", "sk-proj-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
    _write(tmp_path / "sub" / "b.jsonl", "ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n")
    matches = list(scan_paths([tmp_path]))
    cats = {m.category for m in matches}
    assert cats == {"openai_key", "github_pat"}


def test_scan_paths_handles_nonexistent_root(tmp_path: Path) -> None:
    """Missing root is a silent skip, not an exception."""
    matches = list(scan_paths([tmp_path / "does-not-exist"]))
    assert matches == []


def test_scan_paths_handles_file_root(tmp_path: Path) -> None:
    f = _write(tmp_path / "single.jsonl", "sk-proj-cccccccccccccccccccccccccccccc\n")
    matches = list(scan_paths([f]))
    assert len(matches) == 1
    assert matches[0].category == "openai_key"


# ---------------------------------------------------------------------------
# Performance optimizations (v0.4.1): min_confidence pruning + unique-chars
# entropy short-circuit
# ---------------------------------------------------------------------------


def test_min_confidence_skips_entropy_layer(tmp_path: Path) -> None:
    """min_confidence > 6 means the entropy layer (confidence 4-6) is dead
    weight — verify it's actually skipped and yields nothing."""
    # High-entropy 50-char base64-looking string, would match the entropy
    # detector at confidence 5 if it were running.
    blob = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890"
    f = _write(tmp_path / "a.jsonl", f"data: {blob}\n")

    # Default-ish caller (min_confidence=7) — entropy layer dead.
    matches = list(scan_paths([f], min_confidence=7))
    assert matches == []

    # Lowered threshold — entropy layer alive, sees the blob.
    matches = list(scan_paths([f], min_confidence=4))
    assert any(m.category == "high_entropy" for m in matches)


def test_min_confidence_filters_regex_layer_too(tmp_path: Path) -> None:
    """A detector emitting confidence 7 (email) is filtered when caller
    requests min_confidence 9."""
    f = _write(
        tmp_path / "a.jsonl",
        "user=quincy@example.com leak=sk-proj-abc1234567890abcdef1234567890\n",
    )

    # Only confidence >= 9: email (7) gone, openai_key (10) kept.
    matches = list(scan_paths([f], min_confidence=9))
    cats = {m.category for m in matches}
    assert "email" not in cats
    assert "openai_key" in cats


def test_min_confidence_default_keeps_legacy_behavior(tmp_path: Path) -> None:
    """min_confidence defaults to 1 (everything) when caller omits it —
    backward compatible with v0.4.0 call sites."""
    blob = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890"
    f = _write(
        tmp_path / "a.jsonl",
        f"blob: {blob}\nleak: sk-proj-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
    )
    matches = list(scan_paths([f]))  # no min_confidence arg
    cats = {m.category for m in matches}
    # Should see BOTH the entropy hit AND the openai_key
    assert "high_entropy" in cats
    assert "openai_key" in cats


def test_entropy_unique_chars_prune_skips_low_diversity(
    tmp_path: Path,
) -> None:
    """A 60-char string with only 16 unique chars (hex-like) has max
    entropy log2(16) = 4.0 < 4.5 threshold — must be pruned by the
    unique-chars short-circuit before shannon_entropy runs."""
    # All hex chars, 60 long — passes the entropy regex but max possible
    # entropy is log2(16) = 4.0, can never hit the 4.5 threshold.
    hex60 = "0123456789abcdef" * 4  # 64 chars, 16 unique
    # Use 65 to avoid the sha256/64-hex skip pattern
    target = hex60 + "0"
    f = _write(tmp_path / "a.jsonl", f"hex={target}\n")
    matches = list(scan_paths([f], min_confidence=4))
    # Must NOT report — too few unique chars
    assert all(m.category != "high_entropy" for m in matches)


def test_entropy_unique_chars_prune_allows_high_diversity(
    tmp_path: Path,
) -> None:
    """A diverse-character 60-char base64 string passes the prune and
    gets the real entropy check."""
    # 60 chars across many unique values, ent should be > 4.5
    blob = "QWxsWW91ckJhc2VBcmVCZWxvbmdUb1VzMTIzNDU2Nzg5MDEyMzQ1Njc4OTA="
    f = _write(tmp_path / "a.jsonl", f"blob={blob}\n")
    matches = list(scan_paths([f], min_confidence=4))
    assert any(m.category == "high_entropy" for m in matches)


def test_scan_file_signature_backward_compatible(tmp_path: Path) -> None:
    """Tests that exist from v0.4.0 calling `scan_file(path)` keep
    working (no min_confidence arg)."""
    from aifd.vault.scan import scan_file
    f = _write(tmp_path / "a.jsonl", "sk-proj-cccccccccccccccccccccccccccccc\n")
    matches = list(scan_file(f))  # no min_confidence
    assert len(matches) == 1


# ---------------------------------------------------------------------------
# OPT-3: line-level prefix prefilter
# ---------------------------------------------------------------------------


def test_quick_prefix_covers_all_regex_detectors() -> None:
    """Meta test: every regex detector's typical match MUST also trip the
    substring prefilter. Otherwise the prefilter would silently skip
    lines that contain real secrets.

    This guards against DRY drift: when a future contributor adds a new
    detector to _DETECTORS but forgets to add its anchor to
    `_QUICK_PREFIX_LITERALS`, the new detector becomes effectively dead
    code for any line where it's the only category present.
    """
    from aifd.vault.scan import _DETECTORS, _has_vendor_anchor

    # One representative example per detector category. If you add a
    # detector to _DETECTORS, add a sample here.
    samples: dict[str, str] = {
        "anthropic_key": "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "openai_key": "sk-proj-abc1234567890abcdef1234567890",
        "github_pat": "ghp_abcdef0123456789abcdef0123456789xyz",
        "github_fine_grained_pat": "github_pat_" + "a" * 50,
        "github_app_token": "ghs_abcdef0123456789abcdef0123456789",
        "aws_access_key": "AKIAIOSFODNN7EXAMPLE",
        "slack_token": "xoxb-1234567890-abcdef",
        "jwt": (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3"
            "ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        ),
        "bearer_token": "Authorization: Bearer abcdef0123456789abcdef0123",
        "email": "user@example.com",
    }

    # Sanity: samples cover every detector category
    detector_cats = {cat for cat, _, _ in _DETECTORS}
    assert detector_cats == set(samples), (
        f"sample mismatch: missing={detector_cats - samples.keys()}, "
        f"extra={samples.keys() - detector_cats}"
    )

    # Every sample must trip the prefilter
    for cat, sample in samples.items():
        assert _has_vendor_anchor(sample), (
            f"_has_vendor_anchor does NOT match a real {cat} sample: {sample!r}. "
            f"Update _QUICK_PREFIX_LITERALS to include this category's anchor."
        )


def test_prefix_prefilter_skips_innocent_lines(tmp_path: Path) -> None:
    """A jsonl line without any vendor prefix anchor must NOT emit any
    regex-detector matches (the prefilter short-circuits the detector loop)."""
    # Typical jsonl line: pure prose / structural keys, no secrets
    safe_lines = [
        '{"type":"assistant","message":"hello world how are you"}\n',
        '{"role":"user","content":"please summarize this paragraph"}\n',
        '{"sessionId":"abc-123-def","timestamp":"2026-06-04T11:00:00Z"}\n',
    ]
    f = _write(tmp_path / "safe.jsonl", "".join(safe_lines))
    matches = list(scan_paths([f]))
    # No regex matches (entropy might fire on UUID-like strings but those
    # are confidence < 7 — at default the entropy layer is off via the
    # earlier optimization).
    assert all(m.category == "high_entropy" for m in matches), (
        f"Got non-entropy match in safe lines: {[m.category for m in matches]}"
    )


def test_prefix_prefilter_lets_real_secrets_through(tmp_path: Path) -> None:
    """Mixed file: prefilter must NOT block real secrets."""
    f = _write(
        tmp_path / "mixed.jsonl",
        '{"role":"user","content":"hello"}\n'
        '{"role":"user","content":"my key is sk-proj-abc1234567890abcdef1234567890"}\n'
        '{"role":"user","content":"goodbye"}\n',
    )
    matches = [m for m in scan_paths([f]) if m.category == "openai_key"]
    assert len(matches) == 1
    assert "REDACTED" in matches[0].snippet_redacted


def test_prefix_prefilter_does_not_affect_entropy_layer(
    tmp_path: Path,
) -> None:
    """An entropy-only candidate (high-randomness blob, no vendor prefix)
    must still surface when --min-confidence is lowered, because the
    entropy layer runs regardless of prefix match."""
    # 60-char random-looking string, no `sk-`/`ghp_`/etc anchor
    blob = "QWxsWW91ckJhc2VBcmVCZWxvbmdUb1VzMTIzNDU2Nzg5MDEyMzQ1Njc4OTA="
    f = _write(tmp_path / "a.jsonl", f"data: {blob}\n")
    matches = list(scan_paths([f], min_confidence=4))
    assert any(m.category == "high_entropy" for m in matches), (
        "OPT-3 prefilter must NOT affect entropy layer — entropy runs "
        "independent of the vendor-prefix check."
    )
