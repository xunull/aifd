# `aifd ai reflect` — meta-cognitive AI coach

Shipped in **v0.8.0**.

aifd 之前是「查 / 扫 / 盯 / 推」 —— 都是事后工具。**`aifd ai reflect` 是反过来**：
每周一行命令，aifd 看你怎么用 AI，让 LLM 写一段 80-150 字的 reflection。

```
$ aifd ai reflect --week
═══ Your week with AI · 2026-05-30 → 2026-06-05 ═══

上周你在 v0.7 events store 上做了 23 次 session、花 $284，比上上周升 38%。
ship 了 7 个 commit 但其中 5 次有 plan-eng-review 前置 —— 这是 plan-then-
ship 的成熟模式，比起 4 月份的 vibe-coding 多了一截理性。compliance ratio
87% 偏高，AskUserQuestion 时你 87% 都跟推荐 —— 这是 calibration 好还是判断
懒？花两次刻意挑 B 选项试试。最值得说的 anti-pattern：周二凌晨你跑了 8 次
office-hours 但都没 ship，焦虑型 brainstorm。

  🏆 Wins
    · v0.7 events store + webhooks + web UI 一气呵成 ship (137 tests)
    · plan-eng-review 引入后 ship 前 P1 issue 0 个
    · DeepSeek over Claude 是清醒的 vendor 判断

  ⚠ Anti-pattern
    · 凌晨 office-hours 群发症（5+ session 但 0 commit）

  → 下周试一次: 当 D1 的 recommended 看起来"明显对"时，强制选 B 一次
```

成本 ~$0.001/run（DeepSeek）。复制不到一分钱。

---

## Quick start

```bash
# 1. 注册 DeepSeek 拿 API key — https://platform.deepseek.com/api_keys
export DEEPSEEK_API_KEY=sk-xxxxxxxxx

# 2. 立刻跑
aifd ai reflect --week

# 3. 或先生成 config 模板，编辑里头加 key
aifd ai reflect    # 第一次 run 自动生成 ~/.aifd/config.yaml
$EDITOR ~/.aifd/config.yaml
```

---

## Commands

```bash
aifd ai reflect                                # 默认 --week，zh
aifd ai reflect --month                        # 30 天回顾
aifd ai reflect --since 2026-06-01             # 自定义起点（local tz）
aifd ai reflect --since 2026-06-01 --until 2026-06-07
aifd ai reflect --lang en                      # 英文输出
aifd ai reflect --include-questions            # 把 question summary 喂 LLM（默认不喂）
aifd ai reflect --json                         # pipe-friendly
aifd ai reflect -v                             # verbose: 显示 timing breakdown
aifd ai reflect --model zhipu/glm-4-plus       # 换 LLM（LiteLLM provider/model 格式）
aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
```

---

## 9 个反思维度

aifd 看的是什么：

| 维度 | 数据源 | 维度计算 |
|---|---|---|
| **Activity** | v0.5 `summarize_activity` | sessions / cost / tokens / by-provider |
| **Compliance ratio** | gstack `question-log.jsonl` | (user_choice == recommended) / total |
| **Skill diversity** | gstack `timeline.jsonl` | distinct skills / total invocations |
| **Cost trend** | v0.4 TokenUsage | this period $ vs prev period $ ratio |
| **Timing distribution** | session.started_at | 4 buckets (0-6 / 6-12 / 12-18 / 18-24 local hour) |
| **Project focus** | session.cwd | top-1 cwd basename + its share |
| **Plan-then-ship** | timeline.jsonl | ship preceded by plan-eng-review within 7 days |
| **Vibe-coding score** | sessions + ship events | ship after <5 msg session = vibe |
| **Wins** | review_log + ship completions | top 3 clean outcomes |

**缺失数据 = "(no data)"**。比如没装 gstack 的用户 compliance / plan-then-ship
直接没数据，prompt 里 placeholder 写明，LLM 跳过那一面不编造。

---

## Privacy

**默认模式发送给 LLM 的内容**（aggregate only）：

```
- period: 2026-05-30 → 2026-06-05
- sessions: 23, cost: $284.00, tokens: 420000
- compliance_ratio: 87% (13 of 15 questions)
- skill_diversity: 40% (distinct / total invocations)
- cost_trend: +38% vs prev period
- timing_distribution: 0-6h: 2 sess (avg 8 msg), ...
- top_project: aifd (70% of sessions)
- plan_then_ship: 71% of ships had plan-eng-review prior
- vibe_coding_score: 14% of ships had <5 msg session
- top_wins: 2026-06-05:ship; 2026-06-04:plan-eng-review; 2026-06-03:ship
```

**永远不发**：
- AskUserQuestion 原文 / 答案文本
- Session message 内容
- cwd 完整路径（只发 basename — privacy invariant by detector scan）
- secrets / API keys（v0.4 detector 兜底校验）

**opt-in** `--include-questions` 时会发送 question summary，但仍**不**发原文。

测试通过 v0.4 `_DETECTORS` 全套扫 prompt rendering 输出，**任何 SensitiveMatch
= test fail**（D6 invariant）。

---

## Multi-vendor LLM — LiteLLM under the hood

`aifd ai reflect` 把所有 LLM 调用走 **LiteLLM**（100+ provider 统一 OpenAI-format
路由层）。这意味着你能用任何 LiteLLM 支持的 provider，**aifd 不绑死任何一家**。

### 推荐 provider 与 model string

