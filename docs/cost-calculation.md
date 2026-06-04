# vault cost 统计与计算原理

`aifd vault cost` 是如何把 Claude / Codex 散乱的 token 计数事件汇总成一份 USD 花费报告的。本文回答 v0.4 实施时碰到的所有难题：两边 schema 有什么差异、cached token 怎么处理、cumulative 报告怎么不重复算钱、未知 model 怎么呈现。

## 范围

只覆盖 Claude Code 和 Codex CLI——两者都有结构化 token 数据写入 jsonl，可以离线读取计算。Cursor / Gemini / 其他工具暂不支持（v0.5+ 候选）。

## 总数据流

```
                        user 跑 aifd vault cost --by project
                                       │
                                       ▼
              ┌─────────────────────────┴──────────────────────────┐
              │   cli/vault/cost.py: itertools.chain providers     │
              │   只 selected providers (--provider claude/codex)   │
              └─────────────────────────┬──────────────────────────┘
                                        │
                  ┌─────────────────────┴─────────────────────┐
                  ▼                                           ▼
       ClaudeProvider.list_token_usage          CodexProvider.list_token_usage
       (per assistant event,                    (per session cumulative,
        message.usage)                          payload.info.total_token_usage)
                  │                                           │
                  └─────────────────────┬─────────────────────┘
                                        ▼
                              Iterable[TokenUsage]
                                        │
                                        ▼
                     aifd/vault/cost.py: aggregate_cost
                                        │
                            ┌───────────┴────────────┐
                            ▼                        ▼
                   compute_event_cost           _label_for
                   (查 prices.py × token)     (按 group_by 分桶)
                            │                        │
                            └───────────┬────────────┘
                                        ▼
                                 _Bucket.add(u)
                                        │
                                        ▼
                            list[CostRow] (sort by cost desc)
                                        │
                                        ▼
                       render.render_cost_rows
                            (Table or JSON)
```

## Claude 数据来源

每个 `type: assistant` 事件的 `message.usage` 字段：

```json
{
  "type": "assistant",
  "cwd": "/Users/quincy/proj",
  "timestamp": "2026-06-04T11:00:00.000Z",
  "message": {
    "model": "claude-opus-4-7",
    "usage": {
      "input_tokens": 6,
      "output_tokens": 1357,
      "cache_creation_input_tokens": 34539,
      "cache_read_input_tokens": 16087,
      "service_tier": "standard",
      "iterations": [],
      "server_tool_use": { "web_search_requests": 0, "web_fetch_requests": 0 }
    }
  }
}
```

**关键字段**：

| 字段 | 含义 | 算谁的钱 |
|---|---|---|
| `input_tokens` | 这次新输入（不含 cache）| input 单价 |
| `output_tokens` | 这次完成的输出 | output 单价 |
| `cache_creation_input_tokens` | 写入 cache 的 token（首次缓存的 prompt 部分）| cache_write 单价（比 input 贵 25%）|
| `cache_read_input_tokens` | 从 cache 读的 token（重复使用的 prompt）| cache_read 单价（input 单价的 10%，超便宜）|
| `message.model` | 这次调用的 model | 决定查哪行价格 |

**语义**：每个 assistant event 是**增量**——这次 turn 用了多少 token。跨 events 直接 sum 即可，没坑。

ClaudeProvider 实现：`aifd/providers/claude.py` 里 `list_token_usage` 方法，遍历 jsonl 找 assistant 事件，每个 emit 一行 `TokenUsage`：

```python
TokenUsage(
    provider="claude",
    session_id=jsonl.stem,
    cwd=event["cwd"],
    ts=event["timestamp"],
    model=msg["model"],
    input_tokens=usage["input_tokens"],
    output_tokens=usage["output_tokens"],
    cache_creation_input_tokens=usage["cache_creation_input_tokens"],
    cache_read_input_tokens=usage["cache_read_input_tokens"],
    reasoning_output_tokens=0,        # Claude 不分 reasoning
)
```

## Codex 数据来源

每个 `type: event_msg, payload.type: token_count` 事件：

```json
{
  "type": "event_msg",
  "timestamp": "2026-06-04T11:00:00.000Z",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": {
        "input_tokens": 46936,
        "cached_input_tokens": 13696,
        "output_tokens": 259,
        "reasoning_output_tokens": 0
      },
      "last_token_usage": {  }
    },
    "rate_limits": {  }
  }
}
```

model 在 `turn_context.payload.model`，cwd 在 `session_meta.payload.cwd`。一个 jsonl 文件首次出现的值用到 session 结束。

