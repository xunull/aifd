# aifd vault watch — 接外部报警 / 监控系统的 cookbook

v0.7 把 vault watch 的 finding 做成了**事件流**，能 POST 到任何 HTTPS endpoint。
本文档讲清楚：**哪些目标能直接接、哪些要桥接、哪些等以后做**。

每个 target 给：

- **能否直接接** —— 即用 `aifd vault watch webhooks add` 一行
- **payload 示例** —— 接收端实际看到的 JSON
- **cookbook** —— 如果不能直接接，最低成本的桥接方案（一般是 1 行 jq 或一个 ~30 行 relay 脚本）

---

## 现状概览

aifd v0.7 ship 了两个 payload format：

| Format | 哪些 target 适用 | 状态 |
|---|---|---|
| **`aifd_v1`**（默认）| Slack incoming webhook、Discord、自家 HTTP receiver、任意 JSON 入口 | ✅ ship |
| **`pagerduty_v2`** | PagerDuty Events API v2 | ✅ ship，原生 |

未来 native client 候选（v0.7.1+，**未 ship**）：

- `sentry_v7` envelope + X-Sentry-Auth
- `otlp_v1` OpenTelemetry exporter（喂 Datadog / Honeycomb / Grafana Cloud）
- `slack_blockkit_v1` 原生 Slack Block Kit（省 jq 一步）
- `splunk_hec_v1` Splunk HTTP Event Collector

这些都在 eng review 时被列为 Approach C「Full integration ecosystem」明确推迟 ——
当前哲学是 aifd 做检测 + 通用出口，target-specific 美化交给桥接。

---

## Target 兼容性矩阵

