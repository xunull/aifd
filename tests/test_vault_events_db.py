"""Tests for `aifd vault watch events` SQLite store.

Covers WAL mode, fingerprint stability, state machine, occurrences
fan-out, pagination, dead letter, expire_mutes sweep, regression on
v0.6 invariants.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aifd.vault.events_db import (
    STATUS_ACKNOWLEDGED,
    STATUS_MUTED,
    STATUS_NEW,
    STATUS_RESOLVED,
    WatchEventsDB,
    fingerprint_for,
    init_db,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "findings.db"
    init_db(p)
    return p


@pytest.fixture
def db(db_path: Path) -> WatchEventsDB:
    return WatchEventsDB(db_path)


# ---------- fingerprint ----------


def test_fingerprint_stable_across_calls() -> None:
    a = fingerprint_for("openai_key", "sk-A…WXYZ")
    b = fingerprint_for("openai_key", "sk-A…WXYZ")
    assert a == b
    assert len(a) == 16


def test_fingerprint_excludes_file_path() -> None:
    """D2 invariant: fingerprint must NOT depend on file path.

    Same secret in different files = same fingerprint.
    """
    a = fingerprint_for("openai_key", "sk-A…WXYZ")
    # Whatever caller does, fingerprint_for() takes only category+snippet
    b = fingerprint_for("openai_key", "sk-A…WXYZ")
    assert a == b


def test_fingerprint_distinguishes_category() -> None:
    a = fingerprint_for("openai_key", "sk-A…WXYZ")
    b = fingerprint_for("anthropic_key", "sk-A…WXYZ")
    assert a != b


# ---------- WAL mode (D1 invariant) ----------


def test_init_db_enables_wal(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_init_db_idempotent(db_path: Path) -> None:
    """Calling init_db twice doesn't drop data or error."""
    db1 = WatchEventsDB(db_path)
    db1.upsert_finding("openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 1)
    db1.close()
    init_db(db_path)
    db2 = WatchEventsDB(db_path)
    assert db2.count_findings() == 1


# ---------- upsert lifecycle ----------


def test_upsert_new_fingerprint_is_new(db: WatchEventsDB) -> None:
    fp, is_new = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 42,
    )
    assert is_new is True
    row = db.get_finding(fp)
    assert row is not None
    assert row["count"] == 1
    assert row["status"] == STATUS_NEW


def test_upsert_same_fingerprint_increments_count(db: WatchEventsDB) -> None:
    fp1, _ = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 1,
    )
    fp2, new2 = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "def.jsonl", "/tmp/def.jsonl", 99,
    )
    assert fp1 == fp2
    assert new2 is False
    row = db.get_finding(fp1)
    assert row is not None
    assert row["count"] == 2


def test_upsert_resolved_finding_reopens(db: WatchEventsDB) -> None:
    """D2 + Sentry semantics: resolved → re-detect → re-opens as new."""
    fp, _ = db.upsert_finding("aws_secret", "AKIA…WXYZ", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_RESOLVED)
    fp2, is_new = db.upsert_finding(
        "aws_secret", "AKIA…WXYZ", "x.jsonl", "/x.jsonl", 1,
    )
    assert fp == fp2
    assert is_new is True
    row = db.get_finding(fp)
    assert row is not None
    assert row["status"] == STATUS_NEW
    assert row["count"] == 1


def test_upsert_muted_finding_silently_increments(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_MUTED, mute_hours=24)
    fp2, is_new = db.upsert_finding(
        "jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1,
    )
    assert fp == fp2
    assert is_new is False  # muted ⇒ no notify
    row = db.get_finding(fp)
    assert row is not None
    assert row["status"] == STATUS_MUTED
    assert row["count"] == 2


# ---------- occurrences ----------


def test_upsert_records_each_occurrence(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 10, 100,
    )
    db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "def.jsonl", "/tmp/def.jsonl", 20, 200,
    )
    occs = db.list_occurrences(fp)
    assert len(occs) == 2
    basenames = {row["file_basename"] for row in occs}
    assert basenames == {"abc.jsonl", "def.jsonl"}


# ---------- status state machine ----------


