"""Real-time secret detection daemon for `aifd vault watch`.

Watches every provider's jsonl roots (Claude / Codex). When a new line lands,
runs the v0.4 detector pipeline (regex + entropy + suppressors) against it
and pushes a macOS notification when a real match survives. The v0.6 + v0.7
plan reviews locked these architectural decisions:

  D1 — queue.Queue + single worker thread serializes ALL state mutations
       (state file, dedupe cache, counters). watchdog callbacks just push
       events; no shared-mutable-state race possible. v0.7 adds events DB
       writes in the same worker (SQLite WAL handles cross-thread reads).

  D2 — A long-running HTTP server (in watch_server.py) hosts click-to-jump
       URLs + (v0.7) the events list/detail API + web UI. Single port,
       lives with the daemon, dies with it.

  D3 — A periodic 5-minute full-sweep timer runs in parallel with the
       event-driven scan. Catches anything watchdog drops (inotify queue
       overflow, FSEvents coalescing). Belt-and-suspenders.

  D4 (v0.7) — webhook delivery on its own worker thread, fed by a queue
       from the main worker. dead_letter persists to events DB on
       permanent failure; CLI surfaces a manual `retry-dead-letter`.

Architecture (data flow):

    watchdog Observer (1 emitter thread + 1 dispatcher thread)
         │
         │ on_modified(path) → queue.put_nowait(path)
         ▼
    event_queue: queue.Queue[Path]   ──┐
         │                              │
         │                              │ 5-min sweeper thread
         │                              │ enqueues every tracked path
         ▼                              │
    worker thread (single)        ◀────┘
         │
         │ for each path:
         │   TailReader.read_new_lines(path)
         │     for each new line:
         │       _scan_line(...) → SensitiveMatch?
         │         DedupeCache.should_notify(...)?
         │           Notifier.notify(...) + Server.register(...)  (v0.6)
         │           WatchEventsDB.upsert_finding(...)            (v0.7)
         │           state.record_catch()                         (E10)
         │           webhook_queue.put(new_finding_event)         (v0.7)
         │   WatchState.save() (atomic, opportunistic)
         │
         └────────────────────────┐
                                  ▼
                  webhook deliverer thread (v0.7)
                            │
                            │ for each enabled+matching webhook:
                            │   urllib.urlopen(POST aifd_v1 JSON)
                            │   retry 3x exponential
                            │   on permanent failure → events_db.add_dead_letter
                            ▼

    HTTP server thread → serves /, /events, /webhooks, /findings/<token>

SIGTERM / SIGINT flushes the state file, drains the events DB connection,
stops the webhook deliverer, and stops the Observer cleanly. The launchd
`KeepAlive=true` restart contract means a panic just costs ~1 sec of
restart latency.
"""

from __future__ import annotations

import logging
import queue
import secrets
import signal
import subprocess
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from aifd.models import SensitiveMatch
from aifd.providers.registry import PROVIDERS
from aifd.vault.scan import _scan_line
from aifd.vault.watch_state import (
    AIFD_HOME,
    LOG_FILE,
    PID_FILE,
    PORT_FILE,
    STATE_FILE,
    WatchState,
    catches_in_window,
)

# v0.7 events store path — sibling of state.json. Keep this here rather
# than in watch_state.py to avoid forcing the lightweight module to know
# about events_db.
EVENTS_DB_PATH = AIFD_HOME / "findings.db"
WEBHOOKS_YAML_PATH = AIFD_HOME / "webhooks.yaml"

if TYPE_CHECKING:
    from aifd.vault.watch_server import WatchServer
    from aifd.vault.webhooks import WebhookDeliverer

logger = logging.getLogger("aifd.vault.watch")


# ---------- paths + constants ----------

# Path constants all re-exported from watch_state (the lightweight module).

# Dedupe window for "same secret seen N times in this window = 1 notification".
# Tuned to catch paste loops without missing genuine new occurrences.
_DEDUPE_TTL = timedelta(minutes=5)
_DEDUPE_MAX = 1000