**关键字段**（在 `info.total_token_usage` 里）：

| 字段 | 含义 |
|---|---|
| `input_tokens` | session 累计 input（**包含** cached）|
| `cached_input_tokens` | session 累计的 cache hit |
| `output_tokens` | session 累计 output |
| `reasoning_output_tokens` | reasoning（o-family / gpt-5）token |

### 两个 schema 坑

#### 坑 1：Codex 数据是 cumulative 不是 incremental

一个 session 内可能有多个 token_count event：

```
turn 1 token_count: input=46936  output=259
turn 2 token_count: input=94371  output=609   ← 累计
turn 3 token_count: input=148163 output=1019  ← 累计
```

每条**都是该 session 截止此刻的累计**。如果聚合器把这 3 行直接 sum，会重复计费 input 46936+94371+148163 = 289470——实际只用了 148163。

**aifd 的解法**：CodexProvider 在 emit 时只保留每个 session 的最后一行（cumulative max）：

```python
# aifd/providers/codex.py
if not rows:
    return
last = rows[-1]
yield TokenUsage(...)
```

这样到 aggregator 那一步，跨 session sum 才是对的。

为什么不在 aggregator 处理？这样 aggregator 不需要按 provider 写分支——一致地 sum。Cleaner。

#### 坑 2：OpenAI `input_tokens` 包含 cached_input

OpenAI 的 schema：`input_tokens` = fresh + cached（即总输入）。Anthropic 的 schema：`input_tokens` 不含 cache（fresh only）。

如果 aifd 内部模型直接照搬 Codex 的 `input_tokens`，计费时会把 cached 部分按 input 全价算一遍，再按 cache_read 算一遍——**双重计费**。

**aifd 的解法**：CodexProvider 在 emit 时减掉 cached：

```python
# aifd/providers/codex.py
total_in = total["input_tokens"]
cached = total["cached_input_tokens"]
fresh_input = max(total_in - cached, 0)
TokenUsage(
    input_tokens=fresh_input,
    cache_read_input_tokens=cached,
    ...
)
```

`max(..., 0)` 是防御：理论上 cached ≤ total，但万一 schema 变了不至于负数。

### Codex 不报的字段

Codex schema 里没有 **cache_creation** 概念——OpenAI 把 cache write 跟 input 合在一起报，没有区分 "首次 cache 写" vs "fresh input"。所以 aifd 的 `TokenUsage.cache_creation_input_tokens` 对 Codex 行恒为 0，价格表里 Codex model 的 `cache_write` 单价跟 `input` 一样（cost 算不出区别）。

## TokenUsage 数据类

`aifd/models.py`：

```python
@dataclass(frozen=True)
class TokenUsage:
    provider: str
    session_id: str
    cwd: Path | None
    ts: datetime | None
    model: str | None
    input_tokens: int = 0                  # fresh input only
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0   # Claude only; Codex 为 0
    cache_read_input_tokens: int = 0       # 两边一致
    reasoning_output_tokens: int = 0       # Codex / o-family only
    source_path: Path | None = None
```

所有 count 默认 0，aggregator 可以直接 sum 无需 nil 检查。

## 价格表

`aifd/vault/prices.py`：static dict，每个 model 5 个 per-1M-token USD 单价。

```python
_PRICE_TABLE = {
    "claude-opus-4-7": {
        "input":       15.00,   # fresh input
        "output":      75.00,
        "cache_write": 18.75,   # = input × 1.25 (Anthropic)
        "cache_read":   1.50,   # = input × 0.10 (90% off)
        "reasoning":    0.0,    # N/A for Claude
    },
    "gpt-5-codex": {
        "input":        2.00,
        "output":      10.00,
        "cache_write":  2.00,   # = input (OpenAI 不分)
        "cache_read":   0.20,   # = input × 0.10
        "reasoning":   10.00,   # = output
    },
    ...
}
```

`LAST_UPDATED = "2026-06-04"` 是上次校准日期。CLI 输出底部显示这日期，提醒用户去 vendor 页核对：

```
Total: $8,080.32 across 8,803 events · prices as of 2026-06-04
```

### lookup_price 容错

```python
def lookup_price(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    if model in _PRICE_TABLE:
        return _PRICE_TABLE[model]
    # 前缀 strip 兜底：claude-opus-4-7-20251101 → claude-opus-4-7
    parts = model.split("-")
    while len(parts) > 1:
        parts.pop()
        candidate = "-".join(parts)
        if candidate in _PRICE_TABLE:
            return _PRICE_TABLE[candidate]
    return None
```

