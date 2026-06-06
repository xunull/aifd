"""`aifd vault watch` — real-time secret detection daemon (v0.6).

Subcommands:
  start       launch the daemon (background by default, --foreground to attach)
  stop        send SIGTERM to the running daemon
  status      show pid / port / counters / last error
  tail        tail the daemon log file
  install     write a launchd .plist into ~/Library/LaunchAgents
  uninstall   unload + remove the .plist
  daemon      INTERNAL — the actual long-running loop (launchd entrypoint)

Single-instance enforcement: the daemon acquires an fcntl.flock on
~/.aifd/watch.pid. A second invocation fails fast with EWOULDBLOCK.
Stale pidfiles after a crash are tolerated — the lock is exclusive, so
acquiring it means we're the only live process even if a corpse pid is
on disk.

Foreground start is for debugging — the daemon stays attached to the
terminal and Ctrl-C triggers a clean SIGINT shutdown. Background start
double-forks (POSIX daemonize) so the child survives shell exit; stdout
and stderr are redirected to ~/.aifd/watch.log.
"""

from __future__ import annotations

import errno
import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click

from aifd.cli._logging import configure_logging

# Import only from the lightweight watch_state module at module load so the
# `aifd` CLI entry point can boot in environments that haven't installed
# `watchdog` (a hard dep of the Daemon, lazy-loaded inside the commands
# that actually start it: `start --foreground` and `daemon`).
from aifd.vault.watch_state import (
    AIFD_HOME,
    LOG_FILE,
    PID_FILE,
    PORT_FILE,
    STATE_FILE,
    WatchState,
)

logger = logging.getLogger("aifd")


# launchd template — kept inline so the install command is a single-file
# operation, no extra resource files. macOS-only by design; Linux watch
# uses `systemctl --user` (out of v0.6 scope, doc'd as future work).
_LAUNCHD_LABEL = "io.aifd.watch"
_LAUNCHD_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{aifd_bin}</string>
        <string>vault</string>
        <string>watch</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
