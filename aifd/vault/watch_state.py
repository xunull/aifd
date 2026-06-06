"""Persisted state for `aifd vault watch` — kept separate from watch.py.

watch.py imports `watchdog` (a native-ext dependency); this module does
not. Read-only consumers (`aifd ai today` / weekly / monthly via the
E10 catches-in-window line) can pull stats without pulling watchdog
into the import graph.

Shape of the JSON file (~/.aifd/watch-state.json):

    {
      "version": 1,
      "files": {
        "/Users/x/.claude/projects/-foo/abc.jsonl": {
          "offset": 12345,
          "size": 12345,
          "mtime": 1733412345.0,
          "line_no": 87
        },
        ...
      },
      "total_catches": 17,
      "catches_by_day": {"2026-06-04": 3, "2026-06-05": 2}
    }

`catches_by_day` keys are local-date strings ("YYYY-MM-DD") so the
E10 today/weekly windows (local-tz) line up without conversion math.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aifd.vault.watch_state")

AIFD_HOME = Path.home() / ".aifd"
STATE_FILE = AIFD_HOME / "watch-state.json"
PID_FILE = AIFD_HOME / "watch.pid"
LOG_FILE = AIFD_HOME / "watch.log"
PORT_FILE = AIFD_HOME / "watch.port"

_STATE_SCHEMA_VERSION = 1


@dataclass
class WatchState:
    """Persisted per-file scan progress + daily catch counters.

    Written atomically via temp-file + rename so SIGKILL mid-write does
    not corrupt. On load, an unrecognized `version` triggers a reset to
    empty — conservative: better to rescan than serve corrupt state.

    `files[path]` shape: `{"offset": int, "size": int, "mtime": float,
    "line_no": int}`. line_no is best-effort (counted forward from last
    known offset) and is used only to attribute matches to a line in
    the source file for the UI; the offset is authoritative for "what
    has been scanned".
    """

    version: int = _STATE_SCHEMA_VERSION
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_catches: int = 0
    catches_by_day: dict[str, int] = field(default_factory=dict)
    # v0.7 T9: count of findings that hit a write failure (disk full, SQLite
    # error). Exposed via `aifd vault watch status` so silent loss is visible.
    finding_drop_count: int = 0

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> WatchState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Corrupt state file %s: %s — resetting", path, exc)
            return cls()
        if data.get("version") != _STATE_SCHEMA_VERSION:
            logger.warning(
                "Unknown state version %r (expected %d) — resetting",
                data.get("version"), _STATE_SCHEMA_VERSION,
            )
            return cls()
        return cls(
            version=data["version"],
            files=data.get("files", {}),
            total_catches=data.get("total_catches", 0),
            catches_by_day=data.get("catches_by_day", {}),
            finding_drop_count=data.get("finding_drop_count", 0),
        )

    def save(self, path: Path = STATE_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": self.version,
                    "files": self.files,
                    "total_catches": self.total_catches,
                    "catches_by_day": self.catches_by_day,
                    "finding_drop_count": self.finding_drop_count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)

    def record_catch(self, now: datetime | None = None) -> None:
        # Use local date for the key so `catches_in_window` (which works in
        # local time) lines up. A catch that happens at 23:30 local lives
        # on "today", not "yesterday UTC".
        now = now or datetime.now().astimezone()
        day = now.astimezone().strftime("%Y-%m-%d")
        self.total_catches += 1
        self.catches_by_day[day] = self.catches_by_day.get(day, 0) + 1

    def catches_in_window(self, start: datetime, end: datetime) -> int:
        """Sum daily catches that fall in [start, end) using local date keys.

        catches_by_day uses local-date string keys ("YYYY-MM-DD"). Convert
        the window bounds to the same key format and sum inclusive of the
        start day, exclusive of the end day. Out-of-range keys are skipped
        — keeps the function safe for windows that don't align to midnight.
        """
        start_day = start.astimezone().date()
        end_day = end.astimezone().date()
        total = 0
        for key, count in self.catches_by_day.items():
            try:
                d = datetime.strptime(key, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start_day <= d < end_day:
                total += count
        return total


def catches_in_window(start: datetime, end: datetime) -> int:
    """Public helper: read state file from disk, sum catches in window.

    Returns 0 if the daemon has never run (no state file). Used by
    `aifd ai today / weekly / monthly` for the watch-catches line.

    This helper is intentionally kept in this lightweight module (no
    watchdog dependency) so the `aifd ai today` codepath doesn't pull
    a native-ext dep into its import graph.

    Resolves STATE_FILE through the module (not the class default) so
    tests can monkeypatch the location.
    """
    import aifd.vault.watch_state as _self
    return WatchState.load(_self.STATE_FILE).catches_in_window(start, end)