# Re-export markers so tests / CLI consumers keep the same import surface
# even though the canonical home is now watch_state.
__all__ = [
    "AIFD_HOME",
    "LOG_FILE",
    "PID_FILE",
    "PORT_FILE",
    "STATE_FILE",
    "Daemon",
    "DedupeCache",
    "Notifier",
    "TailReader",
    "WatchState",
    "catches_in_window",
]

# Periodic full-sweep cadence — catches anything watchdog dropped (rare, but
# inotify queue overflow + FSEvents coalescing are documented characteristics).
_SWEEP_INTERVAL_SEC = 300

# Event queue bound — if user pastes a giant .env into Claude, we backpressure
# (drop oldest) instead of OOMing. Real workloads are < 100 events/day; this
# is paranoia for the chaos case.
_EVENT_QUEUE_MAX = 1000

# Match the v0.4 scan default: confidence 7+ surfaces, entropy hits stay quiet.
_DEFAULT_MIN_CONFIDENCE = 7


# ---------- TailReader (offset-based line iteration) ----------


class TailReader:
    """Yield only the NEW lines from a jsonl since the last read.

    Handles file rotation (size shrinks → re-read from 0), truncation,
    and partial trailing lines (a line still being written by Claude
    won't be emitted half-formed — wait for the trailing `\\n`).
    """

    def __init__(self, state: WatchState) -> None:
        self._state = state

    def read_new_lines(self, path: Path) -> Iterable[tuple[int, str]]:
        key = str(path)
        rec = self._state.files.get(
            key, {"offset": 0, "size": 0, "mtime": 0.0, "line_no": 0}
        )
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._state.files.pop(key, None)
            return

        # File shrank → assume rotation / truncation. Restart from 0.
        if stat.st_size < rec["offset"]:
            logger.debug(
                "File %s shrank (%d → %d), reading from start",
                path, rec["offset"], stat.st_size,
            )
            rec = {"offset": 0, "size": 0, "mtime": 0.0, "line_no": 0}

        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(rec["offset"])
                buf = f.read()
        except OSError as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return

        if not buf:
            return

        lines = buf.splitlines(keepends=True)
        # Last line may be partial (no trailing newline). Don't emit it
        # — leave its bytes in the unconsumed range so next read picks
        # it up complete.
        emit = lines
        if lines and not lines[-1].endswith(("\n", "\r")):
            emit = lines[:-1]
            consumed = sum(len(line) for line in emit)
        else:
            consumed = len(buf)

        cur_line_no = rec.get("line_no", 0)
        for line in emit:
            cur_line_no += 1
            yield (cur_line_no, line.rstrip("\n\r"))

        self._state.files[key] = {
            "offset": rec["offset"] + consumed,
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "line_no": cur_line_no,
        }


# ---------- DedupeCache (5-min LRU by category+snippet) ----------