"""


@click.group(name="watch", invoke_without_command=False)
def watch() -> None:
    """Real-time secret detection daemon.

    Watches Claude / Codex jsonl roots; pushes a macOS notification when
    a new secret lands. Click the notification to open a localhost page
    with the leak highlighted in its conversation context.

    Typical first run:

    \b
        aifd vault watch install   # one-time: register with launchd
        aifd vault watch status    # confirm pid / port / counters

    Or run foreground for debugging:

    \b
        aifd vault watch start --foreground -v
    """


# ---------- start / stop / status ----------


@watch.command(name="start")
@click.option(
    "--foreground", "-f",
    is_flag=True,
    help="Run attached to the terminal (Ctrl-C to stop). Default forks "
    "into the background and writes to ~/.aifd/watch.log.",
)
@click.option(
    "-v", "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG.",
)
def start_cmd(foreground: bool, verbose: int) -> None:
    """Start the watch daemon.

    If a launchd .plist is installed and launchd has unloaded it (e.g. after
    `aifd vault watch stop`), this re-bootstraps it. Otherwise daemonizes a
    fresh background process. `--foreground` always runs in-place and refuses
    to start if launchd is already managing one.
    """
    configure_logging(verbose)
    AIFD_HOME.mkdir(parents=True, exist_ok=True)

    if _is_running():
        pid = _read_pid()
        raise click.ClickException(
            f"Watch daemon already running (pid {pid}). "
            "Run `aifd vault watch stop` first."
        )

    plist = _launchd_plist_path()
    if plist.exists() and not foreground:
        # User did `install` previously; defer to launchd so KeepAlive +
        # auto-start-on-login keep working. bootstrap = "load this unit".
        uid = os.getuid()
        r = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise click.ClickException(
                f"launchctl bootstrap failed: {r.stderr.strip() or r.stdout.strip()}"
            )
        click.echo(f"Watch daemon re-loaded via launchd ({plist.name}).")
        click.echo("Run `aifd vault watch status` to confirm.")
        return

    if foreground:
        _run_daemon_with_lock()
        return

    _daemonize_and_run()


@watch.command(name="stop")
def stop_cmd() -> None:
    """Stop the running watch daemon.

    If launchd is managing the daemon (`install`-ed previously), uses
    `launchctl bootout` so KeepAlive doesn't immediately respawn it. The
    .plist is kept on disk; `aifd vault watch start` will re-bootstrap it.
    Otherwise sends SIGTERM directly and waits up to 10s for graceful exit.

    Use `aifd vault watch uninstall` to fully remove (this would also stop).
    """
    plist = _launchd_plist_path()
    uid = os.getuid()

    if plist.exists() and _launchd_loaded(uid):
        # bootout = "stop + remove from launchd management". KeepAlive
        # cannot respawn what launchd is no longer tracking.
        r = subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/{_LAUNCHD_LABEL}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise click.ClickException(
                f"launchctl bootout failed: {r.stderr.strip() or r.stdout.strip()}"
            )
        click.echo("Stopped watch daemon (launchd unloaded).")
        click.echo("Daemon will NOT auto-restart until "
                   "`aifd vault watch start` (or login).")
        return

    pid = _read_pid()
    if pid is None or not _pid_alive(pid):
        click.echo("Watch daemon is not running.", err=True)
        sys.exit(1)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        click.echo("Watch daemon disappeared before signal landed.", err=True)
        return
    # Wait for graceful shutdown — daemon flushes state + closes sockets.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            click.echo(f"Stopped watch daemon (pid {pid}).")
            return
        time.sleep(0.2)
    click.echo(
        f"Watch daemon (pid {pid}) did not exit within 10s — "
        "still running, may need SIGKILL.",
        err=True,
    )
    sys.exit(1)


def _launchd_loaded(uid: int) -> bool:
    """Return True if launchctl currently has our service loaded.

    `launchctl print` exits non-zero when the service isn't registered.
    Cheap probe; runs in well under 100ms.
    """
    r = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{_LAUNCHD_LABEL}"],
        capture_output=True,
    )
    return r.returncode == 0


@watch.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def status_cmd(as_json: bool) -> None:
    """Show daemon pid, port, catches today / total, last notify."""
    pid = _read_pid()
    running = pid is not None and _pid_alive(pid)
    port = _read_port() if running else None
    # Resolve STATE_FILE dynamically so tests can monkeypatch the location.
    import aifd.vault.watch_state as _ws
    state = WatchState.load(_ws.STATE_FILE)
    today = time.strftime("%Y-%m-%d")
    notif_backend = _probe_notification_backend()
    info = {
        "running": running,
        "pid": pid if running else None,
        "port": port,
        "url": f"http://127.0.0.1:{port}/" if port else None,
        "state_file": str(STATE_FILE),
        "log_file": str(LOG_FILE),
        "total_catches": state.total_catches,
        "catches_today": state.catches_by_day.get(today, 0),
        "tracked_files": len(state.files),
        "notification_backend": notif_backend,
        "click_to_jump": notif_backend == "terminal-notifier",
        "finding_drop_count": state.finding_drop_count,
    }
    if as_json:
        click.echo(json.dumps(info, indent=2))
        return
    badge = "RUNNING" if running else "STOPPED"
    click.echo(f"aifd vault watch · {badge}")
    if running:
        click.echo(f"  pid          {info['pid']}")
        if port:
            click.echo(f"  server       http://127.0.0.1:{port}/")
    click.echo(f"  state file   {info['state_file']}")
    click.echo(f"  log file     {info['log_file']}")
    click.echo(f"  catches      {info['total_catches']} total, "
               f"{info['catches_today']} today")
    click.echo(f"  tracking     {info['tracked_files']} jsonl file(s)")
    if state.finding_drop_count:
        click.echo(
            f"  drops        ⚠ {state.finding_drop_count} finding(s) dropped "
            "(events DB write failures — check log)"
        )
    if notif_backend == "terminal-notifier":
        click.echo("  notifier     terminal-notifier (click-to-jump enabled)")
    else:
        click.echo(
            "  notifier     osascript "
            "(⚠ click opens Script Editor — install terminal-notifier to fix:"
            " `brew install terminal-notifier`)"
        )


def _probe_notification_backend() -> str:
    """Return 'terminal-notifier' if installed on PATH, else 'osascript'.

    Mirrors aifd.vault.watch.Notifier._probe_terminal_notifier without
    needing to import the watchdog-heavy watch module.
    """
    import shutil
    return "terminal-notifier" if shutil.which("terminal-notifier") else "osascript"


@watch.command(name="tail")
@click.option("-n", "--lines", type=int, default=50, show_default=True,
              help="Print the last N lines, then follow.")
def tail_cmd(lines: int) -> None:
    """Tail the daemon log file. Ctrl-C to stop."""
    if not LOG_FILE.exists():
        click.echo(f"No log file at {LOG_FILE} — daemon may not have run yet.",
                   err=True)
        sys.exit(1)
    # Defer to `tail -F` (follows rotation) instead of reimplementing.
    try:
        subprocess.run(["tail", "-n", str(lines), "-F", str(LOG_FILE)])
    except KeyboardInterrupt:
        pass


# ---------- launchd install / uninstall ----------


@watch.command(name="install")
def install_cmd() -> None:
    """Install the launchd .plist so the daemon survives login/reboot."""
    if sys.platform != "darwin":
        raise click.ClickException(
            "launchd install is macOS-only. Linux: use systemctl --user "
            "(see docs/vault-watch.md)."
        )
    aifd_bin = _resolve_aifd_bin()
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        _LAUNCHD_PLIST_TEMPLATE.format(
            label=_LAUNCHD_LABEL,
            aifd_bin=aifd_bin,
            log_file=str(LOG_FILE),
        ),
        encoding="utf-8",
    )
    # `launchctl bootstrap` (modern API) vs `load` (deprecated). bootstrap
    # is gui/<uid> scoped and survives logout — match what `brew services`
    # uses.
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        check=True,
    )
    click.echo(f"Installed {plist_path}")
    click.echo("Daemon will start at next login (and now via KeepAlive).")
    click.echo("Run `aifd vault watch status` to confirm.")


@watch.command(name="uninstall")
def uninstall_cmd() -> None:
    """Stop the daemon + remove the launchd .plist."""
    if sys.platform != "darwin":
        raise click.ClickException("launchd uninstall is macOS-only.")
    plist_path = _launchd_plist_path()
    if not plist_path.exists():
        click.echo(f"No .plist at {plist_path} — already uninstalled.")
        return
    uid = os.getuid()
    # bootout is the inverse of bootstrap. Best-effort: ignore failure
    # because the plist may have been manually unloaded already.
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{_LAUNCHD_LABEL}"],
        capture_output=True,
    )
    plist_path.unlink()
    click.echo(f"Removed {plist_path}")


# ---------- internal: launchd entrypoint ----------


@watch.command(name="daemon", hidden=True)
def daemon_cmd() -> None:
    """INTERNAL — the long-running daemon process (launchd target)."""
    _setup_daemon_logging()
    _run_daemon_with_lock()


# ---------- helpers ----------


def _run_daemon_with_lock() -> None:
    """Acquire fcntl.flock on PID_FILE, then run Daemon.run().

    The lock is exclusive + non-blocking: a second invocation fails fast
    with EWOULDBLOCK rather than silently second-instancing. PID is
    written AFTER the lock so reading watch.pid is meaningful.

    Lazy-imports `Daemon` so the CLI module can load without watchdog;
    that dep only matters once we're actually starting the loop.
    """
    AIFD_HOME.mkdir(parents=True, exist_ok=True)
    try:
        from aifd.vault.watch import Daemon
    except ModuleNotFoundError as exc:
        raise click.ClickException(
            f"Cannot start watch daemon — missing dependency: {exc.name}. "
            "Reinstall aifd to pull v0.6 deps: `uv tool install --force aifd` "
            "or `pip install --upgrade aifd`."
        ) from exc
    fp = open(PID_FILE, "w+", encoding="utf-8")
    try:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
            fp.close()
            click.echo(
                "Another `aifd vault watch daemon` is already running. "
                "Use `aifd vault watch stop` to terminate it.",
                err=True,
            )
            sys.exit(1)
        raise
    fp.write(str(os.getpid()))
    fp.flush()
    try:
        Daemon().run()
    finally:
        # Lock auto-releases on fd close; pidfile is informational, so
        # remove it on clean exit. On crash, the next start sees a stale
        # pid but flock will allow re-acquisition.
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        fp.close()


def _daemonize_and_run() -> None:
    """Double-fork POSIX daemonize, then exec the daemon subcommand.

    We re-exec `aifd vault watch daemon` instead of forking in-process so
    the child inherits a clean Python interpreter and the same launchd
    .plist would invoke identically. Parent returns to the shell.
    """
    aifd_bin = _resolve_aifd_bin()
    # First fork: detach from the shell process group.
    if os.fork() != 0:
        click.echo("Watch daemon starting in background — "
                   "`aifd vault watch status` to confirm.")
        return
    # Child: become session leader so the next fork can fully detach.
    os.setsid()
    if os.fork() != 0:
        os._exit(0)
    # Grandchild: redirect stdio to log file + exec the daemon command.
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(str(LOG_FILE), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_fd, 0)
    os.execvp(aifd_bin, [aifd_bin, "vault", "watch", "daemon"])


def _setup_daemon_logging() -> None:
    """Route logger output to LOG_FILE for the daemon entrypoint.

    For launchd-spawned daemons, stdout/stderr go to the .plist's
    StandardOut/ErrorPath. For our own _daemonize_and_run path,
    stdout/stderr are already dup2'd onto LOG_FILE — so plain
    StreamHandler(stdout) writes to the right place either way.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    root = logging.getLogger("aifd.vault.watch")
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        text = PID_FILE.read_text(encoding="utf-8").strip()
        return int(text) if text else None
    except (OSError, ValueError):
        return None


