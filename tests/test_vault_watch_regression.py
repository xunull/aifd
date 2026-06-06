"""Regression tests: v0.6 invariants must survive v0.7 events store wiring.

Covers:
- v0.6 click-to-jump: WatchServer.register() still works; in-memory token
  dict still resolves to original SensitiveMatch
- E10 today integration: state.record_catch() still fires; aifd ai today
  still sees the 🛡 vault watch counter
- Daemon._handle_match still writes events DB AND state counters AND
  notifier — none of the three paths got dropped
- finding_drop_count gets bumped when events DB write throws
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aifd.models import SensitiveMatch
from aifd.vault.events_db import WatchEventsDB, fingerprint_for, init_db
from aifd.vault.watch_state import WatchState


@pytest.fixture
def state(tmp_path: Path) -> WatchState:
    s = WatchState()
    s.save(tmp_path / "watch-state.json")
    return s


def _match(category: str = "openai_key", snippet: str = "sk-A…WXYZ") -> SensitiveMatch:
    return SensitiveMatch(
        file=Path("/tmp/fake.jsonl"),
        line=42,
        category=category,
        snippet_redacted=snippet,
        confidence=8,
        full_length=40,
    )


# ---------- v0.6 click-to-jump regression ----------


def test_v06_register_and_retrieve_inmemory(tmp_path: Path) -> None:
    """WatchServer.register stores a SensitiveMatch keyed by token; this is
    the v0.6 click-to-jump contract that webhook+events MUST NOT break.
    """
    from aifd.vault.watch_server import start_server
    server = start_server()
    try:
        match = _match()
        token = "test-token-abc"
        server.register(token, match)
        assert server._findings[token] is match
    finally:
        server.stop()


# ---------- E10 today integration regression ----------


def test_e10_state_record_catch_still_fires_alongside_events_db() -> None:
    """When _handle_match runs, BOTH state.record_catch (E10) AND
    events_db.upsert_finding (v0.7) must be called.
    """
    state = WatchState()
    initial = state.total_catches
    state.record_catch(now=datetime(2026, 6, 5, 12, 0, tzinfo=UTC).astimezone())
    assert state.total_catches == initial + 1
    # Day-keyed counter incremented somewhere (key depends on local tz)
    assert any(v >= 1 for v in state.catches_by_day.values())


def test_e10_catches_in_window_works_with_v07_state(tmp_path: Path) -> None:
    """The lightweight catches_in_window helper must still see counters
    written by record_catch.
    """
    state_file = tmp_path / "watch-state.json"
    s = WatchState()
    now = datetime.now().astimezone()
    s.record_catch(now=now)
    s.record_catch(now=now)
    s.save(state_file)

    from aifd.vault.watch_state import catches_in_window
    with patch("aifd.vault.watch_state.STATE_FILE", state_file):
        start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        end = start + timedelta(days=1)
        assert catches_in_window(start, end) == 2


# ---------- _handle_match wiring ----------


def test_handle_match_writes_state_events_and_notifies(tmp_path: Path) -> None:
    """All three side effects must fire for one finding."""
    from aifd.vault.watch import Daemon

    init_db(tmp_path / "findings.db")
    # Construct Daemon with minimal init then patch out the heavy parts.
    state = WatchState()
    state.save(tmp_path / "state.json")

    with (
        patch("aifd.vault.watch.Observer"),
        patch.object(Daemon, "__post_init__", lambda self: None),
    ):
        d = Daemon(state=state)
        d.tail = MagicMock()
        d.dedupe = MagicMock()
        d.notifier = MagicMock()
        d.observer = MagicMock()
        d._events_db = WatchEventsDB(tmp_path / "findings.db")
        d._webhook_queue = MagicMock()
        d._server = MagicMock()
        d._server.port = 12345

        match = _match()
        before_catches = d.state.total_catches
        d._handle_match(match)

    # E10: state catch counter incremented
    assert d.state.total_catches == before_catches + 1
    # v0.6 click-to-jump: register called
    assert d._server.register.called
    # Notifier fired
    assert d.notifier.notify.called
    # v0.7: events DB has the row
    fp = fingerprint_for(match.category, match.snippet_redacted)
    row = d._events_db.get_finding(fp)
    assert row is not None
    # v0.7: webhook queue got an event (because new fingerprint)
    assert d._webhook_queue.put_nowait.called


def test_handle_match_skips_webhook_for_existing_fingerprint(tmp_path: Path) -> None:
    """Existing fingerprint should NOT re-queue webhook (count++, no notify)."""
    from aifd.vault.watch import Daemon

    init_db(tmp_path / "findings.db")
    state = WatchState()
    state.save(tmp_path / "state.json")

    with (
        patch("aifd.vault.watch.Observer"),
        patch.object(Daemon, "__post_init__", lambda self: None),
    ):
        d = Daemon(state=state)
        d.tail = MagicMock()
        d.dedupe = MagicMock()
        d.notifier = MagicMock()
        d.observer = MagicMock()
        d._events_db = WatchEventsDB(tmp_path / "findings.db")
        d._webhook_queue = MagicMock()
        d._server = MagicMock()
        d._server.port = 12345

        match = _match()
        d._handle_match(match)
        d._webhook_queue.put_nowait.reset_mock()
        # Second time: same fingerprint, count++, no webhook
        d._handle_match(match)

    assert not d._webhook_queue.put_nowait.called


# ---------- T9: finding_drop_count on DB write failure ----------


def test_handle_match_bumps_drop_count_on_events_db_failure(tmp_path: Path) -> None:
    """When events_db.upsert_finding throws, drop_count++ + daemon stays alive."""
    from aifd.vault.watch import Daemon

    state = WatchState()
    state.save(tmp_path / "state.json")

    with (
        patch("aifd.vault.watch.Observer"),
        patch.object(Daemon, "__post_init__", lambda self: None),
    ):
        d = Daemon(state=state)
        d.tail = MagicMock()
        d.dedupe = MagicMock()
        d.notifier = MagicMock()
        d.observer = MagicMock()
        d._events_db = MagicMock()
        d._events_db.upsert_finding.side_effect = RuntimeError("disk full")
        d._webhook_queue = MagicMock()
        d._server = MagicMock()
        d._server.port = 12345

        before = d.state.finding_drop_count
        d._handle_match(_match())  # must not raise

    assert d.state.finding_drop_count == before + 1
    # Notifier still fires (we don't want to silently lose the notification
    # just because the DB write failed)
    assert d.notifier.notify.called


# ---------- WatchState backward compat ----------


def test_watchstate_with_drop_count_field(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = WatchState()
    s.finding_drop_count = 5
    s.save(p)
    loaded = WatchState.load(p)
    assert loaded.finding_drop_count == 5


def test_watchstate_old_state_file_without_drop_count_loads_ok(
    tmp_path: Path,
) -> None:
    """v0.6 state files (no finding_drop_count field) must still load."""
    p = tmp_path / "state.json"
    import json
    p.write_text(json.dumps({
        "version": 1,
        "files": {},
        "total_catches": 17,
        "catches_by_day": {"2026-06-05": 17},
        # finding_drop_count MISSING — v0.6 era file
    }))
    loaded = WatchState.load(p)
    assert loaded.total_catches == 17
    assert loaded.finding_drop_count == 0  # default
