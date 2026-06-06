"""Webhook outbound delivery for `aifd vault watch` (v0.7).

The "out gate" of the events pipeline: when a finding fires (or a
threshold trips), POST a JSON payload to a user-configured URL.

Architectural locks (from /plan-eng-review):

  D3 — webhook is **disabled-by-default**. Adding to yaml is not enough.
       User must explicitly `enable` after a successful `test`. This is
       the "privacy by default" guard — a typo in the URL would otherwise
       silently leak metadata to a stranger.

  D4 — dead_letter is **NOT auto-retried on restart**. User must
       explicitly `webhooks retry-dead-letter` to re-queue. Avoids the
       "fixed the typo but old dead_letter still goes to the bad URL"
       trap.

Threading model:

    Daemon worker thread
        │  (on finding hit)
        │  delivery_queue.put(WebhookEvent)
        ▼
    queue.Queue[WebhookEvent]
        │
        ▼
    WebhookDeliverer worker thread (1)
        │
        │ for each event, for each enabled webhook matching filter:
        │   POST + retry 3x exponential backoff
        │   on permanent failure: WatchEventsDB.add_dead_letter()
        ▼
    (HTTP response or dead_letter row)

Payload formats:
  - aifd_v1 (default): generic flat JSON, documented in docs/vault-events.md
  - pagerduty_v2: PagerDuty Events API v2 shape

Slack incoming webhooks accept any JSON; users either send aifd_v1 raw
or pipe through one-line jq to reshape into Block Kit.
"""

from __future__ import annotations

import http.client
import json
import logging
import queue
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import yaml

from aifd.vault.events_db import WatchEventsDB
from aifd.vault.playbooks import render_for_webhook

logger = logging.getLogger("aifd.vault.webhooks")

# Tunables — defaults align with "good enough for personal use".
_REQUEST_TIMEOUT_SEC = 10.0
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = [10.0, 60.0, 600.0]


# ---------- WebhookConfig ----------


@dataclass(frozen=True)
class WebhookEntry:
    """One user-authored webhook configuration row."""

    id: str
    url: str
    on: tuple[str, ...]                  # ("new_finding", "count_spike", ...)
    filter_categories: tuple[str, ...]   # empty = all categories
    payload_format: str                  # "aifd_v1" | "pagerduty_v2"
    enabled: bool
    lang: str                            # "en" | "zh" | future locales
    threshold_window_hours: float | None
    threshold_count: int | None


