# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.8.0] - 2026-06-06

### Added

#### `aifd ai reflect` — meta-cognitive AI coach

aifd v0.7 是「查 / 扫 / 盯 / 推」型工具；v0.8 把它**反过来**：让 aifd 看你怎么
用 AI，让 LLM 写一段 80-150 字的 weekly reflection。详见 `docs/ai-reflect.md`。

9 个反思维度从现有数据计算（**不**引入新 store）：

- **Activity**（v0.5 复用）—— sessions / cost / tokens / by-provider
- **Compliance ratio** —— `(user_choice == recommended) / total`，从 gstack
  `question-log.jsonl` 读
- **Skill diversity** —— `distinct skills / total invocations`，从 gstack
  `timeline.jsonl` 读
- **Cost trend** —— `this period $ vs prev period $`，复用 v0.4 TokenUsage
- **Timing distribution** —— 4 个 bucket（0-6 / 6-12 / 12-18 / 18-24 local 小时）
- **Project focus** —— top-1 cwd basename + 其 share（**privacy: basename
  only**，从不发完整路径）
- **Plan-then-ship ratio** —— ship 前 7 天内是否跑过 plan-eng-review
- **Vibe-coding score** —— ship 前 session message count < 5 的比例
- **Top wins** —— 最近 clean 状态的 ship / plan-eng-review

**CLI**：

```bash
aifd ai reflect                      # 默认 --week, zh
aifd ai reflect --month --lang en
aifd ai reflect --since 2026-06-01 --json
aifd ai reflect --model zhipu/glm-4-plus           # 任意 LiteLLM provider
aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
aifd ai reflect -v                                  # verbose: 显示 timing breakdown
```

**Architecture locks（来自 /plan-eng-review）**：

- **D1** —— `llm_client.call()` 走 **LiteLLM**（100+ provider 统一 OpenAI-format
  路由层）。`--model` 接 `provider/model` 格式（`deepseek/deepseek-chat` /
  `zhipu/glm-4-plus` / `dashscope/qwen-plus` / `ark/<endpoint_id>` /
  `anthropic/claude-sonnet-4` / `ollama/qwen2.5` ...），`--api-base` override
  endpoint。**显式拒绝 vendor lock-in**
- **D2** —— `PROMPT_VERSION = "v1"` 写进 prompt 和 output JSON，可复现性 + audit
- **D3** —— `ReflectionDataSource` Protocol 抽象数据源。default impl 用 gstack
  slug 三级 fallback（gstack-slug binary / git remote owner-name / basename）。
  缺失时 placeholder 提示，**不** crash
- **D4** —— retry 策略：auth/4xx **不** retry，5xx/timeout/429 LiteLLM retry 1 次，
  total budget 30s
- **D5** —— `~/.aifd/config.yaml` (YAML 跟 webhooks 一致；state.json 仍 JSON)；
  schema 用 generic `llm:` 段（model / api_key / api_base）而非 provider-specific
- **D6** —— **Privacy invariant via v0.4 detector scan**：render_prompt 输出
  跑 `_scan_line` 必须 0 SensitiveMatch。任何新 detector pattern 自动 enforce
- **D7** —— 默认 mocked tests + 1 opt-in `live_api` pytest mark（real LLM smoke，
  default DeepSeek 可通过 `AIFD_LIVE_MODEL` 切其它 provider），不进 CI
- **D8** —— perf contract：local part < 500ms（testable），verbose flag 显示
  per-stage timing breakdown (`local` / `llm` / `render`)

**Privacy invariants**（D6 by detector scan）：

- raw question text / session message content 永远不发
- 完整 cwd path 永远不发（只发 basename）
- v0.4 `_DETECTORS` 任何 secret pattern 永远不发
- opt-in `--include-questions` 也只发 summary，不发原文

**Fallback behavior**：

- 没 API key → 输出引导提示 + 退化到 structured local report，**不** crash
- LLM 401/403 (auth) → 退化到 local report + clear error message
- LLM 400 (bad model name) → 退化 + fallback hint 提示当前 --model 值
- LLM 429 / 5xx / timeout / connection → LiteLLM retry 1 次后退化
- LLM 返非 JSON / 错 schema → 退化

所有退化路径仍输出合法 JSON schema，下游脚本能稳定 parse。

**Env vars**（precedence 从高到低）：

- `AIFD_LLM_API_KEY` / `AIFD_LLM_MODEL` / `AIFD_LLM_API_BASE`（aifd-shaped，跨 provider）
- `DEEPSEEK_API_KEY`（v0.8 pre-release 用户兼容；其它 provider 走 LiteLLM 原生
  env var：`ZHIPUAI_API_KEY` / `DASHSCOPE_API_KEY` / `ARK_API_KEY` /
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等）
- `~/.aifd/config.yaml` 的 `llm:` 段
- built-in default (`deepseek/deepseek-chat`)

#### New dependencies

