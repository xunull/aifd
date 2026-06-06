"""Click-to-jump + events HTTP server for `aifd vault watch`.

A long-running 127.0.0.1 HTTP server hosted inside the watch daemon.

Two responsibilities:

1. **v0.6 click-to-jump** (regression-preserved). Each notification carries
   a URL like `http://127.0.0.1:PORT/findings/{token}` where `token` is a
   one-shot 256-bit random handle registered when the secret was detected.
   Clicking the notification opens the URL in the user's browser. The
   in-memory dict is **dropped on daemon restart** — that's a feature, not
   a bug; tokens are unguessable and shouldn't outlive the process.

2. **v0.7 events store + webhook config** (new). Persistent finding
   history backed by SQLite. Endpoints:

      GET    /events                        list, pagination + filters
      GET    /events/{fingerprint}          detail + occurrences + playbook
      POST   /events/{fp}/ack               status → acknowledged
      POST   /events/{fp}/mute              status → muted (with body)
      POST   /events/{fp}/resolve           status → resolved
      POST   /events/{fp}/note              set notes (with body)
      GET    /webhooks                      list configs (URL not redacted —
                                            user typed it; show as-is)
      POST   /webhooks                      add new (defaults to disabled)
      DELETE /webhooks/{id}                 remove
      POST   /webhooks/{id}/test            send test event (synchronous)
      POST   /webhooks/{id}/enable          flip enabled=true
      POST   /webhooks/{id}/disable         flip enabled=false
      POST   /webhooks/{id}/retry-dead-letter  re-queue dead_letter for this id

      GET    /                              web UI single-page SPA (HTML)
      GET    /static/{path}                 static assets (JS, CSS)

Security boundary: bind 127.0.0.1 only; finding tokens are unguessable;
HTTP server only serves localhost. v0.7 endpoints inherit the same
boundary.
"""

from __future__ import annotations

import http.server
import json
import logging
import mimetypes
import socketserver
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aifd.models import SensitiveMatch
from aifd.render import render_scan_matches_html
from aifd.vault.events_db import (
    STATUS_ACKNOWLEDGED,
    STATUS_MUTED,
    STATUS_RESOLVED,
    WatchEventsDB,
)
from aifd.vault.playbooks import lookup as playbook_lookup
from aifd.vault.webhooks import (
    WebhookEntry,
    load_webhooks_yaml,
    save_webhooks_yaml,
    send_test_event,
)

logger = logging.getLogger("aifd.vault.watch_server")


_STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class WatchServer:
    """Handle to the running HTTP server.

    Wraps threading + socket details + the events store + webhook config
    so the daemon code only deals in a small handle surface.
    """

    httpd: socketserver.TCPServer
    port: int
    _thread: threading.Thread
    _findings: dict[str, SensitiveMatch]      # v0.6 click-to-jump tokens
    _events_db_factory: Callable[[], WatchEventsDB] | None = None
    _webhooks_path: Path | None = None
    _retry_dead_letter_cb: Callable[[str | None], int] | None = None

    def register(self, token: str, match: SensitiveMatch) -> None:
        """v0.6: store a finding so the next GET /findings/{token} renders."""
        self._findings[token] = match

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)


