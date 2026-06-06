"""Tests for v0.7 CLI subcommands: aifd vault watch events / webhooks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from aifd.cli.vault.watch import watch as watch_cli
from aifd.vault.events_db import WatchEventsDB, init_db


@pytest.fixture
def aifd_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all CLI paths to a per-test tmpdir."""
    home = tmp_path / ".aifd"
    home.mkdir()
    monkeypatch.setattr("aifd.vault.watch_state.AIFD_HOME", home)
    monkeypatch.setattr(
        "aifd.vault.watch_state.STATE_FILE", home / "watch-state.json",
    )
    return home


@pytest.fixture
def db(aifd_home: Path) -> WatchEventsDB:
    p = aifd_home / "findings.db"
    init_db(p)
    return WatchEventsDB(p)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------- events list ----------


def test_events_list_empty_no_db(runner: CliRunner, aifd_home: Path) -> None:
    result = runner.invoke(watch_cli, ["events", "list"])
    assert result.exit_code == 0
    assert "No events DB yet" in result.output


def test_events_list_with_data(
    runner: CliRunner, db: WatchEventsDB,
) -> None:
    db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 42,
    )
    result = runner.invoke(watch_cli, ["events", "list"])
    assert result.exit_code == 0
    assert "1 finding(s) total" in result.output
    assert "openai_key" in result.output


def test_events_list_filter_by_status(
    runner: CliRunner, db: WatchEventsDB,
) -> None:
    fp1, _ = db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("openai_key", "sk-B", "x.jsonl", "/x.jsonl", 1)
    from aifd.vault.events_db import STATUS_ACKNOWLEDGED
    db.mutate_status(fp1, STATUS_ACKNOWLEDGED)
    result = runner.invoke(watch_cli, ["events", "list", "--status", "new"])
    assert result.exit_code == 0
    assert "1 finding(s) total" in result.output


