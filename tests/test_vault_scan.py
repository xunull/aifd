"""Tests for aifd.vault.scan (PII / secret detector)."""

from __future__ import annotations

from pathlib import Path

import pytest

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
    # Real domain (not RFC 2606 reserved) so it isn't suppressed by the
    # reserved_email_domain rule. The point of this test is the regex
    # detector itself, not the suppressor.
    f = _write(tmp_path / "a.jsonl", 'user="quincy@quincy.io"\n')
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


# ---------- web mode context capture ----------


_SAMPLE_GITHUB_PAT = "ghp_abcdef0123456789abcdef0123456789xyz"


def test_capture_context_false_preserves_invariant(tmp_path: Path) -> None:
    """The default API path MUST NOT populate raw-secret fields.

    This is a regression guard for the security invariant declared in
    SensitiveMatch's docstring: only `snippet_redacted` carries any
    part of the secret; the full value never lands on the dataclass.
    """
    f = _write(
        tmp_path / "a.jsonl",
        f"leaked {_SAMPLE_GITHUB_PAT} here\n",
    )
    matches = list(scan_paths([f], min_confidence=7))
    assert len(matches) == 1, [m.category for m in matches]
    m = matches[0]
    assert m.match_full is None, (
        "Default scan path leaked the raw secret onto the dataclass. "
        "match_full MUST stay None unless capture_context=True."
    )
    assert m.context_before is None
    assert m.context_after is None
    assert m.raw_line is None
    assert m.line_truncated is None
    # Redacted snippet is still safe to share.
    assert "REDACTED" in m.snippet_redacted


def test_capture_context_true_populates_match_full(tmp_path: Path) -> None:
    """Web mode must capture the raw secret, surrounding text, and raw line."""
    secret = _SAMPLE_GITHUB_PAT
    line = f"prefix text before {secret} and trailing text after"
    f = _write(tmp_path / "a.jsonl", line + "\n")
    matches = list(scan_paths(
        [f], min_confidence=7, capture_context=True,
    ))
    assert len(matches) == 1, [m.category for m in matches]
    m = matches[0]
    assert m.match_full == secret
    assert m.context_before is not None and m.context_before.endswith(
        "prefix text before "
    )
    assert m.context_after is not None and m.context_after.startswith(
        " and trailing text after"
    )
    assert m.raw_line is not None
    assert secret in m.raw_line
    assert m.line_truncated is False


def test_capture_context_entropy_layer_populates_too(tmp_path: Path) -> None:
    """Entropy-only matches also need context fields for the web view."""
    blob = "QWxsWW91ckJhc2VBcmVCZWxvbmdUb1VzMTIzNDU2Nzg5MDEyMzQ1Njc4OTA="
    f = _write(tmp_path / "a.jsonl", f"random: {blob} more\n")
    matches = list(scan_paths(
        [f], min_confidence=4, capture_context=True,
    ))
    entropy_matches = [m for m in matches if m.category == "high_entropy"]
    assert entropy_matches, "expected a high_entropy match"
    m = entropy_matches[0]
    assert m.match_full == blob
    assert m.context_before is not None
    assert m.context_after is not None
    assert m.raw_line is not None


def test_capture_context_line_truncated_flagged(tmp_path: Path) -> None:
    """When scan_file clips a 16 KiB+ line, matches must carry the flag."""
    # Secret sits BEFORE the clip point so it's still matched; the rest
    # of the line is padding to push us over the 16 KiB cap.
    early_secret_line = _SAMPLE_GITHUB_PAT + " " + ("x" * 20000) + "\n"
    f = _write(tmp_path / "b.jsonl", early_secret_line)
    matches = list(scan_paths(
        [f], min_confidence=7, capture_context=True,
    ))
    assert matches, "scan should still emit the leading match"
    assert all(m.line_truncated is True for m in matches), (
        "Every match from a 16 KiB+ source line MUST carry "
        "line_truncated=True so the web UI can warn."
    )


# ---------- false-positive suppression ----------


