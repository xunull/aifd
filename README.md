# aifd

跨 Claude Code、Codex、（即将支持）Cursor 的 AI 编码历史浏览器。从「我的目录 / 我用过的 skill / AI 问过我什么」的视角出发，而不是每个工具各自的私有视角。

每个 AI 编码工具都把历史存在自己的私有格式里。「这个项目里我有哪些 AI session？」「我每天到底用了哪些 skill？」「上周 AI 问过我什么决定我选了什么？」——以前这些问题没有统一答案，现在 `aifd` 一行命令搞定。

## 三种视角看你的 AI 历史

**1. 按目录列 session（v0.1）**

```text
$ aifd ai session list                # 在任意项目目录里跑
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Provider ┃ Session  ┃ Started ┃ Events ┃ Title            ┃ Source           ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ claude   │ bbfc1d21 │  2h ago │    781 │ Install Claude … │ ~/.claude/p…     │
│ codex    │ 019e7d19 │  1d ago │      0 │ 审计计划完成情况 │ ~/.codex/se…     │
└──────────┴──────────┴─────────┴────────┴──────────────────┴──────────────────┘
```

**2. 复盘 AI 问过你的问题（v0.3）**

```text
$ aifd ai question list --cwd --limit 5
┏━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃    Time ┃ Project ┃ Question           ┃ Your Choice      ┃ Recommended      ┃
┡━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ 29m ago │ aifd    │ D8 — 这个 CEO plan │ A) 跑            │ A) 跑            │
│         │         │ 下一步走哪里？     │ /plan-eng-review │ /plan-eng-review │
│ 44m ago │ aifd    │ D7 — 写不写 docs?  │ A) 写            │ A) 写            │
└─────────┴─────────┴────────────────────┴──────────────────┴──────────────────┘
5 questions in /path/to/proj | recommended hit rate: 80% (4/5) | 0 unanswered
```

**3. 跨工具 skill 使用统计（v0.2）**

```text
$ aifd ai skill list                  # 默认全局；--cwd 限定当前目录
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Skill           ┃ Claude ┃ Codex ┃ Total ┃ Last Used ┃ Projects ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ plan-ceo-review │      9 │    32 │    41 │    2h ago │       11 │
│ office-hours    │     13 │    20 │    33 │   11h ago │       17 │
│ model           │     16 │     0 │    16 │    4h ago │       11 │
└─────────────────┴────────┴───────┴───────┴───────────┴──────────┘
```

**4. 今天 / 本周 / 自定义区间的活动 retrospective（v0.5）**

```text
$ aifd ai today
═══ Today ═══ 2026-06-05 00:00 → 2026-06-05 09:41

  5 sessions · $80.30 · 85M tokens
  claude 5 sess · $80.30
  top skills: plan-eng-review x4 · ship x1
  top topics:
    · v0.4.1 vault scan UI/UX
    · FP suppression discussion
    · aifd ai today implementation

  vs previous: -$443.80 cost · -3 sessions
  → at this pace, monthly projection: $5,963.59 (based on 9.7h)
```

还有 `aifd ai weekly` / `monthly` / `retro --since YYYY-MM-DD`，全部支持 `--json`。详见 `docs/ai-retro.md`。

**5. 实时盯 secret 泄露（v0.6）**

```text
$ aifd vault watch install            # 一次性：注册 launchd，开机自启
Installed /Users/quincy/Library/LaunchAgents/io.aifd.watch.plist
Daemon will start at next login (and now via KeepAlive).

$ aifd vault watch status
aifd vault watch · RUNNING
  pid          84231
  server       http://127.0.0.1:54791/
  state file   /Users/quincy/.aifd/watch-state.json
  log file     /Users/quincy/.aifd/watch.log
  catches      0 total, 0 today
  tracking     38 jsonl file(s)
```