def start_server(
    events_db_factory: Callable[[], WatchEventsDB] | None = None,
    webhooks_path: Path | None = None,
    retry_dead_letter_cb: Callable[[str | None], int] | None = None,
) -> WatchServer:
    """Boot the HTTP server on 127.0.0.1:0 (kernel-picked port).

    Returns immediately; the server runs on a daemon thread that dies
    with the process. Caller is responsible for `stop()` on shutdown.

    The events_db_factory returns a thread-local WatchEventsDB connection.
    The HTTP handler thread will call it once and cache the result; do not
    share connections across threads (D1).
    """
    findings: dict[str, SensitiveMatch] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        # Lazy per-thread events DB connection cache. http.server creates a
        # new handler instance per request, but they may run on the same
        # serve_forever() thread; we open one connection and reuse.
        _local_db: WatchEventsDB | None = None

        @classmethod
        def _db(cls) -> WatchEventsDB | None:
            if cls._local_db is None and events_db_factory is not None:
                cls._local_db = events_db_factory()
            return cls._local_db

        # ---------- routing ----------

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/":
                self._serve_index()
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
                return
            if path.startswith("/findings/"):
                self._handle_v06_findings(path[len("/findings/"):])
                return
            if path == "/events":
                self._list_events()
                return
            if path.startswith("/events/"):
                self._show_event(path[len("/events/"):])
                return
            if path == "/webhooks":
                self._list_webhooks()
                return
            if path == "/healthz":
                self._send_json({"ok": True})
                return
            self.send_error(404, "Not found")

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "events":
                fp, verb = parts[1], parts[2]
                self._mutate_event(fp, verb)
                return
            if path == "/webhooks":
                self._add_webhook()
                return
            if len(parts) == 3 and parts[0] == "webhooks":
                wid, verb = parts[1], parts[2]
                self._webhook_action(wid, verb)
                return
            self.send_error(404, "Not found")

        def do_DELETE(self) -> None:
            parts = self.path.strip("/").split("/")
            if len(parts) == 2 and parts[0] == "webhooks":
                self._delete_webhook(parts[1])
                return
            self.send_error(404, "Not found")

        def log_message(self, fmt: str, *args: object) -> None:
            logger.debug("http: " + fmt, *args)

        # ---------- helpers ----------

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return parsed if isinstance(parsed, dict) else {}

        def _send_json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # ---------- v0.6 click-to-jump (regression-preserved) ----------

        def _handle_v06_findings(self, token: str) -> None:
            token = token.rstrip("/")
            if not token or token not in findings:
                self.send_error(404, "Unknown or expired finding")
                return
            match = findings[token]
            page = render_scan_matches_html([match]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)

        # ---------- index + static ----------

        def _serve_index(self) -> None:
            index = _STATIC_DIR / "index.html"
            if not index.exists():
                # During development before the SPA ships, present a
                # minimal placeholder so /events JSON consumers still work.
                placeholder = (
                    b"<!doctype html><meta charset=utf-8>"
                    b"<title>aifd vault watch</title>"
                    b"<h1>aifd vault watch</h1>"
                    b"<p>UI not built yet. Use the JSON API:</p>"
                    b"<ul><li><a href=/events>/events</a></li>"
                    b"<li><a href=/webhooks>/webhooks</a></li></ul>"
                )
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/html; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(placeholder)))
                self.end_headers()
                self.wfile.write(placeholder)
                return
            data = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_static(self, sub_path: str) -> None:
            # Block path traversal: reject anything outside _STATIC_DIR.
            target = (_STATIC_DIR / sub_path).resolve()
            try:
                target.relative_to(_STATIC_DIR.resolve())
            except ValueError:
                self.send_error(404, "Not found")
                return
            if not target.exists() or not target.is_file():
                self.send_error(404, "Not found")
                return
            mime, _ = mimetypes.guess_type(str(target))
            data = target.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", mime or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # ---------- events list + detail + mutate ----------

        def _list_events(self) -> None:
            db = self._db()
            if db is None:
                self._send_json({"error": "events DB not initialized"}, 503)
                return
            qs = _parse_qs(self.path)
            try:
                limit = min(int(qs.get("limit", "50")), 500)
                offset = max(int(qs.get("offset", "0")), 0)
            except ValueError:
                self._send_json({"error": "bad limit/offset"}, 400)
                return
            status = qs.get("status")
            category = qs.get("category")
            rows = db.list_findings(
                status=status, category=category, limit=limit, offset=offset,
            )
            total = db.count_findings(status=status, category=category)
            self._send_json({
                "total": total,
                "limit": limit,
                "offset": offset,
                "findings": [dict(r) for r in rows],
            })

        def _show_event(self, fingerprint: str) -> None:
            db = self._db()
            if db is None:
                self._send_json({"error": "events DB not initialized"}, 503)
                return
            fingerprint = fingerprint.rstrip("/")
            row = db.get_finding(fingerprint)
            if row is None:
                self._send_json({"error": "not found"}, 404)
                return
            occurrences = db.list_occurrences(fingerprint)
            pb = playbook_lookup(row["category"])
            self._send_json({
                "finding": dict(row),
                "occurrences": [dict(o) for o in occurrences],
                "playbook": {
                    "vendor_dashboard": pb["vendor_dashboard"],
                    "instruction": pb["instruction"],
                    "severity": pb["severity"],
                },
            })

        def _mutate_event(self, fingerprint: str, verb: str) -> None:
            db = self._db()
            if db is None:
                self._send_json({"error": "events DB not initialized"}, 503)
                return
            body = self._read_json_body()
            if verb == "ack":
                ok = db.mutate_status(fingerprint, STATUS_ACKNOWLEDGED)
            elif verb == "mute":
                hours = body.get("hours")
                ok = db.mutate_status(
                    fingerprint, STATUS_MUTED,
                    mute_hours=float(hours) if hours is not None else None,
                )
            elif verb == "resolve":
                ok = db.mutate_status(fingerprint, STATUS_RESOLVED)
            elif verb == "note":
                text = str(body.get("text", ""))
                ok = db.set_note(fingerprint, text)
            else:
                self._send_json({"error": f"unknown verb {verb}"}, 400)
                return
            if not ok:
                self._send_json({"error": "not found"}, 404)
                return
            row = db.get_finding(fingerprint)
            self._send_json({"finding": dict(row) if row else None})

        # ---------- webhooks ----------

        def _load_entries(self) -> list[WebhookEntry]:
            if _webhooks_path is None:
                return []
            return load_webhooks_yaml(_webhooks_path)

        def _save_entries(self, entries: list[WebhookEntry]) -> None:
            if _webhooks_path is None:
                return
            save_webhooks_yaml(_webhooks_path, entries)

        def _list_webhooks(self) -> None:
            entries = self._load_entries()
            self._send_json({"webhooks": [_entry_dict(e) for e in entries]})

        def _add_webhook(self) -> None:
            body = self._read_json_body()
            try:
                new_entry = _entry_from_dict(body)
            except (KeyError, TypeError, ValueError) as exc:
                self._send_json({"error": str(exc)}, 400)
                return
            entries = self._load_entries()
            if any(e.id == new_entry.id for e in entries):
                self._send_json(
                    {"error": f"webhook id {new_entry.id!r} already exists"},
                    409,
                )
                return
            entries.append(new_entry)
            self._save_entries(entries)
            self._send_json({"webhook": _entry_dict(new_entry)}, 201)

        def _delete_webhook(self, wid: str) -> None:
            entries = self._load_entries()
            new_list = [e for e in entries if e.id != wid]
            if len(new_list) == len(entries):
                self._send_json({"error": "not found"}, 404)
                return
            self._save_entries(new_list)
            self._send_json({"deleted": wid})

        def _webhook_action(self, wid: str, verb: str) -> None:
            entries = self._load_entries()
            idx = next(
                (i for i, e in enumerate(entries) if e.id == wid), None,
            )
            if idx is None:
                self._send_json({"error": "not found"}, 404)
                return
            entry = entries[idx]
            if verb == "test":
                ok, msg = send_test_event(entry)
                self._send_json({"ok": ok, "message": msg})
                return
            if verb == "enable":
                entries[idx] = _replace(entry, enabled=True)
                self._save_entries(entries)
                self._send_json({"webhook": _entry_dict(entries[idx])})
                return
            if verb == "disable":
                entries[idx] = _replace(entry, enabled=False)
                self._save_entries(entries)
                self._send_json({"webhook": _entry_dict(entries[idx])})
                return
            if verb == "retry-dead-letter":
                if retry_dead_letter_cb is None:
                    self._send_json(
                        {"error": "retry not available"}, 501,
                    )
                    return
                n = retry_dead_letter_cb(wid)
                self._send_json({"requeued": n})
                return
            self._send_json({"error": f"unknown verb {verb}"}, 400)

    # Capture into closure so the handler class can read it.
    _webhooks_path = webhooks_path

    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    host_raw, port = httpd.server_address[:2]
    host = host_raw.decode() if isinstance(host_raw, bytes) else host_raw
    logger.info("WatchServer ready on http://%s:%d/", host, port)

    thread = threading.Thread(
        target=httpd.serve_forever, name="watch-http", daemon=True,
    )
    thread.start()

    return WatchServer(
        httpd=httpd, port=port, _thread=thread, _findings=findings,
        _events_db_factory=events_db_factory,
        _webhooks_path=webhooks_path,
        _retry_dead_letter_cb=retry_dead_letter_cb,
    )


