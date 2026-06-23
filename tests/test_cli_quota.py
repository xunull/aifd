"""Tests for `aifd quota` — MiniMax Coding Plan 5h-window usage.

Covers the cross-store contract that only live testing could pin: model_name
selection (not index), the empty-shell "no subscription" path, defensive parse
on a changed API, and the security invariant that the Bearer key never reaches
any error output (outside-voice #2 blocker).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from aifd import config as config_mod
from aifd.cli.quota import (
    _format_countdown,
    _render,
    _safe_int,
    _select_model,
    quota,
)

_KEY = "mm-secret-key-ABCDEFGHIJ1234567890"

GENERAL = {
    "model_name": "general",
    "current_interval_remaining_percent": 99,
    "remains_time": 12472476,  # ~3h27m
    "current_interval_total_count": 0,
    "current_interval_usage_count": 0,
}
VIDEO = {
    "model_name": "video",
    "current_interval_remaining_percent": 100,
    "remains_time": 44872476,
}


def _resp(model_remains, status_code=0):
    return {
        "model_remains": model_remains,
        "base_resp": {"status_code": status_code, "status_msg": "success"},
    }


class _FakeResp:
    def __init__(self, status_code, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise json.JSONDecodeError("bad", "doc", 0)
        return self._payload


@pytest.fixture
def with_key(monkeypatch):
    """config.load() returns a MiniMax key (env wins in load())."""
    monkeypatch.setenv("MINIMAX_API_KEY", _KEY)
    # Don't let a real ~/.aifd/config.yaml interfere; env takes precedence anyway.
    monkeypatch.setattr(
        config_mod, "_default_config_path", lambda: Path("/nonexistent/config.yaml")
    )
    return _KEY


def _patch_get(monkeypatch, resp):
    # quota.py does `import httpx; httpx.get(...)`, so patching the httpx
    # module's `get` here reaches the same module object it calls.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: resp)


def _patch_raise(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(httpx, "get", boom)


# ---------- happy path ----------


def test_lists_general_quota(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(200, _resp([GENERAL])))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code == 0
    assert "MiniMax 5h" in r.output
    assert "99%" in r.output
    assert "3h27m 后重置" in r.output


def test_selects_general_by_name_not_index(monkeypatch, with_key):
    """outside-voice #4: video first in array — must still pick general."""
    _patch_get(monkeypatch, _FakeResp(200, _resp([VIDEO, GENERAL])))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code == 0
    assert "99%" in r.output  # general's 99, not video's 100


def test_count_shown_when_reliable(monkeypatch, with_key):
    g = dict(GENERAL, current_interval_total_count=40, current_interval_usage_count=2)
    _patch_get(monkeypatch, _FakeResp(200, _resp([g])))
    r = CliRunner().invoke(quota, [])
    assert "剩 38/40" in r.output


def test_minimax_subcommand(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(200, _resp([GENERAL])))
    r = CliRunner().invoke(quota, ["minimax"])
    assert r.exit_code == 0
    assert "MiniMax 5h" in r.output


# ---------- key safety (outside-voice #2 blocker) ----------


def test_key_never_in_network_error_output(monkeypatch, with_key):
    _patch_raise(monkeypatch, httpx.ConnectError("connection refused"))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert _KEY not in r.output
    assert "network error" in r.output


def test_key_never_in_timeout_output(monkeypatch, with_key):
    _patch_raise(monkeypatch, httpx.TimeoutException("timed out"))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert _KEY not in r.output
    assert "timed out" in r.output


def test_key_never_in_401_output(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(401, {}))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert _KEY not in r.output
    assert "invalid or expired" in r.output


# ---------- error paths ----------


def test_no_key(monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setattr(
        config_mod, "_default_config_path", lambda: Path("/nonexistent/config.yaml")
    )
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "MINIMAX_API_KEY" in r.output


def test_no_active_subscription(monkeypatch, with_key):
    """#1: valid key, no active plan → success-shaped empty model_remains."""
    _patch_get(monkeypatch, _FakeResp(200, _resp([])))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "No active MiniMax Coding Plan" in r.output


def test_non_json_response(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(200, None, raise_json=True))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "update aifd" in r.output


def test_status_code_nonzero(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(200, _resp([GENERAL], status_code=1001)))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "update aifd" in r.output


def test_no_general_window(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(200, _resp([VIDEO])))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "update aifd" in r.output


def test_http_500(monkeypatch, with_key):
    _patch_get(monkeypatch, _FakeResp(500, {}))
    r = CliRunner().invoke(quota, [])
    assert r.exit_code != 0
    assert "HTTP 500" in r.output


# ---------- unit: helpers ----------


def test_format_countdown():
    assert _format_countdown(12472476) == "3h27m 后重置"
    assert _format_countdown(120000) == "2m 后重置"
    assert _format_countdown(0) == "重置时间未知"
    assert _format_countdown(None) == "重置时间未知"
    assert _format_countdown(True) == "重置时间未知"  # bool guard


def test_safe_int():
    assert _safe_int(40) == 40
    assert _safe_int(3.9) == 3
    assert _safe_int(None) == 0
    assert _safe_int("x") == 0
    assert _safe_int(True) == 0


def test_render_falls_back_to_percent_when_count_zero():
    assert "99%" in _render(GENERAL)


def test_select_model_by_name():
    row = _select_model(_resp([VIDEO, GENERAL]), "general")
    assert row["model_name"] == "general"