def test_suppressor_escape_prefix_unit() -> None:
    """Direct unit test on the _is_escape_prefix predicate."""
    from aifd.vault.scan import _is_escape_prefix

    # span_start > 0, prev char is backslash → suppress
    assert _is_escape_prefix("n@x.tld", "abc\\n@x.tld", 4, 11) is True
    # prev char is space, NOT backslash → keep
    assert _is_escape_prefix("a@x.tld", "abc a@x.tld", 4, 11) is False
    # span_start == 0 (no prev char) → keep
    assert _is_escape_prefix("a@x.tld", "a@x.tld", 0, 7) is False
    # Real email after sentence → keep
    line = "contact me at alice@example.com please"
    assert _is_escape_prefix("alice@example.com", line, 14, 31) is False


def test_scan_suppresses_python_decorator_fp(tmp_path: Path) -> None:
    """The cited FP class — Python decorators after escaped newline — must NOT
    surface as email findings.

    These are real samples measured at 80.8% of email matches on production
    jsonl data: `n@click.group`, `t@router.post`, `n@pytest.fixture` etc.
    """
    # Use the literal two-char `\n` sequence the scanner sees in jsonl,
    # NOT a Python newline.
    line = (
        r'{"content":"def main():\n@click.group()\ndef cli():\n'
        r'    @pytest.fixture\n    def fix():\n'
        r'\n@router.post(\"/x\")\nasync def post():"}'
    ) + "\n"
    f = _write(tmp_path / "decorators.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert email_matches == [], (
        f"Python decorator pattern should not produce email findings; "
        f"got: {[m.snippet_redacted for m in email_matches]}"
    )