| Target | 直接接 | 推荐方式 | 文档章节 |
|---|---|---|---|
| Slack incoming webhook | ⚠️ JSON 能发但格式难看 | aifd_v1 + jq Block Kit 转换 | [Slack](#slack) |
| Slack（Internal webhook、看不到漂亮卡）| ✅ | aifd_v1 直发 | 同上 |
| PagerDuty Events API v2 | ✅ 原生 | `--payload pagerduty_v2` | [PagerDuty](#pagerduty) |
| Discord webhook | ⚠️ JSON 能发但格式难看 | aifd_v1 + jq → Discord embed | [Discord](#discord) |
| Datadog Events API | ❌ 需 transformer | relay 脚本或 jq + curl | [Datadog](#datadog) |
| **Sentry**（捕成 issue）| ❌ 不原生 | 三种方案见下 | [Sentry](#sentry-) |
| Honeycomb / OTel | ❌ 不原生 | relay 脚本调 OTel SDK | [OTel](#opentelemetry--datadog--honeycomb--grafana-cloud) |
| Splunk HEC | ❌ 不原生 | jq + curl，~3 行 | [Splunk](#splunk-hec) |
| 自家 HTTP receiver | ✅ | aifd_v1 直发 | [自家](#自家-http-receiver) |
| Notion / Linear / Jira | ❌ 不原生 | relay 脚本调对应 SDK | [Linear / Notion / Jira](#linear--notion--jira-create-issue) |
| Email (SMTP) | ❌ 不原生 | relay 脚本 | — |

✅ = 一行 `webhooks add` 就跑；⚠️ = 能跑但 UX 差；❌ = 必须桥接。

---

## `aifd_v1` 长什么样

每个 cookbook 都基于这个 payload。先看它：

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

`url` 字段是**本机 detail 页**，给同机器的人点开看完整 occurrence + 状态机用。
跨机用户看到 `127.0.0.1:54791` 是 unreachable 的，靠 `fingerprint + file + line`
描述定位。

---

## Slack

### 方式 A：直接发 `aifd_v1` 到 Slack incoming webhook

Slack incoming webhook 接受任意 JSON，但只渲染 `text` 字段。直接发 `aifd_v1` 的
话，Slack 显示的是「{"event":"new_finding",...}」这种**裸 JSON 字符串**，可读但
不好看。

```bash
aifd vault watch webhooks add \
    --id slack-secops \
    --url https://hooks.slack.com/services/T.../B.../... \
    --on new_finding \
    --category openai_key --category github_pat
```

### 方式 B（推荐）：jq relay → Slack Block Kit

起个本地 relay 把 `aifd_v1` 转成 Block Kit shape：

```bash
# slack-relay.sh
#!/bin/bash
SLACK_URL="https://hooks.slack.com/services/T.../B.../..."

while read -r line; do
  echo "$line" | jq -c '{
    blocks: [
      {
        type: "header",
        text: { type: "plain_text", text: ("⚠️ aifd: " + .category + " leaked") }
      },
      {
        type: "section",
        fields: [
          { type: "mrkdwn", text: ("*Snippet:*\n`" + .snippet_redacted + "`") },
          { type: "mrkdwn", text: ("*File:*\n" + .file + ":" + (.line|tostring)) },
          { type: "mrkdwn", text: ("*Severity:*\n" + .rotation.severity) },
          { type: "mrkdwn", text: ("*Count:*\n" + (.count|tostring)) }
        ]
      },
      {
        type: "section",
        text: {
          type: "mrkdwn",
          text: ("*Rotate at:* <" + .rotation.vendor_dashboard + "|" + .rotation.vendor_dashboard + ">")
        }
      },
      {
        type: "context",
        elements: [
          { type: "mrkdwn", text: ("fingerprint `" + .fingerprint + "` · first seen " + .first_seen) }
        ]
      }
    ]
  }' | curl -s -X POST -H 'Content-Type: application/json' -d @- "$SLACK_URL"
done
```

或者起一个长驻 HTTP server 接 aifd 的 webhook 转 Slack，模板见 [relay 模板](#relay-脚本通用模板)。

---

## PagerDuty

`pagerduty_v2` 原生。URL 加 `?routing_key=R123` 即可：

```bash
aifd vault watch webhooks add \
    --id pd-secops \
    --url "https://events.pagerduty.com/v2/enqueue?routing_key=R0123456789ABCDEF" \
    --payload pagerduty_v2 \
    --on new_finding
aifd vault watch webhooks test pd-secops
aifd vault watch webhooks enable pd-secops
```

aifd 自动把 `routing_key` 从 URL query 挪到 body，按 PagerDuty Events API v2 spec
发送。`dedup_key` = aifd 的 `fingerprint`，所以同一 secret 不会在 PD 里炸 N 个
incident，会合并到一个。

severity 自动映射：

| aifd category severity | PagerDuty severity |
|---|---|
| critical | critical |
| high | error |
| medium | warning |
| low | info |

---

## Discord

跟 Slack 同理 —— Discord webhook 接 JSON，但需要 `content` 或 `embeds` 字段才有
好看的渲染。直接发 `aifd_v1` Discord 会拒绝（因为没有 `content`/`embeds`）。

最小 jq 转换：

```bash
# discord-relay.sh
DISCORD_URL="https://discord.com/api/webhooks/.../..."

while read -r line; do
  echo "$line" | jq -c '{
    embeds: [{
      title: ("⚠️ aifd: " + .category + " leaked"),
      description: ("`" + .snippet_redacted + "` in " + .file + ":" + (.line|tostring)),
      color: (if .rotation.severity == "critical" then 15158332 else 16753920 end),
      fields: [
        { name: "Rotation", value: .rotation.vendor_dashboard, inline: false },
        { name: "Severity", value: .rotation.severity, inline: true },
        { name: "Count", value: (.count|tostring), inline: true }
      ],
      footer: { text: ("fingerprint " + .fingerprint) }
    }]
  }' | curl -s -X POST -H 'Content-Type: application/json' -d @- "$DISCORD_URL"
done
```

---

## Datadog

Datadog Events API 接受 POST 但 schema 不同（要 `title`、`text`、`tags`、
`alert_type`）。一行 jq 转就行：

```bash
# datadog-relay.sh
DD_API_KEY="your-api-key"

while read -r line; do
  echo "$line" | jq -c '{
    title: ("aifd: " + .category + " leaked"),
    text: ("`" + .snippet_redacted + "` in " + .file + ":" + (.line|tostring) + "\nRotate: " + .rotation.vendor_dashboard),
    tags: [("category:" + .category), ("severity:" + .rotation.severity), ("source:aifd")],
    alert_type: (if .rotation.severity == "critical" then "error" else "warning" end),
    aggregation_key: .fingerprint
  }' | curl -s -X POST \
       -H "Content-Type: application/json" \
       -H "DD-API-KEY: $DD_API_KEY" \
       https://api.datadoghq.com/api/v1/events
done
```

`aggregation_key` 用 fingerprint，Datadog 自动按这个 key 把同一 secret 的事件折
叠。

---

## Sentry 详解

Sentry 不能直接接，原因：

1. **Sentry intake API** (`POST /api/PROJECT_ID/store/`) 期望 `X-Sentry-Auth`
   header 带 DSN 解析的 `sentry_key`、`sentry_version`、`sentry_client`
2. **Sentry envelope** 是 newline-delimited multi-part 格式，不是平 JSON
3. **Sentry event schema** 有特定字段：`event_id` (uuid4)、`timestamp`（特定格式）、
   `level`、`platform`、`exception`/`message`、`tags`、`extra` 等

三种现实路径：

### 方案 1：1 行脚本桥 + sentry-sdk（**推荐起手**）

最短路径。装 `sentry-sdk`，跑一个 HTTP server 转 aifd 的 webhook 成 Sentry SDK 调
用：

```python
# aifd-to-sentry.py
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import sentry_sdk

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    traces_sample_rate=0.0,    # vault watch 不是性能信号源
)


class H(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        n = int(self.headers["Content-Length"])
        ev = json.loads(self.rfile.read(n))
        if ev.get("event") != "new_finding":
            self.send_response(200); self.end_headers(); return
        # capture_message 在 Sentry 里建一个 issue，按 fingerprint 去重
        with sentry_sdk.push_scope() as scope:
            scope.set_tag("aifd.category", ev["category"])
            scope.set_tag("aifd.severity", ev["rotation"]["severity"])
            scope.set_extra("snippet_redacted", ev["snippet_redacted"])
            scope.set_extra("file", ev["file"])
            scope.set_extra("line", ev["line"])
            scope.set_extra("rotation_dashboard", ev["rotation"]["vendor_dashboard"])
            scope.set_extra("rotation_instruction", ev["rotation"]["instruction"])
            scope.fingerprint = [ev["fingerprint"]]  # Sentry-side dedup key
            sentry_sdk.capture_message(
                f"aifd: {ev['category']} leaked in {ev['file']}:{ev['line']}",
                level="error",
            )
        self.send_response(200); self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9099), H).serve_forever()
```

跑起来 + 接 aifd：

```bash
pip install sentry-sdk
SENTRY_DSN="https://....@o0.ingest.sentry.io/0" python3 aifd-to-sentry.py &

aifd vault watch webhooks add \
    --id sentry-relay \
    --url http://127.0.0.1:9099/ \
    --on new_finding
aifd vault watch webhooks test sentry-relay
aifd vault watch webhooks enable sentry-relay
```

**得到的 Sentry 体验**：每条 secret 在 Sentry 里是一个 `Error` level issue，
`scope.fingerprint=[aifd 的 fingerprint]` 保证同一 secret 在 Sentry 里也是一个
issue，count++。所有元数据（category、file、line、rotation link、instruction）都
在 Sentry issue 的 Tags + Additional Data 区。

**缺点**：要长驻一个 python 进程。如果 aifd daemon 死了，relay 也无所谓（它只是
等 webhook）。如果 relay 死了，aifd 的 dead_letter 会接住（user `webhooks
retry-dead-letter` 即可）。

### 方案 2：Sentry Internal Integration（**无脚本**）

Sentry 的「Internal Integrations」允许在 Sentry UI 里建一个 custom webhook URL，
并定义字段映射规则。aifd 直接发 `aifd_v1`，Sentry UI 自动把字段映射到 issue 字段。

步骤：

1. Sentry → Settings → Custom Integrations → Internal Integration → New
2. Permissions：勾 `Issue & Event: Write`
3. Webhooks → Enabled，URL 留空（你不要 Sentry 发 webhook 给你）
4. Save → 拿到 webhook URL 形如
   `https://sentry.io/api/0/issues/?token=...`
   或自定义 alert rule webhook

5. 把这个 URL 配到 aifd：

```bash
aifd vault watch webhooks add \
    --url "<sentry-internal-webhook-url>" \
    --on new_finding
```

**注意**：Sentry Internal Integration 的 URL schema 跟版本相关；查 Sentry 当前
docs。不是所有 plan 都开放这个 feature。

**得到的 Sentry 体验**：是个 generic alert，不是真 exception/error。能 group，
能 close，但不会有 exception stack trace UI。

### 方案 3：aifd 加 `sentry_v7` 原生 payload format（**未 ship**）

工程范围（v0.7.1 候选）：

- 解析 user 提供的 DSN（`https://KEY@HOST/PROJECT_ID`）
- 渲染 Sentry envelope（newline-delimited，含 envelope header + item header + item
  body）
- 拼 `X-Sentry-Auth: Sentry sentry_version=7, sentry_key=KEY, sentry_client=aifd/0.7.0`
- 把 aifd_v1 字段映射到 Sentry event schema：
  - `message` ← `f"aifd: {category} leaked"`
  - `level` ← critical→fatal / high→error / medium→warning / low→info
  - `tags` ← category、severity、file_basename
  - `extra` ← snippet_redacted、rotation_*
  - `fingerprint` ← aifd 的 fingerprint
- 单元测试覆盖 envelope serialization + DSN parse + 集成测试发到 sentry.io test
  project

预估 ~200 LOC + 测试，~1 小时 CC。如果你跑了一两周方案 1 觉得真要原生，再做这个。

---

## OpenTelemetry / Datadog / Honeycomb / Grafana Cloud

OTel 是 vendor-agnostic 协议，接它就接到了上面这些 vendor。aifd 没自带 OTel
exporter（eng review C 推迟），所以走 relay：

```python
# aifd-to-otel.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint=os.environ["OTLP_ENDPOINT"],
    headers={"x-api-key": os.environ["OTLP_API_KEY"]},
)))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("aifd")


class H(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        n = int(self.headers["Content-Length"])
        ev = json.loads(self.rfile.read(n))
        with tracer.start_as_current_span("aifd.secret_detected") as span:
            span.set_attribute("aifd.category", ev["category"])
            span.set_attribute("aifd.severity", ev["rotation"]["severity"])
            span.set_attribute("aifd.file", ev["file"])
            span.set_attribute("aifd.line", ev["line"])
            span.set_attribute("aifd.snippet_redacted", ev["snippet_redacted"])
            span.set_attribute("aifd.fingerprint", ev["fingerprint"])
            span.set_status(trace.Status(trace.StatusCode.ERROR))
        self.send_response(200); self.end_headers()


HTTPServer(("127.0.0.1", 9100), H).serve_forever()
```

`OTLP_ENDPOINT` 就是各家的 OTel 入口：

- Datadog: `https://trace.agent.datadoghq.com/v0.4/traces`（DD API key in header）
- Honeycomb: `https://api.honeycomb.io/v1/traces`（X-Honeycomb-Team in header）
- Grafana Cloud Tempo: 看你的 stack 提供的 OTel 入口

---

## Splunk HEC

Splunk HTTP Event Collector 接受任意 JSON，封装一层即可：

```bash
# splunk-relay.sh
SPLUNK_URL="https://splunk.example.com:8088/services/collector"
SPLUNK_TOKEN="..."

while read -r line; do
  echo "$line" | jq -c '{
    sourcetype: "_json",
    source: "aifd-vault-watch",
    event: .
  }' | curl -s -X POST \
       -H "Authorization: Splunk $SPLUNK_TOKEN" \
       -H "Content-Type: application/json" \
       -d @- "$SPLUNK_URL"
done
```

---

## Linear / Notion / Jira create issue

每家 issue tracker 都有 REST API + 自己的 schema。模板：

```python
# aifd-to-linear.py
import os, json
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

LINEAR_API_KEY = os.environ["LINEAR_API_KEY"]
LINEAR_TEAM_ID = os.environ["LINEAR_TEAM_ID"]


def create_linear_issue(ev):
    query = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) { success issue { id identifier } }
    }
    """
    variables = {
        "input": {
            "teamId": LINEAR_TEAM_ID,
            "title": f"aifd: {ev['category']} leaked in {ev['file']}:{ev['line']}",
            "description": (
                f"**Snippet:** `{ev['snippet_redacted']}`\n\n"
                f"**Rotate at:** {ev['rotation']['vendor_dashboard']}\n\n"
                f"{ev['rotation']['instruction']}\n\n"
                f"---\nFingerprint: `{ev['fingerprint']}` · "
                f"first seen {ev['first_seen']}"
            ),
            "priority": 1 if ev['rotation']['severity'] == "critical" else 2,
            "labelIds": [],  # add your label IDs
        }
    }
    requests.post(
        "https://api.linear.app/graphql",
        json={"query": query, "variables": variables},
        headers={"Authorization": LINEAR_API_KEY},
    )


class H(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        n = int(self.headers["Content-Length"])
        ev = json.loads(self.rfile.read(n))
        if ev.get("event") == "new_finding":
            create_linear_issue(ev)
        self.send_response(200); self.end_headers()


HTTPServer(("127.0.0.1", 9101), H).serve_forever()
```

Notion 用 `https://api.notion.com/v1/pages` + database ID。
Jira 用 `https://YOUR_DOMAIN.atlassian.net/rest/api/3/issue`。

---

## 自家 HTTP receiver

如果你已经有内部 monitoring 接受 webhook，直接配 aifd URL 即可：

```bash
aifd vault watch webhooks add \
    --id internal-monitor \
    --url https://monitor.internal/aifd-events \
    --on new_finding
```

`aifd_v1` 的 schema 在 `docs/vault-events.md` 里固定，可以放心当合约用。

---

## Relay 脚本通用模板

任何 target 都套这个壳：

```python
# template-relay.py
"""Generic aifd webhook → custom relay template.

Replace `forward_to_target()` with your destination's SDK / HTTP call.
"""
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("aifd-relay")


def forward_to_target(event: dict) -> None:
    """Replace this with your actual integration."""
    log.info("would forward: %s", event["fingerprint"])
    # e.g. requests.post(..., json={...})


class _H(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n)
            event = json.loads(raw)
            forward_to_target(event)
            self.send_response(200)
        except Exception as exc:
            log.error("relay failed: %s", exc)
            self.send_response(500)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        log.debug("http: " + fmt, *args)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9099), _H).serve_forever()
```

接 aifd：

```bash
python3 template-relay.py &
aifd vault watch webhooks add --url http://127.0.0.1:9099/ --on new_finding
aifd vault watch webhooks test <id>
aifd vault watch webhooks enable <id>
```

**Relay 进程死了怎么办**？aifd 的 webhook deliverer 会 retry 3 次（10s / 60s /
600s exponential backoff）；都失败进 dead_letter。Relay 复活后跑
`aifd vault watch webhooks retry-dead-letter --id <id>` 重新发。

---

## 路线图

按优先级：

| 候选 | 工程范围 | 取舍 |
|---|---|---|
| `slack_blockkit_v1` payload | ~150 LOC + 测试 | Slack 是最高频用户，省 jq |
| `sentry_v7` payload + envelope | ~200 LOC + DSN parse + 集成测试 | Sentry 是 secret monitoring 的合理归宿，方案 1 工作但有 relay 维护成本 |
| `otlp_v1` exporter | ~300 LOC + OpenTelemetry 依赖 | 一次接，所有 vendor 通 |
| `splunk_hec_v1` payload | ~100 LOC | 企业 SIEM 场景 |
| daily / weekly digest webhook | ~200 LOC + scheduler | 见 TODOS.md "digest webhook" |
| alert rule engine（time-window） | ~400 LOC + rule DSL | 见 NOT in scope |

加哪个由真用户需求决定 —— 先用 relay 桥 1-2 周看 friction 在哪。

---

## 相关文档

- [`vault-events.md`](./vault-events.md) — events store + webhook 命令参考 + 数据模型
- [`vault-watch.md`](./vault-watch.md) — daemon lifecycle + launchd 安装
- [`secret-scan.md`](./secret-scan.md) — detector 原理 + 安全 invariant
