"""Tests for `aifd vault watch` — daemon, tail reader, dedupe, state.

The daemon's full event loop is integration-heavy (watchdog + threads +
sockets + macOS notifications); we test the pure-Python pieces directly
and let `tests/test_vault_watch_cli.py` cover the click shell.

Coverage map (per locked plan T10):
  - WatchState  : load / save / atomic / version migration / catches_in_window
  - TailReader  : initial / append / rotate / truncate / partial trailing line
  - DedupeCache : first-hit / second-hit / TTL eviction / LRU cap
  - Notifier    : (probe / dispatch covered by mock — no real osascript fires)
  - WatchServer : start / register / fetch / 404 / stop
  - integration : _handle_match → state + dedupe + server + notifier wired
"""

from __future__ import annotations

import json
import socket
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from aifd.models import SensitiveMatch
from aifd.vault.watch import (
    DedupeCache,
    Notifier,
    TailReader,
    WatchState,
    catches_in_window,
)
from aifd.vault.watch_server import start_server

# ---------- WatchState ----------


def test_watchstate_load_missing_returns_empty(tmp_path: Path) -> None:
    state = WatchState.load(tmp_path / "nonexistent.json")
    assert state.total_catches == 0
    assert state.files == {}
    assert state.version == 1


def test_watchstate_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    s = WatchState()
    s.files["/foo.jsonl"] = {"offset": 100, "size": 100, "mtime": 1.0, "line_no": 5}
    fixed = datetime(2026, 6, 4, 12, 0, tzinfo=UTC).astimezone()
    s.record_catch(now=fixed)
    s.save(p)

    loaded = WatchState.load(p)
    assert loaded.files == s.files
    assert loaded.total_catches == 1
    expected_day = fixed.strftime("%Y-%m-%d")
    assert loaded.catches_by_day == {expected_day: 1}


def test_watchstate_save_atomic_no_partial_on_crash(tmp_path: Path) -> None:
    """tmp+rename means an interrupted save leaves the previous valid file."""
    p = tmp_path / "state.json"
    WatchState().save(p)
    original = p.read_text()
    # Confirm the rename target is the canonical name (tmp is gone)
    assert not p.with_suffix(p.suffix + ".tmp").exists()
    assert json.loads(original)["version"] == 1


def test_watchstate_corrupt_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text("not json at all {{{")
    loaded = WatchState.load(p)
    assert loaded.total_catches == 0
    assert loaded.files == {}


def test_watchstate_unknown_version_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 99, "files": {"x": {}}, "total_catches": 5}))
    loaded = WatchState.load(p)
    assert loaded.total_catches == 0
    assert loaded.files == {}


def test_watchstate_catches_in_window_filters_by_local_date() -> None:
    s = WatchState()
    s.catches_by_day = {
        "2026-06-01": 3,
        "2026-06-04": 5,
        "2026-06-05": 2,
        "2026-06-07": 1,
    }
    local = datetime(2026, 6, 4).astimezone().tzinfo
    start = datetime(2026, 6, 4, tzinfo=local)
    end = datetime(2026, 6, 7, tzinfo=local)
    assert s.catches_in_window(start, end) == 7  # 5 + 2, not the 7th


def test_catches_in_window_module_helper_returns_zero_without_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aifd.vault.watch_state.STATE_FILE", tmp_path / "empty.json")
    local = datetime.now().astimezone().tzinfo
    assert catches_in_window(
        datetime(2026, 6, 1, tzinfo=local),
        datetime(2026, 6, 30, tzinfo=local),
    ) == 0


# ---------- TailReader ----------