后台 daemon 实时盯 Claude / Codex 的 session jsonl —— 新行一落地立刻扫 secret，发现了推 macOS 通知。点通知打开本地 `127.0.0.1` 页面，把泄漏的 secret 高亮显示在对话上下文里。详见 `docs/vault-watch.md`。

**7. AI Coach — 让 LLM 看你怎么用 AI（v0.8）**

```text
$ aifd ai reflect --week
═══ Your week with AI ═══

上周你在 v0.7 上做了 23 次 session、花 $284，比上上周升 38%。ship 了 7 个
commit 但其中 5 次有 plan-eng-review 前置 —— plan-then-ship 成熟模式。
compliance ratio 87% 偏高，AskUserQuestion 87% 跟推荐 —— 是 calibration
好还是判断懒？最值得说的 anti-pattern：周二凌晨跑 8 次 office-hours 都没
ship，焦虑型 brainstorm。

  🏆 Wins
    · v0.7 events store 一气呵成 ship
    · plan-eng-review 引入后 P1 issue 0 个
    · DeepSeek over Claude 是清醒判断
  ⚠ Anti-pattern: 凌晨 office-hours 群发症
  → 下周试一次: 当 D1 看起来"明显对"时，强制选 B 一次
```

aifd 把你 7 个月的 session / cost / question pattern / skill 使用都倒过来照镜子，
让 LLM 写一段 80-150 字 meta-cognitive reflection。**LLM 经 LiteLLM 路由 100+ provider**
（DeepSeek / 智谱 / 通义 / 方舟 / Anthropic / OpenAI / Gemini / ollama / vLLM / Azure...），
default 是 DeepSeek（~$0.001/run，中文质量好），可任意切换（OpenAI-compatible
base_url）。Privacy: raw 内容永远不发；prompt 跑 v0.4 detector scan 兜底。详见
`docs/ai-reflect.md`。

**6. 持久化事件流 + 接外部报警（v0.7）**

```text
$ aifd vault watch events list
208 finding(s) total, showing 50
STATUS  CAT          SNIPPET        COUNT  LAST SEEN            FINGERPRINT
new     openai_key   sk-J…oNwP          3  2026-06-05T17:01    abc123def456…
new     github_pat   ghp_…ejyW          1  2026-06-05T17:02    7e8a9b0c1d2e…
...

$ aifd vault watch webhooks add --url https://hooks.slack.com/services/T/B/X \
    --on new_finding --category openai_key --category github_pat
$ aifd vault watch webhooks test webhook-12345  # 验证连通
$ aifd vault watch webhooks enable webhook-12345
```

v0.7 把每条 finding 从内存里的瞬时通知升级到 SQLite 持久化事件流：

- **历史查询** —— `aifd vault watch events list/show` + 浏览器 web UI
- **状态机** —— new / acknowledged / resolved / muted（24h 或永久）
- **webhook 出口** —— POST JSON 到 Slack / PagerDuty / Datadog / 自家系统
- **Rotation playbook** —— 每条 finding 附带"去哪 rotate"的 vendor dashboard 链接 + 步骤（en + zh）
- **同一 secret 跨文件 = 同一 issue** —— fingerprint 按 category + redacted snippet 哈希，count++

详见 `docs/vault-events.md`。

## 安装

```bash
# 推荐用 pipx
pipx install aifd

# 或者用 uv
uvx aifd ai session list   # 一次性
uv tool install aifd       # 持久安装

# 或者用 pip
pip install aifd
```

需要 Python 3.12+。

## 使用方法

### `aifd ai question list` — 复盘 AI 问过你的问题（v0.3）

最有意思的命令。把 Claude Code 在每次 `AskUserQuestion` 工具调用里问过的每个问题、连同你的选择，都列出来。**主要用途**：

- 「上周 AI 问过我哪些关键决策？我都选了什么？」
- 「我多大比例跟了推荐选项 vs 反推荐？」
- 「上次别的项目里我被问过 X 主题，我当时选了啥？」