def test_events_list_json_output(
    runner: CliRunner, db: WatchEventsDB,
) -> None:
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(watch_cli, ["events", "list", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["total"] == 1
    assert parsed["findings"][0]["category"] == "github_pat"


# ---------- events show ----------


def test_events_show(runner: CliRunner, db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 42,
    )
    result = runner.invoke(watch_cli, ["events", "show", fp])
    assert result.exit_code == 0
    assert fp in result.output
    assert "ROTATION PLAYBOOK" in result.output
    assert "platform.openai.com" in result.output


def test_events_show_unknown(runner: CliRunner, db: WatchEventsDB) -> None:
    result = runner.invoke(watch_cli, ["events", "show", "nonexistent"])
    assert result.exit_code == 1


# ---------- events ack / mute / resolve ----------


def test_events_ack(runner: CliRunner, db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(watch_cli, ["events", "ack", fp])
    assert result.exit_code == 0
    assert db.get_finding(fp)["status"] == "acknowledged"


def test_events_mute_with_hours(runner: CliRunner, db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(
        watch_cli, ["events", "mute", fp, "--hours", "24"],
    )
    assert result.exit_code == 0
    row = db.get_finding(fp)
    assert row["status"] == "muted"
    assert row["muted_until"] is not None


def test_events_mute_forever(runner: CliRunner, db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(watch_cli, ["events", "mute", fp])
    assert result.exit_code == 0
    row = db.get_finding(fp)
    assert row["status"] == "muted"
    assert row["muted_until"] is None


def test_events_resolve(runner: CliRunner, db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(watch_cli, ["events", "resolve", fp])
    assert result.exit_code == 0
    assert db.get_finding(fp)["status"] == "resolved"


def test_events_export_ndjson(runner: CliRunner, db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    result = runner.invoke(watch_cli, ["events", "export"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        json.loads(line)  # valid JSON


# ---------- webhooks add / list / delete ----------


def test_webhooks_list_empty(runner: CliRunner, aifd_home: Path) -> None:
    result = runner.invoke(watch_cli, ["webhooks", "list"])
    assert result.exit_code == 0
    assert "(no webhooks configured)" in result.output


def test_webhooks_add_then_list(
    runner: CliRunner, aifd_home: Path,
) -> None:
    result = runner.invoke(watch_cli, [
        "webhooks", "add",
        "--id", "test-1",
        "--url", "https://hooks.example.com/abc",
        "--on", "new_finding",
    ])
    assert result.exit_code == 0
    assert "Added webhook test-1 (disabled)" in result.output
    result = runner.invoke(watch_cli, ["webhooks", "list"])
    assert "DISABLED" in result.output
    assert "test-1" in result.output


def test_webhooks_add_rejects_file_url(
    runner: CliRunner, aifd_home: Path,
) -> None:
    result = runner.invoke(watch_cli, [
        "webhooks", "add", "--url", "file:///etc/passwd",
    ])
    assert result.exit_code != 0


def test_webhooks_add_duplicate_id_fails(
    runner: CliRunner, aifd_home: Path,
) -> None:
    runner.invoke(watch_cli, [
        "webhooks", "add", "--id", "dup",
        "--url", "https://hooks.example.com/a",
    ])
    result = runner.invoke(watch_cli, [
        "webhooks", "add", "--id", "dup",
        "--url", "https://hooks.example.com/b",
    ])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_webhooks_enable_disable(
    runner: CliRunner, aifd_home: Path,
) -> None:
    runner.invoke(watch_cli, [
        "webhooks", "add", "--id", "h1",
        "--url", "https://hooks.example.com/x",
    ])
    runner.invoke(watch_cli, ["webhooks", "enable", "h1"])
    list_result = runner.invoke(watch_cli, ["webhooks", "list"])
    assert "ENABLED" in list_result.output
    runner.invoke(watch_cli, ["webhooks", "disable", "h1"])
    list_result = runner.invoke(watch_cli, ["webhooks", "list"])
    assert "DISABLED" in list_result.output


def test_webhooks_delete(
    runner: CliRunner, aifd_home: Path,
) -> None:
    runner.invoke(watch_cli, [
        "webhooks", "add", "--id", "h1",
        "--url", "https://hooks.example.com/x",
    ])
    result = runner.invoke(watch_cli, ["webhooks", "delete", "h1"])
    assert result.exit_code == 0
    list_result = runner.invoke(watch_cli, ["webhooks", "list"])
    assert "(no webhooks configured)" in list_result.output


def test_webhooks_delete_unknown(
    runner: CliRunner, aifd_home: Path,
) -> None:
    result = runner.invoke(watch_cli, ["webhooks", "delete", "nonexistent"])
    assert result.exit_code != 0


# ---------- webhooks list-dead-letter ----------


def test_webhooks_list_dead_letter_empty(
    runner: CliRunner, db: WatchEventsDB,
) -> None:
    result = runner.invoke(watch_cli, ["webhooks", "list-dead-letter"])
    assert result.exit_code == 0
    assert "(no dead_letter entries)" in result.output


def test_webhooks_list_dead_letter_with_entries(
    runner: CliRunner, db: WatchEventsDB,
) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    from aifd.vault.events_db import fingerprint_for
    fp = fingerprint_for("openai_key", "sk-A")
    db.add_dead_letter(fp, "slack-1", "{}", 3, "HTTP 500")
    result = runner.invoke(watch_cli, ["webhooks", "list-dead-letter"])
    assert result.exit_code == 0
    assert "slack-1" in result.output
    assert "HTTP 500" in result.output


# ---------- status command shows drop_count if any ----------


def test_status_shows_drop_count_when_nonzero(
    runner: CliRunner, aifd_home: Path,
) -> None:
    from aifd.vault.watch_state import WatchState
    s = WatchState()
    s.finding_drop_count = 3
    s.save(aifd_home / "watch-state.json")
    result = runner.invoke(watch_cli, ["status"])
    assert result.exit_code == 0
    assert "drops" in result.output
    assert "3 finding(s)" in result.output


def test_status_json_includes_drop_count(
    runner: CliRunner, aifd_home: Path,
) -> None:
    result = runner.invoke(watch_cli, ["status", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "finding_drop_count" in parsed