- `pyyaml>=6.0` 已经在 v0.7 引入；v0.8 复用做 config.yaml
- `litellm>=1.50` —— **新增**。100+ LLM provider 统一接口。选 LiteLLM 而非
  openai-sdk 是因为 openai-sdk 只覆盖 ~50% 用户想接的 endpoint，国内 provider
  (智谱/方舟/通义) 的 OpenAI-compat quirks（tool_call shape / response_format
  flavor / streaming chunk format / usage 字段命名）LiteLLM 已经 normalize
- dev: `types-PyYAML` 已存在

### Changed

- **`aifd/insights/` 从单文件升级成 package**：
  - `aifd/insights.py` → `aifd/insights/activity.py`（v0.5 内容）
  - 加 `aifd/insights/__init__.py` 维持向后兼容（所有 `from aifd.insights
    import X` 仍 work）
  - 加 `aifd/insights/reflection.py`、`reflection_prompt.py`、
    `reflection_source.py`、`llm_client.py`
  - 测试 import 路径不变。一个 internal 测试（`test_today_runs_with_no_providers`）
    需把 patch 目标从 `aifd.insights.PROVIDERS` 改成
    `aifd.insights.activity.PROVIDERS`（package-conversion 副作用，文档已说明）

### Tests

新测试：
- `tests/test_aifd_config.py` — 20 个 (YAML/env precedence/0600/atomic + legacy
  env var compat)
- `tests/test_insights_llm_client.py` — 16 个 (LiteLLM wrapper：response_format /
  api_base / model string / 异常 pass-through / JSON schema validation)
- `tests/test_reflection_data_source.py` — 11 个 (Protocol/slug fallback/jsonl parse)
- `tests/test_insights_reflection.py` — 27 个 (9 compute_* + orchestrator + tz)
- `tests/test_insights_reflection_prompt.py` — 15 个（含 **5 个 PRIVACY ★★★**
  invariants via v0.4 detector scan）
- `tests/test_render_reflection.py` — 9 个
- `tests/test_cli_ai_reflect.py` — 13 个 (新增 provider/model 格式 + bad-model
  fallback)
- `tests/test_litellm_live.py` — 1 个 opt-in (`-m live_api`, skip by default，
  可通过 `AIFD_LIVE_MODEL` 切其它 provider)

总测试数：**585 passed, 2 skipped, 1 live opt-in**。



## [0.7.0] - 2026-06-05

### Added

#### `aifd vault watch events` — persistent finding event stream

v0.6 把 vault watch 的检测做到了实时；v0.7 把单条 finding 从「内存里的瞬时
通知」升级成「持久化事件流 + web 查询 + 接外部报警系统」。详见
`docs/vault-events.md`。

**核心变化**：

- **SQLite events store** (`~/.aifd/findings.db`, WAL mode) — daemon 重启不
  丢；同一 secret 重复出现按 fingerprint 去重（count++），不创建新 issue
- **fingerprint = SHA1(category + snippet_redacted)** — 跨机器、跨用户名稳定；
  同一 secret 在多个文件出现 = 一个 issue，多条 occurrence
- **状态机** — new / acknowledged / resolved / muted；resolved 后再次出现自动
  re-open；muted 可带 `--hours N` 或永久
- **rotation playbook 库** — 8 个核心 category（openai_key / anthropic_key /
  github_pat / github_oauth / aws_access_key / aws_secret / slack_token / jwt /
  gcp_service_account）+ generic fallback；en + zh 双语；vendor dashboard 链接
  + 步骤说明

**新 CLI**：

```bash
aifd vault watch events list  [--status STATUS --category CAT --limit N --offset N --json]
aifd vault watch events show  <fingerprint>
aifd vault watch events ack   <fingerprint>
aifd vault watch events mute  <fingerprint> [--hours N]
aifd vault watch events resolve <fingerprint>
aifd vault watch events export --format ndjson
```

#### `aifd vault watch webhooks` — outbound integration with外部报警系统

通用 webhook 出口，接 Slack / PagerDuty / Datadog / Honeycomb / 自家 monitoring：

```bash
aifd vault watch webhooks add --url URL --on new_finding [--category CAT ...]
aifd vault watch webhooks test <id>      # 必须 test 通才能 enable
aifd vault watch webhooks enable <id>    # 默认 disabled，避免错配泄漏 (D3)
aifd vault watch webhooks list / delete / disable / list-dead-letter / retry-dead-letter
```

**Payload formats**：

- `aifd_v1` (default) — generic flat JSON，含 fingerprint / category / 文件
  basename + line / first_seen + count / rotation playbook（vendor_dashboard +
  instruction + severity）
- `pagerduty_v2` — PagerDuty Events API v2 shape（URL 里 `?routing_key=X` 自动
  挪到 body）

**Delivery 工程**：

- 独立 webhook deliverer 线程（per-thread events DB connection）
- 3 次 exponential backoff retry（10s / 60s / 600s）
- 4xx 直接 dead_letter（不重试 —— URL 错配类）
- 5xx + 网络错误重试（transient 错误类）
- dead_letter 持久化到 SQLite，跨重启**不自动**重试（D4 — 避免「错配修了还会
  连发」陷阱）；用户用 `webhooks retry-dead-letter` 手动 re-queue

