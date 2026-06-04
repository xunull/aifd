"""End-to-end CLI tests for `aifd vault scan` and `aifd vault cost`."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from aifd.cli import cli


def test_vault_group_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
    assert "cost" in result.output


# --------------- aifd vault scan ---------------


def test_vault_scan_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "scan", "--help"])
    assert result.exit_code == 0
    assert "--min-confidence" in result.output
    assert "--root" in result.output
    assert "--no-default-roots" in result.output


def test_vault_scan_explicit_root(tmp_path: Path) -> None:
    """--root + --no-default-roots scans only the given path."""
    fixture = tmp_path / "fake.jsonl"
    fixture.write_text(
        "leaked: sk-proj-abc1234567890abcdef1234567890\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "vault",
            "scan",
            "--no-default-roots",
            "--root",
            str(fixture),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["category"] == "openai_key"
    assert "REDACTED" in parsed[0]["snippet_redacted"]
    # CRITICAL: full secret must NOT appear in JSON output
    assert "sk-proj-abc1234567890abcdef" not in result.output


def test_vault_scan_min_confidence_filters_entropy(tmp_path: Path) -> None:
    """Entropy-only matches (confidence < 7) are suppressed by default."""
    fixture = tmp_path / "f.jsonl"
    fixture.write_text(
        "blob=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["vault", "scan", "--no-default-roots", "--root", str(fixture), "--json"],
    )
    assert json.loads(result.output) == []
    result = runner.invoke(
        cli,
        [
            "vault", "scan", "--no-default-roots", "--root", str(fixture),
            "--min-confidence", "4", "--json",
        ],
    )
    parsed = json.loads(result.output)
    assert parsed and parsed[0]["category"] == "high_entropy"


def test_vault_scan_clean_data_is_friendly(tmp_path: Path) -> None:
    fixture = tmp_path / "clean.jsonl"
    fixture.write_text("nothing interesting here\n", encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        ["vault", "scan", "--no-default-roots", "--root", str(fixture)],
    )
    assert result.exit_code == 0
    assert "No potential secrets found" in result.output


def test_vault_scan_requires_some_root() -> None:
    """--no-default-roots with no --root is a usage error."""
    result = CliRunner().invoke(cli, ["vault", "scan", "--no-default-roots"])
    assert result.exit_code != 0
    assert "No roots to scan" in result.output


# --------------- aifd vault cost ---------------


def test_vault_cost_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--help"])
    assert result.exit_code == 0
    assert "--by" in result.output
    assert "--list-models" in result.output


def test_vault_cost_list_models() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--list-models"])
    assert result.exit_code == 0
    assert "claude-opus-4-7" in result.output
    assert "gpt-5-codex" in result.output


def test_vault_cost_by_invalid_choice() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--by", "garbage"])
    assert result.exit_code != 0
