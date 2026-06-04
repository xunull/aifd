# vault 命令族

`aifd vault` 是 v0.4 引入的命令族，对应 CEO plan 「数据保险柜」方向 ——
把 AI 历史当作**你的资产**来 own / audit / 保护，而不是被 AI 工具锁住的私有格式。

v0.4 ships 2 个命令：
- `aifd vault scan` 扫描 PII / secret 泄露
- `aifd vault cost` 估算 token 用量 + USD 花费

v0.5+ 候选（推迟在 TODOS.md）：`export` 全量备份 / `sync` 多机同步 / `redact` 选择性删除 / `encrypt` 本地加密。

## 为什么是 vault

每次跟 AI 协作，你的代码 / 思路 / 决策都进了它的私有存储：

```
~/.claude/projects/{encoded-cwd}/{uuid}.jsonl   ← 你的对话历史
~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl    ← 你的对话历史
~/.codex/state_5.sqlite                          ← Codex thread 元数据
```

这些是**你**的数据，但你不知道里面有什么、没有备份、可能含 token 泄露、跨机器看不到。
vault 把它们当作你的**数据保险柜**对待。

---

## aifd vault scan

### 设计

逐行扫所有 provider jsonl，对每行跑两层检测：

1. **Regex 检测**（confidence 7-10）—— 已知 secret 形态：
   - `sk-ant-` (Anthropic)
   - `sk-` / `sk-proj-` (OpenAI)
   - `ghp_` / `github_pat_` / `ghs_` (GitHub)
   - `AKIA*` (AWS)
   - `xox[baprs]-` (Slack)
   - `eyJ*.*.*` (JWT)
   - bearer token
   - email 地址

2. **Shannon 熵检测**（confidence 4-6）—— 40-200 字符的高熵字符串：
   - 熵 ≥ 4.5 bits/char
   - 跳过已知格式（md5 / sha1 / sha256 hash）
   - 用来兜底未知 token 格式

### 输出安全

`SensitiveMatch` 数据类**故意不存完整 secret 值**，只存 `snippet_redacted` 字段（首 4 + 尾 4 字符 + `…REDACTED…` 中间）：

```
sk-proj-abc1234567890abcdef1234567890   ← 实际值（永不出现在日志/输出）
sk-p…REDACTED…7890                      ← Table / JSON 看到的
```

JSON 输出也只含 redacted snippet。完整 secret 从读入到 emit 全程在内存里、scan 完即释放。

### Confidence 评分规则

| Confidence | 含义 | 示例 |
|---|---|---|
| 10 | vendor-specific 前缀 regex 强命中 | `sk-`, `sk-ant-`, `ghp_`, `github_pat_` |
| 9 | 已知模式但易混（AWS / Slack）| `AKIA*`, `xox[baprs]-` |
| 8 | 通用 secret 形态 regex | JWT (eyJ-prefix) |
| 7 | PII / 通用 token 弱形态 | email, `bearer XXX` |
| 6 | 高熵字符串 ≥5.5 bits/char | base64-looking blob |
| 5 | 高熵字符串 ≥5.0 bits/char | |
| 4 | 高熵字符串 ≥4.5 bits/char | |

CLI 默认 `--min-confidence 7` —— 只显示 regex 命中。熵检测要 opt-in `--min-confidence 4`，因为噪点大（embedding / hash / UUID 都会被抓）。

### 真实数据校准

扫 32 个 Claude 项目 + 115 个 Codex session：

| 类别 | 数量 |
|---|---|
| openai_key | 304 |
| email | 918 |
| jwt | 4 |
| github_pat | 1 |
| **high_entropy (suppressed)** | 287,776 |

7-默认阈值后正信号 ~1228 个，全部值得人工 review。熵 287K 是噪点（hash 类居多），如果默认显示会淹没 304 个真 key。

---

## aifd vault cost

### 设计

聚合所有 provider 每个 event 的 token usage，按 model 价格表算 USD，按 project / model / month / provider 分组排序。

### 数据来源

#### Claude

