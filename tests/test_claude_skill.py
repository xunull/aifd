"""Tests for ClaudeProvider.list_skill_invocations."""

from __future__ import annotations

from pathlib import Path

from aifd.providers.claude import ClaudeProvider


def test_extracts_single_skill_invocation(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("s1", str(cwd), skills=["/gstack-office-hours"])

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations())
    assert len(invs) == 1
    assert invs[0].skill_name == "office-hours"  # normalized
    assert invs[0].provider == "claude"
    assert invs[0].cwd == cwd


def test_extracts_multiple_invocations_per_session(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session(
        "s1",
        str(cwd),
        skills=["/gstack-office-hours", "/gstack-plan-eng-review", "/model"],
    )

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations())
    names = [i.skill_name for i in invs]
    assert names == ["office-hours", "plan-eng-review", "model"]


def test_global_scope_scans_all_projects(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    """scope=None must reach every project_dir, not just one cwd's encoding."""
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    make_claude_session("a1", str(cwd_a), skills=["/gstack-office-hours"])
    make_claude_session("b1", str(cwd_b), skills=["/gstack-investigate"])

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations(scope=None))
    assert {i.skill_name for i in invs} == {"office-hours", "investigate"}


def test_scope_filter_excludes_other_cwds(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    make_claude_session("a1", str(cwd_a), skills=["/gstack-office-hours"])
    make_claude_session("b1", str(cwd_b), skills=["/gstack-investigate"])

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations(scope=cwd_a))
    assert [i.skill_name for i in invs] == ["office-hours"]


def test_session_without_skills_silent_skip(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("plain", str(cwd), user_text="just chat, no skill")

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations())
    assert invs == []


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    provider = ClaudeProvider(root=tmp_path / "nonexistent")
    assert list(provider.list_skill_invocations()) == []


def test_skill_name_with_dashes_extracted_intact(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("multi", str(cwd), skills=["/gstack-plan-ceo-review"])

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations())
    assert invs[0].skill_name == "plan-ceo-review"


def test_gstack_marker_is_flagged(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session(
        "mix", str(cwd), skills=["/gstack-office-hours", "/model"]
    )

    provider = ClaudeProvider(root=claude_root)
    invs = list(provider.list_skill_invocations())
    flags = {i.skill_name: i.is_gstack for i in invs}
    assert flags["office-hours"] is True
    assert flags["model"] is False
