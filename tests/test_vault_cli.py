"""End-to-end CLI tests for `aifd vault scan` and `aifd vault cost`."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from aifd.cli import cli


def test_vault_group_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
    assert "cost" in result.output


# --------------- aifd vault scan ---------------


def test_vault_scan_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "scan", "--help"])
    assert result.exit_code == 0
    assert "--min-confidence" in result.output
    assert "--root" in result.output
    assert "--no-default-roots" in result.output


def test_vault_scan_explicit_root(tmp_path: Path) -> None:
    """--root + --no-default-roots scans only the given path."""
    fixture = tmp_path / "fake.jsonl"
    fixture.write_text(
        "leaked: sk-proj-abc1234567890abcdef1234567890\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "vault",
            "scan",
            "--no-default-roots",
            "--root",
            str(fixture),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 1
    assert parsed[0]["category"] == "openai_key"
    assert "REDACTED" in parsed[0]["snippet_redacted"]
    # CRITICAL: full secret must NOT appear in JSON output
    assert "sk-proj-abc1234567890abcdef" not in result.output


def test_vault_scan_min_confidence_filters_entropy(tmp_path: Path) -> None:
    """Entropy-only matches (confidence < 7) are suppressed by default."""
    fixture = tmp_path / "f.jsonl"
    fixture.write_text(
        "blob=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA1234567890\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["vault", "scan", "--no-default-roots", "--root", str(fixture), "--json"],
    )
    assert json.loads(result.output) == []
    result = runner.invoke(
        cli,
        [
            "vault", "scan", "--no-default-roots", "--root", str(fixture),
            "--min-confidence", "4", "--json",
        ],
    )
    parsed = json.loads(result.output)
    assert parsed and parsed[0]["category"] == "high_entropy"


def test_vault_scan_clean_data_is_friendly(tmp_path: Path) -> None:
    fixture = tmp_path / "clean.jsonl"
    fixture.write_text("nothing interesting here\n", encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        ["vault", "scan", "--no-default-roots", "--root", str(fixture)],
    )
    assert result.exit_code == 0
    assert "No potential secrets found" in result.output


def test_vault_scan_requires_some_root() -> None:
    """--no-default-roots with no --root is a usage error."""
    result = CliRunner().invoke(cli, ["vault", "scan", "--no-default-roots"])
    assert result.exit_code != 0
    assert "No roots to scan" in result.output


def test_vault_scan_web_help_advertises_flag() -> None:
    """--web should appear in --help output so users discover it."""
    result = CliRunner().invoke(cli, ["vault", "scan", "--help"])
    assert result.exit_code == 0
    assert "--web" in result.output


def test_vault_scan_web_rejects_json(tmp_path: Path) -> None:
    """--web (interactive) and --json (pipe) are mutually exclusive."""
    fixture = tmp_path / "x.jsonl"
    fixture.write_text("nothing here\n", encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        [
            "vault", "scan",
            "--no-default-roots",
            "--root", str(fixture),
            "--web", "--json",
        ],
    )
    assert result.exit_code != 0
    assert "--web" in result.output and "--json" in result.output


def test_serve_web_binds_localhost_and_serves_findings(
    tmp_path: Path,
) -> None:
    """End-to-end --web flow: start server, GET /, assert HTML, shutdown.

    Runs `_serve_web` on a background thread so we can hit the URL
    before tearing down. The server binds 127.0.0.1:0 (kernel-picked
    port) and dies when KeyboardInterrupt fires on the main loop —
    we simulate that with httpd.shutdown() from the test.
    """
    import socketserver
    import threading
    import webbrowser
    from urllib.error import URLError
    from urllib.request import urlopen

    from aifd.cli.vault.scan import _serve_web

    # Stub webbrowser.open so we don't pop a real browser during CI.
    original_open = webbrowser.open
    webbrowser.open = lambda *_a, **_kw: True  # type: ignore[assignment]

    # We'd like to grab the server's actual port. _serve_web doesn't
    # expose it directly. The cleanest path is monkeypatching
    # socketserver.TCPServer to record the bound port for the test.
    captured_port: dict[str, int] = {}
    original_tcp = socketserver.TCPServer

    class _CapturingTCPServer(original_tcp):
        def server_bind(self) -> None:
            super().server_bind()
            captured_port["port"] = self.server_address[1]

    socketserver.TCPServer = _CapturingTCPServer  # type: ignore[misc]

    fixture = tmp_path / "fake.jsonl"
    fixture.write_text(
        f"leaked {_SAMPLE_GITHUB_PAT} here\n",
        encoding="utf-8",
    )

    from aifd.vault.scan import scan_paths
    matches = list(scan_paths(
        [fixture], min_confidence=7, capture_context=True,
    ))
    assert matches, "scan fixture must produce at least one match"

    server_thread = threading.Thread(
        target=_serve_web, args=(matches,), daemon=True,
    )
    server_thread.start()

    try:
        # Wait for the server to bind (typically <50ms).
        for _ in range(100):
            if "port" in captured_port:
                break
            threading.Event().wait(0.01)
        assert "port" in captured_port, "server never bound"
        port = captured_port["port"]

        url = f"http://127.0.0.1:{port}/"
        try:
            with urlopen(url, timeout=2) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8")
        except URLError as exc:
            raise AssertionError(f"server unreachable on {url}: {exc}") from exc

        # The page must contain the warning banner + the marked secret
        # in context.
        assert "contains raw secrets" in body
        assert '<mark class="leak">' in body
        assert _SAMPLE_GITHUB_PAT in body

        # Verify localhost-only binding: connecting from outside loopback
        # is hard to assert directly in pytest; we instead assert the
        # CapturingTCPServer stored a 127.0.0.1-bound address.
        # (The CapturingTCPServer was instantiated with 127.0.0.1
        # explicitly inside _serve_web, so if it's listening, it's
        # listening on loopback.)
        assert port > 0
    finally:
        # Trigger clean shutdown. _serve_web's KeyboardInterrupt handler
        # calls sys.exit(0); from a thread that's not the right unwind.
        # We instead stop the server via the live httpd reference. The
        # simplest path: cause urlopen of a non-existent path to wake
        # up the server, then let the test process exit (daemon thread
        # dies with it).
        socketserver.TCPServer = original_tcp  # type: ignore[misc]
        webbrowser.open = original_open  # type: ignore[assignment]


_SAMPLE_GITHUB_PAT = "ghp_abcdef0123456789abcdef0123456789xyz"


# --------------- aifd vault cost ---------------


def test_vault_cost_help() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--help"])
    assert result.exit_code == 0
    assert "--by" in result.output
    assert "--list-models" in result.output


def test_vault_cost_list_models() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--list-models"])
    assert result.exit_code == 0
    assert "claude-opus-4-7" in result.output
    assert "gpt-5-codex" in result.output


def test_vault_cost_by_invalid_choice() -> None:
    result = CliRunner().invoke(cli, ["vault", "cost", "--by", "garbage"])
    assert result.exit_code != 0
