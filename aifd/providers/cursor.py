"""Cursor provider.

Storage layout (cross-platform — E2):

  macOS:   ~/Library/Application Support/Cursor/User/
  Linux:   $XDG_CONFIG_HOME/Cursor/User/  (or ~/.config/Cursor/User/)
  Windows: %APPDATA%/Cursor/User/  (deferred — see TODOS.md)

  globalStorage/state.vscdb  (SQLite — ItemTable + cursorDiskKV):
    cursorDiskKV:
      composerData:<id>   — one AI session (composer). name / createdAt / tokenCount.
      bubbleId:<id>:<b>   — conversation bubbles. Presence = real session (E3).
    ItemTable:
      composer.composerHeaders — {allComposers:[{composerId, workspaceIdentifier, ...}]}

  workspaceStorage/<hash>/workspace.json — {folder: "file://<cwd>"}

Why this provider is unlike the other three (Claude/Codex/OpenCode):

  Those store cwd as a first-class column and scope reads with `WHERE
  directory = ?`. Cursor splits sessions (globalStorage) from cwd
  (workspaceStorage) into two stores that don't cross-reference, so cwd
  must be JOINed and the read cannot be cwd-scoped at the SQL layer.

Locked decisions (from /plan-eng-review 2026-06-15):

  E1 cwd mapping (hash-only): a composer's workspaceIdentifier.id, when it is
     a 32-hex-char workspace hash, names a workspaceStorage/<hash>/ dir whose
     workspace.json `folder` is the cwd. Timestamp-form ids have no disk
     workspace and yield no cwd (surfaced via stderr count, E5). ~80% coverage
     on real sessions. bubble-text path inference deferred to P3.
  E3 empty-shell filter: only composers appearing in bubbleId:* (real
     conversation content) count as sessions, uniformly across list_sessions,
     iter_all_sessions, and list_token_usage. The other ~80% of composerData
     rows are drafts / migration residue that Cursor's own UI doesn't show.
  E4 WAL concurrency: Cursor is a live Electron app writing state.vscdb via WAL
     while we read. Open mode=ro, retry once on lock, then silent skip (D7).
  E5 unmapped visibility: list_sessions prints a one-line stderr count of real
     sessions whose cwd couldn't be resolved.
  E6 full-scan cost: list_sessions early-returns when the target cwd matches no
     workspace folder, skipping the bubble scan entirely. Disk cache → P3.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation, TokenUsage
from aifd.paths import cwd_equal, normalize_cwd
from aifd.providers._utils import normalize_title

logger = logging.getLogger("aifd.providers.cursor")

# A workspaceIdentifier.id in 32-hex-char form names a workspaceStorage dir.
# Timestamp-form ids (pure digits) have no on-disk workspace (E1).
_WS_HASH_RE = re.compile(r"^[0-9a-f]{32}$")


class CursorProvider:
    name = "cursor"

    def __init__(self, root: Path | None = None) -> None:
        """Args:
            root: the Cursor `User` directory containing `globalStorage/` and
                `workspaceStorage/`. Defaults to the platform-native location.
                Tests inject a fixture path.
        """
        if root is None:
            root = self._default_root()
        self.root = root

    @staticmethod
    def _default_root() -> Path:
        """Platform-native Cursor User dir (E2: macOS + Linux; Windows deferred)."""
        import os

        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Cursor" / "User"
        # Linux (and any non-darwin POSIX): XDG_CONFIG_HOME convention.
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
        base = Path(xdg) if xdg else (Path.home() / ".config")
        return base / "Cursor" / "User"

    def _global_db(self) -> Path:
        return self.root / "globalStorage" / "state.vscdb"

    def _workspace_storage(self) -> Path:
        return self.root / "workspaceStorage"

    # ------------------------------------------------------------------
    # SQLite read (E4: WAL-safe — mode=ro, retry once on lock, silent skip)
    # ------------------------------------------------------------------

    def _connect_ro(self, db_path: Path) -> sqlite3.Connection | None:
        """Open a read-only connection, retrying once on a transient lock.

        Cursor writes state.vscdb via WAL while running. mode=ro lets readers
        coexist, but a hot WAL DB can still raise `database is locked` or
        SQLITE_READONLY mid-checkpoint. We retry once, then give up (D7 silent
        skip) — missing the newest session on a rare race is acceptable; it
        appears on the next list.
        """
        uri = f"file:{db_path}?mode=ro"
        for attempt in (1, 2):
            try:
                conn = sqlite3.connect(uri, uri=True, timeout=5.0)
                conn.row_factory = sqlite3.Row
                return conn
            except sqlite3.Error as exc:
                if attempt == 1:
                    logger.debug("Cursor DB busy (%s), retrying once: %s", db_path, exc)
                    continue
                logger.warning("Cursor DB unreadable after retry (%s): %s", db_path, exc)
                return None
        return None

    # ------------------------------------------------------------------
    # Shared index builders
    # ------------------------------------------------------------------

    def _workspace_folders(self) -> dict[str, Path]:
        """Map workspaceStorage hash -> cwd (from each workspace.json `folder`)."""
        out: dict[str, Path] = {}
        ws_root = self._workspace_storage()
        if not ws_root.is_dir():
            return out
        try:
            entries = list(ws_root.iterdir())
        except OSError as exc:
            logger.warning("Cannot list Cursor workspaceStorage %s: %s", ws_root, exc)
            return out
        for entry in entries:
            wj = entry / "workspace.json"
            try:
                folder = json.loads(wj.read_text(encoding="utf-8")).get("folder", "")
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
            if isinstance(folder, str) and folder.startswith("file://"):
                out[entry.name] = Path(folder[7:])
        return out

    def _composer_cwd_map(
        self, conn: sqlite3.Connection, ws_folders: dict[str, Path]
    ) -> dict[str, Path]:
        """composerId -> cwd via composerHeaders.workspaceIdentifier hash (E1)."""
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key='composer.composerHeaders'"
        ).fetchone()
        if row is None or not isinstance(row["value"], str):
            return {}
        try:
            headers = json.loads(row["value"]).get("allComposers", [])
        except (json.JSONDecodeError, AttributeError):
            return {}
        out: dict[str, Path] = {}
        for h in headers:
            if not isinstance(h, dict):
                continue
            cid = h.get("composerId")
            wsid = h.get("workspaceIdentifier")
            wid = wsid.get("id", "") if isinstance(wsid, dict) else ""
            if (
                isinstance(cid, str)
                and isinstance(wid, str)
                and _WS_HASH_RE.match(wid)
                and wid in ws_folders
            ):
                out[cid] = ws_folders[wid]
        return out

    def _real_composer_bubble_counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        """composerId -> bubble count, for composers with >=1 bubble (E3).

        A composer is a "real session" iff it has conversation bubbles. Reads
        only bubbleId keys (not values) — the empty-shell filter is cheap.
        Bubble count doubles as event_count.
        """
        counts: dict[str, int] = {}
        for r in conn.execute(
            "SELECT key FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
        ):
            key = r["key"]
            if not isinstance(key, str):
                continue
            parts = key.split(":")
            if len(parts) >= 2 and parts[1]:
                counts[parts[1]] = counts.get(parts[1], 0) + 1
        return counts

    # ------------------------------------------------------------------
    # list_sessions  (E5 stderr count, E6 early-return)
    # ------------------------------------------------------------------

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        target = normalize_cwd(cwd)
        db_path = self._global_db()
        if not db_path.is_file():
            logger.debug("Cursor globalStorage DB not found at %s", db_path)
            return

        ws_folders = self._workspace_folders()
        # E6 early-return: if no workspace folder matches target, no hash-mapped
        # session can belong here — skip the full bubble scan entirely.
        if not any(cwd_equal(normalize_cwd(f), target) for f in ws_folders.values()):
            return

        conn = self._connect_ro(db_path)
        if conn is None:
            return
        try:
            cwd_map = self._composer_cwd_map(conn, ws_folders)
            bubble_counts = self._real_composer_bubble_counts(conn)
            unmapped = 0
            for cid, n_bubbles in bubble_counts.items():
                mapped = cwd_map.get(cid)
                if mapped is None:
                    unmapped += 1
                    continue
                if not cwd_equal(normalize_cwd(mapped), target):
                    continue
                session = self._read_composer_session(conn, cid, mapped, n_bubbles, db_path)
                if session is not None:
                    yield session
        finally:
            conn.close()

        # E5: surface the silent loss (only when there is something to report).
        if unmapped:
            print(
                f"Note: {unmapped} Cursor session(s) have no resolvable cwd "
                f"(run `aifd ai retro` to see all).",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # iter_all_sessions  (E3: all real sessions, cwd best-effort)
    # ------------------------------------------------------------------

    def iter_all_sessions(self) -> Iterator[Session]:
        db_path = self._global_db()
        if not db_path.is_file():
            return
        conn = self._connect_ro(db_path)
        if conn is None:
            return
        try:
            ws_folders = self._workspace_folders()
            cwd_map = self._composer_cwd_map(conn, ws_folders)
            bubble_counts = self._real_composer_bubble_counts(conn)
            for cid, n_bubbles in bubble_counts.items():
                # No cwd → Path("") sentinel (same as Codex global scan). retro/
                # habits aggregate on started_at / event_count, not cwd.
                mapped = cwd_map.get(cid, Path(""))
                session = self._read_composer_session(conn, cid, mapped, n_bubbles, db_path)
                if session is not None:
                    yield session
        finally:
            conn.close()

    def _read_composer_session(
        self,
        conn: sqlite3.Connection,
        cid: str,
        cwd: Path,
        event_count: int,
        db_path: Path,
    ) -> Session | None:
        """Build a Session from one composerData row. silent skip on bad JSON."""
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key=?", (f"composerData:{cid}",)
        ).fetchone()
        if row is None or not isinstance(row["value"], str):
            return None
        try:
            d = json.loads(row["value"])
        except json.JSONDecodeError:
            logger.debug("Cursor composerData:%s malformed JSON", cid)
            return None
        name = d.get("name")
        title = normalize_title(name) if isinstance(name, str) and name.strip() else None
        return Session(
            provider=self.name,
            session_id=cid,
            cwd=cwd,
            started_at=_ms_to_dt(d.get("createdAt")),
            event_count=event_count,
            source_path=db_path,
            title=title,
        )

    # ------------------------------------------------------------------
    # list_token_usage  (E3 filter; best-effort — composerData.tokenCount)
    # ------------------------------------------------------------------

    def list_token_usage(
        self, scope: Path | None = None
    ) -> Iterable[TokenUsage]:
        """Emit TokenUsage for real sessions that carry a composerData.tokenCount.

        Cursor's composerData.tokenCount is often null (token detail lives in
        per-bubble payloads); we emit only when a usable total is present.
        Full per-bubble token summation is deferred (see TODOS). Model is not
        recorded at composer granularity, so it stays None.
        """
        db_path = self._global_db()
        if not db_path.is_file():
            return
        conn = self._connect_ro(db_path)
        if conn is None:
            return
        try:
            ws_folders = self._workspace_folders()
            cwd_map = self._composer_cwd_map(conn, ws_folders)
            bubble_counts = self._real_composer_bubble_counts(conn)
            target = normalize_cwd(scope) if scope is not None else None
            for cid in bubble_counts:
                mapped = cwd_map.get(cid)
                if target is not None:
                    if mapped is None or not cwd_equal(normalize_cwd(mapped), target):
                        continue
                row = conn.execute(
                    "SELECT value FROM cursorDiskKV WHERE key=?",
                    (f"composerData:{cid}",),
                ).fetchone()
                if row is None or not isinstance(row["value"], str):
                    continue
                try:
                    d = json.loads(row["value"])
                except json.JSONDecodeError:
                    continue
                total = _safe_int(d.get("tokenCount"))
                if total <= 0:
                    continue
                yield TokenUsage(
                    provider=self.name,
                    session_id=cid,
                    cwd=mapped,
                    ts=_ms_to_dt(d.get("createdAt")),
                    model=None,
                    input_tokens=total,
                    output_tokens=0,
                    source_path=db_path,
                )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # No-op stubs (Cursor has no skills directory / structured AUQ)
    # ------------------------------------------------------------------

    def list_installed_skills(self) -> Iterable[InstalledSkill]:
        return ()

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        return ()

    def list_question_answers(
        self, scope: Path | None = None
    ) -> Iterable[QuestionAnswer]:
        return ()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _ms_to_dt(ms: object) -> datetime | None:
    if not isinstance(ms, int) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