```bash
# DeepSeek (default — 中文质量好，$0.27/M input)
aifd ai reflect --model deepseek/deepseek-chat
export DEEPSEEK_API_KEY=sk-...

# 智谱 GLM
aifd ai reflect --model zhipu/glm-4-plus
export ZHIPUAI_API_KEY=...

# 阿里通义千问 (DashScope)
aifd ai reflect --model dashscope/qwen-plus
export DASHSCOPE_API_KEY=...

# 火山引擎方舟（用 inference endpoint id 不是模型名）
aifd ai reflect --model ark/ep-xxxxx
export ARK_API_KEY=...

# Moonshot Kimi
aifd ai reflect --model moonshot/moonshot-v1-32k
export MOONSHOT_API_KEY=...

# Anthropic Claude
aifd ai reflect --model anthropic/claude-sonnet-4
export ANTHROPIC_API_KEY=...

# OpenAI
aifd ai reflect --model openai/gpt-4o
export OPENAI_API_KEY=...

# 本地 ollama
aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1

# 自托管 vLLM
aifd ai reflect --model openai/qwen2.5 --api-base https://vllm.internal/v1

# Groq / Together / Fireworks — 都是 LiteLLM 一行支持
```

完整 provider 列表见 [LiteLLM docs](https://docs.litellm.ai/docs/providers)。

### Config 三种方式（precedence 从高到低）

```bash
# 1. AIFD_LLM_* env vars (跨 provider 通用)
export AIFD_LLM_API_KEY=sk-...
export AIFD_LLM_MODEL=zhipu/glm-4-plus
export AIFD_LLM_API_BASE=https://...   # optional

# 2. provider 原生 env vars (LiteLLM 自动认)
export ZHIPUAI_API_KEY=...
export DASHSCOPE_API_KEY=...
# ...

# 3. ~/.aifd/config.yaml
llm:
  model: zhipu/glm-4-plus
  api_key: ...
  api_base:        # 留空走 provider 默认

# 4. 单次跑用 CLI flag
aifd ai reflect --model dashscope/qwen-plus --api-base https://...
```

**Note**: v0.8 pre-release 已有 `DEEPSEEK_API_KEY` 的用户**不需要改**，仍然有效。

---

## Failure modes / fallback

| 情况 | 行为 |
|---|---|
| 没 API key | 输出 "[fallback]" + 引导配置，**不**crash |
| LLM 401/403 (auth) | 不 retry，fallback 本地报告 + 清晰 error |
| LLM 400 (bad model name) | 不 retry，fallback hint 提示当前 --model 值 |
| LLM 429 (rate limit) | LiteLLM retry 1 次，fallback |
| LLM 5xx / timeout / connection | LiteLLM retry 1 次（30s budget），fallback |
| LLM 返非 JSON | fallback + log warning |
| LLM 返字段不对 | fallback + log warning |

所有 fallback 路径输出仍是合法 JSON schema（`prompt_version` / `essay` /
`wins` / `anti_pattern` / `concrete_action` / `_fallback_reason`），下游脚本
能稳定 parse。

---

## Config

`~/.aifd/config.yaml` （首次 run 时自动生成，0600 perm）:

```yaml
llm:
  model: deepseek/deepseek-chat   # LiteLLM 'provider/model' 格式
  api_key:                         # 留空让 LiteLLM 读 provider 原生 env var
  api_base:                        # 自托管 / 代理时填，否则留空

reflect:
  default_lang: zh        # 输出语言默认值
  include_questions: false  # opt-in 把 question summary 发给 LLM
```

**Env precedence**: `AIFD_LLM_*` env > 兼容旧 `DEEPSEEK_API_KEY` > config.yaml >
built-in default。CI 时显式用 env var；本地长期用 config.yaml。

---

## 与 `aifd ai today` 的关系

| 命令 | 类型 | 输出 |
|---|---|---|
| `aifd ai today` | 数据查询 (v0.5) | 表格 / JSON 结构化指标 |
| `aifd ai reflect` | LLM 反思 (v0.8) | 80-150 字 essay + wins + anti-pattern + action |

`today` 是「**我做了什么**」；`reflect` 是「**我做得怎么样、下周该改什么**」。
互补使用：周一跑一次 reflect，每天跑一次 today。

---

## 相关文件

| 文件 | 作用 |
|---|---|
| `aifd/config.py` | YAML config + env precedence + 0600 perms |
| `aifd/insights/reflection.py` | 9 个 compute_* + ReflectionInput dataclass |
| `aifd/insights/reflection_prompt.py` | en/zh prompt template + PROMPT_VERSION |
| `aifd/insights/reflection_source.py` | ReflectionDataSource Protocol + gstack impl |
| `aifd/insights/llm_client.py` | LiteLLM wrapper (100+ provider 统一接口) |
| `aifd/cli/ai/reflect.py` | `aifd ai reflect` command + fallback wiring |
| `aifd/render.py:render_reflection_*` | text/json rendering |
| `~/.aifd/config.yaml` | user config (D5: yaml like webhooks.yaml) |
| `tests/test_*reflection*.py` | 73 tests covering 9 dimensions + privacy + CLI |
| `tests/test_insights_llm_client.py` | 16 tests covering LiteLLM wrapper |
| `tests/test_litellm_live.py` | opt-in live API smoke test (D7) |

---

## Future roadmap (v0.8.x+)

| Feature | Why deferred |
|---|---|
| `aifd config set/get/list` 子命令 | v0.8.0 用 env + 编辑 yaml；CLI helper v0.8.1 |
| Daily / quarterly reflect cadence | 1 周使用 feedback 后再决定优先级 |
| 国内 provider compatibility verification | 实测 ark/zhipu/dashscope 的 tool_call + response_format 边界 |
| Streaming reflection output | LiteLLM 原生支持 stream=True；UX 决策后接 |
| HTML reflection (`--web`) | stub method 留口；v0.8.x |
| Webhook integration for reflection | 复用 v0.7 webhook deliverer + `--webhook ID` flag |
| Reflection 历史对比 | "this week vs last week" 需要持久化；v0.9+ |
