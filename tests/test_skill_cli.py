"""End-to-end CLI tests for `aifd ai skill list`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aifd.cli import cli
from aifd.providers.claude import ClaudeProvider
from aifd.providers.codex import CodexProvider


def test_skill_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "skill", "list", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
    assert "--provider" in result.output
    assert "--cwd" in result.output


def test_skill_list_empty_friendly_message(tmp_path: Path) -> None:
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.skill.PROVIDERS",
        [
            ClaudeProvider(root=tmp_path / "no-claude"),
            CodexProvider(root=tmp_path / "no-codex"),
        ],
    ):
        result = runner.invoke(cli, ["ai", "skill", "list"])
    assert result.exit_code == 0
    assert "No skill invocations found" in result.output


def test_skill_list_global_aggregates_claude_and_codex(
    tmp_path: Path, make_claude_session, claude_root, codex_db, codex_root
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("c1", str(cwd), skills=["/gstack-office-hours"])
    codex_db("x1", str(cwd), skill="office-hours")

    runner = CliRunner()
    with patch(
        "aifd.cli.ai.skill.PROVIDERS",
        [ClaudeProvider(root=claude_root), CodexProvider(root=codex_root)],
    ):
        result = runner.invoke(cli, ["ai", "skill", "list", "--json"])
    assert result.exit_code == 0, result.output

    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["skill_name"] == "office-hours"
    assert parsed[0]["count_claude"] == 1
    assert parsed[0]["count_codex"] == 1
    assert parsed[0]["total"] == 2


def test_skill_list_provider_filter(
    tmp_path: Path, make_claude_session, claude_root, codex_db, codex_root
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("c1", str(cwd), skills=["/gstack-office-hours"])
    codex_db("x1", str(cwd), skill="investigate")

    runner = CliRunner()
    with patch(
        "aifd.cli.ai.skill.PROVIDERS",
        [ClaudeProvider(root=claude_root), CodexProvider(root=codex_root)],
    ):
        result = runner.invoke(
            cli, ["ai", "skill", "list", "--json", "--provider", "claude"]
        )
    assert result.exit_code == 0, result.output

    parsed = json.loads(result.output)
    skills = {s["skill_name"] for s in parsed}
    assert skills == {"office-hours"}  # investigate (codex-only) is excluded


def test_skill_list_cwd_flag_scopes_to_current(
    tmp_path: Path, make_claude_session, claude_root, monkeypatch
) -> None:
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    make_claude_session("a1", str(cwd_a), skills=["/gstack-office-hours"])
    make_claude_session("b1", str(cwd_b), skills=["/gstack-investigate"])

    monkeypatch.chdir(cwd_a)
    runner = CliRunner()
    with patch("aifd.cli.ai.skill.PROVIDERS", [ClaudeProvider(root=claude_root)]):
        result = runner.invoke(cli, ["ai", "skill", "list", "--cwd", "--json"])
    assert result.exit_code == 0, result.output

    parsed = json.loads(result.output)
    skills = {s["skill_name"] for s in parsed}
    assert skills == {"office-hours"}  # b's investigate excluded


def test_skill_list_default_is_global(
    tmp_path: Path, make_claude_session, claude_root, monkeypatch
) -> None:
    """Without --cwd, results MUST include skills from other directories."""
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    make_claude_session("a1", str(cwd_a), skills=["/gstack-office-hours"])
    make_claude_session("b1", str(cwd_b), skills=["/gstack-investigate"])

    monkeypatch.chdir(cwd_a)  # we are IN cwd_a but didn't pass --cwd
    runner = CliRunner()
    with patch("aifd.cli.ai.skill.PROVIDERS", [ClaudeProvider(root=claude_root)]):
        result = runner.invoke(cli, ["ai", "skill", "list", "--json"])
    parsed = json.loads(result.output)
    assert {s["skill_name"] for s in parsed} == {"office-hours", "investigate"}