def test_scan_retains_real_email_at_word_boundary(tmp_path: Path) -> None:
    """REGRESSION GUARD — real emails preceded by whitespace/text must
    still surface after the escape_prefix suppressor lands. If this
    breaks, the suppressor is too aggressive on the leading boundary."""
    # Use real (non-RFC-2606) domains so the reserved_email_domain rule
    # doesn't interfere with this test's intent.
    line = (
        r'{"content":"contact alice@personal.io or visit '
        r'git@github.com:user/repo for details"}'
    ) + "\n"
    f = _write(tmp_path / "real_emails.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    # alice@personal.io + git@github.com → 2 matches
    full_lengths = sorted(m.full_length for m in email_matches)
    assert len(email_matches) == 2, (
        f"Expected 2 real email matches; got {len(email_matches)}: "
        f"{[m.snippet_redacted for m in email_matches]}"
    )
    # Sanity: alice@personal.io is 17 chars, git@github.com is 14 chars
    assert full_lengths == [14, 17]


def test_scan_suppresses_unicode_escape_prefix(tmp_path: Path) -> None:
    """A `\\X` prefix from ANY escape family suppresses, not just `\\n`.

    The suppressor only checks `line[start-1] == '\\\\'`, so `\\n`,
    `\\t`, `\\u006e`, `\\x6e` all trigger. Acceptable: jsonl rarely
    encodes email local parts via these escapes, so the false-negative
    risk is tiny.

    Python source-level `\\u006e` is decoded to `n` by the parser before
    raw-string semantics apply, so the literal backslash must be built
    via chr(92) to land on disk verbatim.
    """
    backslash = chr(92)
    line = (
        '{"content":"prefix ' + backslash
        + 'u006e@whatever.tld more"}\n'
    )
    f = _write(tmp_path / "uesc.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert email_matches == [], (
        f"backslash-prefixed unicode escape should also be suppressed; "
        f"got: {[m.snippet_redacted for m in email_matches]}"
    )


def test_suppressor_reserved_email_domain_unit() -> None:
    """Unit test for RFC 2606 domain predicate.

    Covers §3 SLDs (the SLDs themselves and any subdomain — per spec,
    `the labels that compose them` are also reserved) and §2 TLDs.
    """
    from aifd.vault.scan import _is_reserved_email_domain

    # RFC 2606 §3 SLDs — bare SLD case
    assert _is_reserved_email_domain("alice@example.com", "", 0, 0) is True
    assert _is_reserved_email_domain("bob@example.org", "", 0, 0) is True
    assert _is_reserved_email_domain("c@example.net", "", 0, 0) is True
    # RFC 2606 §3 SLDs — subdomain case (the part that earlier leaked
    # `foo@api.example.com` through; regression guard)
    assert _is_reserved_email_domain("foo@api.example.com", "", 0, 0) is True
    assert _is_reserved_email_domain("bar@www.example.org", "", 0, 0) is True
    assert _is_reserved_email_domain("baz@mail.example.net", "", 0, 0) is True
    assert _is_reserved_email_domain("deep@a.b.c.example.com", "", 0, 0) is True
    # Case-insensitive (DNS is case-insensitive)
    assert _is_reserved_email_domain("user@EXAMPLE.COM", "", 0, 0) is True
    assert _is_reserved_email_domain("user@API.Example.Com", "", 0, 0) is True
    # RFC 2606 §2 TLDs
    assert _is_reserved_email_domain("test@foo.test", "", 0, 0) is True
    assert _is_reserved_email_domain("docs@bar.example", "", 0, 0) is True
    assert _is_reserved_email_domain("inv@baz.invalid", "", 0, 0) is True
    assert _is_reserved_email_domain("user@x.localhost", "", 0, 0) is True
    # Real domains NOT touched
    assert _is_reserved_email_domain("alice@example.io", "", 0, 0) is False
    assert _is_reserved_email_domain("bob@personal.com", "", 0, 0) is False
    assert _is_reserved_email_domain("git@github.com", "", 0, 0) is False
    # Boundary guards — leading `.` in the suffix prevents prefix collision
    assert _is_reserved_email_domain("x@attest.com", "", 0, 0) is False
    assert _is_reserved_email_domain("y@notexample.com", "", 0, 0) is False
    # No `@` → False (defensive; shouldn't happen for email matches)
    assert _is_reserved_email_domain("not-an-email", "", 0, 0) is False


def test_suppressor_placeholder_email_domain_unit() -> None:
    """Unit test for the doc/UI placeholder-domain predicate.

    Distinct from `_is_reserved_email_domain` in two ways: (1) these
    domains are real registered domains, not IANA-reserved; (2) no
    subdomain match (api.domain.com is a likely real service, not a
    placeholder).
    """
    from aifd.vault.scan import _is_placeholder_email_domain

    # Top 5 placeholder domains
    assert _is_placeholder_email_domain("user@domain.com", "", 0, 0) is True
    assert _is_placeholder_email_domain("your@email.com", "", 0, 0) is True
    assert _is_placeholder_email_domain("name@yourdomain.com", "", 0, 0) is True
    assert _is_placeholder_email_domain("contact@yoursite.com", "", 0, 0) is True
    assert _is_placeholder_email_domain("me@mysite.com", "", 0, 0) is True
    # Case-insensitive
    assert _is_placeholder_email_domain("USER@DOMAIN.COM", "", 0, 0) is True
    assert _is_placeholder_email_domain("Your@Email.Com", "", 0, 0) is True
    # Subdomains NOT suppressed (deliberately conservative)
    assert _is_placeholder_email_domain("user@api.domain.com", "", 0, 0) is False
    assert _is_placeholder_email_domain("alerts@mail.email.com", "", 0, 0) is False
    # Real (non-placeholder) domains untouched
    assert _is_placeholder_email_domain("alice@github.com", "", 0, 0) is False
    assert _is_placeholder_email_domain("bob@163.com", "", 0, 0) is False
    assert _is_placeholder_email_domain("c@personal.io", "", 0, 0) is False
    # No `@` → False
    assert _is_placeholder_email_domain("not-an-email", "", 0, 0) is False


def test_scan_suppresses_placeholder_email_domains(tmp_path: Path) -> None:
    """End-to-end: doc/UI placeholder emails MUST NOT surface as findings."""
    line = (
        '{"content":"Try user@domain.com or your@email.com for setup. '
        'Replace with name@yourdomain.com when going live."}'
    ) + "\n"
    f = _write(tmp_path / "placeholder.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert email_matches == [], (
        f"Doc/UI placeholder emails must be suppressed; "
        f"got: {[m.snippet_redacted for m in email_matches]}"
    )


def test_suppressor_noreply_local_part_unit() -> None:
    """Unit test for noreply local-part predicate (4 variants, case-insensitive)."""
    from aifd.vault.scan import _is_noreply_local_part

    # 4 variants
    assert _is_noreply_local_part("noreply@anthropic.com", "", 0, 0) is True
    assert _is_noreply_local_part("no-reply@github.com", "", 0, 0) is True
    assert _is_noreply_local_part("do-not-reply@x.com", "", 0, 0) is True
    assert _is_noreply_local_part("donotreply@y.com", "", 0, 0) is True
    # Case-insensitive
    assert _is_noreply_local_part("NoReply@anthropic.com", "", 0, 0) is True
    assert _is_noreply_local_part("NO-REPLY@github.com", "", 0, 0) is True
    # Partial matches NOT touched — exact local part lookup
    assert _is_noreply_local_part("noreplybot@x.com", "", 0, 0) is False
    assert _is_noreply_local_part("alice-noreply@x.com", "", 0, 0) is False
    # Real locals
    assert _is_noreply_local_part("alice@anthropic.com", "", 0, 0) is False
    # No `@` → False
    assert _is_noreply_local_part("not-an-email", "", 0, 0) is False


def test_scan_suppresses_rfc2606_reserved_domains(tmp_path: Path) -> None:
    """End-to-end: RFC 2606 reserved domains MUST NOT surface as findings.

    Tests both the SLD list (§3) and the TLD suffix list (§2) and confirms
    they apply regardless of local-part content.
    """
    line = (
        '{"content":"contact alerts@example.com or docs@example.ORG '
        'or admin@foo.test or user@svc.localhost for details"}'
    ) + "\n"
    f = _write(tmp_path / "rfc2606.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert email_matches == [], (
        f"RFC 2606 reserved domains must be suppressed; "
        f"got: {[m.snippet_redacted for m in email_matches]}"
    )


def test_scan_suppresses_noreply_emails(tmp_path: Path) -> None:
    """End-to-end: noreply@<any-domain> MUST NOT surface."""
    line = (
        '{"content":"From noreply@anthropic.com and No-Reply@github.com '
        'and DO-NOT-REPLY@whatever.io and donotreply@svc.cn"}'
    ) + "\n"
    f = _write(tmp_path / "noreply.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert email_matches == [], (
        f"noreply local parts must be suppressed regardless of case; "
        f"got: {[m.snippet_redacted for m in email_matches]}"
    )


def test_scan_retains_real_pii_after_new_filters(tmp_path: Path) -> None:
    """REGRESSION GUARD — real personal emails must still surface after
    RFC 2606 + noreply suppressors land.

    Confirms the suppressors are scoped tightly:
    - alice@anthropic.com (anthropic.com is NOT in RFC 2606)
    - xunull@163.com (real domain, real-looking local)
    - bob@personal-domain.io (real domain with hyphen)
    """
    line = (
        '{"content":"alice@anthropic.com and xunull@163.com '
        'and bob@personal-domain.io"}'
    ) + "\n"
    f = _write(tmp_path / "real.jsonl", line)
    matches = list(scan_paths([f], min_confidence=7))
    email_matches = [m for m in matches if m.category == "email"]
    assert len(email_matches) == 3, (
        f"Expected 3 real-PII emails to survive; "
        f"got {len(email_matches)}: "
        f"{[m.snippet_redacted for m in email_matches]}"
    )


def test_suppression_logged_at_debug(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`aifd vault scan -vv` (DEBUG) must surface the suppressor name +
    reason so users can verify the filter is doing what they expect.

    The CLI's `configure_logging` (aifd/cli/_logging.py) sets
    `aifd.propagate = False` to keep CLI output isolated. Earlier test
    cases that exercise the CLI flip this flag at module level and it
    persists across tests, so caplog (attached to root) sees nothing
    unless we restore propagation for the duration of this test.
    """
    import logging
    aifd_logger = logging.getLogger("aifd")
    original_propagate = aifd_logger.propagate
    aifd_logger.propagate = True
    try:
        caplog.set_level(logging.DEBUG, logger="aifd.vault.scan")
        line = r'{"x":"\n@router.post(\"/y\")"}' + "\n"
        f = _write(tmp_path / "log.jsonl", line)
        list(scan_paths([f], min_confidence=7))
    finally:
        aifd_logger.propagate = original_propagate

    records = [
        r.getMessage() for r in caplog.records if "suppressed" in r.getMessage()
    ]
    assert records, "expected at least one DEBUG suppression record"
    rec = records[0]
    assert "escape_prefix" in rec, f"missing suppressor name in: {rec!r}"
    assert "backslash" in rec, f"missing reason in: {rec!r}"
