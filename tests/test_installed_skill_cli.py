"""End-to-end CLI tests for `aifd ai claude/codex skill list` (T7)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aifd.cli import cli
from aifd.providers.claude import ClaudeProvider
from aifd.providers.codex import CodexProvider
from tests.conftest import write_skill_md


def test_claude_skill_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "claude", "skill", "list", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_codex_skill_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "codex", "skill", "list", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_claude_group_help_shows_skill_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "claude", "--help"])
    assert result.exit_code == 0
    assert "skill" in result.output


def test_codex_group_help_shows_skill_subcommand() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "codex", "--help"])
    assert result.exit_code == 0
    assert "skill" in result.output


def test_claude_skill_list_empty_friendly_message(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.claude.skill.ClaudeProvider",
        lambda: ClaudeProvider(
            skills_root=claude_skills_root, plugins_root=claude_plugins_root
        ),
    ):
        result = runner.invoke(cli, ["ai", "claude", "skill", "list"])
    assert result.exit_code == 0
    assert "No installed skills found" in result.output
    assert "claude" in result.output


def test_codex_skill_list_empty_friendly_message(codex_skills_root: Path) -> None:
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.codex.skill.CodexProvider",
        lambda: CodexProvider(skills_root=codex_skills_root),
    ):
        result = runner.invoke(cli, ["ai", "codex", "skill", "list"])
    assert result.exit_code == 0
    assert "No installed skills found" in result.output
    assert "codex" in result.output


def test_claude_skill_list_json_output(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    write_skill_md(
        claude_skills_root / "alpha", name="alpha", description="user-installed"
    )
    write_skill_md(
        claude_plugins_root / "m" / "p" / "1.0" / "skills" / "beta",
        name="beta",
        description="plugin-installed",
    )

    runner = CliRunner()
    with patch(
        "aifd.cli.ai.claude.skill.ClaudeProvider",
        lambda: ClaudeProvider(
            skills_root=claude_skills_root, plugins_root=claude_plugins_root
        ),
    ):
        result = runner.invoke(cli, ["ai", "claude", "skill", "list", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    by_name = {p["name"]: p for p in parsed}
    assert by_name["alpha"]["source"] == "user"
    assert by_name["beta"]["source"] == "plugin"
    assert by_name["beta"]["plugin"] == "p"
    assert by_name["alpha"]["provider"] == "claude"


def test_codex_skill_list_json_includes_system(codex_skills_root: Path) -> None:
    write_skill_md(
        codex_skills_root / ".system" / "imagegen",
        name="imagegen",
        description="bundled",
    )
    write_skill_md(
        codex_skills_root / "office-hours", name="office-hours", description="user"
    )

    runner = CliRunner()
    with patch(
        "aifd.cli.ai.codex.skill.CodexProvider",
        lambda: CodexProvider(skills_root=codex_skills_root),
    ):
        result = runner.invoke(cli, ["ai", "codex", "skill", "list", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    by_name = {p["name"]: p for p in parsed}
    assert by_name["imagegen"]["source"] == "system"
    assert by_name["office-hours"]["source"] == "user"
