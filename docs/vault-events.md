# `aifd vault watch events` — persistent finding stream + webhooks

Shipped in **v0.7.0**.

`aifd vault watch` 在 v0.6 把检测做到了实时，v0.7 把它从「内存里的瞬时通知」升级
成「持久化事件流 + web 查询 + 接外部报警系统」。

每条 finding 现在：

- **落盘到 SQLite** (`~/.aifd/findings.db`) — daemon 重启不丢
- **有 fingerprint** —— 同一 secret 重复出现 = 一个 issue，count++
- **有状态机** —— new / acknowledged / resolved / muted
- **触发 webhook** —— POST JSON 到用户配置的 URL，接 Slack / PagerDuty / Datadog / 自家
- **附带 rotation playbook** —— vendor dashboard 链接 + 步骤说明，把检测闭环到 action

---

## Quick start

```bash
# 1. 启动 daemon（同 v0.6）
aifd vault watch install        # macOS launchd 自启
# 或前台调试
aifd vault watch start --foreground

# 2. 看捕获的 findings
aifd vault watch events list
aifd vault watch events show <fingerprint>

# 3. 接外部报警
aifd vault watch webhooks add \
  --id slack-secops \
  --url https://hooks.slack.com/services/T.../B.../... \
  --on new_finding \
  --category openai_key --category github_pat

aifd vault watch webhooks test slack-secops   # 验证通
aifd vault watch webhooks enable slack-secops # 启用

# 4. 浏览器查看
open http://127.0.0.1:$(cat ~/.aifd/watch.port)/
```

---

## CLI

### `events` 子命令

| 命令 | 作用 |
| --- | --- |
| `events list [--status STATUS --category CAT --limit N --offset N --json]` | 列 finding，默认 LIMIT 50，按 `last_seen DESC` |
| `events show <fingerprint> [--json]` | 详情 + 出现历史 + rotation playbook |
| `events ack <fingerprint>` | 标 acknowledged |
| `events mute <fingerprint> [--hours N]` | mute N 小时；省略 = 永久 |
| `events resolve <fingerprint>` | 标 resolved（同一 secret 再出现会 re-open） |
| `events export --format ndjson` | NDJSON 流到 stdout，喂任何 forwarder |

### `webhooks` 子命令

| 命令 | 作用 |
| --- | --- |
| `webhooks list [--json]` | 列已配 webhook |
| `webhooks add --url URL [--id ID --on EVENT --category CAT --payload FMT --lang en\|zh]` | 加新 webhook（默认 disabled） |
| `webhooks delete <id>` | 删 |
| `webhooks test <id>` | 同步发一条测试 event；用于 enable 前验证 |
| `webhooks enable <id>` | 启用（必须先 test 通） |
| `webhooks disable <id>` | 临时禁用，不删配置 |
| `webhooks list-dead-letter [--json]` | 看发失败队列 |
| `webhooks retry-dead-letter [--id ID]` | 重新入队 dead_letter（manual，D4 决策） |

---

## 数据模型

### `~/.aifd/findings.db` — SQLite (WAL mode)

```
findings (1) ←——————— (N) finding_occurrences
    │
    │  fingerprint = SHA1(category + snippet_redacted)
    │  跨机器、跨用户名稳定；同一 secret 在多个文件出现 = 一个 issue
    │
    │  status state machine:
    │    new → acknowledged → resolved
    │             ↘ muted (with optional muted_until)
    │             ↘ resolved 之后 re-detect → re-open 成 new
    │
    └─→ webhook_dead_letter (N)
            fingerprint, webhook_id, payload, attempted_at, attempts, last_error
```

### 字段

| Table.column | 类型 | 说明 |
| --- | --- | --- |
| `findings.fingerprint` | TEXT (PK) | SHA1(category + snippet)[:16] — 16 hex 字符 |
| `findings.category` | TEXT | openai_key / github_pat / aws_secret / jwt / ... |
| `findings.snippet_redacted` | TEXT | 永远是 redacted（"sk-A…WXYZ"），不含完整 secret |
| `findings.status` | TEXT | new / acknowledged / resolved / muted |
| `findings.muted_until` | TEXT | ISO 8601；NULL = 永久 mute 或非 muted |
| `findings.count` | INTEGER | 同一 fingerprint 出现次数 |
| `findings.notes` | TEXT | 用户 note（任意文本） |
| `finding_occurrences.file_basename` | TEXT | 文件名，不含目录 |
| `finding_occurrences.file_path` | TEXT | 完整本地路径（不进 webhook payload） |
| `finding_occurrences.byte_offset` | INTEGER | 重新读 raw 上下文用 |

