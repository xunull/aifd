"""Persistent events store for `aifd vault watch` (v0.7).

SQLite-backed history of every finding the daemon has captured. Companion
to `watch_state.py` (which tracks per-file scan offsets + day counters):
this module tracks per-finding lifecycle.

Architectural locks (from /plan-eng-review 2026-06-05):

  D1 — per-thread connection + WAL mode. SQLite `journal_mode=WAL` lets
       readers (HTTP server, webhook deliverer) not block writers (worker).
       Each thread owns its own connection; never share across threads.

  D2 — fingerprint = SHA1(category + snippet_redacted). file_path is NOT
       part of the fingerprint. Same secret in 3 different files = ONE
       finding with 3 occurrences. Cross-machine stable. Webhook payloads
       only ever leak file basename, not absolute paths.

  D6 — LIMIT 50 default + 3 indices: status+last_seen DESC (main list),
       category (filter), fingerprint PK (dedup join).

Data model:

    findings (1) ←——————— (N) finding_occurrences
        │
        │  fingerprint = SHA1(category + snippet_redacted)
        │  status state machine: new → ack → resolved
        │                          ↘ muted (with optional expiry)
        │                          ↘ (re-detect re-opens to new)
        │
        └─→ webhook_dead_letter (N)
                fingerprint, webhook_id, attempted_at, last_error

Atomicity: every status mutation runs in a transaction. WAL crash-safety
means a SIGKILL mid-write either commits cleanly or leaves the prior
state on disk — never half-written rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aifd.vault.events_db")

_SCHEMA_VERSION = 1

# Status state machine.
STATUS_NEW = "new"
STATUS_ACKNOWLEDGED = "acknowledged"
STATUS_RESOLVED = "resolved"
STATUS_MUTED = "muted"
_VALID_STATUSES = {STATUS_NEW, STATUS_ACKNOWLEDGED, STATUS_RESOLVED, STATUS_MUTED}

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS findings (
        fingerprint TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        snippet_redacted TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        count INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'new',
        muted_until TEXT,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS finding_occurrences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL REFERENCES findings(fingerprint),
        file_basename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        line INTEGER NOT NULL,
        byte_offset INTEGER NOT NULL DEFAULT 0,
        seen_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS webhook_dead_letter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL,
        webhook_id TEXT NOT NULL,
        payload TEXT NOT NULL,
        attempted_at TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        last_error TEXT
    )
    """,
    (
        "CREATE INDEX IF NOT EXISTS idx_findings_status_last_seen "
        "ON findings(status, last_seen DESC)"
    ),
    "CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category)",
    (
        "CREATE INDEX IF NOT EXISTS idx_occurrences_fp_seen "
        "ON finding_occurrences(fingerprint, seen_at DESC)"
    ),
]