#### 基本用法

```bash
# 全局：列出所有项目里 AI 问过的所有问题（默认最近 50 条）
aifd ai question list

# 限定当前目录
aifd ai question list --cwd

# 全部历史，不分页
aifd ai question list --all

# 指定显示条数
aifd ai question list --limit 100
```

#### 在浏览器里看（推荐 — v0.3.1）

终端 Table 对长 question 文本不友好（实测 67% 问题 > 200 字符，最长 1673 字符），看不全。`--open` 一个 flag 直接弹浏览器：

```bash
# 最简形式：写入 temp 文件 + 自动开浏览器（推荐日常使用）
aifd ai question list --cwd --open

# 看全部历史
aifd ai question list --all --open

# 持久化到指定文件（不开浏览器）
aifd ai question list --cwd --output decisions.html

# 持久化 + 同时开浏览器
aifd ai question list --cwd --output decisions.html --open
```

HTML 页面是 Notion / Linear 风格的阅读视图：每个 question 一张卡片、跟随系统主题、最大 70ch 宽度、绿色 `✓` 标你选的、灰色 `★` 标推荐的。所有用户文本经过 `html.escape()` 处理，历史里包含 `<script>` 字符串也不会 XSS。

#### JSON 输出与管道

```bash
# JSON 输出（含完整 record：options / notes / tool_use_id / source_path）
aifd ai question list --cwd --json | jq

# 找出你反推荐的问题
aifd ai question list --all --json | \
  jq '.[] | select(.recommended_option != null and (.chosen_option | contains(.recommended_option) | not)) | .question'

# 统计跨项目偏好（pipe 到 jq 做聚合）
aifd ai question list --all --json | jq 'group_by(.cwd) | map({cwd: .[0].cwd, count: length})'

# pipe HTML 到自己的 static server
aifd ai question list --all --html > public/decisions.html
```

#### 其他过滤 flag

```bash
# 只看 Claude（目前 Codex 返回空 —— 见下方"工具支持"）
aifd ai question list --provider claude

# verbose 日志（看到提取细节）
aifd ai question list --cwd -v
```

#### 表头含义

| 列 | 含义 |
|---|---|
| **Time** | 问题被问出的相对时间 |
| **Project** | 问题所在 cwd 的目录名 |
| **Question** | 问题文本（Table 模式会截断；用 `--open` 或 `--json` 看完整） |
| **Your Choice** | 你选的 option label。multiSelect 用 `, ` 分隔 |
| **Recommended** | 模型推荐的 option（即标了 `(recommended)` / `(推荐)` 的那个） |

底部 footer 显示：

- `N questions in <scope>` — 总数和范围
- `recommended hit rate: X% (M/N)` — 你跟推荐的比例（分母排除"无推荐"和"无答案"的）
- `K unanswered` — 被中断 / session 被压缩没回答的（实测约 4%）

#### Flag 互斥规则

| Flag 组合 | 行为 |
|---|---|
| 不加任何输出 flag | rich Table（默认） |
| `--json` | JSON 到 stdout |
| `--html` | HTML 到 stdout（pipe 用） |
| `--open` | HTML 写 temp 文件 + 开浏览器 |
| `--output PATH` | HTML 写到 PATH（隐含 HTML 模式，不开浏览器） |
| `--output PATH --open` | HTML 写到 PATH + 开浏览器 |
| `--json` + 任一 HTML 模式 | 报错（互斥） |

#### 工具支持

只支持 Claude Code。Codex 的 `agent_message` 事件是自由文本，没有结构化的「问用户」事件——所以 `--provider codex` 总是返回空。要扩展到 Codex / brainstorm 这类纯文本提问需要启发式抽取，会引入 noise，所以 v0.3 路线选择**精度优先**。详细原因见 [docs/question-extraction.md](./docs/question-extraction.md) 和 [TODOS.md](./TODOS.md)。

### `aifd ai session list` — 按目录列 session

