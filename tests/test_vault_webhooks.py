"""Tests for webhook delivery, dead_letter, payload formatters, yaml."""

from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from aifd.vault.events_db import WatchEventsDB, init_db
from aifd.vault.webhooks import (
    WebhookDeliverer,
    WebhookEntry,
    WebhookEvent,
    load_webhooks_yaml,
    render_aifd_v1,
    render_pagerduty_v2,
    save_webhooks_yaml,
    send_test_event,
)


@pytest.fixture
def db(tmp_path: Path) -> WatchEventsDB:
    p = tmp_path / "findings.db"
    init_db(p)
    return WatchEventsDB(p)


@pytest.fixture
def event() -> WebhookEvent:
    return WebhookEvent(
        kind="new_finding",
        fingerprint="abc123def456",
        category="openai_key",
        snippet_redacted="sk-A…WXYZ",
        file_basename="abc.jsonl",
        line=42,
        first_seen="2026-06-05T17:00:00+00:00",
        count=1,
        detail_url="http://127.0.0.1:8080/events/abc123def456",
    )


def _entry(**overrides: Any) -> WebhookEntry:
    base: dict[str, Any] = {
        "id": "test-hook",
        "url": "https://hooks.example.com/abc",
        "on": ("new_finding",),
        "filter_categories": (),
        "payload_format": "aifd_v1",
        "enabled": True,
        "lang": "en",
        "threshold_window_hours": None,
        "threshold_count": None,
    }
    base.update(overrides)
    return WebhookEntry(**base)


# ---------- yaml load + save (D3 disabled-by-default) ----------


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_webhooks_yaml(tmp_path / "nonexistent.yaml") == []