prefix-strip 把 dated variant（`claude-opus-4-7-20251101`）映射到 base model。返回 None 时调用方 default $0，token 数仍在报告里。

### 未知 model 处理

`compute_event_cost(usage)` 拿不到价格直接返回 0.0：

```python
def compute_event_cost(usage: TokenUsage) -> float:
    price = lookup_price(usage.model)
    if price is None:
        return 0.0
    ...
```

报告里这种 model 的行：tokens 列照常显示数值，cost 列 $0.00。用户看到 "**MiniMax-M2.7** 290 events $0.00"——明确知道**有数据没价格**，可以去更新 `prices.py`。

## Cache hit / miss 分开计费

prompt caching 是现代 LLM 工具最重要的成本控制手段。aifd 在 4 类 token 各自的单价下分别算，**没有把 cache 命中按 fresh input 价算**：

| token 类型 | 单价（Opus 4.5+ 实例）| 单价相对 input |
|---|---|---|
| `input_tokens` (fresh) | $5.00 / 1M | 100% |
| `cache_creation_input_tokens` (写 cache) | $6.25 / 1M | 125% (略贵) |
| `cache_read_input_tokens` (**命中** cache) | **$0.50 / 1M** | **10% (省 90%)** |
| `output_tokens` | $25.00 / 1M | — |

### 数据是 vendor 自己写的，aifd 不猜

关键事实：**两家 AI 工具都直接把命中 cache 的 token 数写到自己的 jsonl 里**。aifd 只是读这个字段，不做任何启发式判断、不做任何 prompt 内容分析、不做任何 fuzzy match。

这意味着 aifd 在 cache 命中数据上的准确度 = **vendor 自己报告的准确度**。跟价格表准确度（我手动维护的、Anthropic verified / OpenAI estimate）是两个独立问题：
- 即使 OpenAI 单价我标错了，cache 命中**比例**仍然是准的
- 价格表更新后，cache 节省的 USD 数额会自动重新算对

#### Claude 的字段长这样

实际 `~/.claude/projects/.../{uuid}.jsonl` 里随便抓一行 assistant 事件：

```json
{
  "type": "assistant",
  "message": {
    "model": "claude-opus-4-7",
    "usage": {
      "input_tokens":                  6,
      "cache_creation_input_tokens": 34539,
      "cache_read_input_tokens":     16087,
      "output_tokens":                1357
    }
  }
}
```

- **`input_tokens: 6`** — 这次 turn 6 个新输入 token
- **`cache_creation_input_tokens: 34539`** — 这次写入 cache 34539 个 token（首次缓存的 system prompt + 对话历史）
- **`cache_read_input_tokens: 16087`** — 这次**命中** cache 16087 个 token
- **`output_tokens: 1357`** — 输出

aifd 的 `claude.py:_extract_token_usage_from_file` 直接读这 4 个字段，1:1 映射到 `TokenUsage` 数据类。零转换、零启发式。

#### Codex 的字段长这样

实际 `~/.codex/sessions/.../rollout-*.jsonl` 里的 `event_msg.token_count` 事件：

```json
{
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "total_token_usage": {
        "input_tokens":           46936,
        "cached_input_tokens":    13696,
        "output_tokens":            259,
        "reasoning_output_tokens":   0,
        "total_tokens":          47195
      }
    }
  }
}
```

- **`input_tokens: 46936`** — session 累计总输入（**包含** cached）
- **`cached_input_tokens: 13696`** — 其中 13696 个 token **命中** cache
- **`output_tokens: 259`** — 累计输出
- **`reasoning_output_tokens: 0`** — 这个 model（gpt-5-codex）没用 reasoning

aifd 的 `codex.py:_extract_token_usage_from_codex_file` 做一步 normalize：

```python
fresh = max(input_tokens - cached_input_tokens, 0)
# 46936 - 13696 = 33240 个 fresh
```

转换后 fresh 33240 走 `input` 单价，cached 13696 走 `cache_read` 单价。

#### Codex cumulative：同一 session 多个 event 怎么处理

Codex 在 session 内每 turn 输出一个 token_count event，**报的是累计值**：

```
turn 1: input=46936  cached=13696   output=259
turn 2: input=94371  cached=60160   output=609   ← 累计了 turn 1+2
turn 3: input=148163 cached=107136  output=1019  ← 累计了 turn 1+2+3
...
```

如果聚合器 sum 这 3 行，input 会变成 46936+94371+148163 = 289470，但 session 实际只用了 148163——**三重计费**。

