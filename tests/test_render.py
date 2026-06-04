"""Tests for the output renderer."""

from __future__ import annotations

import datetime as _dt
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aifd.models import Session
from aifd.render import _relative_time, render_sessions


def _make(
    provider: str,
    sid: str,
    started_at: datetime | None = None,
    *,
    title: str | None = None,
) -> Session:
    return Session(
        provider=provider,
        session_id=sid,
        cwd=Path("/some/cwd"),
        started_at=started_at,
        event_count=42,
        source_path=Path(f"/store/{sid}.jsonl"),
        title=title,
    )


def test_empty_rows_prints_friendly_message(capsys: pytest.CaptureFixture[str]) -> None:
    render_sessions([], cwd=Path("/here"), as_json=False)
    captured = capsys.readouterr()
    assert "No AI sessions found" in captured.out
    assert "/here" in captured.out


def test_json_output_is_valid_json_array(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_make("claude", "abc-123", datetime(2026, 6, 1, tzinfo=UTC))]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["provider"] == "claude"
    assert parsed[0]["session_id"] == "abc-123"
    assert parsed[0]["cwd"] == "/some/cwd"
    assert parsed[0]["started_at"].startswith("2026-06-01")
    assert parsed[0]["event_count"] == 42


def test_json_handles_none_started_at(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_make("claude", "x", None)]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["started_at"] is None
    assert parsed[0]["title"] is None


def test_json_includes_full_title(capsys: pytest.CaptureFixture[str]) -> None:
    long_title = "x" * 200  # longer than table truncation
    rows = [_make("claude", "x", title=long_title)]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["title"] == long_title  # untruncated in JSON


def test_skill_stats_table_restores_gstack_prefix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """is_gstack=True must render `gstack-<name>` in the table."""
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=10,
            count_codex=5,
            total=15,
            unique_cwd_count=3,
            last_used=None,
            is_gstack=True,
        ),
        SkillStats(
            skill_name="model",
            count_claude=8,
            count_codex=0,
            total=8,
            unique_cwd_count=2,
            last_used=None,
            is_gstack=False,
        ),
    ]
    render_skill_stats(stats, scope_label="globally", as_json=False)
    out = capsys.readouterr().out
    assert "gstack-office-hours" in out
    # `model` (no gstack-) stays bare
    assert "gstack-model" not in out