def fingerprint_for(category: str, snippet_redacted: str) -> str:
    """SHA1(category + snippet_redacted). Stable across machines / user names.

    Returns first 16 chars of hex digest (~64 bits, plenty for personal
    catalog scope; full SHA1 is overkill and crowds the URL).
    """
    h = hashlib.sha1(f"{category}:{snippet_redacted}".encode())
    return h.hexdigest()[:16]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def init_db(path: Path) -> None:
    """Create schema + enable WAL on the given path.

    Idempotent: safe to call on every daemon start. Use a temporary
    connection that we close immediately; long-lived connections live
    on each thread via WatchEventsDB().
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        # WAL is the whole point of the design decision (D1). Set it
        # before any writes so the journal file is created correctly.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # WAL + NORMAL = safe + fast
        conn.execute("PRAGMA foreign_keys=ON")
        for stmt in _DDL:
            conn.execute(stmt)
        cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cur.fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version(version) VALUES (?)", (_SCHEMA_VERSION,),
            )
        elif row[0] != _SCHEMA_VERSION:
            # Future-proofing: surface unknown schemas loudly instead of
            # silently corrupting. v0.7 has no migration to run.
            logger.warning(
                "events DB schema version %d not recognized (expected %d)",
                row[0], _SCHEMA_VERSION,
            )
        conn.commit()
    finally:
        conn.close()


class WatchEventsDB:
    """Per-thread events store connection.

    Each thread that touches the DB owns one of these. Construct lazily
    via `threading.local` or pass explicitly. Do NOT share across threads
    — SQLite connections are not thread-safe even under WAL.

    Typical usage:

        # in Daemon worker thread
        events = WatchEventsDB(EVENTS_DB_PATH)
        events.upsert_finding(match, file_basename, file_path, line, ts)

        # in HTTP handler thread
        events = WatchEventsDB(EVENTS_DB_PATH)
        rows = events.list_findings(status="new", limit=50)
    """

    def __init__(self, path: Path) -> None:
        # check_same_thread=False is safe ONLY because each thread owns
        # its own instance — we're not sharing. WAL handles the actual
        # cross-thread coordination via SQLite's locking.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()  # serializes writes from THIS connection

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error as exc:
            logger.debug("close events DB: %s", exc)

    # ---------- writes (worker thread + HTTP mutations) ----------

    def upsert_finding(
        self,
        category: str,
        snippet_redacted: str,
        file_basename: str,
        file_path: str,
        line: int,
        byte_offset: int = 0,
        now: datetime | None = None,
    ) -> tuple[str, bool]:
        """Insert a new finding or bump count on an existing fingerprint.

        Re-opens resolved findings (resolved → new + count=1) so users
        see new detections of a previously-resolved leak. Muted findings
        increment count silently and stay muted.

        Returns (fingerprint, is_new). `is_new` is True when this is the
        first time we've seen this fingerprint OR when a previously-resolved
        finding was re-opened — the caller uses this to decide whether to
        fire `new_finding` webhooks.
        """
        fp = fingerprint_for(category, snippet_redacted)
        ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT status FROM findings WHERE fingerprint = ?", (fp,),
            )
            row = cur.fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO findings (
                        fingerprint, category, snippet_redacted,
                        first_seen, last_seen, count, status
                    ) VALUES (?, ?, ?, ?, ?, 1, 'new')
                    """,
                    (fp, category, snippet_redacted, ts, ts),
                )
                is_new = True
            elif row["status"] == STATUS_RESOLVED:
                # Re-open: same secret reappeared after being marked
                # resolved. Treat as a fresh new finding (count resets,
                # status=new) so user is alerted again.
                self._conn.execute(
                    """
                    UPDATE findings
                    SET status='new', count=1, last_seen=?
                    WHERE fingerprint=?
                    """,
                    (ts, fp),
                )
                is_new = True
            else:
                self._conn.execute(
                    """
                    UPDATE findings
                    SET count = count + 1, last_seen = ?
                    WHERE fingerprint = ?
                    """,
                    (ts, fp),
                )
                is_new = False
            self._conn.execute(
                """
                INSERT INTO finding_occurrences (
                    fingerprint, file_basename, file_path, line,
                    byte_offset, seen_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (fp, file_basename, file_path, line, byte_offset, ts),
            )
        return fp, is_new

    def mutate_status(
        self,
        fingerprint: str,
        new_status: str,
        mute_hours: float | None = None,
    ) -> bool:
        """Move a finding between states.

        `mute_hours=None` + `new_status=muted` means mute forever. Other
        statuses ignore `mute_hours`. Returns False if the fingerprint is
        unknown or the transition is invalid.
        """
        if new_status not in _VALID_STATUSES:
            raise ValueError(f"unknown status: {new_status}")
        muted_until: str | None = None
        if new_status == STATUS_MUTED and mute_hours is not None:
            muted_until = (
                datetime.now(UTC)
                + _hours_delta(mute_hours)
            ).isoformat(timespec="seconds")
        with self._lock, self._conn:
            if new_status == STATUS_MUTED:
                cur = self._conn.execute(
                    """
                    UPDATE findings
                    SET status=?, muted_until=?
                    WHERE fingerprint=?
                    """,
                    (new_status, muted_until, fingerprint),
                )
            else:
                cur = self._conn.execute(
                    """
                    UPDATE findings
                    SET status=?, muted_until=NULL
                    WHERE fingerprint=?
                    """,
                    (new_status, fingerprint),
                )
            return cur.rowcount > 0

    def set_note(self, fingerprint: str, text: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE findings SET notes=? WHERE fingerprint=?",
                (text, fingerprint),
            )
            return cur.rowcount > 0

    def expire_mutes(self, now: datetime | None = None) -> int:
        """Transition muted findings whose timer has expired back to new.

        Called by the sweeper. Returns the number of rows flipped.
        """
        ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                UPDATE findings
                SET status='new', muted_until=NULL
                WHERE status='muted' AND muted_until IS NOT NULL
                  AND muted_until <= ?
                """,
                (ts,),
            )
            return int(cur.rowcount)

    # ---------- reads (HTTP server + CLI) ----------

    def list_findings(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Paginated list, default LIMIT 50 (D6)."""
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        if since:
            where.append("last_seen >= ?")
            params.append(since.isoformat(timespec="seconds"))
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        cur = self._conn.execute(
            f"""
            SELECT fingerprint, category, snippet_redacted,
                   first_seen, last_seen, count, status,
                   muted_until, notes
            FROM findings
            {clause}
            ORDER BY last_seen DESC
            LIMIT ? OFFSET ?
            """,
            params,
        )
        return list(cur.fetchall())

    def count_findings(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
    ) -> int:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        cur = self._conn.execute(
            f"SELECT COUNT(*) FROM findings {clause}", params,
        )
        return int(cur.fetchone()[0])

    def get_finding(self, fingerprint: str) -> sqlite3.Row | None:
        cur = self._conn.execute(
            """
            SELECT fingerprint, category, snippet_redacted,
                   first_seen, last_seen, count, status,
                   muted_until, notes
            FROM findings
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        )
        row: sqlite3.Row | None = cur.fetchone()
        return row

    def list_occurrences(
        self, fingerprint: str, limit: int = 50,
    ) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """
            SELECT id, file_basename, file_path, line, byte_offset, seen_at
            FROM finding_occurrences
            WHERE fingerprint = ?
            ORDER BY seen_at DESC
            LIMIT ?
            """,
            (fingerprint, limit),
        )
        return list(cur.fetchall())

    def export_findings_ndjson(self) -> Iterable[str]:
        """Yield one JSON line per finding for `events export --format ndjson`.

        Streams without loading all into memory.
        """
        cur = self._conn.execute(
            """
            SELECT fingerprint, category, snippet_redacted,
                   first_seen, last_seen, count, status,
                   muted_until, notes
            FROM findings
            ORDER BY first_seen ASC
            """,
        )
        for row in cur:
            yield json.dumps(dict(row), ensure_ascii=False)

    # ---------- dead letter (webhooks) ----------

    def add_dead_letter(
        self,
        fingerprint: str,
        webhook_id: str,
        payload: str,
        attempts: int,
        last_error: str,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO webhook_dead_letter (
                    fingerprint, webhook_id, payload,
                    attempted_at, attempts, last_error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    fingerprint, webhook_id, payload,
                    _utcnow_iso(), attempts, last_error,
                ),
            )

    def list_dead_letter(self, limit: int = 100) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            """
            SELECT id, fingerprint, webhook_id, payload,
                   attempted_at, attempts, last_error
            FROM webhook_dead_letter
            ORDER BY attempted_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def drop_dead_letter(self, dead_letter_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM webhook_dead_letter WHERE id = ?", (dead_letter_id,),
            )
            return cur.rowcount > 0

    def clear_dead_letter(self) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM webhook_dead_letter")
            return int(cur.rowcount)


def _hours_delta(hours: float) -> Any:
    from datetime import timedelta
    return timedelta(hours=hours)