### 并发模型 (D1)

每个线程开自己的 connection；WAL 模式允许 reader 不阻 writer。daemon 内有：

- **worker thread** — 写 findings 和 occurrences
- **HTTP server thread** — 读 findings + status 变更
- **webhook deliverer thread** — 读 + 写 dead_letter
- **sweeper thread** — 5min 全量重扫 + mute 过期 sweep

WAL 模式下 4 个线程并发读写 SQLite **不会 SQLITE_BUSY**（v0.7 测试覆盖）。

---

## Webhook payload formats

完整接入 cookbook（Slack / PagerDuty / Discord / Datadog / Sentry / OTel /
Splunk / Linear / Notion / Jira / 自家 receiver / relay 模板）见
[`vault-events-integrations.md`](./vault-events-integrations.md)。

### `aifd_v1` (default)

```json
{
  "event": "new_finding",
  "fingerprint": "abc123def456",
  "category": "openai_key",
  "snippet_redacted": "sk-J…oNwP",
  "file": "rollout-2026-05-01-019de13e.jsonl",
  "line": 1112,
  "first_seen": "2026-06-05T17:01:34+00:00",
  "count": 1,
  "url": "http://127.0.0.1:54791/events/abc123def456",
  "rotation": {
    "vendor_dashboard": "https://platform.openai.com/api-keys",
    "instruction": "1. Revoke the leaked key at the dashboard\n2. ...",
    "severity": "critical"
  }
}
```

Slack incoming webhook 可以直接吃这个 JSON（会拒绝因为不是 Block Kit 形态），
但用 1 行 jq 就能转：

```bash
jq '{text: ("⚠ aifd: " + .category + " leaked in " + .file)}' < payload.json
```

PagerDuty / Datadog incoming webhook 同理 —— `aifd_v1` 是 generic shape，
具体目标用 transform middleware 接。

### `pagerduty_v2`

如果 URL 是 `https://events.pagerduty.com/v2/enqueue?routing_key=R123` 这种
形式，aifd 把 `routing_key` 挪到 body，按 PagerDuty Events API v2 spec 发：

```json
{
  "routing_key": "R123",
  "event_action": "trigger",
  "dedup_key": "abc123def456",
  "payload": {
    "summary": "aifd vault watch: openai_key leaked in rollout-...:1112",
    "source": "aifd vault watch",
    "severity": "critical",
    "custom_details": {
      "snippet_redacted": "sk-J…oNwP",
      "rotation_dashboard": "https://platform.openai.com/api-keys",
      "rotation_instruction": "...",
      "first_seen": "2026-06-05T17:01:34+00:00",
      "count": 1,
      "detail_url": "http://127.0.0.1:54791/events/abc123def456"
    }
  }
}
```

---

## Rotation playbooks

每个 category 在 `aifd/vault/playbooks.py` 里有一个 `vendor_dashboard` +
multi-locale instruction 表。v0.7 已 ship 的 category：

- `openai_key` → https://platform.openai.com/api-keys
- `anthropic_key` → https://console.anthropic.com/settings/keys
- `github_pat` → https://github.com/settings/tokens
- `github_oauth` → https://github.com/settings/applications
- `aws_access_key` / `aws_secret` → IAM Console
- `slack_token` → https://api.slack.com/apps
- `jwt` → server-side rotation guidance
- `gcp_service_account` → IAM & Admin > Service Accounts
- `email`, `high_entropy` → low-severity 提示

unknown category → generic「找到、rotate、audit」三步指令。

Locale: en (default), zh (中文)。webhook 配 `lang: zh` 时 payload 里 instruction
是中文版。

加新 playbook = 给 `PLAYBOOKS` 加一个 entry，en + zh + severity，三个字段必填。
未来 TODO 提了多 locale 候选（ja, ko 等）。

---

## Web UI