# ---------- pure helpers ----------


def _parse_qs(path: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse
    parsed = urlparse(path)
    return {k: v[0] for k, v in parse_qs(parsed.query).items() if v}


def _entry_dict(e: WebhookEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "url": e.url,
        "on": list(e.on),
        "filter_categories": list(e.filter_categories),
        "payload_format": e.payload_format,
        "enabled": e.enabled,
        "lang": e.lang,
        "threshold_window_hours": e.threshold_window_hours,
        "threshold_count": e.threshold_count,
    }


def _entry_from_dict(body: dict[str, Any]) -> WebhookEntry:
    from aifd.vault.webhooks import _validate_url
    wid = str(body.get("id") or "").strip()
    url = body.get("url")
    if not isinstance(url, str) or not url:
        raise KeyError("missing url")
    _validate_url(url)
    if not wid:
        wid = f"webhook-{abs(hash(url)) % 100000}"
    on_list = body.get("on") or ["new_finding"]
    if not isinstance(on_list, list):
        raise TypeError("on must be list")
    cats_raw = body.get("filter_categories") or body.get("categories") or []
    if isinstance(cats_raw, str):
        cats_raw = [cats_raw]
    if not isinstance(cats_raw, list):
        raise TypeError("filter_categories must be list")
    fmt = str(body.get("payload_format") or "aifd_v1")
    if fmt not in {"aifd_v1", "pagerduty_v2"}:
        raise ValueError(f"unknown payload_format: {fmt}")
    return WebhookEntry(
        id=wid,
        url=url,
        on=tuple(str(x) for x in on_list),
        filter_categories=tuple(str(x) for x in cats_raw),
        payload_format=fmt,
        enabled=bool(body.get("enabled", False)),
        lang=str(body.get("lang") or "en"),
        threshold_window_hours=None,
        threshold_count=None,
    )


def _replace(entry: WebhookEntry, **changes: Any) -> WebhookEntry:
    """Frozen dataclass shallow update."""
    from dataclasses import replace
    return replace(entry, **changes)


