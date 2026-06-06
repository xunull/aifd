"""Tests for v0.7 endpoints added to watch_server.py.

Black-box test: start a real server bound to 127.0.0.1:0, hit endpoints
with urllib, verify response shape + DB persistence.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aifd.vault.events_db import (
    STATUS_ACKNOWLEDGED,
    STATUS_MUTED,
    STATUS_RESOLVED,
    WatchEventsDB,
    init_db,
)
from aifd.vault.watch_server import WatchServer, start_server


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "findings.db"
    init_db(p)
    return p


@pytest.fixture
def webhooks_path(tmp_path: Path) -> Path:
    return tmp_path / "webhooks.yaml"


@pytest.fixture
def server(db_path: Path, webhooks_path: Path) -> Iterator[WatchServer]:
    s = start_server(
        events_db_factory=lambda: WatchEventsDB(db_path),
        webhooks_path=webhooks_path,
    )
    try:
        yield s
    finally:
        s.stop()


def _safe_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {}


def _get(server: WatchServer, path: str) -> tuple[int, dict[str, Any]]:
    url = f"http://127.0.0.1:{server.port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, _safe_json(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        return exc.code, _safe_json(body)


def _post(
    server: WatchServer, path: str, body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    url = f"http://127.0.0.1:{server.port}{path}"
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            resp_body = resp.read().decode("utf-8")
            return resp.status, _safe_json(resp_body)
    except urllib.error.HTTPError as exc:
        body_b = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        return exc.code, _safe_json(body_b)


def _delete(
    server: WatchServer, path: str,
) -> tuple[int, dict[str, Any]]:
    url = f"http://127.0.0.1:{server.port}{path}"
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, _safe_json(body)
    except urllib.error.HTTPError as exc:
        body_b = exc.read().decode("utf-8") if hasattr(exc, "read") else ""
        return exc.code, _safe_json(body_b)


# ---------- events list + detail ----------


def test_get_events_empty(server: WatchServer) -> None:
    status, body = _get(server, "/events")
    assert status == 200
    assert body == {
        "total": 0, "limit": 50, "offset": 0, "findings": [],
    }


def test_get_events_returns_data_after_upsert(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 42,
    )
    status, body = _get(server, "/events")
    assert status == 200
    assert body["total"] == 1
    assert body["findings"][0]["category"] == "openai_key"


def test_get_events_filter_by_category(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    db.upsert_finding("openai_key", "sk-A", "x.jsonl", "/x.jsonl", 1)
    db.upsert_finding("github_pat", "ghp_A", "x.jsonl", "/x.jsonl", 1)
    status, body = _get(server, "/events?category=openai_key")
    assert status == 200
    assert body["total"] == 1
    assert body["findings"][0]["category"] == "openai_key"


def test_get_events_filter_by_status(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    db.mutate_status(fp, STATUS_ACKNOWLEDGED)
    db.upsert_finding("jwt", "eyJ…B", "x.jsonl", "/x.jsonl", 1)
    _, body = _get(server, "/events?status=new")
    assert body["total"] == 1
    assert body["findings"][0]["status"] == "new"


def test_get_events_pagination(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    for i in range(10):
        db.upsert_finding("openai_key", f"sk-{i:02d}", "x.jsonl", "/x.jsonl", i)
    _, body = _get(server, "/events?limit=3&offset=0")
    assert body["total"] == 10
    assert len(body["findings"]) == 3


def test_get_events_bad_limit_returns_400(server: WatchServer) -> None:
    status, _ = _get(server, "/events?limit=abc")
    assert status == 400


def test_get_event_detail(server: WatchServer, db_path: Path) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding(
        "openai_key", "sk-A…WXYZ", "abc.jsonl", "/tmp/abc.jsonl", 42,
    )
    status, body = _get(server, f"/events/{fp}")
    assert status == 200
    assert body["finding"]["fingerprint"] == fp
    assert len(body["occurrences"]) == 1
    assert body["playbook"]["vendor_dashboard"].startswith(
        "https://platform.openai.com"
    )


def test_get_event_detail_unknown_returns_404(server: WatchServer) -> None:
    status, _ = _get(server, "/events/nonexistent")
    assert status == 404


# ---------- mutate endpoints ----------


def test_post_event_ack(server: WatchServer, db_path: Path) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    status, body = _post(server, f"/events/{fp}/ack")
    assert status == 200
    assert body["finding"]["status"] == STATUS_ACKNOWLEDGED


def test_post_event_mute_with_hours(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    status, body = _post(server, f"/events/{fp}/mute", {"hours": 24})
    assert status == 200
    assert body["finding"]["status"] == STATUS_MUTED
    assert body["finding"]["muted_until"] is not None


def test_post_event_resolve(server: WatchServer, db_path: Path) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    status, body = _post(server, f"/events/{fp}/resolve")
    assert status == 200
    assert body["finding"]["status"] == STATUS_RESOLVED


def test_post_event_note(server: WatchServer, db_path: Path) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    status, body = _post(
        server, f"/events/{fp}/note", {"text": "rotated 2026-06-05"},
    )
    assert status == 200
    assert body["finding"]["notes"] == "rotated 2026-06-05"


def test_post_event_unknown_verb_returns_400(
    server: WatchServer, db_path: Path,
) -> None:
    db = WatchEventsDB(db_path)
    fp, _ = db.upsert_finding("jwt", "eyJ…A", "x.jsonl", "/x.jsonl", 1)
    status, _ = _post(server, f"/events/{fp}/frobnicate")
    assert status == 400


def test_post_event_unknown_fp_returns_404(server: WatchServer) -> None:
    status, _ = _post(server, "/events/nonexistent/ack")
    assert status == 404


# ---------- webhooks ----------


def test_webhooks_empty(server: WatchServer) -> None:
    status, body = _get(server, "/webhooks")
    assert status == 200
    assert body == {"webhooks": []}


def test_post_webhook_disabled_by_default(
    server: WatchServer, webhooks_path: Path,
) -> None:
    status, body = _post(server, "/webhooks", {
        "id": "slack-1",
        "url": "https://hooks.slack.com/services/T/B/X",
        "on": ["new_finding"],
    })
    assert status == 201
    assert body["webhook"]["enabled"] is False  # D3 invariant


def test_post_webhook_rejects_file_url(server: WatchServer) -> None:
    status, _ = _post(server, "/webhooks", {
        "id": "bad", "url": "file:///etc/passwd",
    })
    assert status == 400


def test_post_webhook_duplicate_id_returns_409(server: WatchServer) -> None:
    _post(server, "/webhooks", {
        "id": "slack-1", "url": "https://hooks.slack.com/services/A/B/C",
    })
    status, _ = _post(server, "/webhooks", {
        "id": "slack-1", "url": "https://hooks.slack.com/services/D/E/F",
    })
    assert status == 409


def test_webhook_enable_disable(server: WatchServer) -> None:
    _post(server, "/webhooks", {
        "id": "h1", "url": "https://hooks.slack.com/services/A/B/C",
    })
    status, body = _post(server, "/webhooks/h1/enable")
    assert status == 200
    assert body["webhook"]["enabled"] is True
    status, body = _post(server, "/webhooks/h1/disable")
    assert body["webhook"]["enabled"] is False


def test_webhook_delete(server: WatchServer) -> None:
    _post(server, "/webhooks", {
        "id": "h1", "url": "https://hooks.slack.com/services/A/B/C",
    })
    status, body = _delete(server, "/webhooks/h1")
    assert status == 200
    status, body = _get(server, "/webhooks")
    assert body["webhooks"] == []


def test_webhook_delete_unknown_returns_404(server: WatchServer) -> None:
    status, _ = _delete(server, "/webhooks/nonexistent")
    assert status == 404


# ---------- index + static ----------


def test_get_root_serves_html(server: WatchServer) -> None:
    url = f"http://127.0.0.1:{server.port}/"
    with urllib.request.urlopen(url, timeout=2) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8")
        assert "aifd" in body.lower()


def test_healthz(server: WatchServer) -> None:
    status, body = _get(server, "/healthz")
    assert status == 200 and body == {"ok": True}


def test_unknown_path_returns_404(server: WatchServer) -> None:
    status, _ = _get(server, "/nope")
    assert status == 404


# ---------- v0.6 click-to-jump regression (no-op endpoint registered) ----------


def test_v06_findings_404_without_register(server: WatchServer) -> None:
    # No register() call → /findings/anything 404s
    url = f"http://127.0.0.1:{server.port}/findings/anything"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            pytest.fail(f"expected 404, got {resp.status}")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