每个 `assistant` 事件的 `message.usage`：

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-7",
    "usage": {
      "input_tokens": 6,
      "output_tokens": 1357,
      "cache_creation_input_tokens": 34539,
      "cache_read_input_tokens": 16087
    }
  }
}
```

per-message 增量数据 —— 跨 events sum 即可。

#### Codex

`event_msg.token_count.payload.info.total_token_usage`：

```json
{
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": {
        "input_tokens": 46936,
        "cached_input_tokens": 13696,
        "output_tokens": 259,
        "reasoning_output_tokens": 0
      }
    }
  }
}
```

**关键**：Codex 的 `total_token_usage` 是 session 累计 —— 同一 session 内多个 `token_count` event 报的是该 session **截止此刻的累计**，不是增量。直接 sum 会**重复计费**。

aifd 在 provider 层处理：每个 session 只 emit 最后一行 token_count（cumulative max）。聚合器只 sum。

### Schema 一致性

OpenAI 的 `input_tokens` **包含** `cached_input_tokens`。Claude 的 `input_tokens` 不含 cache。为了跨 provider 一致：

```python
# Codex provider
fresh_input = max(total_input - cached, 0)
```

这样 aifd 内部模型 `TokenUsage.input_tokens` 在两边都是"fresh input"语义。没这步会双重计费 cached tokens 在 full input rate。

### 价格表

`aifd/vault/prices.py` 是 hard-coded 表，顶部 `LAST_UPDATED` 是上次校准日期。CLI 每次输出底部显示这日期，提醒用户去 vendor 页核对。

格式：per 1M tokens, USD。每个 model 5 个单价：
- `input` 新输入
- `output` 输出
- `cache_write` cache 写
- `cache_read` cache 读
- `reasoning` reasoning token（Codex / o-family，按 output 计）

未知 model 计 $0 但 token 数照样出现在报告里 —— 让用户看到 "model X 没在表里" 然后去 update。

### 真实数据校准

我这台机器扫出来：

| Provider | 总花费 | events | 主力 model |
|---|---|---|---|
| claude | $6,224 | 8684 | opus-4-7 ($5933) |
| codex | $1,856 | 119 | gpt-5.5 ($1854) |
| **总计** | **$8,080** | | |

按项目 top 3：aifd $1638 / laipeini $1525 / ocrserver $886.

---

## 数据流总图

```
              user 跑 aifd vault scan/cost
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
         scan command                  cost command
              │                           │
              │                  PROVIDERS.list_token_usage(None)
              │                           │
   scan_paths([~/.claude/projects,        │
               ~/.codex/sessions,         │
               ~/.codex/archived])        │
              │                           │
   scan_file(path) for each *.jsonl       │
              │                           │
   _scan_line (regex + entropy)           │
              │                           │
              ▼                           ▼
   list[SensitiveMatch]            Iterable[TokenUsage]
                                          │
                                          ▼
                              aggregate_cost(group_by)
                                          │
                                          ▼
                                  list[CostRow]
                                  (sorted by $)
                                          │
              ┌───────────────────────────┘
              ▼                           ▼
       render_scan_matches         render_cost_rows
              │                           │
          ┌───┴───┐                   ┌───┴───┐
          ▼       ▼                   ▼       ▼
      Table     JSON                Table   JSON
   (color-      (redacted          (color- (numeric
    coded)      snippet            coded   fields)
                 only)              col)
```

## v0.5+ 演进

按 v0.4 CEO plan：

| Command | 描述 | 触发条件 |
|---|---|---|
| `aifd vault export --output path.zip` | 全量备份 + manifest.json | 用户报告"想备份" |
| `aifd vault sync` | 多机同步（先 export-import 简单版） | export 出后 + 用户跨机 |
| `aifd vault redact session-id --pattern X` | 选择性删除 | 找到泄露后清理 |
| `aifd vault encrypt --key /path` | 本地加密存档 | 隐私要求升级 |

完整方向决策在 `~/.gstack/projects/aifd/ceo-plans/2026-06-04-vault-direction.md`。

---

## 隐私 / 安全保证

| 项 | 保证 |
|---|---|
| 完整 secret 值不存内存超 scan 函数生命周期 | ✓ `SensitiveMatch.snippet_redacted` 只有头尾 4 字符 |
| 完整 secret 值不进 JSON 输出 | ✓ Test `test_vault_scan_explicit_root` 验证 |
| 不发任何网络请求 | ✓ aifd 是纯本地工具，无 HTTP client 依赖 |
| 不修改任何 provider 文件 | ✓ vault scan 是 read-only |
| 价格表本地，不查 vendor API | ✓ `aifd/vault/prices.py` 静态表 |

`aifd vault scan` 默认输出可以**直接 paste 给同事** debug —— redact 已经处理。