#### Web UI — 单页 SPA at `http://127.0.0.1:PORT/`

vanilla JS，零 build step。三个视图：

- **Findings**（list view）— 按 status / category 过滤、按 last_seen DESC 排
  序、分页（LIMIT 50）；click 进 detail
- **Detail** — status mutation 按钮（Ack / Mute 24h / Mute forever / Resolve）+
  rotation playbook block（醒目卡片，vendor link + 步骤）+ occurrences timeline
- **Webhooks** — list 现有 + add form + per-row Test / Enable / Disable /
  Delete

浏览器 `navigator.language` 决定 playbook 显示 en 还是 zh。

#### Architecture locks (v0.7)

- **D1**：per-thread SQLite connection + WAL 模式 —— reader 不阻 writer
- **D2**：fingerprint 不含 file path —— 跨机稳定、webhook payload 只发 basename
- **D3**：webhook 默认 disabled —— privacy-by-default 防错配
- **D4**：dead_letter 不自动重试 —— user 明确同意才 re-queue
- **D5**：web UI 无 Playwright 依赖 —— release-time 手动 QA checklist
- **D6**：LIMIT 50 + 3 indices（status+last_seen DESC, category, fingerprint）

#### E10 cross-feature surface 保留

`aifd ai today / weekly / monthly` 的 `🛡 vault watch: N` 一行仍然来自
`state.catches_by_day` (v0.6)，与新 events DB 并存 —— state.json 管 day
counters + scan offset，events DB 管 finding history。

#### T9: finding_drop_count metric

events DB 写失败（disk full、SQLite error）会 +1 `finding_drop_count`，daemon
不 crash；`aifd vault watch status` 显示 `⚠ N finding(s) dropped`。

### Changed

- **Notifier 警告策略升级**：v0.6.x 已经做过 osascript 警告，v0.7 加进 status 命令
- `aifd vault watch stop/start` 在 launchd .plist 存在时自动用
  `launchctl bootout`/`bootstrap`，避免 KeepAlive respawn 与 stop 竞态（v0.6.x fix
  在 v0.7 整理进 docs）
- `aifd/vault/scan.py:_scan_line` SEMI-PUBLIC marker docstring 加 v0.7 events DB
  ingestion path 为新 caller

### Dependencies

- 新增 `pyyaml>=6.0` —— 解析 `~/.aifd/webhooks.yaml` 用户配置
- 新增 `types-PyYAML>=6.0` (dev) —— mypy 类型补全

### Tests

107 个新测试：
- `tests/test_vault_events_db.py` — 29 (WAL、fingerprint、state machine、并发)
- `tests/test_vault_playbooks.py` — 31 (lookup、i18n、render、generic fallback)
- `tests/test_vault_webhooks.py` — 22 (yaml load/save、retry/dead_letter、payload、
  send_test_event)
- `tests/test_vault_watch_server_events.py` — 25 (HTTP endpoints integration via real
  127.0.0.1 server)
- `tests/test_vault_watch_cli_events.py` — 22 (click CLI subcommands)
- `tests/test_vault_watch_regression.py` — 8 (v0.6 click-to-jump + E10 invariants)

总测试数：474 passed + 1 skipped。



## [0.6.0] - 2026-06-05

### Added

#### `aifd vault watch` — real-time secret detection daemon

Long-running background daemon that listens for new lines in every
Claude / Codex jsonl. When a new line lands, runs the v0.4 detector
pipeline (regex + entropy + suppressors) against it. If a real match
survives the dedupe filter, pushes a macOS notification; clicking it
opens a localhost page (127.0.0.1, kernel-picked port) that highlights
the leak in its conversation context.

Subcommands:

- `aifd vault watch install` — one-time launchd setup (macOS only;
  Linux uses `systemctl --user`, see `docs/vault-watch.md`).
- `aifd vault watch start [--foreground]` — manually start (background
  default; `--foreground` for debugging with Ctrl-C to stop).
- `aifd vault watch stop` — graceful SIGTERM with 10s deadline.
- `aifd vault watch status [--json]` — pid / port / counters / log path.
- `aifd vault watch tail` — `tail -F ~/.aifd/watch.log`.
- `aifd vault watch uninstall` — `launchctl bootout` + remove .plist.
- `aifd vault watch daemon` — internal launchd entrypoint.

Architecture (locked in `/gstack-plan-eng-review`):

- **D1 — queue + single worker**: every state mutation (WatchState,
  DedupeCache, counters) flows through one worker thread. No locks,
  no shared-mutable-state races.
- **D2 — daemon-hosted HTTP server**: one long-lived server bound to
  127.0.0.1 on a kernel-picked port, findings registered against a
  ~256-bit `secrets.token_urlsafe(32)` token. Process dies → server dies.