def test_load_disabled_by_default(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    p.write_text(
        "webhooks:\n"
        "  - id: slack\n"
        "    url: https://hooks.slack.com/services/T/B/X\n"
    )
    entries = load_webhooks_yaml(p)
    assert len(entries) == 1
    assert entries[0].enabled is False  # D3 invariant


def test_load_explicit_enabled(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    p.write_text(
        "webhooks:\n"
        "  - id: slack\n"
        "    url: https://hooks.slack.com/services/T/B/X\n"
        "    enabled: true\n"
    )
    entries = load_webhooks_yaml(p)
    assert entries[0].enabled is True


def test_load_rejects_file_url_scheme(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    p.write_text(
        "webhooks:\n"
        "  - id: bad\n"
        "    url: file:///etc/passwd\n"
    )
    # Bad entry is skipped, not fatal
    assert load_webhooks_yaml(p) == []


def test_load_malformed_yaml_treated_as_empty(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    p.write_text("this is :: not [valid yaml")
    assert load_webhooks_yaml(p) == []


def test_load_filter_category(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    p.write_text(
        "webhooks:\n"
        "  - id: slack\n"
        "    url: https://hooks.slack.com/services/X/Y/Z\n"
        "    enabled: true\n"
        "    filter:\n"
        "      category: [openai_key, github_pat]\n"
    )
    entries = load_webhooks_yaml(p)
    assert entries[0].filter_categories == ("openai_key", "github_pat")


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "webhooks.yaml"
    entry = _entry(
        id="hook1", url="https://example.com/h",
        on=("new_finding",), filter_categories=("openai_key",),
    )
    save_webhooks_yaml(p, [entry])
    loaded = load_webhooks_yaml(p)
    assert loaded == [entry]


# ---------- payload formatters ----------


def test_render_aifd_v1_includes_rotation(event: WebhookEvent) -> None:
    payload = render_aifd_v1(event, lang="en")
    assert payload["event"] == "new_finding"
    assert payload["fingerprint"] == event.fingerprint
    assert payload["snippet_redacted"] == "sk-A…WXYZ"
    assert payload["file"] == "abc.jsonl"
    assert payload["rotation"]["vendor_dashboard"].startswith(
        "https://platform.openai.com"
    )


def test_render_aifd_v1_zh_locale(event: WebhookEvent) -> None:
    payload = render_aifd_v1(event, lang="zh")
    assert "撤销" in payload["rotation"]["instruction"]


def test_render_pagerduty_v2_shape(event: WebhookEvent) -> None:
    payload = render_pagerduty_v2(event, routing_key="R123", lang="en")
    assert payload["routing_key"] == "R123"
    assert payload["event_action"] == "trigger"
    assert payload["dedup_key"] == event.fingerprint
    assert payload["payload"]["severity"] == "critical"  # openai_key → critical


# ---------- WebhookDeliverer.run lifecycle ----------


def _make_deliverer(
    db: WatchEventsDB, config: list[WebhookEntry],
    backoff: list[float] | None = None,
) -> tuple[WebhookDeliverer, queue.Queue[WebhookEvent]]:
    dq: queue.Queue[WebhookEvent] = queue.Queue()
    d = WebhookDeliverer(
        events_db=db,
        delivery_queue=dq,
        config_provider=lambda: list(config),
        backoff_seconds=backoff if backoff is not None else [0.0, 0.0, 0.0],
    )
    return d, dq


def test_deliverer_skips_disabled(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry(enabled=False)])
    with patch("aifd.vault.webhooks.urllib.request.urlopen") as urlopen:
        d._fan_out(event)
    assert not urlopen.called


def test_deliverer_filters_by_kind(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry(on=("count_spike",))])
    with patch("aifd.vault.webhooks.urllib.request.urlopen") as urlopen:
        d._fan_out(event)
    assert not urlopen.called


def test_deliverer_filters_by_category(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(
        db, [_entry(filter_categories=("github_pat",))],
    )
    with patch("aifd.vault.webhooks.urllib.request.urlopen") as urlopen:
        d._fan_out(event)
    assert not urlopen.called


def test_deliverer_fires_on_match(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry()])
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch(
        "aifd.vault.webhooks.urllib.request.urlopen", return_value=mock_resp,
    ) as urlopen:
        d._fan_out(event)
    assert urlopen.called


# ---------- retry + dead_letter (D4) ----------


def test_4xx_goes_straight_to_dead_letter_no_retry(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry()])
    call_count = 0

    def fake_open(*_a: Any, **_kw: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise HTTPError(
            url="x", code=404, msg="not found", hdrs=None, fp=None,  # type: ignore[arg-type]
        )

    with patch("aifd.vault.webhooks.urllib.request.urlopen", side_effect=fake_open):
        d._fan_out(event)
    assert call_count == 1  # no retry on 4xx
    dl = db.list_dead_letter()
    assert len(dl) == 1
    assert "404" in dl[0]["last_error"]


def test_5xx_retries_then_dead_letter(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry()], backoff=[0.0, 0.0, 0.0])
    call_count = 0

    def fake_open(*_a: Any, **_kw: Any) -> Any:
        nonlocal call_count
        call_count += 1
        raise HTTPError(
            url="x", code=503, msg="oops", hdrs=None, fp=None,  # type: ignore[arg-type]
        )

    with patch("aifd.vault.webhooks.urllib.request.urlopen", side_effect=fake_open):
        d._fan_out(event)
    assert call_count == 4  # 1 initial + 3 retries
    dl = db.list_dead_letter()
    assert len(dl) == 1


def test_transient_then_success(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    d, _ = _make_deliverer(db, [_entry()], backoff=[0.0, 0.0, 0.0])
    calls = [0]

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    def flaky(*_a: Any, **_kw: Any) -> Any:
        calls[0] += 1
        if calls[0] < 3:
            raise URLError("dns")
        return mock_resp

    with patch("aifd.vault.webhooks.urllib.request.urlopen", side_effect=flaky):
        d._fan_out(event)
    assert calls[0] == 3
    assert db.list_dead_letter() == []  # eventually succeeded


# ---------- send_test_event ----------


def test_send_test_event_success() -> None:
    entry = _entry()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch(
        "aifd.vault.webhooks.urllib.request.urlopen", return_value=mock_resp,
    ):
        ok, msg = send_test_event(entry)
    assert ok is True
    assert msg == "ok"


def test_send_test_event_permanent_failure() -> None:
    entry = _entry()
    err = HTTPError(
        url="x", code=403, msg="forbidden", hdrs=None, fp=None,  # type: ignore[arg-type]
    )
    with patch("aifd.vault.webhooks.urllib.request.urlopen", side_effect=err):
        ok, msg = send_test_event(entry)
    assert ok is False
    assert "permanent" in msg


# ---------- pagerduty URL handling ----------


def test_pagerduty_routing_key_stripped_from_url() -> None:
    entry = _entry(
        payload_format="pagerduty_v2",
        url="https://events.pagerduty.com/v2/enqueue?routing_key=ABC123",
    )
    url = WebhookDeliverer._url_for_post(entry)
    assert "routing_key" not in url


# ---------- stop_event responsiveness ----------


def test_deliverer_stops_on_signal(
    db: WatchEventsDB,
) -> None:
    d, _ = _make_deliverer(db, [])
    thread = threading.Thread(target=d.run)
    thread.start()
    time.sleep(0.1)
    d.stop_event.set()
    thread.join(timeout=2)
    assert not thread.is_alive()


# ---------- integration: full payload through urlopen ----------


def test_full_delivery_posts_aifd_v1_json(
    db: WatchEventsDB, event: WebhookEvent,
) -> None:
    """Verify the actual POSTed body is well-formed aifd_v1 JSON."""
    d, _ = _make_deliverer(db, [_entry()])
    captured: dict[str, bytes] = {}

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)

    def capture(req: Any, *_a: Any, **_kw: Any) -> Any:
        captured["body"] = req.data
        return mock_resp

    with patch("aifd.vault.webhooks.urllib.request.urlopen", side_effect=capture):
        d._fan_out(event)
    body = json.loads(captured["body"])
    assert body["event"] == "new_finding"
    assert body["category"] == "openai_key"
    assert "rotation" in body
