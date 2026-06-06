# `aifd vault watch` — real-time secret detection daemon

Shipped in **v0.6.0**.

`aifd vault watch` is a long-running daemon that listens for new lines in
every Claude / Codex session jsonl. When a new line lands, it runs the
v0.4 detector pipeline (regex + entropy + suppressors) against it, and if
a real match survives, pushes a macOS notification. Click the notification
to open a localhost page that highlights the leak in its conversation context.

This is the safety-net companion to `aifd vault scan`: scan finds what's
already on disk, watch catches it the moment it lands.

---

## Quick start

```bash
# One-time setup (macOS)
aifd vault watch install      # registers ~/Library/LaunchAgents/io.aifd.watch.plist
aifd vault watch status       # confirm pid + port + counters

# Or run foreground for debugging:
aifd vault watch start --foreground -v
```

A first-run test notification is fired to verify macOS notification
permissions. If you don't see "Watch daemon started — notifications
working." in Notification Center, open **System Settings → Notifications
→ Terminal / terminal-notifier** and allow notifications, then restart
the daemon.

**Strongly recommended**: install `terminal-notifier` first.

```bash
brew install terminal-notifier
```

Without it, the daemon falls back to `osascript`, and clicking a
notification opens macOS Script Editor instead of the finding URL —
a known limitation of the `display notification` AppleScript verb.
`aifd vault watch status` shows which backend is active.

---

## Commands

| Subcommand   | What it does |
| ------------ | ------------ |
| `start`      | Launch the daemon. Default forks into background, logs to `~/.aifd/watch.log`. `--foreground / -f` keeps it attached (Ctrl-C stops). |
| `stop`       | Send SIGTERM to the running daemon. Waits up to 10s for graceful shutdown. |
| `status`     | Print pid / HTTP port / state file / total + today catches / tracked file count. `--json` for pipe output. |
| `tail`       | Follow `~/.aifd/watch.log` (uses `tail -F`, so log rotation Just Works). |
| `install`    | Write the launchd `.plist` and bootstrap it so the daemon auto-starts at login. macOS only. |
| `uninstall`  | `launchctl bootout` + remove the `.plist`. |
| `daemon`     | **Internal**. The actual long-running loop. This is what launchd invokes. Don't run manually unless debugging. |

---

## Architecture

```
   watchdog Observer (1 emitter + 1 dispatcher thread)
        │
        │ on_modified(path) → queue.put_nowait(path)
        ▼
   event_queue: queue.Queue[Path]   ──┐
        │                              │
        │                              │ 5-min sweep timer
        │                              │ enqueues every tracked path
        ▼                              │
   worker thread (single)        ◀────┘
        │
        │ for each path:
        │   TailReader.read_new_lines(path)
        │     for each new line:
        │       _scan_line(...) → SensitiveMatch?
        │         DedupeCache.should_notify(...)?
        │           Notifier.notify(...) + Server.register(...)
        │   WatchState.save() (atomic)
        ▼

   HTTP server on 127.0.0.1:<kernel-picked> (daemon-hosted, single port)
     GET /findings/{token} → render_scan_matches_html([match])
```

Three architectural locks (from the v0.6 engineering review):

1. **D1: queue + single worker** — every state mutation (WatchState,
   DedupeCache, counters) flows through one worker thread. No locks,
   no shared-mutable-state races.

2. **D2: daemon-hosted HTTP server** — one long-lived server bound to
   127.0.0.1 on a kernel-picked port, registered findings keyed by a
   ~256-bit URL-safe random token. Process dies → server dies.

3. **D3: 5-minute full-sweep timer** — runs in parallel with the
   event-driven scan. Catches anything watchdog dropped (inotify queue
   overflow, FSEvents coalescing under extreme load).

---

## Files

详细的 state file 字段、增量扫描语义、五种边界情况（首次跑 / 新文件 / rotation /
SIGKILL / state 损坏）见 [vault-watch-lifecycle.md](./vault-watch-lifecycle.md)。