`GET http://127.0.0.1:PORT/` —— 单页 SPA（vanilla JS，零 build step）。

三个视图：

- **Findings**（默认）— list + filter by status / category + 分页 + click 进 detail
- **Detail** — 单条 finding 的 status 按钮（Ack / Mute 24h / Mute forever /
  Resolve）+ rotation playbook block（醒目 yellow 卡片，vendor link + 步骤）
  + occurrences timeline
- **Webhooks** — list 现有 webhook + add form + per-row Test / Enable / Disable / Delete 按钮

浏览器语言（`navigator.language`）决定 playbook 是 en 还是 zh。

---

## 安全 invariant

| Invariant | 在哪保证 |
| --- | --- |
| HTTP server 只绑 127.0.0.1 | `aifd/vault/watch_server.py:socketserver.TCPServer(("127.0.0.1", 0), ...)` |
| webhook URL 只接受 http/https | `aifd/vault/webhooks.py:_validate_url` |
| webhook 默认 disabled | D3 — 必须 explicit `enable` 才发送 |
| raw secret 永不落 SQLite | `_handle_match` 只传 `snippet_redacted` 进 `upsert_finding` |
| webhook payload 只含 file basename | D2 — `match.file.name` 而不是 `str(match.file)` |
| fingerprint 跨机稳定 | D2 — SHA1(category + snippet) 不含 path |
| dead_letter 不自动重试 | D4 — 必须 CLI 手动 `retry-dead-letter` |
| events DB 失败不杀 daemon | `_handle_match` 包 try/except → `finding_drop_count++` |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `aifd vault watch events list` 返回 "No events DB yet" | daemon 还没跑过；启动后捕获第一条 secret 时建表 |
| webhook 发不出去，但 `webhooks list` 显示 ENABLED | 看 `aifd vault watch tail`；可能是 webhook URL 错配；试 `webhooks test <id>` |
| `webhooks test` 返回 "permanent: HTTP 4xx" | URL 不对 / endpoint 拒绝 payload 格式 / token 过期 |
| dead_letter 越积越多 | webhook 接收端坏了；`webhooks list-dead-letter` 看错误；fix URL 后 `webhooks retry-dead-letter` |
| `aifd vault watch status` 显示 `drops ⚠ N` | events DB 写失败 N 次（多半是 disk full 或权限问题）；检查 `~/.aifd/` 权限和容量 |
| 重启 daemon 后 click-to-jump URL 404 | 设计如此 —— in-memory token 跨进程不存；用 `aifd vault watch events show <fp>` 或浏览器开 `/events/<fp>` |
| Web UI 列表很慢 | 加 `?limit=20` 或 categorize filter；events DB 默认 `last_seen DESC` 索引覆盖 |

---

## 相关文件

| 文件 | 作用 |
|---|---|
| `aifd/vault/events_db.py` | WatchEventsDB + WAL + fingerprint + state machine |
| `aifd/vault/playbooks.py` | rotation 库，en + zh |
| `aifd/vault/webhooks.py` | WebhookEntry yaml load/save + WebhookDeliverer + dead_letter |
| `aifd/vault/watch_server.py` | HTTP server + /events + /webhooks + /findings/{token} |
| `aifd/vault/watch.py` | Daemon.run + Daemon._handle_match (events DB + webhook 触发) |
| `aifd/cli/vault/watch.py` | `events`, `webhooks` 子命令 |
| `aifd/vault/static/{index.html,app.js,style.css}` | 单页 SPA |
| `~/.aifd/findings.db` | SQLite, WAL |
| `~/.aifd/webhooks.yaml` | webhook 配置（yaml） |
| `~/.aifd/watch-state.json` | v0.6 scan offset + daily counters + drop count (T9) |
| `tests/test_vault_events_db.py` | 29 events store 测试 |
| `tests/test_vault_playbooks.py` | 31 playbook 测试 |
| `tests/test_vault_webhooks.py` | 22 webhook 测试 |
| `tests/test_vault_watch_server_events.py` | 25 HTTP endpoint 测试 |
| `tests/test_vault_watch_cli_events.py` | 22 CLI 测试 |
| `tests/test_vault_watch_regression.py` | 8 v0.6 + E10 invariant 回归测试 |