```bash
# 列出当前目录所有 AI session
aifd ai session list

# JSON 输出
aifd ai session list --json | jq '.[] | .session_id'

# 按 provider 过滤
aifd ai session list --provider claude
aifd ai session list --provider codex
```

默认**精确匹配**当前目录。递归扫描（`-r`）在 roadmap 上。

### `aifd ai skill list` — 跨工具 skill 使用统计

```bash
# 全局 skill 使用情况（所有 Claude 项目 + 所有 Codex thread）
aifd ai skill list

# 限定当前项目
aifd ai skill list --cwd

# JSON 输出
aifd ai skill list --json | jq '.[] | select(.total > 5)'

# 按 provider 过滤
aifd ai skill list --provider claude
```

| 列 | 含义 |
|---|---|
| **Claude / Codex / Total** | 各工具调用次数 + 合计 |
| **Last Used** | 最近一次调用的相对时间 |
| **Projects** | 这个 skill 被用过的**不同**目录数（高 = 跨项目通用工具；低 = 单项目专用）|

默认**全局**——单项目 skill 调用通常不多，跨项目 pattern 才有意思。要看「我建这个项目用了哪些 skill」加 `--cwd`。

跨 provider 命名归一：Claude 的 `/gstack-office-hours` 和 Codex 的 `[$office-hours]` 都聚合成 `office-hours`。

### `aifd vault scan` — 扫描 PII / secret 泄露（v0.4）

定期跑一次，看你的 AI 历史里有没有不小心 paste 出去的 API key、token、内部 email 等：

```bash
# 默认扫所有 provider history，confidence >= 7（只显 regex 命中）
aifd vault scan

# JSON 输出（含 redacted snippet，永远不含完整 secret）
aifd vault scan --json | jq

# 加入熵检测（confidence 4，会有噪点）
aifd vault scan --min-confidence 4

# 只扫指定路径
aifd vault scan --no-default-roots --root /path/to/scan
```

**安全保证**：完整 secret 值绝不出现在输出 / JSON / 日志中。`SensitiveMatch` 数据类只存 redacted snippet（首 4 + 尾 4 字符）。可以直接 paste 给同事 debug，不会泄露真 secret。

支持检测：Anthropic / OpenAI / GitHub PAT / AWS access key / Slack token / JWT / email / 高熵字符串。详细原理见 [docs/vault.md](./docs/vault.md)。

### `aifd vault cost` — 估算 token 用量 + USD 花费（v0.4）

```bash
# 按项目分组（默认）
aifd vault cost

# 按 model
aifd vault cost --by model

# 按月
aifd vault cost --by month

# 按 provider
aifd vault cost --by provider

# JSON 输出
aifd vault cost --by project --json | jq

# 看价格表里有哪些 model（debug 未知 model）
aifd vault cost --list-models
```

输出含完整 token breakdown（fresh input / cache read / output / reasoning）+ USD 估算 + 底部 prices last_updated 日期。

| 列 | 含义 |
|---|---|
| **In (k)** | 新输入 token（千）|
| **Cache (k)** | cache read token（千，便宜得多）|
| **Out (k)** | 输出 + reasoning token（千）|
| **Cost ($)** | 该行 USD 估算 |
| **Model** | 单一 model 显原名；多 model 显 `mixed (N)` |

未知 model（不在价格表里）会显示 token 数但 cost = $0，方便你发现需要 update 表。

### `aifd vault watch` — 实时 secret 检测 daemon（v0.6）

`vault scan` 是事后查；`vault watch` 是事前防 —— 常驻 daemon 盯每个 Claude / Codex 的 session jsonl，新行一落地立刻跑同一套检测，发现真 secret 推 macOS 通知。点通知打开 `127.0.0.1` 的页面，secret 在对话上下文里被高亮。

**典型工作流（macOS）：**