- **D3 — 5-minute full-sweep timer**: runs in parallel with the
  event-driven scan. Catches anything watchdog dropped (inotify queue
  overflow, FSEvents coalescing under extreme load).

Safety + privacy:

- HTTP server binds 127.0.0.1 only (never 0.0.0.0).
- Finding tokens are unguessable (~256 bits).
- `~/.aifd/watch-state.json` only stores `category` + `snippet_redacted`
  — never a full secret.
- State file uses atomic write (tmp + rename) — SIGKILL mid-write does
  not corrupt.
- `fcntl.flock(LOCK_EX | LOCK_NB)` on `~/.aifd/watch.pid` enforces
  single-instance: a second `daemon` invocation fails fast.
- launchd `KeepAlive=true` survives crashes; SIGTERM flushes cleanly.

E10 cross-feature surface: `aifd ai today / weekly / monthly` now shows
a `🛡 vault watch: N secrets caught this period` line when the daemon
has caught secrets in the same window. The line is hidden when watch
has never run or when the window is empty. JSON output gains
`"watch_catches": <int>`.

New dependency: `watchdog>=4.0` (wraps macOS FSEvents / Linux inotify
/ Windows ReadDirectoryChangesW). Picked over PyObjC (macOS-only) and
rolling our own (re-inventing 10 years of edge-case fixes).

Docs: `docs/vault-watch.md` (commands + architecture + troubleshooting),
`docs/secret-scan.md § Watch mode security` (threat model + invariants).

27 new tests in `tests/test_vault_watch.py` cover WatchState
(load/save/atomic/version migration/window summing), TailReader
(initial/append/rotate/partial trailing line), DedupeCache
(first-hit/TTL/LRU cap), Notifier (osascript vs terminal-notifier
dispatch), WatchServer (register/fetch/404/loopback-only/stop), and
the E10 today integration.

### Changed

- `aifd/vault/scan.py:_scan_line` is now marked as a **semi-public API**
  (called by both `vault scan` and `vault watch`). Its signature is
  part of our internal contract; future MCP server will reuse it too.

## [0.5.0] - 2026-06-05

### Added

#### `aifd ai today / weekly / monthly / retro` — activity retrospective

Four new subcommands aggregate your AI activity over a time window and
present session count, USD cost, token total, per-provider split, top
skills, top topics (from `Session.title`), a delta vs the equivalent
prior window, and a monthly cost projection extrapolated from the
current run rate.

- `aifd ai today` — local midnight to now
- `aifd ai weekly` — rolling 7 days
- `aifd ai monthly` — first of month to now
- `aifd ai retro --since YYYY-MM-DD [--until YYYY-MM-DD]` — custom range

All four support `--json` (stable schema documented in `docs/ai-retro.md`)
and `-v` / `-vv` log verbosity. The JSON shape is designed to be the
return schema for a future `aifd mcp serve` MCP tool so Claude can query
your own AI history as part of its context.

Sample output:

```
═══ Today ═══ 2026-06-05 00:00 → 2026-06-05 09:41

  5 sessions · $80.30 · 85M tokens
  claude 5 sess · $80.30
  top skills: plan-eng-review x4 · ship x1
  top topics:
    · v0.4.1 vault scan UI/UX
    · FP suppression discussion

  vs previous: -$443.80 cost · -3 sessions
  → at this pace, monthly projection: $5,963.59 (based on 9.7h)
```

Session semantics: "session_count" counts DISTINCT `(provider, session_id)`
that emitted any TokenUsage event in the window. A conversation started
yesterday but continued today counts as today's activity — matches user
intuition over "new sessions started today" (which would show 0 sessions
+ $50 cost on a long-running follow-up day).

#### Provider Protocol: `iter_all_sessions()`

Added to `aifd.providers.base.Provider` (Claude + Codex implement, default
returns empty for other providers). Lets callers walk every session a
provider knows about regardless of cwd — required by `aifd ai retro` and
unlocks future cross-tool dashboards / MCP tools without breaking the
existing cwd-scoped `list_sessions(cwd)` contract.

Codex uses a `SELECT * FROM threads ORDER BY created_at_ms DESC` (no
cwd filter) when the SQLite state DB is present; falls back to a jsonl
walk otherwise.

### Improved

#### `aifd vault cost` event-cost helper now shared with insights

`aifd.vault.cost.compute_event_cost` was previously private to the
cost subcommand; it's now the single source of truth for "what does
one TokenUsage event cost in USD?", consumed by both `aifd vault cost`
and `aifd ai retro / today / ...`. DRY enforcement via
`tests/test_insights.py`.

### Documentation

- `docs/ai-retro.md` — full command reference, session semantics, JSON
  schema, performance notes, comparison to `aifd vault cost`
- README — new "视角 4" section showing the `aifd ai today` output
  alongside session / question / skill views

### Performance

- Today window: < 1s on 800 MB of jsonl
- Weekly window: ~2.5s
- Monthly window: ~9.5s (essentially full scan)