def test_mutate_status_ack(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("github_pat", "ghp_…ABCD", "x.jsonl", "/x.jsonl", 1)
    assert db.mutate_status(fp, STATUS_ACKNOWLEDGED) is True
    assert db.get_finding(fp)["status"] == STATUS_ACKNOWLEDGED


def test_mutate_status_mute_with_hours(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    assert db.mutate_status(fp, STATUS_MUTED, mute_hours=24) is True
    row = db.get_finding(fp)
    assert row["status"] == STATUS_MUTED
    assert row["muted_until"] is not None


def test_mutate_status_mute_forever(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    assert db.mutate_status(fp, STATUS_MUTED) is True
    row = db.get_finding(fp)
    assert row["status"] == STATUS_MUTED
    assert row["muted_until"] is None


def test_mutate_status_unknown_status_raises(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    with pytest.raises(ValueError):
        db.mutate_status(fp, "frobnicated")


def test_mutate_status_unknown_fingerprint_returns_false(db: WatchEventsDB) -> None:
    assert db.mutate_status("nonexistent", STATUS_ACKNOWLEDGED) is False


def test_mutate_status_clears_muted_until_on_non_mute_transition(
    db: WatchEventsDB,
) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_MUTED, mute_hours=24)
    db.mutate_status(fp, STATUS_ACKNOWLEDGED)
    row = db.get_finding(fp)
    assert row["muted_until"] is None


# ---------- expire_mutes (sweeper) ----------


def test_expire_mutes_flips_past_due_to_new(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_MUTED, mute_hours=1)
    # Fast-forward "now" past the mute window
    future = datetime.now(UTC) + timedelta(hours=2)
    n = db.expire_mutes(now=future)
    assert n == 1
    row = db.get_finding(fp)
    assert row["status"] == STATUS_NEW
    assert row["muted_until"] is None


def test_expire_mutes_leaves_forever_mutes_alone(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("jwt", "eyJ…ABCD", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_MUTED)  # forever
    n = db.expire_mutes(now=datetime.now(UTC) + timedelta(days=365))
    assert n == 0
    assert db.get_finding(fp)["status"] == STATUS_MUTED


# ---------- list + filter + pagination (D6) ----------


def test_list_findings_default_limit(db: WatchEventsDB) -> None:
    for i in range(75):
        db.upsert_finding("openai_key", f"sk-{i}", "x.jsonl", "/x.jsonl", i)
    rows = db.list_findings()
    assert len(rows) == 50  # D6 default LIMIT


def test_list_findings_filter_by_status(db: WatchEventsDB) -> None:
    fp1, _ = db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    fp2, _ = db.upsert_finding("openai_key", "sk-B", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp1, STATUS_RESOLVED)
    rows_new = db.list_findings(status="new")
    rows_res = db.list_findings(status="resolved")
    assert len(rows_new) == 1 and rows_new[0]["fingerprint"] == fp2
    assert len(rows_res) == 1 and rows_res[0]["fingerprint"] == fp1


def test_list_findings_filter_by_category(db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    rows = db.list_findings(category="openai_key")
    assert len(rows) == 1
    assert rows[0]["category"] == "openai_key"


def test_list_findings_filter_by_since(db: WatchEventsDB) -> None:
    past = datetime(2026, 1, 1, tzinfo=UTC)
    future = datetime(2026, 7, 1, tzinfo=UTC)
    db.upsert_finding(
        "openai_key", "sk-old", "x.jsonl", "/x.jsonl", 1, now=past,
    )
    fp_new, _ = db.upsert_finding(
        "openai_key", "sk-new", "x.jsonl", "/x.jsonl", 1, now=future,
    )
    rows = db.list_findings(since=datetime(2026, 6, 1, tzinfo=UTC))
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == fp_new


def test_list_findings_pagination_offset(db: WatchEventsDB) -> None:
    for i in range(10):
        db.upsert_finding("openai_key", f"sk-{i:02d}", "x.jsonl", "/x.jsonl", i)
    page1 = db.list_findings(limit=3, offset=0)
    page2 = db.list_findings(limit=3, offset=3)
    assert len(page1) == 3 and len(page2) == 3
    page1_fps = {r["fingerprint"] for r in page1}
    page2_fps = {r["fingerprint"] for r in page2}
    assert page1_fps.isdisjoint(page2_fps)


def test_count_findings_respects_filters(db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    assert db.count_findings() == 2
    assert db.count_findings(category="openai_key") == 1


# ---------- notes ----------


def test_set_note(db: WatchEventsDB) -> None:
    fp, _ = db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    assert db.set_note(fp, "rotated 2026-06-05") is True
    assert db.get_finding(fp)["notes"] == "rotated 2026-06-05"


# ---------- dead letter ----------


def test_dead_letter_add_list_drop(db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    fp = fingerprint_for("openai_key", "sk-A")
    db.add_dead_letter(fp, "slack-id", '{"event":"new_finding"}', 3, "HTTP 500")
    rows = db.list_dead_letter()
    assert len(rows) == 1
    assert rows[0]["webhook_id"] == "slack-id"
    assert db.drop_dead_letter(rows[0]["id"]) is True
    assert db.list_dead_letter() == []


def test_clear_dead_letter(db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    fp = fingerprint_for("openai_key", "sk-A")
    db.add_dead_letter(fp, "slack-id", "{}", 3, "err")
    db.add_dead_letter(fp, "pd-id", "{}", 3, "err")
    assert db.clear_dead_letter() == 2


# ---------- export ----------


def test_export_ndjson_streams_findings(db: WatchEventsDB) -> None:
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    lines = list(db.export_findings_ndjson())
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    categories = {p["category"] for p in parsed}
    assert categories == {"openai_key", "github_pat"}


# ---------- concurrency (D1) ----------


def test_concurrent_per_thread_connections(db_path: Path) -> None:
    """WAL allows readers + writers from different threads.

    Each thread creates its own connection; we run writes from N threads
    in parallel and expect zero SQLITE_BUSY.
    """
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            local_db = WatchEventsDB(db_path)
            for j in range(20):
                local_db.upsert_finding(
                    "openai_key", f"sk-{i}-{j}",
                    f"thread-{i}.jsonl", f"/t-{i}.jsonl", j,
                )
            local_db.close()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    reader = WatchEventsDB(db_path)
    assert reader.count_findings() == 5 * 20