```bash
# 1. 一次性安装：注册 launchd .plist，开机自启
aifd vault watch install

# 2. 看状态（pid / 端口 / 今天捕获了多少 / 跟踪了多少 jsonl）
aifd vault watch status
aifd vault watch status --json     # 给脚本用

# 3. 看实时 log
aifd vault watch tail

# 4. 调试时前台跑（Ctrl-C 退出，stdout 直接看到 log）
aifd vault watch start --foreground -vv

# 5. 临时停 daemon
aifd vault watch stop

# 6. 完全卸载（停 daemon + 删 .plist）
aifd vault watch uninstall
```

**强烈建议**先装 `terminal-notifier`：

```bash
brew install terminal-notifier
```

不装会 fallback 到 `osascript`，**点击通知会打开 macOS 自带的「脚本编辑器」**而不是浏览器跳到 finding URL —— 这是 `osascript display notification` AppleScript 命令的已知限制（不支持自定义点击回调）。`aifd vault watch status` 会显示当前用的是哪个 backend。

**首次运行**：daemon 启动后会发一条测试通知「Watch daemon started — notifications working.」。**如果没看到**，去系统设置 → 通知 → Terminal / terminal-notifier 里允许，然后 `aifd vault watch stop && aifd vault watch start`。

**与 `aifd ai today` 联动**：daemon 捕到的 secret 数会在每日 / 每周 / 每月活动报告底部多一行：

```text
🛡 vault watch: 3 secrets caught this period (run `aifd vault watch status` for details)
```

**安全 invariant**（详见 `docs/secret-scan.md`）：

- HTTP server 只绑 `127.0.0.1`（不是 `0.0.0.0`）—— LAN 上其它机器永远碰不到
- 通知 URL 里的 token 是 `secrets.token_urlsafe(32)`（~256 bit 不可猜）
- `~/.aifd/watch-state.json` 只存 `category` + redacted snippet，完整 secret 永不落盘
- state file 用 `tmp + rename` 原子写 —— SIGKILL 半途也不会留半截 JSON
- `fcntl.flock` 防止两个 daemon 同时跑

**Linux**：`install` 子命令是 macOS-only（launchd）。Linux 用 `systemctl --user` 跑 `aifd vault watch daemon`，参考 `docs/vault-watch.md` 里的 `.service` 模板。

### `aifd ai reflect` — AI Coach：让 LLM 看你怎么用 AI（v0.8）

aifd v0.8 把所有"做事"工具反过来 —— 让 aifd 看你这周怎么用 AI，让 LLM 写一段 80-150 字的 meta-cognitive reflection。每周一行，~$0.001/run。

**首次配置**（三选一）：

```bash
# 方式 1: 环境变量（最直接）
export DEEPSEEK_API_KEY=sk-xxxxxxxxx      # 或 ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ...
aifd ai reflect --week

# 方式 2: ~/.aifd/config.yaml（推荐长期方案）
aifd ai reflect           # 首次跑自动生成模板
$EDITOR ~/.aifd/config.yaml   # 填 llm.api_key + llm.model
# 文件自动 chmod 600

# 方式 3: 临时 prefix（不写入 env / 不存 history）
DEEPSEEK_API_KEY=sk-xxx aifd ai reflect --week
AIFD_LLM_API_KEY=sk-xxx aifd ai reflect --model zhipu/glm-4-plus
```

