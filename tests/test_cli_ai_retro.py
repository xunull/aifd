"""CLI tests for `aifd ai today / weekly / monthly / retro`.

The backend (`summarize_activity`) is exercised in `test_insights.py` with
fake providers. These tests cover the CLI surface: flag wiring, help text,
date parsing, and the JSON pass-through path.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from aifd.cli import cli


def _empty_providers():  # type: ignore[no-untyped-def]
    """Patch PROVIDERS list to empty so commands hit the no-activity path
    deterministically — keeps these tests independent of the user's
    actual jsonl history.
    """
    # After v0.8 package conversion, PROVIDERS is read from its canonical
    # location (aifd.insights.activity.PROVIDERS) — patching the package-
    # level alias would no longer affect summarize_activity's resolution.
    return patch("aifd.insights.activity.PROVIDERS", [])


def test_today_help_advertises_json_flag() -> None:
    result = CliRunner().invoke(cli, ["ai", "today", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_today_runs_with_no_providers() -> None:
    with _empty_providers():
        result = CliRunner().invoke(cli, ["ai", "today"])
    assert result.exit_code == 0
    assert "No AI activity" in result.output


def test_today_json_emits_stable_schema() -> None:
    """--json output must contain every documented top-level key."""
    with _empty_providers():
        result = CliRunner().invoke(cli, ["ai", "today", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    expected_keys = {
        "period_start",
        "period_end",
        "session_count",
        "cost_usd",
        "total_tokens",
        "by_provider",
        "top_skills",
        "top_topics",
        "delta",
        "projection",
    }
    assert expected_keys.issubset(payload.keys()), (
        f"missing keys: {expected_keys - payload.keys()}"
    )


def test_retro_rejects_inverted_range() -> None:
    """--until before --since is a usage error."""
    result = CliRunner().invoke(
        cli, ["ai", "retro", "--since", "2026-06-01", "--until", "2026-05-01"]
    )
    assert result.exit_code != 0
    assert "after" in result.output.lower()