### Internal

- New module `aifd/insights.py` (270 lines): `ActivityReport`,
  `Delta`, `ProjectionEstimate` frozen dataclasses; `summarize_activity`,
  `compute_diff`, `compute_projection` pure functions; four window
  helpers (today / weekly / monthly / previous_window)
- 16 unit tests for insights + 4 CLI tests for retro
- Existing tests untouched; full suite now 307 (was 287)

## [0.4.1] - 2026-06-04

### Added

#### `aifd vault scan --web` — browser UI with redacted secrets in context

New flag opens a localhost-only HTTP server (`127.0.0.1`, kernel-picked
ephemeral port) that renders findings as an HTML page with:

- Per-category tabs (`anthropic_key`, `openai_key`, …, `high_entropy`),
  ordered by detector confidence DESC — most dangerous category first
- CSS-only tab switching (radio + sibling combinator) — zero JS
- Each finding shows ±200 chars of conversation context around the
  secret, with the leak highlighted via `<mark>`
- Expandable `<details>` block per finding for the full raw jsonl line
- JSON escape sequences (`\n` / `\t` / `\"` / `\uXXXX`) are decoded so
  conversation context reads naturally instead of showing literal `\n`
- Warning banner: "this page contains raw secrets; press Ctrl-C in the
  terminal when done"
- 16 KiB truncation badge surfaces when a scan-clipped line might have
  cut off `context_after`

Architecture: nothing is written to disk. Findings live in process
memory; the HTTP server dies on Ctrl-C and secrets drop with it. Server
binds 127.0.0.1 only — never reachable from another host on the LAN.
`SensitiveMatch` gained five optional fields (`context_before` /
`match_full` / `context_after` / `raw_line` / `line_truncated`) that
populate only when `capture_context=True` (via `--web`); all other
code paths continue to carry just `snippet_redacted`. See
`docs/secret-scan.md` Security section for the dual-mode posture.

`--web` and `--json` are mutually exclusive (interactive vs pipe).

#### Suppressor framework + 4 built-in FP filters

Scan now runs a post-match suppression layer before emitting matches.
Each suppressor is a named predicate with a debug-loggable reason
(`aifd vault scan -vv` surfaces every suppression). Built-in rules:

