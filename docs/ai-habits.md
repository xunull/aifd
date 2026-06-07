# `aifd ai habits` — 长期 AI 行为人格画像

Shipped in **v0.9.0**.

`aifd ai reflect` 回答「这周怎么样」；**`aifd ai habits` 回答「我是什么类型的
AI 用户」**。它分析 60-90 天的 session 数据，让 LLM 识别你**自己没意识到**的
行为模式，并附具体数字证据。

```
$ aifd ai habits
═══ 你的 AI 行为人格 (90 天画像) ═══

模式 1「周五放松崩」
你周五的 vibe-coding 比率是工作日均值的 2.4x。
周五 session 平均 7 条事件，工作日平均 38 条。
  → 建议：周五下午 5 点后不要开新的 plan review。

模式 2「深夜决策次日后悔」
22 点后开始的 session 仅 33% 在 24 小时内 ship。
早晨 session 的 ship 转化率 91%。
  → 建议：复杂架构决策推到次日早晨，深夜只做 quick task。

模式 3「过度规划型」
36% 的 office-hours session 没有对应的 ship。
平均每 4.2 次 office-hours 才 ship 1 次。
  → 建议：office-hours 结束时强制定一个 deadline。

prompt_version: v1
```

跟 `aifd ai reflect` 的关系：

| | `aifd ai reflect` | `aifd ai habits` |
|---|---|---|
| 定位 | 周期性回顾 | 长期人格画像 |
| 时间窗口 | 7-30 天 | 60-90 天 |
| 运行频率 | 每周 | 每季度或按需 |
| 输出 | essay + wins + anti-pattern + action | patterns 数组（name + evidence + suggestion）|
| LLM 任务 | 写反思 | 命名模式 |

---

## Commands

```bash
aifd ai habits                              # 默认 90 天
aifd ai habits --since 60d                  # 自定义窗口（按天）
aifd ai habits --since 2026-01-01           # 自定义起点
aifd ai habits --lang en --json             # 英文 JSON 输出
aifd ai habits --model zhipu/glm-4-plus     # 换 LLM provider
aifd ai habits --api-base http://127.0.0.1:11434/v1 --model ollama/qwen2.5
aifd ai habits -v                           # verbose: 显示 timing breakdown
```

---

## 8 个长期行为维度

| 维度 | 数据来源 | 揭示什么 |
|---|---|---|
| **星期分布** | Session.started_at + event_count | 周几最 productive / 最放松崩 |
| **时段分布（2h 粒度）** | Session.started_at | 哪个具体时段是 peak（比 reflect 的 6h 桶更细）|
| **session 双峰** | Session.event_count | 你有几种工作模式（quick check vs deep work）|
| **项目切换频率** | Session.cwd + started_at | 每日跨项目数量的中位数（专注度 vs 散）|
| **ship 间隔** | SkillEvent(skill=ship) | 节奏感（中位数天数）|
| **深夜 ship 率** | Session + SkillEvent | 22 点后 session 在 24 小时内有 ship 的比例 |
| **过度规划率** | SkillEvent(skill=office-hours / ship) | office-hours 后没 ship 的比例（分析瘫痪）|
| **skill 重复率** | SkillEvent | top skill 占比（专注 vs 尝新）|

每个维度独立 None-safe：数据不足时 prompt 显示 `(no data)`，LLM 被指示**跳过
不要编造**。

---

## Privacy

跟 `aifd ai reflect` 共享相同的 D6 invariant：

- **永远不发**：原始问题文本、session 内容、cwd 完整路径、secrets / API keys
- **会发**：聚合数字、比率、basename、ISO 日期
- 测试通过 v0.4 `_DETECTORS` 全套扫 prompt rendering 输出，**任何
  SensitiveMatch = test fail**

---

## Multi-vendor LLM

`habits` 完全复用 v0.8 的 LiteLLM 路由层。任何 LiteLLM 支持的 100+ provider
都能用：

```bash
aifd ai habits --model deepseek/deepseek-chat   # 默认
aifd ai habits --model zhipu/glm-4-plus
aifd ai habits --model dashscope/qwen-plus
aifd ai habits --model ark/<endpoint_id>        # 火山引擎方舟
aifd ai habits --model anthropic/claude-sonnet-4
aifd ai habits --model openai/gpt-4o
aifd ai habits --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
```

详细 provider 列表见 `docs/ai-reflect.md` 的 Multi-vendor 段（同一 config schema）。

---

## Config

`~/.aifd/config.yaml` 在 `llm:` / `reflect:` 段之外新增 `habits:` 段：

```yaml
llm:
  model: deepseek/deepseek-chat
  api_key: sk-...
  api_base:

reflect:
  default_lang: zh
  include_questions: false

habits:
  # 默认分析窗口（天）。--since 可临时覆盖。
  default_days: 90
```

`AIFD_LLM_*` env vars 同样适用。

---

## Failure modes / fallback

| 情况 | 行为 |
|---|---|
| 没 API key | fallback 到本地结构化输出（空 patterns 数组 + `_fallback_reason`）|
| 90 天内 sessions 为空 | compute_* 返回 None → prompt 显示 `(no data)` |
| GstackDataSource 读不到 | NullSource fallback（继承自 v0.8）|
| LLM auth / 5xx / timeout | LiteLLM retry 1 次后 fallback，**不 crash**|
| LLM 返回非 JSON / 错 schema | LLMResponseError → fallback |
| sessions 量大（>1000）| materialize 一次后所有 compute_* 是 O(n)，内存可控 |

---

## 相关文件

| 文件 | 作用 |
|---|---|
| `aifd/insights/habits.py` | 8 个 compute_habit_* + HabitsInput dataclass + collect_habits_data |
| `aifd/insights/habits_prompt.py` | PROMPT_VERSION + en/zh prompt 模板 |
| `aifd/cli/ai/habits.py` | `aifd ai habits` click command + fallback wiring |
| `aifd/render.py:render_habits_*` | text / json 渲染 |
| `aifd/config.py:HabitsConfig` | habits 配置 dataclass |
| `tests/test_insights_habits.py` | 25 个 compute_* + orchestrator 测试 |
| `tests/test_insights_habits_prompt.py` | 15 个 prompt + ★★★ privacy 测试 |
| `tests/test_cli_ai_habits.py` | 12 个 CLI integration 测试 |
| `tests/test_render_habits.py` | 9 个 render 测试 |

---

## Future roadmap (v0.10+)

| Feature | Why deferred |
|---|---|
| Git 集成 / revert 追踪 | D1 决策：v0.9 用 SkillEvent ship 已够；先 ship 看反馈 |
| habits 历史对比（this quarter vs last quarter） | 需要 habits 输出持久化 store |
| `aifd config set habits.default_days N` | 复用 v0.8.x 已 deferred 的 aifd config 子命令 |
