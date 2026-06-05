# aifd ai today / weekly / monthly / retro

按时间窗口聚合你的 AI 活动（Claude Code + Codex），一行命令看到：

- 多少个 session 今天 / 本周有活动
- 花了多少钱（cost），跑了多少 token
- 哪些 skill 用得最频繁
- 哪些 topic（每个 session 的第一句 user prompt）跑得最多
- 跟上一个对等周期对比（今天 vs 昨天 / 本周 vs 上周）
- 按当前速度，月度预算预估

## 命令一览

| 命令 | 时间窗口 |
|---|---|
| `aifd ai today` | 本地 00:00 到现在 |
| `aifd ai weekly` | 过去 7 天 rolling（不是 ISO 周） |
| `aifd ai monthly` | 当月 1 号 00:00 到现在 |
| `aifd ai retro --since YYYY-MM-DD [--until YYYY-MM-DD]` | 自定义区间。`--until` 缺省为现在 |

所有命令支持：
- `--json` — 输出稳定 schema 的 JSON（pipe / MCP 友好）
- `-v` / `-vv` — INFO / DEBUG 级别日志（stderr）

## 输出示例

```
═══ Today ═══ 2026-06-05 00:00 → 2026-06-05 09:41

  5 sessions · $80.30 · 85,384,666 tokens
  claude 5 sess · $80.30
  top skills: plan-eng-review x4 · ship x1
  top topics:
    · v0.4.1 vault scan UI/UX
    · FP suppression discussion
    · aifd ai today implementation

  vs previous: -$443.80 cost · -3 sessions
  → at this pace, monthly projection: $5,963.59 (based on 9.7h)
```

颜色提示（terminal mode）：
- $1 以下 cost 走白色
- $1–5 走黄
- $5 以上走红

## "Session" 的语义

**session_count = 本时间窗口内有 token 活动的不同 session 数**，*不是* "本窗口内新启动的 session 数"。

为什么这样？反例：你昨天开了一个 Claude 会话，今天早上继续在那个会话里跑。直觉上"今天的活动"应该包含这个会话。如果只数新启动的 session，今天的 cost 可能是 $50 但 session_count = 0，反直觉。

实现上：扫所有 `TokenUsage`，把 ts 落在窗口内的取出，按 `(provider, session_id)` 去重，得到 session_count。

## "Top topics" 是什么

每个 Session 在 v0.2 已经提取了 `title` 字段（Claude 的 `ai-title` 事件，否则第一句 user prompt）。`top_topics` 就是 active session 的 title 计数 top N。

通常每个 session 的 title 都唯一，所以 count 大多是 1。但如果你在同一个会话里反复迭代同一个问题（比如多次 try），同 title 会合并、count > 1。

## `--json` schema

稳定字段，未来的 MCP server（v0.6+）会直接 expose 这个结构给 Claude：

```json
{
  "period_start": "2026-06-05T00:00:00+00:00",
  "period_end": "2026-06-05T09:41:00+00:00",
  "session_count": 5,
  "cost_usd": 80.3015,
  "total_tokens": 85384666,
  "by_provider": [
    {"provider": "claude", "sessions": 5, "cost_usd": 80.3015, "total_tokens": 85384666}
  ],
  "top_skills": [
    {"skill": "plan-eng-review", "count": 4},
    {"skill": "ship", "count": 1}
  ],
  "top_topics": [
    {"topic": "v0.4.1 vault scan UI/UX", "count": 1}
  ],
  "delta": {
    "has_prior": true,
    "cost_delta": -443.80,
    "session_delta": -3,
    "token_delta": -120000000
  },
  "projection": {
    "enough_data": true,
    "monthly_usd": 5963.59,
    "hours_elapsed": 9.7
  }
}
```

`delta.has_prior=false` 时，渲染器显示 "vs previous: no prior data"。

`projection.enough_data=false` 时（窗口 elapsed < 1 小时），显示 "(too early)" 而不是给一个 wildly inflated 数字。

## 性能

复用 `aifd vault scan` 同一套 jsonl 读取层。`today` 窗口在我这边数据（>800MB jsonl）实测 < 1 秒。`weekly` ~2.5s。`monthly` ~9.5s（基本等于全量扫，因为月度窗口囊括了几乎所有数据）。

## 跟 `aifd vault cost` 的区别

| 维度 | `aifd vault cost` | `aifd ai today/weekly` |
|---|---|---|
| 时间维度 | 全量 / by month | 按窗口聚合 + diff + projection |
| 视角 | "钱花在哪里" | "今天 / 本周做了什么" |
| 输出 | 一张大表 | 紧凑摘要 + topics + skills |
| 使用频率 | 月报型 | 日报 / 周报型 |

两个命令互补不重叠。

## 与未来 feature 的关系

- **MCP server (v0.6+)**：`--json` schema 就是 `ai_today_summary` tool 的 return schema。Claude 直接调，问 "上周我们怎么决策 X 的？" 可以看到对应 session topic。
- **`--web` 模式 (TODOS)**：复用 `aifd vault scan --web` 的 localhost HTTP server 模式，渲染同一份 `ActivityReport`。
- **Per-project breakdown (TODOS)**：按 cwd 分组的视图，给多项目用户。
- **Git correlation (TODOS)**：和 `git log --since` 关联，标"今天 ship 了什么"。

## 相关文件
- `aifd/insights.py` — `summarize_activity` / `compute_diff` / `compute_projection` / window helpers
- `aifd/cli/ai/retro.py` — 4 个 CLI 子命令的薄壳层
- `aifd/render.py:render_activity_report` — rich Table + JSON 渲染
- `tests/test_insights.py` — 16 个单元测试
- `tests/test_cli_ai_retro.py` — 4 个 CLI 测试