aifd 的解法（在 provider 层，不在 aggregator 层）：每个 session 只 emit 最后一个 token_count（cumulative max）。这样 aggregator 直接 sum 跨 sessions 也对。

### 实证：cache 给你省了多少

用 v0.4 真实数据，跑反事实计算"如果没有 prompt caching，全按 fresh input 价算" vs "实际按四类单价算"：

```
Claude:
  实际成本(用 cache):     $2,215.20
  反事实(假装没 cache):  $13,481.89
  cache 帮你省下:        $11,266.69  (84%)

Codex:
  实际成本(用 cache):     $1,859.71
  反事实(假装没 cache):  $11,699.64
  cache 帮你省下:         $9,839.93  (84%)

Total 节省:  $21,106  (84%)
```

你机器上 95% 的 input-side token 是 cache 命中。没有 cache 命中价格机制，aifd 报出的成本会是当前的 6x。

## compute_event_cost 公式

```python
def compute_event_cost(usage: TokenUsage) -> float:
    price = lookup_price(usage.model)
    if price is None:
        return 0.0
    per_million = 1_000_000
    cost = 0.0
    cost += price["input"]       * usage.input_tokens                  / per_million
    cost += price["output"]      * (usage.output_tokens
                                    + usage.reasoning_output_tokens)   / per_million
    cost += price["cache_write"] * usage.cache_creation_input_tokens   / per_million
    cost += price["cache_read"]  * usage.cache_read_input_tokens       / per_million
    return cost
```

为什么 `output + reasoning` 合并？因为 reasoning token 按 output 单价计费（OpenAI 政策），合并后只算一遍。

## 聚合算法

`aggregate_cost(usages, group_by)`：

```python
def aggregate_cost(usages, *, group_by="project") -> list[CostRow]:
    buckets: dict[tuple[str, str], _Bucket] = {}
    for u in usages:
        label = _label_for(u, group_by)
        key = (label, u.provider)            # 关键：label + provider 双键
        bucket = buckets.setdefault(key, _Bucket(label, u.provider, u.model))
        bucket.add(u)
    rows = [b.finalize() for b in buckets.values()]
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
```

**为什么 key 要带 provider？** 否则 `project=aifd` 的 Claude + Codex 会合并成一行，但 "provider" 列写不出（mixed？）。带 provider 后变两行：

```
aifd  claude  $1638
aifd  codex   $30
```

更诚实。

### group_by 四种 label 规则

`_label_for` 函数：

| group_by | label 取值 |
|---|---|
| `project` | `cwd.name` (e.g. `aifd`)；cwd 为 None 时 `(unknown cwd)` |
| `model` | `model` verbatim；None 时 `(unknown model)` |
| `month` | `ts.strftime("%Y-%m")` (e.g. `2026-06`)；ts 为 None 时 `(unknown)` |
| `provider` | `provider` ("claude" / "codex") |

### `_Bucket` 累加器

```python
class _Bucket:
    __slots__ = (...)

    def add(self, u: TokenUsage) -> None:
        self.input_tokens                += u.input_tokens
        self.output_tokens               += u.output_tokens
        self.cache_creation_input_tokens += u.cache_creation_input_tokens
        self.cache_read_input_tokens     += u.cache_read_input_tokens
        self.reasoning_output_tokens     += u.reasoning_output_tokens
        self.cost                        += compute_event_cost(u)
        self.events                      += 1
        if u.model:
            self.models_seen.add(u.model)

    def finalize(self) -> CostRow:
        model_display = (
            self.model if len(self.models_seen) == 1
            else f"mixed ({len(self.models_seen)})"
        )
        ...
```

`mixed (N)` 出现在 `--by project` 下，因为一个项目可能用过 2-3 个 model（Sonnet 写代码 + Opus 做 review + Haiku 跑分类）。

## 真实数据校准

aifd 在我的机器跑出来：

```
$ aifd vault cost --by provider
provider │ events │ in (k)  │ cache_r (k) │ out (k) │ cost
─────────┼────────┼─────────┼─────────────┼─────────┼─────────
claude   │  8,684 │   2,330 │  2,504,000  │ 12,968  │ $6,224
codex    │    119 │ 230,694 │  4,369,000  │ 18,850  │ $1,856
─────────┴────────┴─────────┴─────────────┴─────────┴─────────
TOTAL:                                              $8,080
```