去 https://platform.deepseek.com/api_keys 拿 DeepSeek key（或换任意 LiteLLM
[provider](https://docs.litellm.ai/docs/providers)）。优先级：`AIFD_LLM_*` env >
provider 原生 env (`DEEPSEEK_API_KEY` 等) > config.yaml > built-in default。

**日常使用**：

```bash
aifd ai reflect                                # 默认 --week, zh
aifd ai reflect --month                        # 30 天回顾
aifd ai reflect --month --lang en              # 英文输出
aifd ai reflect --since 2026-06-01             # 自定义窗口
aifd ai reflect --since 2026-06-01 --until 2026-06-07
aifd ai reflect --json                         # pipe-friendly
aifd ai reflect -v                             # verbose: 显示 timing breakdown
aifd ai reflect --include-questions            # opt-in: 把 question summary 喂 LLM
```

**切换 LLM 后端**（任意 LiteLLM provider）：

```bash
# 国内 provider — 每家用 LiteLLM 的 provider/model 格式
aifd ai reflect --model zhipu/glm-4-plus
aifd ai reflect --model dashscope/qwen-plus            # 阿里通义
aifd ai reflect --model ark/ep-xxxxx                   # 火山引擎方舟 (endpoint_id)
aifd ai reflect --model moonshot/moonshot-v1-32k       # Kimi

# 国际 provider
aifd ai reflect --model anthropic/claude-sonnet-4
aifd ai reflect --model openai/gpt-4o
aifd ai reflect --model gemini/gemini-2.0-flash

# 本地 ollama / 自托管 vLLM / Azure / 公司代理
aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
aifd ai reflect --model openai/qwen2.5 --api-base https://vllm.internal/v1

# 或写进 ~/.aifd/config.yaml 的 llm.model / llm.api_base
```

**`~/.aifd/config.yaml` 完整 schema**（首次跑 `aifd ai reflect` 时自动生成，
权限自动 `chmod 600`）：

```yaml
llm:
  # LiteLLM 'provider/model' 格式 —— 换 provider 只改这一行
  model: deepseek/deepseek-chat
  # API key。留空让 LiteLLM 读 provider 原生 env var
  # (DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY /
  #  ANTHROPIC_API_KEY / OPENAI_API_KEY / MOONSHOT_API_KEY / GROQ_API_KEY ...)
  api_key: sk-xxxxxxxxx
  # 自托管 / 代理时填；hosted provider 留空走默认 endpoint
  api_base:

reflect:
  default_lang: zh           # en | zh
  include_questions: false   # true = 把 question summary 喂给 LLM（仍不发原文）
```

各 provider 的 yaml 写法：

```yaml
# DeepSeek (default)
llm: { model: deepseek/deepseek-chat, api_key: sk-... }

# 智谱 GLM
llm: { model: zhipu/glm-4-plus, api_key: ... }

# 阿里通义千问 (DashScope)
llm: { model: dashscope/qwen-plus, api_key: sk-... }

# 火山引擎方舟（model 字段填 inference endpoint id，不是模型名）
llm: { model: ark/ep-xxxxxxxx, api_key: ... }

# Moonshot Kimi
llm: { model: moonshot/moonshot-v1-32k, api_key: sk-... }

# Anthropic Claude
llm: { model: anthropic/claude-sonnet-4, api_key: sk-ant-... }

# OpenAI
llm: { model: openai/gpt-4o, api_key: sk-... }

# 本地 ollama（api_key 空即可，必须填 api_base）
llm:
  model: ollama/qwen2.5
  api_base: http://127.0.0.1:11434/v1

# 自托管 vLLM / OpenAI-compatible 代理
llm:
  model: openai/qwen2.5
  api_key: any-non-empty-string
  api_base: https://vllm.internal/v1
```

**优先级**：`AIFD_LLM_*` env > provider 原生 env > `~/.aifd/config.yaml` > 默认值。
v0.8 pre-release 已经在用 `DEEPSEEK_API_KEY` 的不用改，自动兼容。

**9 个反思维度**（aifd 看什么）：

| 维度 | 说什么 |
|---|---|
| Activity | sessions / cost / tokens / by-provider |
| Compliance ratio | 你 AskUserQuestion 时跟推荐的比例 |
| Skill diversity | distinct skill / total invocations |
| Cost trend | 本周 vs 上周花费变化 |
| Timing distribution | 4 个时段 bucket，看你哪时段最 productive |
| Project focus | 最深的项目 + 其 share（**只发 basename**） |
| Plan-then-ship | ship 前 7 天内有 plan-eng-review 的比例 |
| Vibe-coding score | ship 前 session < 5 message 的比例 |
| Top wins | 最近 clean ship + plan-eng-review |

**Privacy invariant**（hard guarantee）：

- raw question 答题原文永远不发
- session message 内容永远不发
- cwd 完整路径永远不发（只发 basename）
- v0.4 detector 任何 secret pattern 永远不发（render_prompt 跑 `_scan_line` 兜底校验，0 SensitiveMatch = test pass）
- `--include-questions` opt-in 也只发 summary，**不**发原文

**Fallback**：没 API key / 401 auth / 5xx / timeout → 退化到 structured local report + 清晰 error message，不 crash。完整 spec 见 `docs/ai-reflect.md`。

### `aifd ai habits` — 长期 AI 行为人格画像（v0.9）

`reflect` 回答「这周怎么样」；`habits` 回答「**我是什么类型的 AI 用户**」。
分析 60-90 天的 session 数据，让 LLM 识别你**自己没意识到**的行为模式。

```
$ aifd ai habits
═══ 你的 AI 行为人格 (90 天画像) ═══

模式 1「周五放松崩」
你周五的 vibe-coding 比率是工作日均值的 2.4x。
  → 建议：周五下午 5 点后不要开新的 plan review。

模式 2「深夜决策次日后悔」
22 点后开始的 session 仅 33% 在 24 小时内 ship。
  → 建议：复杂架构决策推到次日早晨。
```

跟 `reflect` 的分工：

| | `aifd ai reflect` | `aifd ai habits` |
|---|---|---|
| 时间窗口 | 7-30 天 | 60-90 天 |
| 频率 | 每周 | 每季度或按需 |
| LLM 任务 | 写反思 essay | 命名模式 + 数字证据 |

```bash
aifd ai habits                              # 默认 90 天
aifd ai habits --since 60d
aifd ai habits --since 2026-01-01
aifd ai habits --lang en --json
aifd ai habits --model zhipu/glm-4-plus     # 任何 LiteLLM provider
```

`~/.aifd/config.yaml` 加 `habits:` 段（首次跑自动生成）：

```yaml
habits:
  default_days: 90
```

8 个维度（星期分布 / 时段分布 / session 双峰 / 项目切换频率 / ship 间隔 /
深夜 ship 率 / 过度规划率 / skill 重复率），与 `reflect` 共享 LiteLLM 路由层
和 D6 privacy invariant。完整规格见 `docs/ai-habits.md`。

### `aifd ai claude skill list` / `aifd ai codex skill list` — 列出已装 skill

```bash
# 当前 Claude Code 装了哪些 skill
aifd ai claude skill list

# Codex 的同样查询
aifd ai codex skill list

# JSON 过滤
aifd ai claude skill list --json | jq '.[] | select(.source == "plugin")'
aifd ai codex skill list --json | jq '.[] | select(.source == "system") | .name'
```

列：**Skill / Source / Description / Version / Plugin**。

Source 区分 skill 来源：

| Source | 含义 |
|---|---|
| **user** | 你自己安装的（`~/.claude/skills/...` 或 `~/.codex/skills/...`） |
| **plugin** | 通过 marketplace 装的（只有 Claude）|
| **system** | 工具自带（Codex `.system/` 内置）|

同名 skill 从不同 source 来会显示成两行——故意的，让你看清装在哪。

### 通用 flag

```bash
aifd --version
aifd ai session list -v     # INFO 日志
aifd ai session list -vv    # DEBUG 日志
```

## 当前支持矩阵

| 工具 | 状态 | 说明 |
|---|---|---|
| Claude Code | ✅ | 读 `~/.claude/projects/{encoded-cwd}/*.jsonl` |
| Codex | ✅ | 读 `~/.codex/state_5.sqlite` + `~/.codex/sessions/` 兜底 |
| Cursor | ⏳ v0.4+ | 需要 SQLite + workspace-hash 反查（见 [TODOS.md](./TODOS.md)）|

## 架构

每个 AI 工具一个 adapter 放在 `aifd/providers/` 下。新增 provider = 一个文件 + 一行注册。CLI 分三层（`aifd ai session list`）给未来 `session show` / `session resume` / `ai prompt` 等命令留空间。

```text
aifd/
├── cli/
│   ├── _logging.py          # 所有 CLI 命令共享的日志配置
│   ├── _runner.py           # 共享的 provider-query 框架（v0.3）
│   ├── ai/
│   │   ├── session.py       # aifd ai session list
│   │   ├── skill.py         # aifd ai skill list（v0.2）
│   │   ├── question.py      # aifd ai question list（v0.3 + HTML v0.3.1）
│   │   ├── claude/skill.py  # aifd ai claude skill list（v0.2.1）
│   │   └── codex/skill.py   # aifd ai codex skill list（v0.2.1）
│   └── vault/               # v0.4
│       ├── scan.py          # aifd vault scan (PII/secret 扫描)
│       └── cost.py          # aifd vault cost (token + $)
├── providers/
│   ├── base.py              # Provider Protocol，新 provider 必须实现
│   ├── _utils.py            # 共享正则 / 命名归一 / frontmatter 解析
│   ├── claude.py            # Claude Code adapter
│   ├── codex.py             # Codex adapter
│   └── registry.py          # 注册新 provider 的地方
├── vault/                   # v0.4 业务逻辑
│   ├── prices.py            # model → USD 价格表
│   ├── cost.py              # 聚合 token → $
│   └── scan.py              # PII/secret detector
├── aggregation.py           # skill 统计聚合（v0.2）
├── models.py                # Session / SkillInvocation / SkillStats / InstalledSkill / QuestionAnswer / TokenUsage / CostRow / SensitiveMatch
├── paths.py                 # cwd 归一化
└── render.py                # rich Table / JSON / HTML 渲染
```

## 贡献一个新 provider

1. 新建 `aifd/providers/yourtool.py`，实现 `aifd/providers/base.py` 里的 `Provider` Protocol。
2. 把你的 provider 实例追加到 `aifd/providers/registry.py` 的 `PROVIDERS` 列表。
3. 在 `tests/fixtures/yourtool/` 下加 fixture，写 `test_yourtool_provider.py`。
4. 确认 `uv run pytest`、`uv run ruff check aifd/ tests/`、`uv run mypy aifd/` 全过。

**单文件解析错误必须 silent skip**（log 在 `warning` 或 `debug` 级别），永远不能 raise——一个坏文件不能让整个列表挂掉。

## 开发

```bash
git clone https://github.com/xunull/aifd
cd aifd
uv sync
uv run pytest
uv run ruff check aifd/ tests/
uv run mypy aifd/
```

### Editable 安装的 dep trap

如果你用 `uv tool install --editable .`（或 `pipx install -e .`）把开发版 `aifd`
装到 PATH 上，要小心：

- **source 改动会自动生效** —— editable 模式直接指向 repo，改 `.py` 不用重装。
- **但 deps 不会自动同步** —— `uv sync` 只更新项目的 `.venv`，不碰 tool 的隔离
  venv（`~/Library/Application Support/uv/tools/aifd/` 或 pipx 的 `~/.local/pipx/venvs/aifd/`）。

所以：**`pyproject.toml` 里 deps 变了（新增、删除、bump）→ 必须重装一次**：

```bash
uv tool install --reinstall --editable .     # uv tool
pipx reinstall aifd                          # pipx
```

报错样子通常是 `ModuleNotFoundError: No module named 'litellm'`（明明 `uv run`
能跑，命令行直接 `aifd` 就 import 不到）—— 那就是 tool venv 里没装新 dep。

## License

Apache-2.0