def test_skill_stats_json_includes_is_gstack(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=10,
            count_codex=5,
            total=15,
            unique_cwd_count=3,
            last_used=None,
            is_gstack=True,
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["is_gstack"] is True
    # JSON keeps the normalized skill_name — programs filter by that
    assert parsed[0]["skill_name"] == "office-hours"


def test_installed_skills_empty_friendly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.render import render_installed_skills

    render_installed_skills([], provider_label="claude", as_json=False)
    out = capsys.readouterr().out
    assert "No installed skills found" in out
    assert "claude" in out


def test_installed_skills_json_includes_all_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import InstalledSkill
    from aifd.render import render_installed_skills

    skills = [
        InstalledSkill(
            name="alpha",
            description="d",
            provider="claude",
            source="plugin",
            source_path=Path("/p/SKILL.md"),
            version="1.0",
            plugin="my-plugin",
            is_symlink=True,
        )
    ]
    render_installed_skills(skills, provider_label="claude", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["name"] == "alpha"
    assert parsed[0]["source"] == "plugin"
    assert parsed[0]["plugin"] == "my-plugin"
    assert parsed[0]["version"] == "1.0"
    assert parsed[0]["is_symlink"] is True


def test_installed_skills_table_renders_without_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import InstalledSkill
    from aifd.render import render_installed_skills

    skills = [
        InstalledSkill(
            name="x",
            description="d" * 200,  # long, must be truncated
            provider="claude",
            source="user",
            source_path=Path("/p/SKILL.md"),
        )
    ]
    render_installed_skills(skills, provider_label="claude", as_json=False)
    out = capsys.readouterr().out
    assert "x" in out
    assert "user" in out


def test_json_handles_chinese_title(capsys: pytest.CaptureFixture[str]) -> None:
    """ensure_ascii=False so Chinese titles survive jq pipes."""
    rows = [_make("codex", "x", title="实现一个 CLI 工具")]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    out = capsys.readouterr().out
    assert "实现" in out
    parsed = json.loads(out)
    assert parsed[0]["title"] == "实现一个 CLI 工具"


def test_relative_time_minutes() -> None:
    now = datetime.now(UTC)
    five_min_ago = now - _dt.timedelta(minutes=5)
    assert _relative_time(five_min_ago) == "5m ago"


def test_relative_time_days() -> None:
    now = datetime.now(UTC)
    three_days_ago = now - _dt.timedelta(days=3)
    assert _relative_time(three_days_ago) == "3d ago"


def test_relative_time_handles_naive_datetime() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None) - _dt.timedelta(minutes=2)
    # Should not crash; assumes UTC.
    out = _relative_time(naive)
    assert "ago" in out


# ---------- render_skill_stats ----------


def test_render_skill_stats_empty_friendly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.render import render_skill_stats

    render_skill_stats([], scope_label="globally", as_json=False)
    out = capsys.readouterr().out
    assert "No skill invocations found" in out
    assert "globally" in out


def test_render_skill_stats_json(capsys: pytest.CaptureFixture[str]) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=5,
            count_codex=3,
            total=8,
            unique_cwd_count=4,
            last_used=datetime(2026, 6, 1, tzinfo=UTC),
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["skill_name"] == "office-hours"
    assert parsed[0]["total"] == 8
    assert parsed[0]["unique_cwd_count"] == 4
    assert parsed[0]["last_used"].startswith("2026-06-01")


def test_render_skill_stats_json_handles_none_last_used(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="x",
            count_claude=1,
            count_codex=0,
            total=1,
            unique_cwd_count=1,
            last_used=None,
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["last_used"] is None


# ---------- render_scan_matches_html (--web mode) ----------


def _scan_match(
    secret: str = "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    *,
    before: str = "before text ",
    after: str = " after text",
    truncated: bool = False,
    category: str = "anthropic_key",
    confidence: int = 10,
    line_no: int = 5,
    file_path: str = "/tmp/fixture.jsonl",
):
    from aifd.models import SensitiveMatch
    return SensitiveMatch(
        file=Path(file_path),
        line=line_no,
        category=category,
        snippet_redacted="sk-a…REDACTED…aaaa",
        confidence=confidence,
        full_length=len(secret),
        context_before=before,
        match_full=secret,
        context_after=after,
        raw_line=before + secret + after,
        line_truncated=truncated,
    )


def test_render_scan_matches_html_marks_match_span() -> None:
    from aifd.render import render_scan_matches_html

    m = _scan_match()
    html_out = render_scan_matches_html([m])
    assert '<mark class="leak">' in html_out
    assert m.match_full in html_out
    # Match must be wrapped — before+secret+after should be contiguous.
    assert f'before text <mark class="leak">{m.match_full}</mark> after text' in html_out


def test_render_scan_matches_html_escapes_user_text() -> None:
    """Defense against XSS via leaked-content that looks like HTML."""
    from aifd.render import render_scan_matches_html

    m = _scan_match(
        secret="</mark><script>alert(1)</script>",
        before='<img src=x>',
        after='</body>',
    )
    html_out = render_scan_matches_html([m])
    # The raw HTML must not survive into the output unescaped — every
    # < / > / & in user-derived strings must be entity-encoded.
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "<img src=x>" not in html_out
    assert "&lt;img src=x&gt;" in html_out


def test_render_scan_matches_html_warning_banner_present() -> None:
    from aifd.render import render_scan_matches_html

    html_out = render_scan_matches_html([_scan_match()])
    assert "contains raw secrets" in html_out
    assert "Ctrl-C" in html_out


def test_render_scan_matches_html_empty_state() -> None:
    from aifd.render import render_scan_matches_html

    html_out = render_scan_matches_html([])
    assert "No findings" in html_out
    # Warning banner still present (the page itself doesn't know whether
    # the caller is about to expose anything; the banner is unconditional).
    assert "contains raw secrets" in html_out


def test_render_scan_matches_html_truncation_badge() -> None:
    from aifd.render import render_scan_matches_html

    html_out = render_scan_matches_html(
        [_scan_match(truncated=True)]
    )
    assert "line truncated" in html_out


def test_render_scan_matches_html_no_truncation_badge_when_clean() -> None:
    from aifd.render import render_scan_matches_html

    html_out = render_scan_matches_html(
        [_scan_match(truncated=False)]
    )
    assert "line truncated" not in html_out


def test_render_scan_matches_html_groups_by_file() -> None:
    from aifd.render import render_scan_matches_html

    a1 = _scan_match(file_path="/tmp/a.jsonl", line_no=1)
    a2 = _scan_match(file_path="/tmp/a.jsonl", line_no=2)
    b1 = _scan_match(file_path="/tmp/b.jsonl", line_no=1)
    html_out = render_scan_matches_html([a1, a2, b1])
    # Each file gets ONE section heading
    assert html_out.count('section class="file"') == 2
    assert "/tmp/a.jsonl" in html_out
    assert "/tmp/b.jsonl" in html_out


def test_render_scan_matches_html_emits_tabs_for_multiple_categories() -> None:
    """When matches span >1 category, the page emits one tab per category
    with `<input type="radio">` state carriers and a `<nav class="tabs">`
    bar of labels.
    """
    from aifd.render import render_scan_matches_html

    m_email = _scan_match(category="email", confidence=7)
    m_key = _scan_match(category="anthropic_key", confidence=10)
    html_out = render_scan_matches_html([m_email, m_key])
    # Radio inputs as state carriers
    assert 'id="t-email"' in html_out
    assert 'id="t-anthropic_key"' in html_out
    assert 'class="tab-radio"' in html_out
    # Tab bar with labels
    assert 'class="tabs"' in html_out
    assert 'for="t-email"' in html_out
    assert 'for="t-anthropic_key"' in html_out
    # Panels
    assert 'id="p-email"' in html_out
    assert 'id="p-anthropic_key"' in html_out


def test_render_scan_matches_html_tabs_ordered_by_confidence() -> None:
    """Tabs are ordered by detector confidence DESC; anthropic_key (10)
    must appear before email (7) in the rendered DOM order so the most
    dangerous findings hit the user first.
    """
    from aifd.render import render_scan_matches_html

    m_email = _scan_match(category="email", confidence=7)
    m_key = _scan_match(category="anthropic_key", confidence=10)
    # Reverse insertion order to prove it's the SORT that determines
    # ordering, not insertion order.
    html_out = render_scan_matches_html([m_email, m_key])
    i_key = html_out.find('for="t-anthropic_key"')
    i_email = html_out.find('for="t-email"')
    assert i_key < i_email, (
        "anthropic_key (conf 10) should appear before email (conf 7) "
        "in tab DOM order"
    )


def test_render_scan_matches_html_default_tab_is_highest_severity() -> None:
    """The radio carrying `checked` must be the highest-severity tab."""
    from aifd.render import render_scan_matches_html

    m_email = _scan_match(category="email", confidence=7)
    m_key = _scan_match(category="anthropic_key", confidence=10)
    html_out = render_scan_matches_html([m_email, m_key])
    # The anthropic_key input has `checked`
    import re
    key_input = re.search(
        r'<input[^>]*id="t-anthropic_key"[^>]*>', html_out
    )
    email_input = re.search(
        r'<input[^>]*id="t-email"[^>]*>', html_out
    )
    assert key_input is not None and email_input is not None
    assert "checked" in key_input.group(0)
    assert "checked" not in email_input.group(0)


def test_render_scan_matches_html_hides_empty_categories() -> None:
    """A category with zero findings does NOT show a tab. Only the
    detected categories appear in the tab bar.
    """
    from aifd.render import render_scan_matches_html

    # Only email + anthropic_key present, no openai_key / github_pat / etc.
    m_email = _scan_match(category="email", confidence=7)
    m_key = _scan_match(category="anthropic_key", confidence=10)
    html_out = render_scan_matches_html([m_email, m_key])
    # Untriggered detectors must NOT have tabs / panels
    for absent_cat in (
        "openai_key", "github_pat", "aws_access_key", "jwt", "high_entropy",
    ):
        assert f'id="t-{absent_cat}"' not in html_out, (
            f"category {absent_cat} has no findings but its tab appeared"
        )
        assert f'id="p-{absent_cat}"' not in html_out


def test_render_scan_matches_html_panel_contains_only_its_category() -> None:
    """Each panel contains only its own category's matches; cross-category
    leakage would defeat the whole tab purpose.
    """
    from aifd.render import render_scan_matches_html

    m_email = _scan_match(
        category="email",
        secret="alice@personal.io",
        before='email context: ',
        after=' end',
    )
    m_key = _scan_match(
        category="anthropic_key",
        secret="sk-ant-FOOFOOFOOFOOFOOFOOFOO",
        before='key context: ',
        after=' end',
    )
    html_out = render_scan_matches_html([m_email, m_key])
    # Slice the anthropic_key panel and verify it has the key but NOT
    # the email. Boundary alternates so the regex works whether another
    # panel follows or the page ends.
    import re
    panel_open = r'<div class="panel" id="p-anthropic_key"[^>]*>'
    panel_close = r'</div>\s*(?=<div class="panel"|</main>)'
    panel_re = re.compile(panel_open + r"(.*?)" + panel_close, re.S)
    m = panel_re.search(html_out)
    assert m is not None
    panel_body = m.group(1)
    assert "sk-ant-FOOFOOFOOFOOFOOFOOFOO" in panel_body
    assert "alice@personal.io" not in panel_body, (
        "email match leaked into the anthropic_key panel"
    )


def test_render_scan_matches_html_single_category_still_groups_by_file() -> None:
    """With only one category, the page still emits 1 tab; matches inside
    are still grouped by source file (same `<section class="file">` pattern).
    """
    from aifd.render import render_scan_matches_html

    a1 = _scan_match(category="email", file_path="/tmp/a.jsonl", line_no=1)
    b1 = _scan_match(category="email", file_path="/tmp/b.jsonl", line_no=1)
    html_out = render_scan_matches_html([a1, b1])
    # One tab
    assert html_out.count('class="tab-radio"') == 1
    assert 'for="t-email"' in html_out
    # Two file sections inside the panel
    assert html_out.count('<section class="file">') == 2
    assert "/tmp/a.jsonl" in html_out
    assert "/tmp/b.jsonl" in html_out


def test_render_scan_matches_html_no_findings_keeps_empty_state() -> None:
    """Zero findings → no tabs, page falls back to existing empty marker."""
    from aifd.render import render_scan_matches_html

    html_out = render_scan_matches_html([])
    assert "No findings" in html_out
    # No tab UI at all
    assert 'class="tab-radio"' not in html_out
    assert 'class="tabs"' not in html_out
    assert 'class="panel"' not in html_out


def test_category_sort_key_unit() -> None:
    """anthropic_key (conf 10) sorts before email (conf 7) sorts before
    high_entropy (conf 6) sorts before unknown (conf 0).
    """
    from aifd.render import _category_sort_key

    cats = ["high_entropy", "email", "anthropic_key", "totally_unknown_cat"]
    cats_sorted = sorted(cats, key=_category_sort_key)
    assert cats_sorted == [
        "anthropic_key",     # conf 10
        "email",             # conf 7
        "high_entropy",      # conf 6
        "totally_unknown_cat",  # conf 0 (fallback)
    ]


def test_render_scan_matches_html_unescapes_jsonl_chunks() -> None:
    """Literal `\\n` / `\\t` / `\\"` sequences become real characters in HTML.

    jsonl context arrives JSON-encoded (backslash-n etc). Users complained
    the web view showed `\\n` as visible noise; the renderer must decode
    standard JSON string escapes before applying html.escape, then rely
    on CSS `white-space: pre-wrap` to render the real newlines.
    """
    from aifd.render import render_scan_matches_html

    m = _scan_match(
        secret="ghp_abcdef0123456789abcdef0123456789xyz",
        before='"text": "hello\\nworld\\nthird line ',
        after='\\nthe leak is above\\n"}',
    )
    html_out = render_scan_matches_html([m])
    # Real newline must be present (assert by counting how many lines
    # the context block was decoded into).
    assert "hello\nworld\nthird line" in html_out
    assert "the leak is above\n" in html_out
    # The literal escape sequence must NOT survive as text.
    assert "hello\\nworld" not in html_out


def test_render_scan_matches_html_unescapes_unicode_escapes() -> None:
    """`\\uXXXX` sequences decode to the actual code point."""
    from aifd.render import render_scan_matches_html

    m = _scan_match(
        secret="ghp_abcdef0123456789abcdef0123456789xyz",
        before='"text": "\\u4e2d\\u6587 prefix ',
        after=' \\u540e\\u7f00"',
    )
    html_out = render_scan_matches_html([m])
    assert "中文 prefix" in html_out
    assert "后缀" in html_out
    assert "\\u4e2d" not in html_out


def test_render_scan_matches_html_keeps_incomplete_escape() -> None:
    """A lone trailing backslash at a chunk boundary stays literal.

    The windowed context slices the raw line at arbitrary char offsets,
    so a chunk might end in `\\` with the matching `n` having landed in
    the next chunk. Leave it untouched rather than gobbling the next
    char or corrupting the display.
    """
    from aifd.render import render_scan_matches_html

    m = _scan_match(
        secret="ghp_abcdef0123456789abcdef0123456789xyz",
        before="trailing backslash here \\",
        after="\\ leading backslash here",
    )
    html_out = render_scan_matches_html([m])
    # Backslash survives, html-escaped or not (html.escape doesn't touch
    # backslash). The point: no crash, no eaten characters.
    assert "trailing backslash here \\" in html_out
    assert "\\ leading backslash here" in html_out


def test_render_scan_matches_html_unescapes_raw_line() -> None:
    """Expandable raw jsonl <details> block also needs the unescape."""
    from aifd.models import SensitiveMatch
    from aifd.render import render_scan_matches_html

    m = SensitiveMatch(
        file=Path("/tmp/x.jsonl"),
        line=1,
        category="anthropic_key",
        snippet_redacted="sk-a…REDACTED…aaaa",
        confidence=10,
        full_length=40,
        context_before="x",
        match_full="y",
        context_after="z",
        raw_line='{"text": "line1\\nline2\\nline3"}',
        line_truncated=False,
    )
    html_out = render_scan_matches_html([m])
    # raw_line block (inside <details>) should show real newlines too.
    assert "line1\nline2\nline3" in html_out


def test_unescape_jsonl_chunk_unit() -> None:
    """Direct unit test for the unescape helper."""
    from aifd.render import _unescape_jsonl_chunk

    assert _unescape_jsonl_chunk(r"a\nb") == "a\nb"
    assert _unescape_jsonl_chunk(r'a\"b') == 'a"b'
    assert _unescape_jsonl_chunk(r"a\\b") == "a\\b"
    assert _unescape_jsonl_chunk(r"a\tb") == "a\tb"
    assert _unescape_jsonl_chunk(r"a中b") == "a中b"
    # Incomplete escape stays literal
    assert _unescape_jsonl_chunk("a\\") == "a\\"
    # Mixed
    assert (
        _unescape_jsonl_chunk(r'before\n\"quoted\"\nafter')
        == 'before\n"quoted"\nafter'
    )