def _validate_url(url: str) -> None:
    """Reject configs that would clearly leak to wrong places.

    file://, ftp://, raw IPs without scheme — all rejected. http://
    is allowed (intranet use case); HTTPS strongly recommended in docs.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"webhook URL must use http:// or https:// — got {parsed.scheme!r}"
        )
    if not parsed.netloc:
        raise ValueError(f"webhook URL missing host: {url!r}")


def load_webhooks_yaml(path: Path) -> list[WebhookEntry]:
    """Read user's webhooks.yaml, return validated entries.

    Malformed entries are logged + skipped (not fatal) so a broken row
    doesn't kill the whole daemon. A completely missing file returns [].
    """
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        logger.warning("Cannot parse %s: %s — treating as empty", path, exc)
        return []
    if not isinstance(raw, dict):
        logger.warning("%s must be a YAML mapping; got %s", path, type(raw).__name__)
        return []
    entries_raw = raw.get("webhooks", [])
    if not isinstance(entries_raw, list):
        logger.warning("'webhooks' in %s must be a list", path)
        return []

    out: list[WebhookEntry] = []
    for idx, item in enumerate(entries_raw):
        try:
            entry = _build_entry(item, idx)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping webhook entry %d in %s: %s", idx, path, exc,
            )
            continue
        out.append(entry)
    return out


def _build_entry(item: object, idx: int) -> WebhookEntry:
    if not isinstance(item, dict):
        raise TypeError(f"entry {idx} is not a mapping")
    wid = str(item.get("id") or f"webhook-{idx}")
    url = item.get("url")
    if not isinstance(url, str):
        raise KeyError("missing 'url'")
    _validate_url(url)
    on_list = item.get("on") or ["new_finding"]
    if not isinstance(on_list, list):
        raise TypeError("'on' must be a list")
    filter_section = item.get("filter") or {}
    if not isinstance(filter_section, dict):
        raise TypeError("'filter' must be a mapping")
    cat_list = filter_section.get("category") or []
    if isinstance(cat_list, str):
        cat_list = [cat_list]
    if not isinstance(cat_list, list):
        raise TypeError("'filter.category' must be a list or string")
    payload_fmt = str(item.get("payload") or "aifd_v1")
    if payload_fmt not in {"aifd_v1", "pagerduty_v2"}:
        raise ValueError(f"unknown payload format: {payload_fmt}")
    enabled = bool(item.get("enabled", False))  # D3: disabled by default
    lang = str(item.get("lang") or "en")
    threshold = item.get("threshold") or {}
    if not isinstance(threshold, dict):
        raise TypeError("'threshold' must be a mapping")
    window_hours = threshold.get("window_hours")
    count = threshold.get("count")
    return WebhookEntry(
        id=wid,
        url=url,
        on=tuple(str(x) for x in on_list),
        filter_categories=tuple(str(x) for x in cat_list),
        payload_format=payload_fmt,
        enabled=enabled,
        lang=lang,
        threshold_window_hours=(
            float(window_hours) if window_hours is not None else None
        ),
        threshold_count=int(count) if count is not None else None,
    )


def save_webhooks_yaml(path: Path, entries: Iterable[WebhookEntry]) -> None:
    """Write the webhook list back to yaml (atomic tmp + rename)."""
    payload: dict[str, list[dict[str, Any]]] = {
        "webhooks": [
            _entry_to_dict(e) for e in entries
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _entry_to_dict(e: WebhookEntry) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": e.id,
        "url": e.url,
        "on": list(e.on),
        "payload": e.payload_format,
        "enabled": e.enabled,
        "lang": e.lang,
    }
    if e.filter_categories:
        out["filter"] = {"category": list(e.filter_categories)}
    if e.threshold_window_hours is not None or e.threshold_count is not None:
        thresh: dict[str, Any] = {}
        if e.threshold_window_hours is not None:
            thresh["window_hours"] = e.threshold_window_hours
        if e.threshold_count is not None:
            thresh["count"] = e.threshold_count
        out["threshold"] = thresh
    return out


# ---------- WebhookEvent (queue payload) ----------


@dataclass(frozen=True)
class WebhookEvent:
    """One in-flight thing to send.

    Sent from the daemon worker thread into the delivery queue. The
    deliverer fans this out across every enabled webhook whose filter
    matches.
    """

    kind: str                            # "new_finding" | "count_spike"
    fingerprint: str
    category: str
    snippet_redacted: str
    file_basename: str
    line: int
    first_seen: str                      # ISO 8601
    count: int
    detail_url: str                      # http://127.0.0.1:PORT/events/{fp}


# ---------- payload formatters ----------


def render_aifd_v1(
    event: WebhookEvent, lang: str = "en",
) -> dict[str, Any]:
    rotation = render_for_webhook(event.category, lang=lang)
    return {
        "event": event.kind,
        "fingerprint": event.fingerprint,
        "category": event.category,
        "snippet_redacted": event.snippet_redacted,
        "file": event.file_basename,
        "line": event.line,
        "first_seen": event.first_seen,
        "count": event.count,
        "url": event.detail_url,
        "rotation": rotation,
    }


def render_pagerduty_v2(
    event: WebhookEvent, routing_key: str, lang: str = "en",
) -> dict[str, Any]:
    """PagerDuty Events API v2 shape.

    routing_key is parsed out of the URL query: users put
    `https://events.pagerduty.com/v2/enqueue?routing_key=R123` and we
    pull it on send. (PD requires routing_key in the body, not the URL,
    so we move it.)
    """
    rotation = render_for_webhook(event.category, lang=lang)
    severity_map = {
        "critical": "critical",
        "high": "error",
        "medium": "warning",
        "low": "info",
    }
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": event.fingerprint,
        "payload": {
            "summary": (
                f"aifd vault watch: {event.category} leaked in "
                f"{event.file_basename}:{event.line}"
            ),
            "source": "aifd vault watch",
            "severity": severity_map.get(rotation["severity"], "warning"),
            "custom_details": {
                "snippet_redacted": event.snippet_redacted,
                "rotation_dashboard": rotation["vendor_dashboard"],
                "rotation_instruction": rotation["instruction"],
                "first_seen": event.first_seen,
                "count": event.count,
                "detail_url": event.detail_url,
            },
        },
    }


# ---------- WebhookDeliverer ----------


@dataclass
class WebhookDeliverer:
    """Single worker thread that fans out webhook events.

    Owns its own EventsDB connection (D1 per-thread). Pulls from
    delivery_queue; for each event, finds all matching enabled webhooks
    and POSTs the appropriate payload. Failures go through retry then
    dead_letter.
    """

    events_db: WatchEventsDB
    delivery_queue: queue.Queue[WebhookEvent]
    config_provider: Any                 # callable() -> list[WebhookEntry]
    backoff_seconds: list[float] = field(
        default_factory=lambda: list(_RETRY_BACKOFF_SEC),
    )
    stop_event: threading.Event = field(default_factory=threading.Event)

    def run(self) -> None:
        """Worker loop. Exit when stop_event is set."""
        while not self.stop_event.is_set():
            try:
                event = self.delivery_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._fan_out(event)
            except Exception as exc:
                logger.error(
                    "webhook deliverer crashed on %s: %s",
                    event.fingerprint, exc, exc_info=True,
                )

    def _fan_out(self, event: WebhookEvent) -> None:
        configs = self.config_provider()
        for entry in configs:
            if not entry.enabled:
                continue
            if event.kind not in entry.on:
                continue
            if (
                entry.filter_categories
                and event.category not in entry.filter_categories
            ):
                continue
            self._deliver(event, entry)

    def _deliver(self, event: WebhookEvent, entry: WebhookEntry) -> None:
        payload = self._build_payload(event, entry)
        body = json.dumps(payload).encode("utf-8")
        last_error = "unknown"
        attempts = 0
        # Stable POST URL: strip routing_key from URL for PD, keep
        # everything for aifd_v1.
        post_url = self._url_for_post(entry)
        for delay in [0.0, *self.backoff_seconds]:
            if delay > 0:
                _interruptible_sleep(delay, self.stop_event)
                if self.stop_event.is_set():
                    return
            attempts += 1
            try:
                self._post(post_url, body)
                logger.info(
                    "webhook %s delivered for %s (attempt %d)",
                    entry.id, event.fingerprint, attempts,
                )
                return
            except _PermanentDeliveryError as exc:
                last_error = str(exc)
                logger.warning(
                    "webhook %s permanent fail for %s: %s",
                    entry.id, event.fingerprint, exc,
                )
                break  # 4xx-class: don't retry
            except _TransientDeliveryError as exc:
                last_error = str(exc)
                logger.info(
                    "webhook %s transient fail for %s attempt %d: %s",
                    entry.id, event.fingerprint, attempts, exc,
                )
                if attempts > _MAX_RETRY_ATTEMPTS:
                    break
        # Exhausted retries (or hit permanent error) → dead_letter
        try:
            self.events_db.add_dead_letter(
                event.fingerprint, entry.id, json.dumps(payload),
                attempts, last_error,
            )
        except Exception as exc:
            logger.error("Cannot write dead_letter for %s: %s",
                         event.fingerprint, exc)

    def _build_payload(
        self, event: WebhookEvent, entry: WebhookEntry,
    ) -> dict[str, Any]:
        if entry.payload_format == "pagerduty_v2":
            routing_key = _extract_query(entry.url, "routing_key") or ""
            return render_pagerduty_v2(event, routing_key, lang=entry.lang)
        return render_aifd_v1(event, lang=entry.lang)

    @staticmethod
    def _url_for_post(entry: WebhookEntry) -> str:
        """For PD, strip the routing_key query param from the POST URL
        because we moved it into the body. Other formats: URL untouched.
        """
        if entry.payload_format != "pagerduty_v2":
            return entry.url
        parsed = urllib.parse.urlparse(entry.url)
        q = dict(urllib.parse.parse_qsl(parsed.query))
        q.pop("routing_key", None)
        new_query = urllib.parse.urlencode(q)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))

    @staticmethod
    def _post(url: str, body: bytes) -> None:
        """Single POST attempt. Raise transient or permanent errors."""
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SEC) as resp:
                if 200 <= resp.status < 300:
                    return
                if 400 <= resp.status < 500:
                    raise _PermanentDeliveryError(
                        f"HTTP {resp.status} {resp.reason}"
                    )
                raise _TransientDeliveryError(
                    f"HTTP {resp.status} {resp.reason}"
                )
        except HTTPError as exc:
            if 400 <= exc.code < 500:
                raise _PermanentDeliveryError(f"HTTP {exc.code}") from exc
            raise _TransientDeliveryError(f"HTTP {exc.code}") from exc
        except (URLError, TimeoutError, http.client.HTTPException, OSError) as exc:
            raise _TransientDeliveryError(str(exc)) from exc


class _PermanentDeliveryError(Exception):
    pass


class _TransientDeliveryError(Exception):
    pass


def _extract_query(url: str, key: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    return dict(urllib.parse.parse_qsl(parsed.query)).get(key)


def _interruptible_sleep(seconds: float, stop_event: threading.Event) -> None:
    """Sleep that wakes up on stop_event so daemon shutdown is fast."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if stop_event.wait(timeout=min(remaining, 1.0)):
            return


