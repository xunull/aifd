"""Tests for the OpenCode provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from aifd.providers._utils import parse_opencode_model
from aifd.providers.opencode import OpenCodeProvider


# ---------- parse_opencode_model ----------


def test_parse_model_full() -> None:
    assert parse_opencode_model('{"id":"MiniMax-M3","providerID":"minimax-cn"}') == "MiniMax-M3 (minimax-cn)"


def test_parse_model_no_provider() -> None:
    assert parse_opencode_model('{"id":"gpt-4o"}') == "gpt-4o"


def test_parse_model_empty_string() -> None:
    assert parse_opencode_model("") is None


def test_parse_model_bad_json() -> None:
    assert parse_opencode_model("{not json}") is None


def test_parse_model_missing_id() -> None:
    assert parse_opencode_model('{"providerID":"openai"}') is None


def test_parse_model_modelid_field() -> None:
    # Some versions use "modelID" instead of "id"
    assert parse_opencode_model('{"modelID":"claude-sonnet","providerID":"anthropic"}') == "claude-sonnet (anthropic)"


# ---------- list_sessions ----------


def test_lists_matching_session(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("ses-1", str(cwd), title="Fix the auth bug")

    provider = OpenCodeProvider(root=opencode_root)
    sessions = list(provider.list_sessions(cwd))

    assert len(sessions) == 1
    assert sessions[0].session_id == "ses-1"
    assert sessions[0].title == "Fix the auth bug"
    assert sessions[0].cwd == cwd
    assert sessions[0].provider == "opencode"


def test_filters_by_directory(opencode_db, opencode_root, tmp_path: Path) -> None:
    right = tmp_path / "right"
    wrong = tmp_path / "wrong"
    right.mkdir()
    wrong.mkdir()
    opencode_db("ours", str(right), title="In scope")
    opencode_db("theirs", str(wrong), title="Out of scope")

    provider = OpenCodeProvider(root=opencode_root)
    ids = {s.session_id for s in provider.list_sessions(right)}
    assert ids == {"ours"}


def test_includes_sub_sessions(opencode_db, opencode_root, tmp_path: Path) -> None:
    """D1: sub-sessions (parent_id != NULL) are included, not filtered."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("parent", str(cwd), title="Main session")
    opencode_db("child", str(cwd), title="Sub agent session", parent_id="parent")

    provider = OpenCodeProvider(root=opencode_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"parent", "child"}


