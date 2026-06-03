"""End-to-end CLI tests via click.testing.CliRunner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aifd.cli import cli
from aifd.providers.claude import ClaudeProvider
from aifd.providers.codex import CodexProvider


def test_help_works() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Operations across AI coding tools" in result.output


def test_version() -> None:
    """Should report whatever aifd.__version__ says — track the source of truth."""
    from aifd import __version__

    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_ai_session_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "session", "list", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
    assert "--provider" in result.output


def test_list_empty_dir_is_friendly(tmp_path: Path) -> None:
    """In an empty/unknown cwd, exit code is 0 and message is friendly."""
    runner = CliRunner()
    fake_root = tmp_path / "no-claude"
    fake_codex = tmp_path / "no-codex"

    with patch(
        "aifd.cli.ai.session.PROVIDERS",
        [ClaudeProvider(root=fake_root), CodexProvider(root=fake_codex)],
    ):
        result = runner.invoke(cli, ["ai", "session", "list"])

    assert result.exit_code == 0
    assert "No AI sessions found" in result.output


def test_list_json_output_with_session(
    tmp_path: Path, make_claude_session, claude_root: Path, monkeypatch
) -> None:
    """Full end-to-end: prepare a Claude session, run `aifd ai session list --json`,
    parse the output."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("e2e-1", str(cwd), extra_events=2)

    monkeypatch.chdir(cwd)
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.session.PROVIDERS",
        [ClaudeProvider(root=claude_root)],
    ):
        result = runner.invoke(cli, ["ai", "session", "list", "--json"])

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["session_id"] == "e2e-1"
    assert parsed[0]["provider"] == "claude"