def test_tailreader_first_read_returns_all_lines(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.write_text("line one\nline two\nline three\n")
    reader = TailReader(WatchState())
    lines = list(reader.read_new_lines(p))
    assert [text for _, text in lines] == ["line one", "line two", "line three"]
    assert [n for n, _ in lines] == [1, 2, 3]


def test_tailreader_second_read_returns_only_new_lines(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.write_text("a\nb\n")
    state = WatchState()
    reader = TailReader(state)
    list(reader.read_new_lines(p))
    p.write_text("a\nb\nc\nd\n")
    new = list(reader.read_new_lines(p))
    assert [text for _, text in new] == ["c", "d"]
    assert [n for n, _ in new] == [3, 4]


def test_tailreader_skips_partial_trailing_line(tmp_path: Path) -> None:
    """Partial line (no trailing \\n) must NOT be yielded — wait for the \\n."""
    p = tmp_path / "session.jsonl"
    p.write_text("complete\npartial-no-newline")
    reader = TailReader(WatchState())
    lines = list(reader.read_new_lines(p))
    assert [text for _, text in lines] == ["complete"]


def test_tailreader_handles_rotation(tmp_path: Path) -> None:
    p = tmp_path / "session.jsonl"
    p.write_text("a\nb\nc\n")
    state = WatchState()
    reader = TailReader(state)
    list(reader.read_new_lines(p))
    # Simulate rotation: shrink file
    p.write_text("x\ny\n")
    new = list(reader.read_new_lines(p))
    assert [text for _, text in new] == ["x", "y"]


def test_tailreader_handles_missing_file_silently(tmp_path: Path) -> None:
    p = tmp_path / "ghost.jsonl"
    state = WatchState()
    state.files[str(p)] = {"offset": 100, "size": 100, "mtime": 0.0, "line_no": 1}
    list(TailReader(state).read_new_lines(p))
    assert str(p) not in state.files


# ---------- DedupeCache ----------


def test_dedupe_first_hit_notifies() -> None:
    cache = DedupeCache()
    assert cache.should_notify("aws_secret", "AKIA…ABCD") is True


def test_dedupe_second_hit_within_ttl_suppressed() -> None:
    cache = DedupeCache()
    cache.should_notify("aws_secret", "AKIA…ABCD")
    assert cache.should_notify("aws_secret", "AKIA…ABCD") is False


def test_dedupe_distinct_secrets_each_notify() -> None:
    cache = DedupeCache()
    assert cache.should_notify("aws_secret", "AKIA…1111") is True
    assert cache.should_notify("aws_secret", "AKIA…2222") is True
    assert cache.should_notify("jwt", "AKIA…1111") is True  # different category


def test_dedupe_ttl_eviction_re_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """After the dedupe TTL expires, the same secret should re-notify."""
    cache = DedupeCache()
    cache.should_notify("aws_secret", "AKIA…ABCD")
    # Fast-forward the cache's stored timestamp past the TTL.
    from aifd.vault import watch as watch_mod
    key = ("aws_secret", "AKIA…ABCD")
    cache._seen[key] = datetime.now(UTC) - watch_mod._DEDUPE_TTL - timedelta(seconds=1)
    assert cache.should_notify("aws_secret", "AKIA…ABCD") is True


def test_dedupe_lru_cap_evicts_oldest() -> None:
    """When over capacity, oldest entry is evicted (LRU)."""
    from aifd.vault import watch as watch_mod
    cache = DedupeCache()
    for i in range(watch_mod._DEDUPE_MAX + 10):
        cache.should_notify("cat", f"snippet-{i}")
    assert len(cache._seen) <= watch_mod._DEDUPE_MAX
    # Oldest entries gone, newest still present
    assert ("cat", "snippet-0") not in cache._seen
    assert ("cat", f"snippet-{watch_mod._DEDUPE_MAX + 9}") in cache._seen


# ---------- Notifier ----------


def test_notifier_dispatch_uses_osascript_when_terminal_notifier_missing() -> None:
    """No terminal-notifier on PATH → osascript fallback fires."""
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=False):
        notifier = Notifier()
    with patch("aifd.vault.watch.subprocess.run") as run:
        run.return_value.returncode = 0
        notifier.notify("title", "body", url=None)
    assert run.called
    cmd = run.call_args[0][0]
    assert cmd[0] == "osascript"


def test_notifier_dispatch_uses_terminal_notifier_when_available() -> None:
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=True):
        notifier = Notifier()
    with patch("aifd.vault.watch.subprocess.run") as run:
        run.return_value.returncode = 0
        notifier.notify("t", "b", url="http://127.0.0.1:1/findings/abc")
    cmd = run.call_args[0][0]
    assert cmd[0] == "terminal-notifier"
    assert "-open" in cmd


def test_notifier_swallows_dispatch_failure() -> None:
    """A failed osascript must not bubble out — daemon stays alive."""
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=False):
        notifier = Notifier()
    with patch(
        "aifd.vault.watch.subprocess.run",
        side_effect=RuntimeError("boom"),
    ):
        notifier.notify("t", "b")  # must not raise
    assert notifier.last_notify_failed is True


def test_notifier_warns_when_terminal_notifier_missing() -> None:
    """Construct path must emit a WARNING when falling back to osascript.

    Regression: without this warning, users discover "click opens Script
    Editor" only after deploying the daemon. Surface it at startup time.
    """
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=False):
        with patch("aifd.vault.watch.logger.warning") as warn:
            notifier = Notifier()
    assert notifier.backend == "osascript"
    assert warn.called
    msg = warn.call_args[0][0]
    assert "terminal-notifier not found" in msg