def test_orders_newest_first(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("old", str(cwd), time_created=1_000_000)
    opencode_db("new", str(cwd), time_created=2_000_000)

    provider = OpenCodeProvider(root=opencode_root)
    ids = [s.session_id for s in provider.list_sessions(cwd)]
    assert ids == ["new", "old"]


def test_started_at_from_time_created(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("s1", str(cwd), time_created=1780617600000)  # 2026-06-02 UTC

    provider = OpenCodeProvider(root=opencode_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].started_at is not None
    assert sessions[0].started_at.year == 2026


def test_missing_db_yields_nothing(tmp_path: Path) -> None:
    provider = OpenCodeProvider(root=tmp_path / "no-opencode-here")
    assert list(provider.list_sessions(tmp_path)) == []


def test_title_none_when_empty(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("s1", str(cwd), title="")

    provider = OpenCodeProvider(root=opencode_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title is None


def test_source_path_is_db(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("s1", str(cwd))

    provider = OpenCodeProvider(root=opencode_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].source_path == opencode_root / "opencode.db"


# ---------- iter_all_sessions ----------


def test_iter_all_returns_all_sessions(opencode_db, opencode_root, tmp_path: Path) -> None:
    opencode_db("a", str(tmp_path / "proj-a"))
    opencode_db("b", str(tmp_path / "proj-b"))

    provider = OpenCodeProvider(root=opencode_root)
    ids = {s.session_id for s in provider.iter_all_sessions()}
    assert ids == {"a", "b"}


def test_iter_all_missing_db(tmp_path: Path) -> None:
    provider = OpenCodeProvider(root=tmp_path / "no-db")
    assert list(provider.iter_all_sessions()) == []


# ---------- list_token_usage ----------


def test_token_usage_returned(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db(
        "s1",
        str(cwd),
        model='{"id":"MiniMax-M3","providerID":"minimax-cn"}',
        tokens_input=1000,
        tokens_output=200,
        tokens_reasoning=50,
        tokens_cache_read=300,
        tokens_cache_write=100,
        time_created=1780617600000,
    )

    provider = OpenCodeProvider(root=opencode_root)
    usages = list(provider.list_token_usage(cwd))

    assert len(usages) == 1
    u = usages[0]
    assert u.provider == "opencode"
    assert u.session_id == "s1"
    assert u.input_tokens == 1000
    assert u.output_tokens == 200
    assert u.reasoning_output_tokens == 50
    assert u.cache_read_input_tokens == 300
    assert u.cache_creation_input_tokens == 100
    assert u.model == "MiniMax-M3 (minimax-cn)"


def test_token_usage_skips_zero_token_sessions(opencode_db, opencode_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    opencode_db("zero", str(cwd), tokens_input=0, tokens_output=0)

    provider = OpenCodeProvider(root=opencode_root)
    assert list(provider.list_token_usage(cwd)) == []


def test_token_usage_scope_none_returns_all(opencode_db, opencode_root, tmp_path: Path) -> None:
    opencode_db("a", str(tmp_path / "proj-a"), tokens_input=100, tokens_output=10)
    opencode_db("b", str(tmp_path / "proj-b"), tokens_input=200, tokens_output=20)

    provider = OpenCodeProvider(root=opencode_root)
    ids = {u.session_id for u in provider.list_token_usage()}
    assert ids == {"a", "b"}


def test_token_usage_missing_db(tmp_path: Path) -> None:
    provider = OpenCodeProvider(root=tmp_path / "no-db")
    assert list(provider.list_token_usage()) == []


# ---------- list_installed_skills ----------


def test_installed_skills_reads_skill_md(opencode_root, opencode_skills_root, tmp_path: Path) -> None:
    skill_dir = opencode_skills_root / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Does something\nversion: 1.0.0\n---\nBody.\n",
        encoding="utf-8",
    )

    provider = OpenCodeProvider(root=opencode_root, skills_root=opencode_skills_root)
    skills = list(provider.list_installed_skills())

    assert len(skills) == 1
    assert skills[0].name == "my-skill"
    assert skills[0].description == "Does something"
    assert skills[0].version == "1.0.0"
    assert skills[0].provider == "opencode"
    assert skills[0].source == "user"


def test_installed_skills_falls_back_to_dir_name(opencode_root, opencode_skills_root) -> None:
    skill_dir = opencode_skills_root / "fallback-name"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("No frontmatter here.\n", encoding="utf-8")

    provider = OpenCodeProvider(root=opencode_root, skills_root=opencode_skills_root)
    skills = list(provider.list_installed_skills())
    assert skills[0].name == "fallback-name"


def test_installed_skills_skips_dir_without_skill_md(opencode_root, opencode_skills_root) -> None:
    (opencode_skills_root / "no-skill-md").mkdir()

    provider = OpenCodeProvider(root=opencode_root, skills_root=opencode_skills_root)
    assert list(provider.list_installed_skills()) == []


def test_installed_skills_missing_root(opencode_root, tmp_path: Path) -> None:
    provider = OpenCodeProvider(root=opencode_root, skills_root=tmp_path / "no-skills")
    assert list(provider.list_installed_skills()) == []


# ---------- no-op stubs ----------


def test_skill_invocations_returns_empty(opencode_root) -> None:
    provider = OpenCodeProvider(root=opencode_root)
    assert list(provider.list_skill_invocations()) == []


def test_question_answers_returns_empty(opencode_root) -> None:
    provider = OpenCodeProvider(root=opencode_root)
    assert list(provider.list_question_answers()) == []
