"""Tests for the shared provider helper module."""

from __future__ import annotations

from datetime import datetime

from aifd.providers._utils import (
    CLAUDE_COMMAND_RE,
    CODEX_SKILL_RE,
    normalize_skill_name,
    normalize_title,
    parse_iso_ts,
)


def test_normalize_title_collapses_whitespace() -> None:
    assert normalize_title("line one\n  line two\t\textra") == "line one line two extra"


def test_normalize_title_handles_empty() -> None:
    assert normalize_title("") == ""


def test_parse_iso_ts_handles_z_suffix() -> None:
    dt = parse_iso_ts("2026-06-01T10:00:00.000Z")
    assert isinstance(dt, datetime)
    assert dt.year == 2026


def test_parse_iso_ts_returns_none_on_garbage() -> None:
    assert parse_iso_ts("not a date") is None
    assert parse_iso_ts("") is None


def test_normalize_skill_name_strips_slash_and_gstack_prefix() -> None:
    # Claude form
    assert normalize_skill_name("/gstack-office-hours") == "office-hours"
    # Codex form (already normalized)
    assert normalize_skill_name("office-hours") == "office-hours"
    # Slash only
    assert normalize_skill_name("/model") == "model"
    # Already gstack-prefixed without slash
    assert normalize_skill_name("gstack-investigate") == "investigate"


def test_normalize_skill_name_keeps_namespaced_skills() -> None:
    """Some skills are namespaced like `superpowers:using-superpowers`."""
    assert (
        normalize_skill_name("/superpowers:using-superpowers")
        == "superpowers:using-superpowers"
    )


def test_claude_command_re_matches_inline_marker() -> None:
    text = "intro\n<command-name>/gstack-foo</command-name>\nbody"
    matches = CLAUDE_COMMAND_RE.findall(text)
    assert matches == ["/gstack-foo"]


def test_claude_command_re_matches_multiple_markers() -> None:
    text = "<command-name>/a</command-name> mid <command-name>/b</command-name>"
    assert CLAUDE_COMMAND_RE.findall(text) == ["/a", "/b"]


def test_codex_skill_re_only_matches_leading_marker() -> None:
    assert CODEX_SKILL_RE.match("[$office-hours](/path) body").group(1) == "office-hours"
    # Not at start -> no match
    assert CODEX_SKILL_RE.match("prefix [$office-hours](/path)") is None


def test_codex_skill_re_handles_namespace_skill() -> None:
    assert (
        CODEX_SKILL_RE.match("[$compound-engineering:ce-brain](/path)").group(1)
        == "compound-engineering:ce-brain"
    )


def test_is_gstack_name_detects_prefix() -> None:
    from aifd.providers._utils import is_gstack_name

    assert is_gstack_name("/gstack-office-hours") is True
    assert is_gstack_name("gstack-office-hours") is True
    assert is_gstack_name("/model") is False
    assert is_gstack_name("office-hours") is False  # Codex form, no prefix
    assert is_gstack_name("graphify") is False
    # Edge: an empty / whitespace marker
    assert is_gstack_name("") is False
    assert is_gstack_name("/") is False