| Path                          | What's in it |
| ----------------------------- | ------------ |
| `~/.aifd/watch-state.json`    | Per-file scan offsets, daily catch counters, schema version. Atomic write via tmp+rename. |
| `~/.aifd/watch.pid`           | Daemon PID. Locked with `fcntl.flock(LOCK_EX | LOCK_NB)` for single-instance enforcement. |
| `~/.aifd/watch.port`          | Current HTTP server port. Removed on clean shutdown. |
| `~/.aifd/watch.log`           | Daemon log output (INFO+). Tail with `aifd vault watch tail`. |
| `~/Library/LaunchAgents/io.aifd.watch.plist` | launchd unit (macOS only). |

---

## Privacy & security posture

- **Secrets stay in process memory.** The daemon never writes a secret
  to disk. `~/.aifd/watch-state.json` holds only `category` + the
  already-redacted snippet (e.g. `AKIA…REDACTED…WXYZ`).
- **HTTP server binds 127.0.0.1 only.** No other host on your LAN can
  reach the findings URLs.
- **Finding tokens are unguessable.** Each match gets a fresh
  `secrets.token_urlsafe(32)` (~256 bits). Without holding the URL from
  the notification, you can't fetch a finding even from localhost.
- **State file mode 0644 (default umask).** The directory `~/.aifd/` is
  inside your home; OS-level perms protect it from other users.
- **SIGTERM flushes state cleanly.** launchd `KeepAlive=true` restart on
  crash; on graceful stop, the worker drains the queue, the state file
  is saved, and the HTTP socket is released.

See [secret-scan.md § Watch mode security](./secret-scan.md#watch-mode-security)
for the full threat model.

---

## E10: integration with `aifd ai today`

When the daemon has caught secrets in the same window as your activity
report, `aifd ai today / weekly / monthly` adds one line at the bottom:

```
🛡 vault watch: 3 secrets caught this period (run `aifd vault watch status` for details)
```

The line is hidden when:
- the daemon has never run (no `~/.aifd/watch-state.json`), or
- there were zero catches in the report's window.

JSON output adds `"watch_catches": <int>` at the top level of the report
payload. The schema is documented in [ai-retro.md](./ai-retro.md).

---

## Linux

`install` is macOS-only because launchd is macOS-only. On Linux, run
under `systemd --user`:

```ini
# ~/.config/systemd/user/aifd-watch.service
[Unit]
Description=aifd vault watch daemon

[Service]
ExecStart=%h/.local/bin/aifd vault watch daemon
Restart=always

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now aifd-watch
journalctl --user -u aifd-watch -f
```

A native `install` for Linux ships in a future release.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| ------- | ------------------ |
| **Click notification opens Script Editor.app** (not browser) | `terminal-notifier` is missing; daemon fell back to osascript whose `display notification` AppleScript verb does not support click handlers (macOS routes click to the script's owning app = Script Editor). Fix: `brew install terminal-notifier`, then restart daemon. `aifd vault watch status` shows which backend is active. |
| **`stop` then `start` says "already running" with a different pid** | launchd's `KeepAlive=true` respawned the daemon between your stop and start. Since v0.6.1 `stop` uses `launchctl bootout` when the .plist is installed — this stops the daemon AND tells launchd not to respawn. If you see this on v0.6.0, upgrade (`uv tool install --force aifd`). |
| No notifications appear | Check System Settings → Notifications → Terminal / terminal-notifier. Try `aifd vault watch start --foreground` and watch for `Notification permission probe failed` in the log. |
| `Watch daemon already running` on start | A previous instance is alive. Run `aifd vault watch stop` first, or check `~/.aifd/watch.pid`. |
| `status` shows RUNNING but `tail` is empty | The daemon is alive but no events have triggered yet. Append a line to any jsonl in `~/.claude/projects/` or wait for the 5-min sweep. |
| Click-to-jump 404 after restart | Tokens are in-memory only. Restarting the daemon drops all in-flight findings — re-scan with `aifd vault scan --web` to inspect historical hits. |
| `bootstrap failed: 5: Input/output error` | The `.plist` was already loaded. Run `aifd vault watch uninstall` first, then `install` again. |