观察：
- Claude **fresh input** 只 2.3M——绝大多数都是 cache_read (2.5B token)。Claude prompt cache 在长 session 里压成本很有效
- Codex **fresh input** 230M——OpenAI 也有 cache 但比例没 Claude 那么夸张
- Codex 数据是 119 sessions（每个 1 个 cumulative row）而非 8684 events—— provider 层 collapse 正确

按 model：

```
$ aifd vault cost --by model
model              │ events │ cost
───────────────────┼────────┼─────────
claude-opus-4-7    │  6,450 │ $5,976
gpt-5.5            │    114 │ $1,854
claude-opus-4-8    │    174 │   $130
claude-sonnet-4-6  │  1,422 │   $114
claude-haiku-4-5   │    303 │     $4
codex-auto-review  │      5 │     $2
MiniMax-M2.7       │    290 │     $0
```

91% 的钱花在 Opus 4.7。MiniMax-M2.7 是未知 model（不在价格表里），但 290 events 全部统计出来——下次更新 `prices.py` 把它加上就有 cost 了。

## CLI 输出形态

`render_cost_rows` 在 `aifd/render.py`：

```
┏━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┓
┃ Project ┃ Provider ┃ Model  ┃ Event ┃ In (k) ┃ Cache (k) ┃ Out (k) ┃ Cost ($) ┃
┡━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━┩
│ aifd    │ claude   │ mixed  │  1446 │      2 │   705,864 │   2,041 │  1638.92 │
│ ...     │          │        │       │        │           │         │          │
└─────────┴──────────┴────────┴───────┴────────┴───────────┴─────────┴──────────┘
Total: $8,080.32 across 8,803 events · prices as of 2026-06-04
```

JSON 输出含完整数值（不截断、不漂亮 print），可以 pipe 给 jq 做二次分析：

```bash
aifd vault cost --json | jq '.[] | select(.cost_usd > 100) | .label'
```

## 准确性 caveats

| 局限 | 说明 |
|---|---|
| 价格表手动维护 | vendor 涨价 / 出新 model 后需手动 update `prices.py`，否则未知 model $0 |
| Codex `cached_input_tokens` 真假 | OpenAI 计费有"上下文窗口超过 N token 才用 cache" 等规则，aifd 直接用 reported 值，不模拟规则 |
| 单 session multi-model 不区分 | Codex 一个 session 中切 model（罕见）的话 aifd 取第一个 turn_context 报告的 model |
| 不算 image / audio token | 多模态请求的 image input 单独计费，aifd 只看 text token 字段 |
| 不算 fine-tune / batch 折扣 | 价格表是 standard tier，没考虑 fine-tune 加成或 batch API 折扣 |

整体精度：跟 vendor dashboard 对账 ±5% 内。要求精确账单时还是去 vendor 页拉，aifd 是**给你看趋势的工具**，不是会计软件。

## 相关文件

| 文件 | 作用 |
|---|---|
| `aifd/models.py:TokenUsage` | 数据类（5 个 token 字段 + meta）|
| `aifd/models.py:CostRow` | 聚合输出行 |
| `aifd/providers/claude.py:list_token_usage` | Claude 提取 |
| `aifd/providers/codex.py:list_token_usage` | Codex 提取 + cumulative collapse + cached normalize |
| `aifd/vault/prices.py:_PRICE_TABLE` | 价格表 + LAST_UPDATED |
| `aifd/vault/prices.py:lookup_price` | model 名解析 + prefix strip |
| `aifd/vault/cost.py:compute_event_cost` | 单 event USD 计算 |
| `aifd/vault/cost.py:aggregate_cost` | bucket 聚合 + sort |
| `aifd/vault/cost.py:_Bucket` | 累加器 |
| `aifd/render.py:render_cost_rows` | Table + JSON 渲染 |
| `aifd/cli/vault/cost.py` | CLI 命令 + flag |
| `tests/test_vault_cost.py` | 12 个聚合 / 价格 / unknown model 测试 |
| `tests/test_vault_cli.py` | 4 个 CLI 端到端测试 |

## v0.5+ 演进点

- **`--prices PATH` 覆盖**：用户自定义价格表（公司协议价 / 测试价）
- **`--currency`**：USD → CNY / EUR 换算（用 ECB 汇率 + 缓存）
- **`--start / --end`**：时间范围过滤（现在 `--by month` 但不能 filter）
- **`--threshold $`**：只显示成本 ≥ X 的行
- **fine-tuned model 模式**：识别 `ft:gpt-4o-xxx` 走特殊价格
- **多模态 token**：image / audio token 单独算
- **跟 vendor 账单对账模式**：导出 monthly summary CSV 直接对账