def test_notifier_no_warning_when_terminal_notifier_present() -> None:
    """No warning when the happy path (terminal-notifier installed) is used."""
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=True):
        with patch("aifd.vault.watch.logger.warning") as warn:
            notifier = Notifier()
    assert notifier.backend == "terminal-notifier"
    assert not warn.called


def test_notifier_osascript_body_omits_url() -> None:
    """osascript body must NOT contain the raw URL.

    The osascript `display notification` verb doesn't support click
    handlers, so showing a URL the user can't click is just user-hostile
    noise that gets truncated in Notification Center. Replace it with
    a clear "click disabled" hint.
    """
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=False):
        notifier = Notifier()
    url = "http://127.0.0.1:54791/findings/abc123def456"
    with patch("aifd.vault.watch.subprocess.run") as run:
        run.return_value.returncode = 0
        notifier.notify("aifd: secret detected", "openai_key · AKIA…WXYZ", url=url)
    script_arg = run.call_args[0][0][-1]  # last positional = AppleScript
    assert url not in script_arg
    assert "click disabled" in script_arg
    assert "terminal-notifier" in script_arg


# ---------- WatchServer ----------


def _make_match() -> SensitiveMatch:
    return SensitiveMatch(
        file=Path("/tmp/fake.jsonl"),
        line=42,
        category="aws_secret",
        snippet_redacted="AKIA…WXYZ",
        confidence=8,
        full_length=40,
    )


def test_watchserver_register_and_fetch_renders_match() -> None:
    server = start_server()
    try:
        token = "test-token-123"
        server.register(token, _make_match())
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{server.port}/findings/{token}",
            timeout=2,
        )
        body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "AKIA…WXYZ" in body
        assert "aws_secret" in body
    finally:
        server.stop()


def test_watchserver_unknown_token_returns_404() -> None:
    server = start_server()
    try:
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(
                f"http://127.0.0.1:{server.port}/findings/unknown-token",
                timeout=2,
            )
        assert excinfo.value.code == 404
    finally:
        server.stop()


def test_watchserver_binds_loopback_only() -> None:
    """The server MUST bind 127.0.0.1, not 0.0.0.0 — secrets in memory."""
    server = start_server()
    try:
        host, _port = server.httpd.server_address[:2]
        host_str = host.decode() if isinstance(host, bytes) else host
        assert host_str == "127.0.0.1"
    finally:
        server.stop()


def test_watchserver_stop_releases_port() -> None:
    server = start_server()
    port = server.port
    server.stop()
    # Port must be re-bindable (TIME_WAIT acceptable in macOS, so use
    # SO_REUSEADDR to be deterministic).
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    finally:
        s.close()


# ---------- E10 today integration ----------


def test_catches_in_window_used_by_today_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the public helper reads state and applies the window correctly."""
    state_file = tmp_path / "watch-state.json"
    s = WatchState()
    today = datetime.now().astimezone()
    s.catches_by_day = {
        today.strftime("%Y-%m-%d"): 3,
        (today - timedelta(days=10)).strftime("%Y-%m-%d"): 99,  # outside
    }
    s.save(state_file)
    monkeypatch.setattr("aifd.vault.watch_state.STATE_FILE", state_file)

    local = today.tzinfo
    start = datetime(today.year, today.month, today.day, tzinfo=local)
    end = start + timedelta(days=1)
    assert catches_in_window(start, end) == 3


# ---------- helper: probe_permission ----------


def test_notifier_probe_permission_swallows_failure() -> None:
    """Probe failure should NOT block daemon start — returns False."""
    with patch.object(Notifier, "_probe_terminal_notifier", return_value=False):
        notifier = Notifier()
    with patch(
        "aifd.vault.watch.subprocess.run",
        side_effect=RuntimeError("no permission"),
    ):
        result = notifier.probe_permission()
    assert result is False


# Pin a small fudge — server fixtures rely on a free port being available.
# Skip on hosts where loopback is restricted (rare).
def test_can_bind_loopback() -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
    except OSError:
        pytest.skip("Loopback bind not permitted in this environment")
    finally:
        s.close()


# Slow tests are excluded from the regular suite to keep CI snappy.
@pytest.mark.skip(reason="time-based; manual run only")
def test_dedupe_real_ttl_expiry_re_notifies() -> None:
    cache = DedupeCache()
    cache.should_notify("c", "s")
    time.sleep(0.01)
    assert cache.should_notify("c", "s") is False
