"""`aifd vault scan` — find PII / secrets across provider jsonl.

Default scope: all known provider history roots (Claude + Codex). Default
min_confidence: 7 (regex hits only — entropy-only matches need explicit
opt-in via --min-confidence 4 because they're noisy).

Output is safe to paste / share / log: every snippet is redacted
(first 4 + last 4 chars only, never the full secret).

`--web` opens a localhost-only HTTP server that renders the findings
with the secret highlighted in its surrounding conversation context.
This is the only flag that exposes raw secrets — the server binds to
127.0.0.1, never writes to disk, and dies on Ctrl-C. See
`docs/secret-scan.md` Security section.
"""

from __future__ import annotations

import http.server
import logging
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

import click

from aifd.cli._logging import configure_logging
from aifd.models import SensitiveMatch
from aifd.render import render_scan_matches, render_scan_matches_html
from aifd.vault.scan import scan_paths

logger = logging.getLogger("aifd")


@click.command(name="scan")
@click.option(
    "--root",
    "extra_roots",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
    help="Additional path to scan (file or directory). Default scans "
    "~/.claude/projects and ~/.codex/sessions. Repeatable.",
)
@click.option(
    "--min-confidence",
    type=click.IntRange(1, 10),
    default=7,
    show_default=True,
    help="Suppress findings below this confidence. 7 keeps regex hits "
    "(API keys, JWTs, emails). Lower to 4 to include entropy-only matches "
    "(often noisy: hashes, UUIDs, embeddings).",
)
@click.option(
    "--no-default-roots",
    is_flag=True,
    help="Skip ~/.claude and ~/.codex; only scan paths from --root.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="JSON output (pipe-friendly). Redacted snippets only — never the "
    "full secret value.",
)
@click.option(
    "--web",
    "as_web",
    is_flag=True,
    help="Open a localhost browser page with each leak highlighted in "
    "its surrounding conversation context. Holds raw secrets in memory; "
    "press Ctrl-C in the terminal to drop them.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def scan(
    extra_roots: tuple[Path, ...],
    min_confidence: int,
    no_default_roots: bool,
    as_json: bool,
    as_web: bool,
    verbose: int,
) -> None:
    """Scan provider jsonl for PII / API keys / secrets.

    By default scans ~/.claude/projects and ~/.codex/sessions. Add
    --root /path to scan extra locations, or --no-default-roots to scan
    only your --root paths.

    Output snippets are redacted (head + tail only). Safe to share.

    --web opens a browser view with each leak highlighted in its
    original conversation context. The HTML is served from a
    localhost-only HTTP server (127.0.0.1, kernel-picked port) and is
    NEVER written to disk. Press Ctrl-C to stop the server when done.
    """
    configure_logging(verbose)

    if as_json and as_web:
        raise click.UsageError(
            "--web is interactive (browser); --json is pipe-only. "
            "Pick one."
        )

    roots: list[Path] = []
    if not no_default_roots:
        roots.append(Path.home() / ".claude" / "projects")
        roots.append(Path.home() / ".codex" / "sessions")
        roots.append(Path.home() / ".codex" / "archived_sessions")
    roots.extend(extra_roots)

    if not roots:
        raise click.UsageError(
            "No roots to scan. Drop --no-default-roots or supply --root PATH."
        )

    logger.info("Scanning %d root(s) for PII / secrets", len(roots))
    # Propagate min_confidence into the scanner so the entropy layer
    # (confidence 4-6 only) is skipped whenever the caller wouldn't
    # display its results. This is the main perf optimization — default
    # `aifd vault scan` (min_confidence=7) goes from ~50s to ~3s on
    # 800MB of jsonl by skipping shannon_entropy entirely.
    matches = list(scan_paths(
        roots,
        min_confidence=min_confidence,
        capture_context=as_web,
    ))

    if as_web:
        # Filter at the CLI layer (same threshold semantics as table mode)
        # so the server only renders what the user actually wants to see.
        visible = [m for m in matches if m.confidence >= min_confidence]
        _serve_web(visible)
        return

    render_scan_matches(matches, as_json=as_json, min_confidence=min_confidence)


def _serve_web(matches: list[SensitiveMatch]) -> None:
    """Start a localhost-only HTTP server serving the scan report.

    Binds 127.0.0.1 on a kernel-picked port (port=0), serves the HTML
    on every GET, opens the user's default browser, then blocks until
    Ctrl-C. The HTML is generated once and held in memory; nothing is
    persisted to disk. SIGINT triggers `server.shutdown()` and the
    process exits cleanly.

    The handler returns 200 + HTML for `GET /` and 404 for everything
    else (no favicon requests, no asset paths) — the page is fully
    self-contained, so any other route is junk.
    """
    page = render_scan_matches_html(matches).encode("utf-8")

    class _Handler(http.server.BaseHTTPRequestHandler):
        # http.server requires the literal `do_GET` method name.
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(404, "Not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, fmt: str, *args: object) -> None:
            # Silence default stdout/stderr access log — keep terminal
            # clean so the only thing the user sees is our "press Ctrl-C"
            # banner. Set -vv to re-enable via standard logging if needed.
            logger.debug("http: " + fmt, *args)

    # 127.0.0.1 explicitly (NOT 0.0.0.0) so other hosts on the LAN cannot
    # reach our secrets. port=0 lets the kernel pick an unused ephemeral
    # port so concurrent --web invocations don't collide.
    with socketserver.TCPServer(("127.0.0.1", 0), _Handler) as httpd:
        # server_address is (host_bytes_or_str, port). On AF_INET it's
        # always (str, int) but the typeshed widens to bytes — decode
        # defensively.
        host_raw, port = httpd.server_address[:2]
        host = host_raw.decode() if isinstance(host_raw, bytes) else host_raw
        url = f"http://{host}:{port}/"
        click.echo(
            f"aifd vault scan --web · {len(matches)} finding"
            f"{'' if len(matches) == 1 else 's'} on {url}",
            err=True,
        )
        click.echo(
            "  ⚠ this URL exposes raw secrets; do not share.",
            err=True,
        )
        click.echo(
            "  Ctrl-C to stop the server and drop secrets from memory.",
            err=True,
        )

        # serve_forever() blocks; run on a background thread so we can
        # catch KeyboardInterrupt on the main thread and shut down.
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        webbrowser.open(url)
        try:
            thread.join()
        except KeyboardInterrupt:
            click.echo("\nShutting down. Secrets dropped.", err=True)
            httpd.shutdown()
            sys.exit(0)