# ---------- test / probe ----------


def send_test_event(entry: WebhookEntry) -> tuple[bool, str]:
    """Synchronous test ping. Returns (ok, message).

    Used by the CLI `webhooks test` command and the HTTP `/webhooks/{id}/test`
    endpoint. Sends a fake `aifd_test_event` event so the user can confirm
    receipt in their downstream channel before flipping `enabled`.
    """
    fake = WebhookEvent(
        kind="aifd_test_event",
        fingerprint="0000000000000000",
        category="aifd_test",
        snippet_redacted="test…body",
        file_basename="aifd-test.jsonl",
        line=1,
        first_seen="2026-06-05T00:00:00+00:00",
        count=1,
        detail_url="http://127.0.0.1:0/events/test",
    )
    if entry.payload_format == "pagerduty_v2":
        routing_key = _extract_query(entry.url, "routing_key") or ""
        payload = render_pagerduty_v2(fake, routing_key, lang=entry.lang)
        post_url = WebhookDeliverer._url_for_post(entry)
    else:
        payload = render_aifd_v1(fake, lang=entry.lang)
        post_url = entry.url
    body = json.dumps(payload).encode("utf-8")
    try:
        WebhookDeliverer._post(post_url, body)
        return True, "ok"
    except _PermanentDeliveryError as exc:
        return False, f"permanent: {exc}"
    except _TransientDeliveryError as exc:
        return False, f"transient: {exc}"
    except Exception as exc:
        return False, f"unexpected: {exc}"