class DedupeCache:
    """Quiet duplicate notifications within a sliding window.

    Key: (category, snippet_redacted) — same secret hitting 10 times in
    a paste loop ⇒ 1 notification. The 5-minute TTL is plenty of time
    for the user to read + act on the first notification; new occurrences
    after that genuinely warrant a re-alert.
    """

    def __init__(
        self,
        ttl: timedelta = _DEDUPE_TTL,
        max_entries: int = _DEDUPE_MAX,
    ) -> None:
        self._ttl = ttl
        self._max = max_entries
        self._seen: OrderedDict[tuple[str, str], datetime] = OrderedDict()

    def should_notify(
        self, category: str, snippet: str, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(UTC)
        self._evict_expired(now)
        key = (category, snippet)
        if key in self._seen:
            self._seen.move_to_end(key)
            return False
        self._seen[key] = now
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return True

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - self._ttl
        # OrderedDict insertion order = age; pop from front while expired.
        while self._seen:
            oldest_key = next(iter(self._seen))
            if self._seen[oldest_key] < cutoff:
                self._seen.popitem(last=False)
            else:
                break


# ---------- Notifier (osascript / terminal-notifier) ----------


class Notifier:
    """Dispatch macOS notifications. terminal-notifier if installed (better
    click-to-open support), else osascript fallback (URL in body, no native
    click).

    Failures are caught + logged + reflected in `last_notify_failed` so the
    `status` subcommand can warn the user when permission is silently denied.

    UX caveat — `backend` is `"osascript"` when terminal-notifier is missing.
    osascript's `display notification` AppleScript verb does NOT support a
    click handler; click routes to the app that owns the osascript process
    (Script Editor.app), which is broken UX. We log a startup warning and
    expose `backend` so `aifd vault watch status` can surface it.
    """

    def __init__(self) -> None:
        self._use_terminal_notifier = self._probe_terminal_notifier()
        self.backend = "terminal-notifier" if self._use_terminal_notifier else "osascript"
        self.last_notify_ts: datetime | None = None
        self.last_notify_failed = False
        if not self._use_terminal_notifier:
            logger.warning(
                "terminal-notifier not found; falling back to osascript. "
                "Notification click will open Script Editor instead of the "
                "finding URL. Install with: brew install terminal-notifier"
            )

    @staticmethod
    def _probe_terminal_notifier() -> bool:
        try:
            r = subprocess.run(
                ["which", "terminal-notifier"],
                capture_output=True, timeout=2,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def probe_permission(self) -> bool:
        """Send one test notification at startup. Returns True on success.

        First-time UX: if user has not allowed notifications for Terminal /
        terminal-notifier in System Preferences, this is the only place
        we'll see the failure — daemon would otherwise be silently broken.
        """
        try:
            self._dispatch(
                "aifd watch",
                "Watch daemon started — notifications working.",
                url=None,
            )
            return True
        except Exception as exc:
            logger.warning("Notification permission probe failed: %s", exc)
            return False

    def notify(self, title: str, body: str, url: str | None = None) -> None:
        try:
            self._dispatch(title, body, url)
            self.last_notify_ts = datetime.now(UTC)
            self.last_notify_failed = False
        except Exception as exc:
            self.last_notify_failed = True
            logger.warning("Notification dispatch failed: %s", exc)

    def _dispatch(self, title: str, body: str, url: str | None) -> None:
        if self._use_terminal_notifier:
            cmd = [
                "terminal-notifier",
                "-title", title,
                "-message", body,
                "-sound", "default",
            ]
            if url:
                cmd.extend(["-open", url])
            subprocess.run(cmd, capture_output=True, timeout=5, check=True)
        else:
            # osascript path: click is non-functional (routes to Script
            # Editor.app), so don't put the long URL in the body — it just
            # gets truncated and confuses users. Tell them how to fix it.
            if url:
                full = (
                    f"{body}\nclick disabled — run `brew install "
                    "terminal-notifier`"
                )
            else:
                full = body
            esc_t = title.replace('"', '\\"')
            esc_b = full.replace('"', '\\"')
            script = (
                f'display notification "{esc_b}" with title "{esc_t}" '
                'sound name "Glass"'
            )
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5, check=True,
            )


# ---------- Daemon (the long-running process) ----------


# Dynamic import to avoid a hard load cycle if the user imports watch.py
# without ever spinning the daemon (e.g. running unit tests on TailReader).
def _load_server_module() -> Any:
    from aifd.vault import watch_server
    return watch_server


class _Handler(FileSystemEventHandler):
    """Forward every modify/create event for `*.jsonl` into the queue.

    Empty handler body keeps watchdog's worker thread cheap; the real
    work (tail-read + scan + notify) runs on our serialization worker.
    """

    def __init__(self, event_queue: queue.Queue[Path]) -> None:
        super().__init__()
        self._q = event_queue

    def on_modified(self, event: FileSystemEvent) -> None:
        self._enqueue(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._enqueue(event)

    def _enqueue(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # watchdog returns bytes | str depending on platform — normalize.
        raw = event.src_path
        src = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not src.endswith(".jsonl"):
            return
        try:
            self._q.put_nowait(Path(src))
        except queue.Full:
            # Drop oldest, put new — bounded backpressure.
            try:
                self._q.get_nowait()
                self._q.put_nowait(Path(src))
            except queue.Empty:
                pass


@dataclass
class Daemon:
    """Long-running watch daemon. Run via `daemon = Daemon(); daemon.run()`.

    Lifecycle:
      1. Load state, init Observer/queue/worker, start HTTP server,
         probe notification permission.
      2. Schedule full-sweep timer thread.
      3. Install SIGTERM/SIGINT handlers.
      4. Block on event_queue.get() — worker thread loop.
      5. On shutdown signal: stop Observer, drain queue, save state,
         stop HTTP server.
    """

    state: WatchState = field(default_factory=WatchState.load)
    event_queue: queue.Queue[Path] = field(
        default_factory=lambda: queue.Queue(maxsize=_EVENT_QUEUE_MAX),
    )
    tail: TailReader = field(init=False)
    dedupe: DedupeCache = field(init=False)
    notifier: Notifier = field(init=False)
    observer: BaseObserver = field(init=False)
    _server: WatchServer | None = field(default=None, init=False)
    _events_db: Any = field(default=None, init=False)
    _webhook_deliverer: WebhookDeliverer | None = field(default=None, init=False)
    _webhook_queue: Any = field(default=None, init=False)
    _webhook_thread: threading.Thread | None = field(default=None, init=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False)

    def __post_init__(self) -> None:
        self.tail = TailReader(self.state)
        self.dedupe = DedupeCache()
        self.notifier = Notifier()
        # Observer() returns a platform-specific BaseObserver subclass
        # (FSEventsObserver on macOS, InotifyObserver on Linux).
        self.observer = Observer()

    # ----- lifecycle -----

    def run(self) -> None:
        AIFD_HOME.mkdir(parents=True, exist_ok=True)

        # v0.7: init events DB before HTTP server so the server can read
        # existing findings on first request.
        from aifd.vault.events_db import WatchEventsDB, init_db
        init_db(EVENTS_DB_PATH)
        self._events_db = WatchEventsDB(EVENTS_DB_PATH)

        # v0.7: webhook delivery thread (queue + worker).
        from aifd.vault.webhooks import WebhookDeliverer, load_webhooks_yaml
        self._webhook_queue = queue.Queue(maxsize=10000)
        self._webhook_deliverer = WebhookDeliverer(
            events_db=WatchEventsDB(EVENTS_DB_PATH),  # per-thread (D1)
            delivery_queue=self._webhook_queue,
            config_provider=lambda: load_webhooks_yaml(WEBHOOKS_YAML_PATH),
        )
        self._webhook_thread = threading.Thread(
            target=self._webhook_deliverer.run,
            name="watch-webhook-deliverer",
            daemon=True,
        )
        self._webhook_thread.start()

        # Start HTTP server before anything emits findings, so notifications
        # can include a working URL from the very first match. v0.7 wires
        # the events DB factory + webhooks config path into the server so it
        # can serve /events and /webhooks endpoints.
        server_module = _load_server_module()
        self._server = server_module.start_server(
            events_db_factory=lambda: WatchEventsDB(EVENTS_DB_PATH),
            webhooks_path=WEBHOOKS_YAML_PATH,
            retry_dead_letter_cb=self._retry_dead_letter,
        )
        PORT_FILE.write_text(str(self._server.port))
        logger.info("Server bound: http://127.0.0.1:%d/", self._server.port)

        # First-time UX: announce + verify permission before the user's
        # first real secret hits.
        self.notifier.probe_permission()

        # Set up watchdog Observer on each provider root.
        handler = _Handler(self.event_queue)
        for root in self._roots_to_watch():
            if root.is_dir():
                self.observer.schedule(handler, str(root), recursive=True)
                logger.info("Watching %s", root)
        self.observer.start()

        # Worker thread serializes ALL state mutations (D1).
        worker = threading.Thread(
            target=self._worker_loop, name="watch-worker", daemon=True,
        )
        worker.start()

        # Periodic full-sweep timer (D3).
        sweeper = threading.Thread(
            target=self._sweep_loop, name="watch-sweeper", daemon=True,
        )
        sweeper.start()

        # Initial sweep so we catch anything that landed between last
        # daemon stop and current start.
        self._enqueue_all_tracked()

        # SIGTERM (launchd) and SIGINT (Ctrl-C in foreground) both flush
        # and exit cleanly.
        signal.signal(signal.SIGTERM, self._signal_shutdown)
        signal.signal(signal.SIGINT, self._signal_shutdown)

        # Block until _stop_event is set by the signal handler.
        self._stop_event.wait()
        self._shutdown()

    def _shutdown(self) -> None:
        logger.info("Shutdown: stopping observer + saving state")
        self.observer.stop()
        self.observer.join(timeout=5)
        # v0.7: stop webhook deliverer cleanly so in-flight POSTs aren't
        # interrupted mid-flight. The worker checks stop_event between
        # retries; queue-empty timeout returns within 1s.
        if self._webhook_deliverer is not None:
            self._webhook_deliverer.stop_event.set()
        if self._webhook_thread is not None:
            self._webhook_thread.join(timeout=5)
        if self._server is not None:
            self._server.stop()
            try:
                PORT_FILE.unlink()
            except FileNotFoundError:
                pass
        self.state.save()
        if self._events_db is not None:
            self._events_db.close()
        logger.info("Shutdown complete.")

    def _signal_shutdown(self, _signum: int, _frame: object) -> None:
        self._stop_event.set()

    # ----- worker loop (serializes all state mutations) -----

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                path = self.event_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._scan_one(path)
            except Exception as exc:
                # Per Section 2 eng review: handler exception isolated,
                # daemon stays alive. Log + continue.
                logger.error("Scan failed for %s: %s", path, exc, exc_info=True)

    def _sweep_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_SWEEP_INTERVAL_SEC)
            if self._stop_event.is_set():
                return
            logger.debug("Periodic sweep: re-enqueue all tracked files")
            self._enqueue_all_tracked()

    def _enqueue_all_tracked(self) -> None:
        """Enqueue every jsonl under every watched root for a re-scan.

        Idempotent — TailReader uses offsets, so re-enqueueing a file
        that's already up-to-date is a no-op (zero new lines).
        """
        for root in self._roots_to_watch():
            if not root.is_dir():
                continue
            try:
                for p in root.rglob("*.jsonl"):
                    try:
                        self.event_queue.put_nowait(p)
                    except queue.Full:
                        # During a flood, drop oldest. Sweep will catch
                        # whatever we dropped on its next pass.
                        try:
                            self.event_queue.get_nowait()
                            self.event_queue.put_nowait(p)
                        except queue.Empty:
                            pass
            except OSError as exc:
                logger.warning("Cannot walk %s: %s", root, exc)

    # ----- per-file scan (the hot path) -----

    def _scan_one(self, path: Path) -> None:
        any_hit = False
        for line_no, line in self.tail.read_new_lines(path):
            for match in _scan_line(
                path, line_no, line, _DEFAULT_MIN_CONFIDENCE,
                capture_context=True, line_truncated=False,
            ):
                if self.dedupe.should_notify(
                    match.category, match.snippet_redacted,
                ):
                    self._handle_match(match)
                    any_hit = True
        if any_hit:
            # Save state opportunistically after a real catch. Otherwise
            # the periodic sweep + shutdown handler covers state flushes.
            self.state.save()

    def _handle_match(self, match: SensitiveMatch) -> None:
        # E10 invariant (v0.6): state.catches_by_day still drives aifd ai
        # today's "🛡 vault watch: N" line. Keep this even after events DB
        # exists — they serve different lookups.
        self.state.record_catch()

        # v0.7: persist to events DB. fingerprint is content-only (D2);
        # same secret in different files = same fingerprint, count++. On
        # disk failure we log + bump the drop counter (T9) but don't
        # crash the daemon.
        is_new_finding = False
        fingerprint = ""
        if self._events_db is not None:
            try:
                fingerprint, is_new_finding = self._events_db.upsert_finding(
                    match.category,
                    match.snippet_redacted,
                    match.file.name,                          # basename only
                    str(match.file),
                    match.line,
                )
            except Exception as exc:
                logger.error(
                    "events DB write failed for %s: %s — dropping",
                    match.snippet_redacted, exc,
                )
                self.state.finding_drop_count += 1

        # v0.6 invariant: register with HTTP server so click-to-jump works.
        # The in-memory dict is per-process; daemon restart drops it. Tokens
        # are unguessable; the events DB picks up where the in-memory dict
        # leaves off.
        token = secrets.token_urlsafe(32)
        if self._server is not None:
            self._server.register(token, match)
            url = f"http://127.0.0.1:{self._server.port}/findings/{token}"
        else:
            url = None
        title = "aifd: secret detected"
        body = (
            f"{match.category} · {match.snippet_redacted} · "
            f"{match.file.name}:{match.line}"
        )
        self.notifier.notify(title, body, url=url)
        logger.info(
            "FINDING %s %s at %s:%d",
            match.category, match.snippet_redacted,
            match.file.name, match.line,
        )

        # v0.7: queue webhook delivery if this is a NEW fingerprint (or a
        # re-opened resolved one). Existing fingerprints just count++, no
        # webhook re-fire.
        if (
            is_new_finding
            and self._server is not None
            and self._webhook_queue is not None
            and fingerprint
        ):
            from aifd.vault.events_db import fingerprint_for as _fp
            from aifd.vault.webhooks import WebhookEvent
            now_iso = datetime.now(UTC).isoformat(timespec="seconds")
            event = WebhookEvent(
                kind="new_finding",
                fingerprint=fingerprint or _fp(
                    match.category, match.snippet_redacted,
                ),
                category=match.category,
                snippet_redacted=match.snippet_redacted,
                file_basename=match.file.name,
                line=match.line,
                first_seen=now_iso,
                count=1,
                detail_url=(
                    f"http://127.0.0.1:{self._server.port}"
                    f"/events/{fingerprint}"
                ),
            )
            try:
                self._webhook_queue.put_nowait(event)
            except queue.Full:
                logger.warning(
                    "webhook queue full — dropping event for %s",
                    fingerprint,
                )

    def _retry_dead_letter(self, webhook_id: str | None) -> int:
        """Pull dead_letter rows back into the delivery queue.

        Called from CLI / HTTP. Returns the count of events re-queued.
        Filters to a single webhook_id if provided, else all.
        """
        if self._events_db is None or self._webhook_queue is None:
            return 0
        import json
        rows = self._events_db.list_dead_letter(limit=1000)
        requeued = 0
        for row in rows:
            if webhook_id is not None and row["webhook_id"] != webhook_id:
                continue
            try:
                payload = json.loads(row["payload"])
            except (ValueError, TypeError):
                continue
            from aifd.vault.webhooks import WebhookEvent
            event = WebhookEvent(
                kind=payload.get("event", "new_finding"),
                fingerprint=payload.get("fingerprint", ""),
                category=payload.get("category", ""),
                snippet_redacted=payload.get("snippet_redacted", ""),
                file_basename=payload.get("file", ""),
                line=int(payload.get("line", 0)),
                first_seen=payload.get("first_seen", ""),
                count=int(payload.get("count", 1)),
                detail_url=payload.get("url", ""),
            )
            try:
                self._webhook_queue.put_nowait(event)
                self._events_db.drop_dead_letter(row["id"])
                requeued += 1
            except queue.Full:
                break
        return requeued

    # ----- helpers -----

    @staticmethod
    def _roots_to_watch() -> Iterable[Path]:
        """Walk every Provider's known root.

        Reuses the same path discovery as `aifd vault scan` so coverage
        stays in sync — adding a Cursor provider future will automatically
        be watched here.
        """
        seen: set[Path] = set()
        for p in PROVIDERS:
            for attr in ("root",):
                root = getattr(p, attr, None)
                if isinstance(root, Path) and root not in seen:
                    seen.add(root)
                    yield root


# Suppress unused-import warning when this module is imported without ever
# instantiating the Daemon — its time-module side use only matters for the
# integration smoke test, not the runtime path.
_ = time