- **`escape_prefix`** — matches starting right after a literal `\` in
  the source line are dropped. Catches the `\n@click.group` /
  `\n@router.post` / `\n@pytest.fixture` class where the email regex's
  `\b` word boundary fires between the escape and the decorator's
  module name. Measured on 50-file sample: 80.8% of email matches.
- **`reserved_email_domain`** — RFC 2606 §3 SLDs (`example.com` /
  `.org` / `.net`) including subdomains (`api.example.com` etc, since
  RFC 2606 reserves "the labels that compose them") + §2 TLDs
  (`.test` / `.example` / `.invalid` / `.localhost`). Case-insensitive.
- **`noreply_local_part`** — `noreply@` / `no-reply@` / `do-not-reply@`
  / `donotreply@` (case-insensitive). SMTP sender-only convention;
  not PII for an individual.
- **`placeholder_email_domain`** — common doc/UI placeholder domains:
  `domain.com` / `email.com` / `yourdomain.com` / `yoursite.com` /
  `mysite.com`. No subdomain match (`api.email.com` is likely a real
  service endpoint, not a placeholder).

Cumulative impact on a real history: 953 email findings at v0.4.0 →
271 after all four suppressors land = **71.6% noise reduction**, zero
real-PII loss verified via regression tests.

### Improved

#### `aifd vault scan` ~9.5s on 832 MB jsonl (was ~14.5s, ~50s pre-v0.4)

OPT-3 prefix prefilter swapped its Python regex alternation for a
substring `in` loop (`_QUICK_PREFIX_LITERALS` + `_has_vendor_anchor`).
C `strstr` runs 3.4× faster than NFA alternation on the same workload
(micro-benchmark). End-to-end scan: 14.5s → 9.3s. Cumulative since
v0.3.x: ~5.4× wall-clock speedup.

DRY meta-test (`test_quick_prefix_covers_all_regex_detectors`) updated
to use the new substring helper. Detector list and prefilter literals
stay synchronized at test time.

### Fixed

- The RFC 2606 suppressor's first cut only matched exact SLDs
  (`example.com`); subdomains (`api.example.com`, `mail.example.org`)
  leaked through. Predicate now matches both the SLD itself and any
  subdomain of it, per spec wording ("the labels that compose them
  are reserved"). Regression test added.

### Performance

- `_has_vendor_anchor` substring loop: 3.4× faster than alternation
  regex on the hot path
- Suppressors add < 50 ms total on 1369 raw matches (negligible)
- Web HTML rendering: 1369 findings → 6 MB HTML in < 100 ms

### Documentation

- `docs/secret-scan.md` — new "⚠ --web 模式与安全 invariant" section
  documenting the dual-mode security posture of `SensitiveMatch`
- `TODOS.md` — added v0.5 candidates: `aifd vault scan --exclude REGEX`
  (user-configurable suppressors) and `--show-suppressed` (debug flag
  surfacing suppressed matches with reasons)

## [0.4.0] - 2026-06-04

### Added

`aifd vault` — new top-level command group for data-sovereignty
operations. v0.3 was "look at your AI history"; v0.4 starts treating
that history as your asset that you own, audit, and protect.

#### `aifd vault scan` — PII / secret detector

Walks every provider's jsonl (`~/.claude/projects`, `~/.codex/sessions`,
`~/.codex/archived_sessions`) looking for likely-secret patterns.
Output is safe to share: every snippet is redacted (first 4 + last 4
chars only), the full secret is never stored beyond the scan loop.

Detectors:
- Anthropic `sk-ant-`, OpenAI `sk-` / `sk-proj-`, GitHub `ghp_` /
  `github_pat_` / `ghs_`, AWS `AKIA*`, Slack `xox[baprs]-`, JWT
  (eyJ-prefixed) — confidence 8-10, all regex
- email addresses, bearer tokens — confidence 7
- high-entropy strings (Shannon ≥4.5, length 40-200) — confidence 4-6,
  noisy fallback for unknown secret formats; suppressed by default
  via `--min-confidence 7`

Flags:
- `--root PATH` (repeatable) — add a path to scan, file or directory
- `--no-default-roots` — only scan `--root` paths
- `--min-confidence N` (default 7) — suppress lower-confidence finds
- `--json` — full record (with redacted snippet), pipe-friendly
- `-v / -vv` — log verbosity

Real-world calibration: scanning my own history (32 Claude projects,
115 Codex sessions) surfaced 304 leaked OpenAI keys, 1 GitHub PAT, 918
emails, 4 JWTs. The 7-default threshold suppressed ~287K low-confidence
entropy hits (hashes, embeddings, etc.) that would have drowned the
real findings.

#### `aifd vault cost` — token + USD spend aggregation

Reads per-event token usage from both providers and rolls it up by
project / model / month / provider. Prices from a bundled table
(`aifd/vault/prices.py`), date-stamped so users know when to verify.

Data sources:
- Claude: `message.usage` on every assistant event (per-message
  incremental — sums cleanly)
- Codex: `event_msg.token_count.payload.info.total_token_usage` (per
  session cumulative — provider collapses to one row per session
  holding the cumulative max so the aggregator can still simply sum)

OpenAI schema reconciliation: `input_tokens` in OpenAI's payload
INCLUDES `cached_input_tokens`. The Codex provider subtracts cached
so our schema (and Claude's) consistently treats `input_tokens` as
fresh-input-only. Without this, cached tokens would be double-billed
at the full input rate.

Flags:
- `--by project|model|month|provider` (default project)
- `--provider claude|codex` — filter
- `--json` — pipe-friendly
- `--list-models` — show priced models so unknown ones are easy to spot
- `-v / -vv`

Bundled model prices cover Claude 4 family (opus / sonnet / haiku),
3.5 family, 3-opus + OpenAI gpt-5 / gpt-5.5 / gpt-4o / gpt-4o-mini /
o1 / o3 / codex-auto-review. Unknown models render with $0 attributed
so token volume is still visible.

#### Infrastructure

- `aifd/models.py`: `TokenUsage`, `CostRow`, `SensitiveMatch` dataclasses
- `aifd/vault/`: new package (`prices.py`, `cost.py`, `scan.py`)
- `aifd/cli/vault/`: new command group (`scan.py`, `cost.py`)
- `aifd/providers/base.py`: Protocol gains `list_token_usage(scope)
  -> Iterable[TokenUsage]` default returning `()` (matches v0.2/v0.3
  pattern)
- `aifd/providers/claude.py`, `codex.py`: both implement
  `list_token_usage` against their native schemas
- `aifd/render.py`: `render_scan_matches`, `render_cost_rows` (Table +
  JSON modes, color-coded confidence for scan, sorted-by-cost for cost)
- 42 new tests across `test_vault_scan.py` / `test_vault_cost.py` /
  `test_vault_cli.py` — total 237 passed, 0 ruff, 0 mypy

### Notes

- `aifd vault export` and `aifd vault sync` are deferred to v0.5+ per
  the v0.4 CEO plan; both are in TODOS.md with context. v0.5 candidate
  triggers: user reports wanting backup before any incident, or
  cross-machine migration.
- Model price table verified against vendor pages as of 2026-06-04.
  The CLI footer always shows this date so users know when to
  re-verify. To override locally without a release: copy
  `aifd/vault/prices.py` and patch (no `--config` flag yet — deferred
  to v0.5).

## [0.3.1] - 2026-06-03

### Added

- `aifd ai question list --open` — zero-friction browser view. Writes
  the HTML to a temp file and launches your default browser in one
  command. Solves the v0.3 Table pain point that 67% of real questions
  are longer than 200 characters and 12% exceed 500 (median 408) —
  terminals truncate, browsers don't. No `--output`, no `--html`, no
  thinking about a path.
- `aifd ai question list --output PATH` — persist HTML to a specific
  file. Combine with `--open` to also launch the browser. Implies
  HTML mode (no need to also pass `--html`).
- `aifd ai question list --html` — print the HTML page to stdout for
  pipes (`> out.html`, `| caddy file-server`, etc.).
- HTML layout is Notion / Linear style: one card per question,
  system-followed dark/light theme, 70ch max-width, chosen option
  highlighted green, recommended option marked with ★. Long question
  text wraps; multiSelect answers render as a separate "Selected:" row.
- ALL user-derived text passes through `html.escape()` — question /
  options / chosen / recommended / notes / cwd / source / scope_label —
  so a historic question like "how do I sanitize `<script>`?" cannot
  XSS the rendered page. Verified by regression tests in
  `tests/test_question_render.py`.

### Notes

- HTML / JSON modes are mutually exclusive; mixing them emits a
  one-line `click.UsageError`. The other knobs (`--html`, `--open`,
  `--output`) compose freely.
- File-write failures (e.g. read-only path) surface as
  `Error: cannot write to <path>: <reason>` on stderr with exit code 1.
  Per CLAUDE.md "zero silent failures + every error has a name".

## [0.3.0] - 2026-06-03

### Added

- `aifd ai question list` — retro of every `AskUserQuestion` call the AI
  asked you, paired with the option you selected. Reads Claude jsonl,
  finds `tool_use` blocks whose name matches
  `^(AskUserQuestion|mcp__.*__AskUserQuestion)$` (covers MCP host
  variants), then pairs each call's `tool_use_id` to the user's
  `tool_result` so the row carries both the question and the chosen
  answer. Orphan questions (~4% of real sessions — user interrupted or
  session compacted) emit with `chosen_option=None` and render as
  "no answer recorded" so they stay visible in the retro.
- `--cwd` flag to limit to the current directory (default is global,
  mirrors `aifd ai session list`).
- `--limit N` (default 50) plus `--all` to opt out, so the first run on
  a heavy-AUQ user doesn't dump thousands of rows.
- `--provider claude` filter; Codex returns an empty iterable because
  its `agent_message` events are free-form text with no structured
  question event (covered in `docs/question-extraction.md`).
- `--json` flag emits the full record including `options`, `notes`,
  `tool_use_id`, `source_path` for pipe / jq workflows.
- Summary footer: `N questions in <scope> | recommended hit rate: X%
  (M/N) | K unanswered`. Hit-rate denominator excludes orphans and
  rows with no recommendation, so the percentage reflects only the
  decisions that had a baseline.
- `aifd.models.QuestionAnswer` dataclass — one row per question (a
  single 1-4-question AUQ call yields multiple rows). Frozen, so it
  composes cleanly into v0.3+ stats / search.
- `aifd.cli._runner.run_provider_query` — shared harness extracted
  from `cli/ai/session.py` once the second multi-provider list command
  joined the file. session.py now delegates to it, so the v0.3+
  commands (stats, search, ...) plug in three callables instead of
  re-deriving the boilerplate.
- `aifd.providers._utils.split_recommended_suffix` recognises both
  English `(recommended)` and Chinese / Japanese / Korean / Spanish /
  French / German glosses (`(推荐)`, `(推奨)`, `(권장)`, ...). Driven
  by real-world data: every user-recorded session in the dev set used
  the localized suffix.
- `docs/question-extraction.md` — Chinese design doc covering the AUQ
  jsonl schema, `tool_use_id` pairing, multi-question splitting,
  orphan handling, and why Codex/brainstorm are deferred. Matches the
  v0.2.1 `docs/skill-detection.md` pattern.
- 45 new tests across `test_question_extraction.py` (provider unit),
  `test_question_render.py` (Table + footer + JSON), `test_question_cli.py`
  (end-to-end), `test_runner.py` (shared harness contract).

### Changed

- Provider Protocol gains `list_question_answers(scope) -> Iterable[QA]`
  default body returning `()`, matching the v0.2 pattern for
  `list_skill_invocations` and `list_installed_skills`. `CodexProvider`
  explicitly overrides with the same no-op shape because duck-typed
  classes don't inherit Protocol default bodies.
- `cli/ai/session.py` refactored to use `run_provider_query`. Behaviour
  identical (132 prior tests pass unchanged) but the harness is now
  shared with `aifd ai question list`.

## [0.2.1] - 2026-06-03

### Added

- `aifd ai claude skill list` — list all skills installed for Claude Code.
  Scans both `~/.claude/skills/` (user-installed) and
  `~/.claude/plugins/cache/.../skills/` (plugin-installed). Each row carries a
  `Source` column distinguishing user / plugin entries and surfaces the plugin
  name + version for the latter.
- `aifd ai codex skill list` — list all skills installed for Codex. Scans
  `~/.codex/skills/` and `.system/`. Built-in Codex skills (imagegen,
  skill-creator, etc.) appear with `source="system"`.
- `aifd/providers/_utils.py` `parse_skill_frontmatter` — handwritten YAML
  frontmatter parser, no PyYAML runtime dependency. Extracts `name`,
  `description`, `version`. Tolerates missing / malformed frontmatter.
- `InstalledSkill` dataclass in `aifd/models.py`. Provider Protocol gains a
  default `list_installed_skills()` returning `()` so third-party providers
  without a skills directory inherit no-op behavior.
- Shared `aifd/cli/_logging.py` `configure_logging()` helper. Replaces three
  duplicated `_configure_logging` definitions across `session.py`,
  `skill.py`, and the new per-provider commands.
- `docs/skill-detection.md` — technical reference for how skill markers and
  installed-skill discovery work across Claude jsonl, Codex SQLite, and the
  filesystem scans.

### Changed

- README updated with new command examples (`aifd ai claude/codex skill list`),
  architecture diagram now shows the v0.2.1 layout (`cli/_logging.py`,
  `cli/ai/claude/`, `cli/ai/codex/`).

## [0.2.0] - 2026-06-02

### Added

- `aifd ai skill list` — aggregates skill (slash-command) invocations across
  Claude Code and Codex into a single cross-tool view. Columns: skill name,
  per-provider counts, total, last-used relative time, distinct project count.
- `--cwd` flag to limit aggregation to the current directory. Default is global.
- `--provider claude|codex` flag to filter by source tool.
- `--json` flag for pipe-friendly output.
- `aifd/aggregation.py` — pure `aggregate_skill_stats(invocations) -> [stats]`
  function. Lives outside `cli/` so v0.3 `aifd ai stats` can reuse without
  coupling to a command's flag layout.
- `aifd/providers/_utils.py` — shared regexes (`CLAUDE_COMMAND_RE`,
  `CODEX_SKILL_RE`), `normalize_title`, `parse_iso_ts`,
  `normalize_skill_name` (strips `/` and `gstack-` prefix for cross-provider
  alignment), `is_gstack_name` for display restoration.
- `SkillInvocation` and `SkillStats` dataclasses with `is_gstack` flag.
  Aggregation OR-combines `is_gstack` so any tool's `/gstack-foo` flips the
  stat. Renderer restores `gstack-` prefix in the Table display while JSON
  keeps the normalized name plus `"is_gstack": bool` field.
- Codex provider extracts skill invocations from the `state_5.sqlite`
  `threads.first_user_message LIKE '[$%'` query (primary) with rollout-jsonl
  fallback when SQLite is unavailable.
- Claude provider extracts `<command-name>` markers from user-typed messages
  only; the `type=="user"` filter rejects assistant echoes and documentation
  strings that contain the literal marker text.

### Changed

- Codex provider migrated to **SQLite-first** architecture for session
  listing (`state_5.sqlite` `threads` table). jsonl scan remains as fallback
  for older Codex installs. Surfaces AI-generated `title` + `first_user_message`
  fields the jsonl path never had access to.
- `Session.message_count` renamed to `Session.event_count` to honestly
  describe the unit (jsonl lines / Codex events, not user/assistant turns).
- Session listing now displays an AI-generated title column when available
  (Claude `ai-title` event, Codex `threads.title`).

## [0.1.0] - 2026-06-01

### Added

- `aifd ai session list` — list AI sessions in the current directory across
  Claude Code and Codex.
- Provider Protocol (`typing.Protocol` + `@runtime_checkable`) with two
  initial implementations.
- Claude provider: two-phase cwd matching (directory-name encoding +
  authoritative jsonl cwd field) to handle paths containing `-` correctly.
- Codex provider: scans both `~/.codex/sessions/` and
  `~/.codex/archived_sessions/`.
- Three-tier error handling: IO error → warning skip file, JSON parse error →
  debug skip line, no matching event → silent skip. Single bad file never
  breaks the listing.
- `paths.normalize_cwd` + `cwd_equal` with OSError fallback for broken
  symlinks (Python 3.13 macOS) and case-insensitive matching on
  HFS+/APFS/NTFS.
- `--json`, `--provider`, `--verbose` flags.
- pytest + ruff + mypy strict + GitHub Actions CI matrix
  (Python 3.12+3.13 × Linux/macOS/Windows).
- GitHub Actions release workflow targeting PyPI Trusted Publisher.

[0.4.0]: https://github.com/xunull/aifd/releases/tag/v0.4.0
[0.3.1]: https://github.com/xunull/aifd/releases/tag/v0.3.1
[0.3.0]: https://github.com/xunull/aifd/releases/tag/v0.3.0
[0.2.1]: https://github.com/xunull/aifd/releases/tag/v0.2.1
[0.2.0]: https://github.com/xunull/aifd/releases/tag/v0.2.0
[0.1.0]: https://github.com/xunull/aifd/releases/tag/v0.1.0