def _read_port() -> int | None:
    if not PORT_FILE.exists():
        return None
    try:
        return int(PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Different uid owns the pid — treat as alive (we can't signal it,
        # but the slot is taken).
        return True
    return True


def _is_running() -> bool:
    pid = _read_pid()
    return pid is not None and _pid_alive(pid)


def _resolve_aifd_bin() -> str:
    """Find the `aifd` binary path for embedding into launchd / exec.

    sys.argv[0] is usually a wrapper script created by pip / uv. Resolve
    via shutil.which so the path is stable across shell invocations.
    """
    import shutil
    found = shutil.which("aifd")
    if found is None:
        # Fallback: invoke via current Python interpreter
        # (`python -m aifd`). Less pretty but always works.
        return f"{sys.executable} -m aifd"
    return found


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"


# ---------- v0.7 events + webhooks subcommands ----------


def _events_db_path() -> Path:
    # Resolve dynamically so tests can monkeypatch AIFD_HOME at runtime.
    import aifd.vault.watch_state as _ws
    return _ws.AIFD_HOME / "findings.db"


def _webhooks_yaml_path() -> Path:
    import aifd.vault.watch_state as _ws
    return _ws.AIFD_HOME / "webhooks.yaml"


def _open_events_db() -> Any:
    """Open events DB read-only — for CLI commands. Returns None if no DB yet."""
    db_path = _events_db_path()
    if not db_path.exists():
        return None
    from aifd.vault.events_db import WatchEventsDB
    return WatchEventsDB(db_path)


@watch.group(name="events")
def events_group() -> None:
    """Browse / manage persistent finding events (v0.7)."""


@events_group.command(name="list")
@click.option("--status", type=click.Choice(
    ["new", "acknowledged", "resolved", "muted"], case_sensitive=False,
), help="Filter by status.")
@click.option("--category", help="Filter by category (e.g. openai_key).")
@click.option("--limit", type=int, default=50, show_default=True)
@click.option("--offset", type=int, default=0, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def events_list(
    status: str | None, category: str | None,
    limit: int, offset: int, as_json: bool,
) -> None:
    """List findings, most recent first."""
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet — daemon hasn't run or hasn't caught anything.",
                   err=True)
        return
    rows = db.list_findings(
        status=status, category=category, limit=limit, offset=offset,
    )
    total = db.count_findings(status=status, category=category)
    if as_json:
        click.echo(json.dumps({
            "total": total, "limit": limit, "offset": offset,
            "findings": [dict(r) for r in rows],
        }, indent=2))
        return
    click.echo(f"{total} finding(s) total, showing {len(rows)}")
    click.echo(
        f"{'STATUS':<13} {'CAT':<18} {'SNIPPET':<22} "
        f"{'COUNT':>5} {'LAST SEEN':<19} FINGERPRINT"
    )
    for r in rows:
        click.echo(
            f"{r['status']:<13} {r['category'][:18]:<18} "
            f"{r['snippet_redacted'][:22]:<22} {r['count']:>5} "
            f"{r['last_seen'][:19]:<19} {r['fingerprint']}"
        )


@events_group.command(name="show")
@click.argument("fingerprint")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def events_show(fingerprint: str, as_json: bool) -> None:
    """Show one finding's full detail (occurrences + playbook)."""
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        sys.exit(1)
    row = db.get_finding(fingerprint)
    if row is None:
        click.echo(f"No finding with fingerprint {fingerprint!r}", err=True)
        sys.exit(1)
    occurrences = db.list_occurrences(fingerprint)
    from aifd.vault.playbooks import lookup as playbook_lookup
    pb = playbook_lookup(row["category"])
    if as_json:
        click.echo(json.dumps({
            "finding": dict(row),
            "occurrences": [dict(o) for o in occurrences],
            "playbook": {
                "vendor_dashboard": pb["vendor_dashboard"],
                "instruction": pb["instruction"],
                "severity": pb["severity"],
            },
        }, indent=2))
        return
    click.echo(f"Finding {row['fingerprint']}")
    click.echo(f"  category   {row['category']}")
    click.echo(f"  snippet    {row['snippet_redacted']}")
    click.echo(f"  status     {row['status']}")
    click.echo(f"  count      {row['count']}")
    click.echo(f"  first seen {row['first_seen']}")
    click.echo(f"  last seen  {row['last_seen']}")
    if row["notes"]:
        click.echo(f"  notes      {row['notes']}")
    click.echo()
    click.echo("ROTATION PLAYBOOK")
    if pb["vendor_dashboard"]:
        click.echo(f"  → {pb['vendor_dashboard']}")
    for line in pb["instruction"]["en"].splitlines():
        click.echo(f"  {line}")
    click.echo()
    click.echo(f"OCCURRENCES ({len(occurrences)})")
    for o in occurrences:
        click.echo(f"  {o['seen_at'][:19]} {o['file_basename']}:{o['line']}")


@events_group.command(name="ack")
@click.argument("fingerprint")
def events_ack(fingerprint: str) -> None:
    """Mark a finding as acknowledged."""
    _mutate_status(fingerprint, "ack")


@events_group.command(name="mute")
@click.argument("fingerprint")
@click.option("--hours", type=float, default=None,
              help="Mute for N hours; omit for forever.")
def events_mute(fingerprint: str, hours: float | None) -> None:
    """Mute a finding for N hours (or forever)."""
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        sys.exit(1)
    from aifd.vault.events_db import STATUS_MUTED
    if not db.mutate_status(fingerprint, STATUS_MUTED, mute_hours=hours):
        click.echo(f"No finding with fingerprint {fingerprint!r}", err=True)
        sys.exit(1)
    click.echo(f"Muted {fingerprint}" + (f" for {hours}h" if hours else " forever"))


@events_group.command(name="resolve")
@click.argument("fingerprint")
def events_resolve(fingerprint: str) -> None:
    """Mark a finding as resolved."""
    _mutate_status(fingerprint, "resolve")


@events_group.command(name="export")
@click.option("--format", "fmt", type=click.Choice(["ndjson"]),
              default="ndjson", show_default=True)
def events_export(fmt: str) -> None:
    """Stream all findings as NDJSON to stdout."""
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        sys.exit(1)
    for line in db.export_findings_ndjson():
        click.echo(line)


def _mutate_status(fingerprint: str, verb: str) -> None:
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        sys.exit(1)
    from aifd.vault.events_db import STATUS_ACKNOWLEDGED, STATUS_RESOLVED
    new_status = {"ack": STATUS_ACKNOWLEDGED, "resolve": STATUS_RESOLVED}[verb]
    if not db.mutate_status(fingerprint, new_status):
        click.echo(f"No finding with fingerprint {fingerprint!r}", err=True)
        sys.exit(1)
    click.echo(f"{verb}: {fingerprint}")


# ---------- webhooks subcommands ----------


@watch.group(name="webhooks")
def webhooks_group() -> None:
    """Manage outbound webhook configuration (v0.7)."""


@webhooks_group.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="JSON output.")
def webhooks_list(as_json: bool) -> None:
    """List configured webhooks."""
    from aifd.vault.webhooks import load_webhooks_yaml
    entries = load_webhooks_yaml(_webhooks_yaml_path())
    if as_json:
        click.echo(json.dumps([
            {
                "id": e.id, "url": e.url, "on": list(e.on),
                "filter_categories": list(e.filter_categories),
                "payload": e.payload_format,
                "enabled": e.enabled, "lang": e.lang,
            }
            for e in entries
        ], indent=2))
        return
    if not entries:
        click.echo("(no webhooks configured)")
        click.echo(
            "Add one: aifd vault watch webhooks add --url URL --on new_finding",
        )
        return
    for e in entries:
        badge = "ENABLED " if e.enabled else "DISABLED"
        click.echo(
            f"{badge}  {e.id}  ({e.payload_format}, lang={e.lang})\n"
            f"  url: {e.url}\n"
            f"  on:  {', '.join(e.on)}\n"
            f"  filter: {', '.join(e.filter_categories) or '(all)'}\n",
        )


@webhooks_group.command(name="add")
@click.option("--id", "wid", required=False, help="Webhook ID. Auto if omitted.")
@click.option("--url", required=True, help="Endpoint URL (http/https only).")
@click.option("--on", multiple=True, default=("new_finding",),
              help="Trigger events. Repeatable.")
@click.option("--category", multiple=True,
              help="Filter by category. Repeatable. Empty = all.")
@click.option("--payload", "fmt", type=click.Choice(["aifd_v1", "pagerduty_v2"]),
              default="aifd_v1", show_default=True)
@click.option("--lang", default="en", show_default=True,
              help="Payload locale (en, zh).")
def webhooks_add(
    wid: str | None, url: str, on: tuple[str, ...],
    category: tuple[str, ...], fmt: str, lang: str,
) -> None:
    """Add a webhook (defaults to disabled — run `test` then `enable`).

    \b
    Example:
        aifd vault watch webhooks add \\
            --id slack-secops \\
            --url https://hooks.slack.com/services/T/B/X \\
            --on new_finding \\
            --category openai_key --category github_pat
    """
    from aifd.vault.webhooks import (
        WebhookEntry,
        _validate_url,
        load_webhooks_yaml,
        save_webhooks_yaml,
    )
    try:
        _validate_url(url)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    path = _webhooks_yaml_path()
    entries = load_webhooks_yaml(path)
    wid_final = wid or f"webhook-{abs(hash(url)) % 100000}"
    if any(e.id == wid_final for e in entries):
        raise click.ClickException(f"webhook id {wid_final!r} already exists")
    entry = WebhookEntry(
        id=wid_final,
        url=url,
        on=tuple(on),
        filter_categories=tuple(category),
        payload_format=fmt,
        enabled=False,
        lang=lang,
        threshold_window_hours=None,
        threshold_count=None,
    )
    entries.append(entry)
    save_webhooks_yaml(path, entries)
    click.echo(f"Added webhook {wid_final} (disabled).")
    click.echo(f"Test it:   aifd vault watch webhooks test {wid_final}")
    click.echo(f"Enable:    aifd vault watch webhooks enable {wid_final}")


@webhooks_group.command(name="delete")
@click.argument("wid")
def webhooks_delete(wid: str) -> None:
    """Remove a webhook."""
    from aifd.vault.webhooks import load_webhooks_yaml, save_webhooks_yaml
    path = _webhooks_yaml_path()
    entries = load_webhooks_yaml(path)
    new_list = [e for e in entries if e.id != wid]
    if len(new_list) == len(entries):
        click.echo(f"No webhook with id {wid!r}", err=True)
        sys.exit(1)
    save_webhooks_yaml(path, new_list)
    click.echo(f"Deleted webhook {wid}.")


@webhooks_group.command(name="test")
@click.argument("wid")
def webhooks_test(wid: str) -> None:
    """Send a test event to a webhook (sync). Use before `enable`."""
    from aifd.vault.webhooks import load_webhooks_yaml, send_test_event
    entries = load_webhooks_yaml(_webhooks_yaml_path())
    entry = next((e for e in entries if e.id == wid), None)
    if entry is None:
        click.echo(f"No webhook with id {wid!r}", err=True)
        sys.exit(1)
    ok, msg = send_test_event(entry)
    click.echo(f"Test {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        sys.exit(1)


@webhooks_group.command(name="enable")
@click.argument("wid")
def webhooks_enable(wid: str) -> None:
    """Flip a webhook to enabled (after successful test)."""
    _flip_enabled(wid, True)


@webhooks_group.command(name="disable")
@click.argument("wid")
def webhooks_disable(wid: str) -> None:
    """Flip a webhook to disabled (stop sending without removing)."""
    _flip_enabled(wid, False)


def _flip_enabled(wid: str, enabled: bool) -> None:
    from dataclasses import replace

    from aifd.vault.webhooks import load_webhooks_yaml, save_webhooks_yaml
    path = _webhooks_yaml_path()
    entries = load_webhooks_yaml(path)
    new_list: list[Any] = []
    found = False
    for e in entries:
        if e.id == wid:
            new_list.append(replace(e, enabled=enabled))
            found = True
        else:
            new_list.append(e)
    if not found:
        click.echo(f"No webhook with id {wid!r}", err=True)
        sys.exit(1)
    save_webhooks_yaml(path, new_list)
    click.echo(f"{'Enabled' if enabled else 'Disabled'} webhook {wid}.")


@webhooks_group.command(name="retry-dead-letter")
@click.option("--id", "wid", default=None,
              help="Restrict to a single webhook ID. Default: all.")
def webhooks_retry_dead_letter(wid: str | None) -> None:
    """Re-queue failed webhook deliveries from dead_letter.

    See `aifd vault watch webhooks list-dead-letter` to inspect first.
    """
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        sys.exit(1)
    rows = db.list_dead_letter(limit=1000)
    if wid is not None:
        rows = [r for r in rows if r["webhook_id"] == wid]
    if not rows:
        click.echo("No dead_letter entries to retry.")
        return
    # Mark as ready to retry by removing them — they'll be re-queued by
    # the daemon if it's running. For CLI-only use (daemon not running),
    # this is informational: the user knows they need to manually re-send.
    # Future: send a SIGUSR1 to the daemon to trigger retry.
    if _is_running():
        click.echo(
            f"Daemon is running. {len(rows)} dead_letter entries can be "
            "re-queued via the daemon. (Note: this CLI path is informational; "
            "future versions will signal the daemon directly.)"
        )
    else:
        click.echo(
            f"Daemon is NOT running. {len(rows)} dead_letter entries remain "
            "in the DB. Start the daemon to retry."
        )


@webhooks_group.command(name="list-dead-letter")
@click.option("--json", "as_json", is_flag=True)
def webhooks_list_dead_letter(as_json: bool) -> None:
    """Show failed webhook deliveries."""
    db = _open_events_db()
    if db is None:
        click.echo("No events DB yet.", err=True)
        return
    rows = db.list_dead_letter(limit=100)
    if as_json:
        click.echo(json.dumps([dict(r) for r in rows], indent=2, default=str))
        return
    if not rows:
        click.echo("(no dead_letter entries)")
        return
    for r in rows:
        click.echo(
            f"  {r['attempted_at'][:19]}  webhook={r['webhook_id']}  "
            f"fp={r['fingerprint']}  attempts={r['attempts']}\n"
            f"    error: {r['last_error']}"
        )
