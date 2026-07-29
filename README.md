# aifd

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/aifd.svg)](https://pypi.org/project/aifd/)

[English](./README.en.md) | **简体中文**

> 跨 Claude Code / Codex / OpenCode / Cursor 的 AI 编码历史浏览器 + secret 扫描 + LLM coach。
> 把「我的目录 / 我用过的 skill / AI 问过我什么 / 我花了多少钱 / 我是什么类型的 AI 用户」这些问题，用一行命令回答。

每个 AI 编码工具都把历史存在自己的私有格式里。`aifd` 把所有工具的数据**按你的视角**聚合：按目录、按 skill、按问题、按花费、按行为模式 —— 而不是按工具。

```text
查 → 算 → 扫 → 盯 → 反思 → 看
session / skill / question → cost / token → secret / PII → 实时 daemon → AI Coach → 星图
```

**三个事实**，决定了你会不会用它：

1. **只读、离线、本地**。aifd 从不写你的 AI 工具数据目录，也不需要联网 —— 除非你主动跑 `aifd ai reflect` / `habits`（调 LLM）或 `aifd quota`（查订阅额度）。
2. **完整 secret 值永不出现在任何输出里**。扫描结果、JSON、日志、webhook payload、LLM prompt，一律只有脱敏片段（首 4 + 尾 4 字符）。
3. **加一个新 AI 工具 = 一个文件 + 一行注册**。见[贡献一个新 provider](#贡献一个新-provider)。

当前版本 **v0.14.0**，Python 3.12+，744 个测试跑在 3 个操作系统 × 2 个 Python 版本上。

---

## 📑 目录

### ✨ [亮点速览（8 个截图）](#-亮点速览gif-风格)

### 🚀 [快速开始](#-快速开始)
- [安装](#-安装) · [一分钟试用](#-一分钟试用)

### 📋 [完整命令树](#-完整命令树)

### 🔍 [查 — 列你的历史](#-查--列你的历史)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd ai session list`](#aifd-ai-session-list--按目录列-session) | 列出当前目录的所有 AI session | v0.1 |
| [`aifd ai question list`](#aifd-ai-question-list--复盘-ai-问过你的问题) | 复盘 AskUserQuestion 历史 + recommended hit rate | v0.3 |
| [`aifd ai skill list`](#aifd-ai-skill-list--跨工具-skill-使用统计) | 跨工具 skill 使用统计 + 热门排行 | v0.2 |
| [`aifd ai claude skill list`](#aifd-ai-claude-skill-list--aifd-ai-codex-skill-list--列出已装-skill) / [`aifd ai codex skill list`](#aifd-ai-claude-skill-list--aifd-ai-codex-skill-list--列出已装-skill) | 列出已装的 Claude / Codex skill | v0.2.1 |

### 📊 [算 — 活动 retrospective](#-算--活动-retrospective)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd ai today`](#aifd-ai-today--weekly--monthly--retro--活动-retrospective) | 今天的活动摘要（session / cost / token / skill）| v0.5 |
| [`aifd ai weekly`](#aifd-ai-today--weekly--monthly--retro--活动-retrospective) | 过去 7 天滚动窗口 | v0.5 |
| [`aifd ai monthly`](#aifd-ai-today--weekly--monthly--retro--活动-retrospective) | 当月活动摘要 | v0.5 |
| [`aifd ai retro --since YYYY-MM-DD`](#aifd-ai-today--weekly--monthly--retro--活动-retrospective) | 自定义区间 retrospective | v0.5 |

### 🔐 [扫 — secret / PII 防泄漏](#-扫--secret--pii-防泄漏)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd vault scan`](#aifd-vault-scan--扫描-pii--secret-泄露) | 一次性扫所有 session jsonl 找 secret / PII | v0.4 |
| [`aifd vault cost`](#aifd-vault-cost--估算-token-用量--usd-花费) | 估算 token 用量 + USD 花费（含历史趋势）| v0.4 |
| [`aifd vault watch`](#aifd-vault-watch--实时-secret-检测-daemon) | 后台 daemon：新增 session 行实时扫 secret + macOS 通知 | v0.6 |
| [`aifd vault watch events`](#aifd-vault-watch-events--持久化事件流) | 持久化事件流（SQLite）+ web UI + 状态机 | v0.7 |
| [`aifd vault watch webhooks`](#aifd-vault-watch-webhooks--外部报警系统接入) | webhook 推送到 Slack / PagerDuty / Datadog | v0.7 |

### 🧘 [反思 — AI Coach](#-反思--ai-coach)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd ai reflect`](#aifd-ai-reflect--ai-coach让-llm-看你怎么用-ai) | 每周让 LLM 写一段 80-150 字 meta-cognitive reflection | v0.8 |
| [`aifd ai habits`](#aifd-ai-habits--长期-ai-行为人格画像) | 60-90 天长期行为人格画像（你是什么类型的 AI 用户）| v0.9 |

### 🌌 [看 — 把 AI 史变成星图](#-看--把-ai-史变成星图)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd cosmos`](#aifd-cosmos--鼠标拖拽旋转的立体星图) | 生成可拖拽旋转的 2.5D 星图（自包含 HTML，离线可看）| v0.13 → v0.14 |

### 📉 [额度 — 订阅用量](#-额度--订阅用量)
| 命令 | 一句话 | 版本 |
|---|---|---|
| [`aifd quota`](#aifd-quota--minimax-coding-plan-5h-额度) | MiniMax Coding Plan 5 小时滚动窗口剩余额度 | v0.12 |

### 🛠️ [配置与运行时](#%EF%B8%8F-配置与运行时)
- [`~/.aifd/config.yaml` 完整 schema](#aifdconfigyaml-完整-schema) · [配置优先级](#配置优先级) · [aifd 在磁盘上写了什么](#aifd-在磁盘上写了什么) · [通用 flag](#通用-flag) · [当前支持矩阵](#当前支持矩阵)

### 🔒 [数据来源与隐私](#-数据来源与隐私)
- [aifd 读哪些文件](#aifd-读哪些文件) · [隐私 invariant](#隐私-invariant) · [什么时候会联网](#什么时候会联网)

### ❓ [常见问题排查](#-常见问题排查)

### 🏗️ [架构与贡献](#%EF%B8%8F-架构与贡献)
- [架构](#架构) · [贡献一个新 provider](#贡献一个新-provider) · [开发](#开发) · [测试与 CI](#测试与-ci) · [Editable 安装的 dep trap](#editable-安装的-dep-trap)

### 🧭 [版本历程](#-版本历程)

---

## ✨ 亮点速览（gif 风格）

八条命令，八个不同的问题。下面的输出都是真实跑出来的（数字做了脱敏）。

**1. 按目录列 session（v0.1）**

```text
$ aifd ai session list                # 在任意项目目录里跑
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Provider ┃ Session  ┃ Started ┃ Events ┃ Title            ┃ Source           ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ claude   │ bbfc1d21 │  2h ago │    781 │ Install Claude … │ ~/.claude/p…     │
│ codex    │ 019e7d19 │  1d ago │      0 │ 审计计划完成情况 │ ~/.codex/se…     │
│ opencode │ ses_148b │ 15h ago │      0 │ 查找出站连接代码 │ ~/.local/sh…     │
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

**5. 实时 secret 检测 + webhook 推送（v0.6 → v0.7）**

```text
$ aifd vault watch install            # launchd 自启
$ aifd vault watch events list        # 持久化事件流
$ aifd vault watch webhooks add --url https://hooks.slack.com/...
```

后台 daemon 盯 session jsonl，新行一落地立刻扫 secret，发现了推 macOS 通知 + SQLite 持久化 + webhook 推送 Slack/PagerDuty。详见 [`aifd vault watch`](#aifd-vault-watch--实时-secret-检测-daemon) 章节。

**6. AI Coach — 周度反思（v0.8）**

```text
$ aifd ai reflect --week
═══ Your week with AI ═══

上周你在 v0.7 上做了 23 次 session、花 $284，比上上周升 38%。ship 了 7 个
commit 但其中 5 次有 plan-eng-review 前置 —— plan-then-ship 成熟模式。
最值得说的 anti-pattern：周二凌晨跑 8 次 office-hours 都没 ship。

  🏆 Wins · plan-eng-review 引入后 P1 issue 0 个
  ⚠ Anti-pattern: 凌晨 office-hours 群发症
  → 下周试一次: 当 D1 看起来"明显对"时，强制选 B 一次
```

**7. AI 行为人格画像 — 长期模式（v0.9）**

```text
$ aifd ai habits
═══ 你的 AI 行为人格 (90 天画像) ═══

模式 1「周五放松崩」
你周五的 vibe-coding 比率是工作日均值的 2.4x。
  → 建议：周五下午 5 点后不要开新的 plan review。

模式 2「深夜决策次日后悔」
22 点后开始的 session 仅 33% 在 24 小时内 ship。
  → 建议：复杂架构决策推到次日早晨。
```

`reflect` 回答「这周怎么样」；`habits` 回答「**我是什么类型的 AI 用户**」。LLM 路由经 [LiteLLM](https://github.com/BerriAI/litellm) 100+ provider（DeepSeek / 智谱 / 通义 / 方舟 / Anthropic / OpenAI / Gemini / ollama / vLLM / Azure）。详见 [`aifd ai reflect`](#aifd-ai-reflect--ai-coach让-llm-看你怎么用-ai) / [`aifd ai habits`](#aifd-ai-habits--长期-ai-行为人格画像)。

**8. 你的 AI 宇宙 — 可拖拽旋转的立体星图（v0.13 → v0.14）**

```text
$ aifd cosmos
✨ 1106 sessions → aifd-cosmos.html
```

```text
              ·  ✦        ·
        ✦   ·      ●aifd        ·   ✦          ← 紫色 hub = 项目
   ·        ✦   ·   ·  ✦   ·        ·
      ●gstack   ·  ✦  ·      ●dotfiles  ✦      ← 蓝点 = vibe-coding
   ✦     ·   ✦      ·    ✦      ·   ·          ← 红点 = 深聊（长 session）
        ·       ✦        ·      ✦
   [ 按住鼠标拖拽 → 星云绕轴旋转，近大远小 ]
```

每个 session 是一颗星（半径 = event 数，冷蓝 = vibe-coding、暖红 = 深聊），每个项目是它环绕的 hub。
**按住鼠标拖拽即可绕轴旋转**（v0.14 默认 2.5D；`--flat` 回到 v0.13 的 2D force-graph）。
输出是 66KB 自包含 HTML —— 离线可看、零网络依赖、cwd 只显 basename 所以截图分享不泄漏项目名。
详见 [`aifd cosmos`](#aifd-cosmos--鼠标拖拽旋转的立体星图)。

---

## 🚀 快速开始

### 📦 安装

```bash
# 推荐：pipx（隔离 venv，工具级安装）
pipx install aifd

# 或：uv tool（uv 用户推荐）
uvx aifd ai session list   # 一次性试跑
uv tool install aifd       # 持久安装

# 或：pip（不隔离 venv，可能跟项目依赖冲突）
pip install aifd
```

需要 **Python 3.12+**。

### ⚡ 一分钟试用

在任意有 AI session 历史的项目目录跑：

```bash
# 1. 看这个项目里你之前都跑过哪些 AI session
aifd ai session list

# 2. 看过去 7 天总活动（cost / token / 顶部 skill）
aifd ai weekly

# 3. 扫所有 session 找泄漏的 secret
aifd vault scan

# 4. 复盘 AskUserQuestion 历史 + recommended hit rate
aifd ai question list --cwd --limit 10

# 5. 把你的 AI 史渲染成可拖拽旋转的星图
aifd cosmos
```

这 5 条**都不需要任何配置和 API key** —— 直接读你本机已有的 AI 工具数据。

要用 **AI Coach（`reflect` / `habits`）** 才需要配一个 LLM API key，见 [`~/.aifd/config.yaml` 完整 schema](#aifdconfigyaml-完整-schema)。
要用 **`aifd quota`** 需要一个 MiniMax coding-plan key（跟 LLM key 是两回事）。

**一条命令都没输出？** 大概率是 aifd 还没适配你在用的工具，或者当前目录没有历史。跳到[常见问题排查](#-常见问题排查)。

---

## 📋 完整命令树

v0.14 的全部命令。四个顶层 group：`ai`（跨工具查询与反思）、`vault`（数据主权）、`cosmos`（可视化）、`quota`（订阅额度）。

```text
aifd
├── ai                                  跨 AI 工具的操作
│   ├── session list                    列当前目录的 session                     v0.1
│   ├── skill list                      跨工具 skill 使用统计                     v0.2
│   ├── question list                   复盘 AskUserQuestion 历史（+ HTML）        v0.3
│   ├── claude skill list               列已装的 Claude skill                     v0.2.1
│   ├── codex skill list                列已装的 Codex skill                      v0.2.1
│   ├── today                           今天的活动摘要                            v0.5
│   ├── weekly                          过去 7 天滚动窗口                         v0.5
│   ├── monthly                         当月活动摘要                              v0.5
│   ├── retro --since/--until           自定义区间 retrospective                  v0.5
│   ├── reflect                         每周 meta-cognitive 反思（需 LLM）         v0.8
│   └── habits                          60-90 天行为人格画像（需 LLM）             v0.9
│
├── vault                               数据主权：scan / cost / watch
│   ├── scan                            一次性扫 secret / PII                     v0.4
│   ├── cost                            token 用量 + USD 估算                     v0.4
│   └── watch                           实时 secret 检测 daemon                   v0.6
│       ├── install / uninstall         注册 / 移除 launchd 开机自启（macOS）
│       ├── start / stop / status       启停 + 看 pid / 端口 / 今日捕获数
│       ├── tail                        跟踪 ~/.aifd/watch.log
│       ├── events                      持久化 finding 事件流（SQLite）           v0.7
│       │   ├── list / show             列出 / 查看单条（含 rotation playbook）
│       │   ├── ack / mute / resolve    状态机流转
│       │   └── export                  导出 NDJSON
│       └── webhooks                    外部报警系统接入                          v0.7
│           ├── add / delete / list     增删查
│           ├── test                    发测试事件（必须 test 通才能 enable）
│           ├── enable / disable        启停单个 webhook
│           └── list-dead-letter        投递失败队列 + retry-dead-letter
│
├── cosmos                              AI 史 → 可旋转 2.5D 星图 HTML            v0.13 → v0.14
│
└── quota                               订阅额度（默认 MiniMax）                  v0.12
    └── minimax                         MiniMax Coding Plan 5h 窗口
```

任意层级都能 `--help`：`aifd vault watch events --help`。

---

## 📚 命令完整参考

下面按「**查 → 算 → 扫 → 反思 → 看 → 额度**」六组展开。每节顶部有一句话总结 + 何时用，下面是详细 flag 和示例。

---

## 🔍 查 — 列你的历史

### `aifd ai question list` — 复盘 AI 问过你的问题

> **何时用：** 想看 AI 问过你的所有问题、你选了什么、跟推荐一不一致。  
> **版本：** v0.3（HTML 渲染 v0.3.1）

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
# 只看 Claude（目前 Codex / OpenCode 返回空 —— 见下方"工具支持"）
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

只支持 Claude Code。Codex 的 `agent_message`、OpenCode 和 Cursor 的消息都是自由文本，没有结构化的「问用户」事件——所以 `--provider codex` / `--provider opencode` / `--provider cursor` 总是返回空（返回空，不是报错）。要扩展到这类纯文本提问需要启发式抽取，会引入 noise，所以路线选择**精度优先**。详细原因见 [`docs/question-extraction.md`](./docs/question-extraction.md) 和 [TODOS.md](./TODOS.md)。

### `aifd ai session list` — 按目录列 session

> **何时用：** 在某个项目目录下，看你之前都跑过哪些 AI session（什么时候开的、用了多少 event）。  
> **版本：** v0.1（基础）

```bash
# 列出当前目录所有 AI session
aifd ai session list

# JSON 输出
aifd ai session list --json | jq '.[] | .session_id'

# 按 provider 过滤
aifd ai session list --provider claude
aifd ai session list --provider codex
aifd ai session list --provider opencode
aifd ai session list --provider cursor
```

| 列 | 含义 |
|---|---|
| **Provider** | 哪个 AI 工具 |
| **Session** | session id 前缀（够短好认，够长不撞） |
| **Started** | 相对开始时间 |
| **Events** | 该 session 的事件数。**跨工具不可比** —— 各家 jsonl 的事件粒度不同 |
| **Title** | 自动抽取的会话标题 |
| **Source** | 数据来自哪个文件（缩略显示） |

默认**精确匹配**当前目录，不递归子目录。递归扫描（`-r`）在 roadmap 上。跨目录看全局用 `aifd ai skill list`（默认全局）或 `aifd ai weekly`。

四个 provider 全都支持这条命令，但 Cursor 有已知的 ~80% cwd 映射覆盖率，见[常见问题排查](#-常见问题排查)。

### `aifd ai skill list` — 跨工具 skill 使用统计

> **何时用：** 想看你 Claude + Codex 加起来哪些 skill 用得最多、上次用是什么时候、跨多少个项目。  
> **版本：** v0.2

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

### `aifd ai claude skill list` / `aifd ai codex skill list` — 列出已装 skill

> **何时用：** 想看当前 Claude Code / Codex 装了哪些 skill（user / plugin / system 三类来源分别列出）。  
> **版本：** v0.2.1

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

---

## 📊 算 — 活动 retrospective

### `aifd ai today` / `weekly` / `monthly` / `retro` — 活动 retrospective

> **何时用：** 想看「今天 / 本周 / 本月 / 自定义区间我跟 AI 干了多少活、花了多少钱」。  
> **版本：** v0.5

```bash
aifd ai today                              # 今天（local midnight → now）
aifd ai weekly                             # 过去 7 天滚动窗口
aifd ai monthly                            # 本月（local 月初 → now）
aifd ai retro --since 2026-05-01 --until 2026-05-31
aifd ai retro --since 7d                   # 7d / 14d / 90d 简写
aifd ai retro --json                       # pipe-friendly

# 详见 docs/ai-retro.md
```

示例输出：

```text
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

包含：session / cost / token 统计、by-provider 拆分、top skills、top topics（自动抽取的对话主题）、跟上一周期对比的 delta、月度投影。

---

## 🔐 扫 — secret / PII 防泄漏

### `aifd vault scan` — 扫描 PII / secret 泄露

> **何时用：** 定期 audit 一次 —— 看你的 AI 历史里有没有不小心 paste 出去的 API key / token / 内部 email。  
> **版本：** v0.4

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

**检测器与 confidence**

| Category | 匹配 | Confidence |
|---|---|---|
| `anthropic_key` | `sk-ant-…` | 10 |
| `openai_key` | `sk-…` / `sk-proj-…` | 10 |
| `github_pat` | `ghp_…` | 10 |
| `github_fine_grained_pat` | `github_pat_…` | 10 |
| `github_app_token` | `ghs_…` | 10 |
| `aws_access_key` | `AKIA…` | 9 |
| `slack_token` | `xoxb/xoxa/xoxp/xoxr/xoxs-…` | 9 |
| `jwt` | `eyJ….….…` 三段式 | 8 |
| `bearer_token` | `Bearer <20+ 字符>` | 7 |
| `email` | 邮箱地址 | 7 |
| `high_entropy` | 高熵字符串（仅 `--min-confidence 4` 时启用） | 4 |

默认阈值是 **7**，所以只显示上面前 10 个 regex 命中；熵检测要显式降低阈值才开，因为它在真实数据上噪点很多（base64 片段、hash、UUID）。

误报抑制器会滤掉明显不是泄漏的命中：转义前缀、保留域名（`example.com` 等）、`noreply` 类本地部分、占位邮箱域名。

**性能**：先用一次廉价的子串扫描判断这行有没有可能命中任何 vendor 前缀，没有就整段跳过 10 个 regex。实测 26 万行 jsonl 里只有 8.2% 含 vendor 前缀，省掉 92% 的检测器开销。

详细原理、误报抑制规则和安全 invariant 见 [`docs/vault.md`](./docs/vault.md) 和 [`docs/secret-scan.md`](./docs/secret-scan.md)。

### `aifd vault cost` — 估算 token 用量 + USD 花费

> **何时用：** 想看你过去一段时间 / 当前进行中的 session 花了多少 token 和钱；按 provider / 月 / project 拆分。  
> **版本：** v0.4

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

### `aifd vault watch` — 实时 secret 检测 daemon

> **何时用：** 后台常驻盯 Claude / Codex 的 session jsonl —— 新行一落地立刻扫 secret，发现立刻推 macOS 通知。  
> **版本：** v0.6（daemon）→ v0.7（events store + webhooks）

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

### `aifd vault watch events` — 持久化事件流

> **何时用：** v0.7 把每条 finding 从内存里的瞬时通知升级到 SQLite 持久化事件流。要在 web UI 里查询历史 / 管理 status / 看 rotation playbook 时用。  
> **版本：** v0.7

```bash
aifd vault watch events list                       # 列所有 finding
aifd vault watch events list --status new          # 只看新发现
aifd vault watch events list --category openai_key
aifd vault watch events list --json                # pipe-friendly

aifd vault watch events show <fingerprint>         # 单条详情 + rotation playbook
aifd vault watch events ack <fingerprint>          # 标记 acknowledged
aifd vault watch events mute <fingerprint> --hours 24
aifd vault watch events resolve <fingerprint>      # 标记已修复
aifd vault watch events export --format ndjson > findings.ndjson
```

示例：

```text
$ aifd vault watch events list
208 finding(s) total, showing 50
STATUS  CAT          SNIPPET        COUNT  LAST SEEN            FINGERPRINT
new     openai_key   sk-J…oNwP          3  2026-06-05T17:01    abc123def456…
new     github_pat   ghp_…ejyW          1  2026-06-05T17:02    7e8a9b0c1d2e…
```

特性：

- **状态机** — `new` / `acknowledged` / `resolved` / `muted`（24h 或永久）；`resolved` 后再出现自动 re-open
- **同一 secret 跨文件 = 同一 issue** — fingerprint 按 `category + redacted_snippet` 哈希
- **Rotation playbook 库** — 11 类 secret（`openai_key` / `anthropic_key` / `github_pat` / `github_oauth` / `aws_access_key` / `aws_secret` / `slack_token` / `jwt` / `gcp_service_account` / `email` / `high_entropy`）+ generic fallback；中英双语；每条附 vendor dashboard 链接 + 撤销步骤 + severity 分级
- **Web UI** — daemon 起一个只绑 `127.0.0.1` 的单页 SPA，点通知直接跳到该 finding 在对话上下文里的高亮位置

`aifd vault watch events show <fingerprint>` 会连着 rotation playbook 一起打出来 —— 发现泄漏后不用再去翻各家文档找「怎么撤销这把 key」。

详见 [`docs/vault-events.md`](./docs/vault-events.md) 和 [`docs/vault-events-integrations.md`](./docs/vault-events-integrations.md)。

### `aifd vault watch webhooks` — 外部报警系统接入

> **何时用：** 想把 finding 推到 Slack / PagerDuty / Datadog / 自家 monitoring 系统时用。  
> **版本：** v0.7

```bash
aifd vault watch webhooks add --url https://hooks.slack.com/services/T/B/X \
    --on new_finding --category openai_key --category github_pat
aifd vault watch webhooks test <id>          # 必须 test 通才能 enable
aifd vault watch webhooks enable <id>        # 默认 disabled（避免错配泄漏）
aifd vault watch webhooks list
aifd vault watch webhooks delete <id>
aifd vault watch webhooks list-dead-letter   # 投递失败队列
aifd vault watch webhooks retry-dead-letter
```

安全 invariant：默认 disabled、必须 test 通才能 enable、payload 永远不含完整 secret（只发 fingerprint + redacted snippet）、retry 限次 + dead letter 队列。

---

## 🧘 反思 — AI Coach

### `aifd ai reflect` — AI Coach：让 LLM 看你怎么用 AI

> **何时用：** 每周一次 —— 把 aifd 累积的 session / cost / question / skill / ship 历史倒过来照镜子，让 LLM 写一段 80-150 字的 meta-cognitive reflection。  
> **版本：** v0.8（LiteLLM 多 provider）

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

**配置文件**（首次跑 `aifd ai reflect` 时自动生成 `~/.aifd/config.yaml`，权限自动 `chmod 600`）：

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

含 `habits:` / `minimax:` 的完整 schema 见 [`~/.aifd/config.yaml` 完整 schema](#aifdconfigyaml-完整-schema)。

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

### `aifd ai habits` — 长期 AI 行为人格画像

> **何时用：** 每季度一次 —— 让 LLM 看你 60-90 天的 session 数据，识别你**自己没意识到**的长期行为模式（如「周五放松崩」「深夜决策次日后悔」「过度规划型」）。  
> **版本：** v0.9

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

---

## 🌌 看 — 把 AI 史变成星图

### `aifd cosmos` — 鼠标拖拽旋转的立体星图

> **何时用：** 想一眼看到「我这几个月的 AI 使用形状」—— 哪些项目是主力、哪些是一次性、深聊和 vibe-coding 的比例。或者单纯想要一张能发到群里的图。
> **版本：** v0.13（2D force-graph）→ **v0.14（2.5D 可旋转，新默认）**

```bash
aifd cosmos                            # 最近 90 天，生成 + 自动开浏览器
aifd cosmos --since 30                 # 最近 30 天
aifd cosmos --since 365                # 最近一年
aifd cosmos --output ~/my-cosmos.html  # 指定输出路径
aifd cosmos --no-open                  # 只生成不开浏览器（CI / 远程机）
aifd cosmos --flat                     # 回到 v0.13 的 2D force-graph
```

输出：

```text
✨ 1106 sessions → aifd-cosmos.html
```

**Flag 参考**

| Flag | 默认值 | 含义 |
|---|---|---|
| `--since N` | `90` | 只包含最近 N 天启动的 session（最小 1） |
| `--output PATH` | `aifd-cosmos.html` | HTML 输出路径 |
| `--open` / `--no-open` | `--open` | 生成后是否自动开浏览器 |
| `--flat` | 关 | 渲染 v0.13 的 2D force-graph 而不是默认 2.5D |

**视觉编码**

| 元素 | 含义 |
|---|---|
| 星点半径 | 该 session 的 event 数（越大 = 交互越多） |
| 冷蓝 | vibe-coding（短 session，event 数低于阈值） |
| 暖红 | 深聊（长 session） |
| 紫色 hub | 一个项目目录；它的 session 环绕它 |
| 拖拽 | 绕轴旋转整片星云（左右 + 上下），近大远小 + 景深 |
| hover | 看该 session 的 provider / 标题 / event 数 |

**2.5D vs 2D（`--flat`）**

| | 默认 2.5D（v0.14） | `--flat` 2D（v0.13） |
|---|---|---|
| 交互 | 拖拽旋转 + 自转 | 力导向布局、缩放、拖节点 |
| 渲染 | 手写 canvas 2D + CPU 三角函数旋转 | vendored force-graph 1.51.4（MIT，内联） |
| 依赖 | 零 vendored lib，不需要 WebGL | 内联 force-graph |
| 适合 | 「我的 AI 宇宙」观感、截图分享 | 看清项目之间的拓扑关系 |

v0.14 之所以是 **2.5D 而不是真 3D**：spike 实测下来，真 3D（Three.js + bloom）在密集数据上必然糊（调了 6 版都白/雾）、WebGL 在受限环境黑屏、还要 600KB CDN。而用户真正要的是「能转动的立体感」——旋转是三角函数 + 透视投影，不是 GPU 特权，canvas 上千个点 CPU 算下来是毫秒级。

**设计约束**

- **隐私**：cwd 只显 basename，session title 里的 home 路径脱敏成 `~` —— 截图 / HTML 分享不泄漏用户名和私有项目名
- **自包含**：所有 JS 内联进 HTML（约 66KB），离线可看，零运行时网络依赖
- **XSS 两层防护**：用户内容过 `html.escape()` + JSON 里的 `</` 转义
- **link 模型**：项目 hub 节点（session 连 hub 而不是两两互连），边数 O(n) 而非 O(n²)，几百个 session 的大项目也不会边爆炸
- **node id** 用 `(provider, session_id)` 复合 key，防跨工具 id 碰撞
- `event_count` **跨工具不可比**（各家 jsonl 的事件粒度不同），只是 aifd 内部的相对指标
- 海报 / PNG 导出还没做（force-graph 无 export API，`devicePixelRatio` 太脆），后续 spike

**没有输出？** `aifd cosmos` 在窗口内没有任何 session 时会明确报错并提示放宽 `--since`，不会生成空白 HTML。

---

## 📉 额度 — 订阅用量

### `aifd quota` — MiniMax Coding Plan 5h 额度

> **何时用：** 用 MiniMax Coding Plan 订阅写代码时，随时查当前 5 小时滚动窗口还剩多少额度，免得写一半被卡。
> **版本：** v0.12

```bash
aifd quota            # 默认查 MiniMax
aifd quota minimax    # 显式指定（等价）
```

输出：

```text
MiniMax 5h: 剩 99%，3h27m 后重置
```

配置 key —— **跟 LLM key 是两回事**。`llm.api_key` 是驱动 `reflect` / `habits` 的模型 key（默认 DeepSeek）；这里是你的 MiniMax coding-plan 订阅凭证，通常是完全不同的一把。aifd 从不拿 `llm.api_key` 兜底：

```bash
export MINIMAX_API_KEY=你的key            # env 优先
```

```yaml
# 或 ~/.aifd/config.yaml
minimax:
  api_key: 你的key
```

**安全设计**：MiniMax key 是 Bearer 凭证，只在发请求那一行被拼进 `Authorization` header。所有错误路径都用 `raise ... from None` 切断异常链，因为 httpx 的原始异常可能带上完整 request（含 Bearer key）。结果是 key 永远不会出现在任何报错、traceback 或日志里 —— 顺带一提，aifd 自己的 `vault scan` 就把 `Bearer <key>` 列为 secret 模式。

**其他行为**

- 查询不消耗你的 prompt 额度
- 有效 key 但没有在跑的订阅 → 明确提示「No active MiniMax Coding Plan」
- 按 `model_name == "general"` 精确选行，不按数组下标（`model_remains[]` 顺序无保证，取 `[0]` 可能拿到 video 窗口）
- 倒计时用服务端返回的 `remains_time`，不用本地时钟 —— 时钟偏移不会污染读数

> best-effort：MiniMax 的 usage 端点未公开文档。若他们改了响应格式，命令会提示「update aifd」而不是抛 stack trace。

---

## 🛠️ 配置与运行时

### `~/.aifd/config.yaml` 完整 schema

只有 `aifd ai reflect` / `aifd ai habits` / `aifd quota` 需要配置。其余命令零配置。

首次跑 `aifd ai reflect` 会自动生成带注释的模板，并 `chmod 600`。文件权限过宽（group / other 可读）时 aifd 会警告但不阻塞。

```yaml
llm:
  # LiteLLM 'provider/model' 格式 —— 换 provider 只改这一行
  model: deepseek/deepseek-chat
  # API key。留空则让 LiteLLM 读 provider 原生 env var
  # (DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY /
  #  ANTHROPIC_API_KEY / OPENAI_API_KEY / MOONSHOT_API_KEY / GROQ_API_KEY ...)
  api_key: sk-xxxxxxxxx
  # 自托管 / 代理 / ollama / Azure 时填；hosted provider 留空走默认 endpoint
  api_base:

reflect:
  default_lang: zh           # en | zh，`aifd ai reflect` 的输出语言
  include_questions: false   # true = 把 question summary 喂给 LLM（仍不发原文）

habits:
  default_days: 90           # `aifd ai habits` 的默认分析窗口（天）；< 1 会被重置为 90

minimax:
  # `aifd quota` 用的 MiniMax Coding Plan key。
  # 跟上面的 llm.api_key 是两把独立的 key，aifd 不会互相兜底。
  api_key:
```

**容错**：文件不存在 → 全部走默认值。YAML 解析失败 → 警告 + 走默认值，不 crash。某个段不是 mapping → 该段走默认值。

### 配置优先级

| 配置项 | 优先级（左 > 右） |
|---|---|
| LLM key | `AIFD_LLM_API_KEY` → `DEEPSEEK_API_KEY`（v0.8 兼容） → `llm.api_key` |
| LLM model | `AIFD_LLM_MODEL` → `llm.model` → `deepseek/deepseek-chat` |
| LLM api_base | `AIFD_LLM_API_BASE` → `llm.api_base` → provider 默认 endpoint |
| MiniMax key | `MINIMAX_API_KEY` → `minimax.api_key`（**绝不**回退到 `llm.api_key`） |
| provider 原生 key | 当 `llm.api_key` 为空时由 LiteLLM 自行发现（`ZHIPUAI_API_KEY` 等） |

命令行 flag（`--model` / `--api-base` / `--lang` / `--since`）压过以上所有来源，只对当次运行生效。

aifd 刻意**不**覆盖 provider 原生的 env var —— LiteLLM 在 `api_key` 为 `None` 时会自己去找，如果 aifd 在这层抢先，用户就没法只靠切 env var 换 provider。

### aifd 在磁盘上写了什么

所有 aifd 自己的状态都在 `~/.aifd/` 下。**aifd 从不写你的 AI 工具数据目录**（`~/.claude/`、`~/.codex/` 等一律只读打开）。

| 路径 | 写入者 | 内容 |
|---|---|---|
| `~/.aifd/config.yaml` | 你（首次由 aifd 生成模板） | LLM / reflect / habits / minimax 配置，`chmod 600` |
| `~/.aifd/webhooks.yaml` | 你 | `vault watch webhooks` 的目标配置 |
| `~/.aifd/watch-state.json` | daemon | 每个文件的扫描进度 + 每日捕获计数。**只存 category + 脱敏片段** |
| `~/.aifd/findings.db` | daemon | SQLite 持久化 finding 事件流（v0.7） |
| `~/.aifd/watch.pid` / `watch.port` | daemon | pid + HTTP 端口，`flock` 防双开 |
| `~/.aifd/watch.log` | daemon | 后台运行时的 stdout / stderr |
| `~/Library/LaunchAgents/*.plist` | `vault watch install` | macOS 开机自启（`uninstall` 会删掉） |
| `aifd-cosmos.html` | `aifd cosmos` | 当前目录下的自包含星图（路径可改） |

状态文件全部用 `tmp + rename` 原子写 —— 半途被 SIGKILL 也不会留下半截 JSON。

### 通用 flag

```bash
aifd --version
aifd --help                 # 任意层级都能 --help
aifd vault watch events --help

aifd ai session list -v     # INFO 日志
aifd ai session list -vv    # DEBUG 日志
aifd ai retro --json        # 几乎所有命令都支持 --json
```

`--json` 是给管道用的：所有查询类命令的 JSON 输出都是稳定 schema，可以直接 `| jq`。

### 当前支持矩阵

**AI 工具 × 能力**

| 工具 | session | token/cost | skill 调用 | question | 数据源 |
|---|---|---|---|---|---|
| **Claude Code** | ✅ | ✅ | ✅ | ✅ | `~/.claude/projects/{encoded-cwd}/*.jsonl` |
| **Codex** | ✅ | ✅ | ✅ | ➖ | `~/.codex/state_5.sqlite` + `~/.codex/sessions/` 兜底 |
| **OpenCode** (v0.10) | ✅ | ✅ | ➖ | ➖ | `~/.local/share/opencode/opencode.db` |
| **Cursor** (v0.11) | ✅ | ✅ | ➖ | ➖ | `globalStorage/state.vscdb` + `workspaceStorage/` |

➖ = 该工具没有对应的结构化数据，命令返回空而不是报错。Codex 的 `agent_message` 和 OpenCode 的消息都是自由文本，没有结构化的「问用户」事件；要覆盖这类纯文本提问需要启发式抽取，会引入 noise，所以路线上选了**精度优先**。理由详见 [`docs/question-extraction.md`](./docs/question-extraction.md)。

**已装 skill 列举**（`aifd ai claude skill list` / `aifd ai codex skill list`）目前覆盖 Claude Code 和 Codex；OpenCode 的 skill 目录（`~/.config/opencode/skills`）已识别但尚未接进 CLI。

**Cursor 的特殊之处**：其他三家都把 cwd 当一等公民存成字段，能直接 `WHERE directory = ?`；Cursor 把 session（globalStorage）和 cwd（workspaceStorage）拆进两个互不引用的 store，必须跨 store JOIN，SQL 层没法按 cwd 收窄。实测 hash 映射覆盖约 80% 的真实 session（时间戳形式的 id 在磁盘上没有对应 workspace），没映射上的会在 stderr 打一行计数。另外 Cursor 是活的 Electron 应用，边写 WAL 边被我们读，所以是 `mode=ro` 打开、锁冲突重试一次后静默跳过。Windows 路径支持还没做，见 [TODOS.md](./TODOS.md)。

**LLM provider（经 LiteLLM）**

| provider | `reflect` / `habits` | 备注 |
|---|---|---|
| DeepSeek（默认）、智谱 GLM、阿里通义 DashScope、火山方舟 Ark、Moonshot Kimi | ✅ | 国内 provider，`provider/model` 格式 |
| OpenAI、Anthropic、Gemini、Groq、Together、Fireworks | ✅ | |
| ollama / vLLM / Azure OpenAI / 公司 OpenAI-compat 代理 | ✅ | 需要 `--api-base` 或 `llm.api_base` |

理论上 LiteLLM 支持的 100+ provider 都能用 —— aifd 不维护自己的 provider 列表，只是转发 `provider/model` 字符串。

---

## 🔒 数据来源与隐私

### aifd 读哪些文件

aifd 全部以**只读**方式打开这些路径。它不创建、不修改、不删除你的 AI 工具数据。

| 工具 | 会话数据 | 已装 skill |
|---|---|---|
| Claude Code | `~/.claude/projects/{encoded-cwd}/*.jsonl` | `~/.claude/skills/`、`~/.claude/plugins/cache/` |
| Codex | `~/.codex/state_5.sqlite`（主）+ `~/.codex/sessions/`（兜底） | `~/.codex/skills/` |
| OpenCode | `~/.local/share/opencode/opencode.db` | `~/.config/opencode/skills/` |
| Cursor (macOS) | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` + `workspaceStorage/` | — |
| Cursor (Linux) | `$XDG_CONFIG_HOME/Cursor/User/`（或 `~/.config/Cursor/User/`） | — |
| Cursor (Windows) | `%APPDATA%/Cursor/User/` —— **尚未支持**，见 TODOS.md | — |

**单个文件解析失败必须静默跳过**（日志降到 `warning` / `debug`），永远不 raise —— 一个坏文件不能让整张表挂掉。这是 provider 层的硬约束，也是新 provider PR 的验收项。

### 隐私 invariant

这几条是硬保证，有测试守着：

1. **完整 secret 值永不离开检测器**。`SensitiveMatch` 数据类只存脱敏片段（首 4 + 尾 4 字符）。终端输出、`--json`、`watch.log`、`watch-state.json`、`findings.db`、webhook payload —— 一律只有脱敏片段。`aifd vault scan --json` 的结果可以直接贴给同事 debug。
2. **发给 LLM 的 prompt 里没有你的内容**。`reflect` / `habits` 只发聚合后的统计维度：
   - 不发 session message 内容
   - 不发 AskUserQuestion 的原文和你的答案原文
   - 不发完整 cwd 路径（**只发 basename**）
   - `--include-questions` 是 opt-in，而且也只发 summary，**不**发原文
   - `render_prompt` 出口跑一遍 `_scan_line` 兜底校验：prompt 里出现任何 v0.4 detector 能命中的 secret pattern，测试即失败
3. **HTTP server 只绑 `127.0.0.1`**，不是 `0.0.0.0` —— LAN 上其它机器碰不到 finding 页面。通知 URL 里的 token 是 `secrets.token_urlsafe(32)`（约 256 bit，不可猜）。
4. **分享出去的产物已脱敏**。`aifd cosmos` 的 HTML 和 `aifd ai question list --output` 的 HTML 里，cwd 只有 basename，home 路径脱敏成 `~`；所有用户文本过 `html.escape()`，历史里有 `<script>` 字符串也不会 XSS。
5. **webhook 只发 fingerprint + 脱敏片段**，且默认 disabled，必须 `test` 通过才能 enable —— 避免配错地址就把告警推到错误的地方。

### 什么时候会联网

aifd 默认完全离线。只有这三种情况会发出网络请求，都是你显式触发的：

| 命令 | 目标 | 发出去的内容 |
|---|---|---|
| `aifd ai reflect` / `aifd ai habits` | 你配置的 LLM provider | 聚合统计维度（见上面第 2 条），约 $0.001/次 |
| `aifd quota` | MiniMax usage 端点 | 一个 Bearer header，无 body |
| `aifd vault watch webhooks` | 你配置的 webhook URL | fingerprint + category + 脱敏片段 |

其余所有命令 —— `session list` / `skill list` / `question list` / `today` / `weekly` / `monthly` / `retro` / `vault scan` / `vault cost` / `cosmos` —— **零网络请求**。`cosmos` 生成的 HTML 也把 JS 全部内联，打开时不发任何请求。

---

## ❓ 常见问题排查

**`aifd ai session list` 什么都不显示**

默认是**精确匹配**当前目录，不递归子目录。确认你在跑过 AI session 的那个目录里。用 `aifd ai session list -vv` 看 DEBUG 日志，能看到它扫了哪些路径、跳过了什么。跨目录看用 `aifd ai skill list`（默认全局）或 `aifd ai weekly`。

**`aifd ai question list` 对 Codex / OpenCode / Cursor 返回空**

预期行为，不是 bug。只有 Claude Code 有结构化的 `AskUserQuestion` 工具调用事件。见[当前支持矩阵](#当前支持矩阵)。

**`aifd vault cost` 里某些行 cost 是 $0，但 token 数不为 0**

那个 model 不在价格表里。跑 `aifd vault cost --list-models` 看表里有什么，然后提个 issue（或 PR）补上 `aifd/vault/prices.py`。aifd 刻意显示 token 但不瞎猜价格。

**`vault watch` 装了但收不到通知**

按顺序排查：

1. `aifd vault watch status` —— daemon 在跑吗？用的是哪个 notify backend？
2. 没装 `terminal-notifier` 的话 `brew install terminal-notifier`。fallback 的 `osascript` 会让**点击通知打开「脚本编辑器」**而不是浏览器，这是 AppleScript `display notification` 的已知限制（不支持自定义点击回调）。
3. 系统设置 → 通知 → 允许 Terminal / terminal-notifier，然后 `aifd vault watch stop && aifd vault watch start`。
4. 还不行就前台跑看日志：`aifd vault watch start --foreground -vv`。

daemon 首次启动会发一条「Watch daemon started — notifications working.」测试通知。看不到这条就是通知权限问题，跟检测逻辑无关。

**Linux 上 `aifd vault watch install` 报错**

`install` / `uninstall` 是 macOS-only（走 launchd）。Linux 用 `systemctl --user` 跑 `aifd vault watch daemon`，`.service` 模板在 [`docs/vault-watch.md`](./docs/vault-watch.md)。检测逻辑本身跨平台（watchdog 封装了 inotify）。

**`ModuleNotFoundError: No module named 'litellm'`（但 `uv run aifd` 能跑）**

editable 安装的 dep trap。见 [Editable 安装的 dep trap](#editable-安装的-dep-trap)。

**`aifd ai reflect` 报没有 API key**

设一个 env var（`export DEEPSEEK_API_KEY=sk-...`）或编辑 `~/.aifd/config.yaml` 的 `llm.api_key`。首次跑 `aifd ai reflect` 会自动生成模板文件。优先级见[配置优先级](#配置优先级)。

没有 key 也不会崩 —— 会降级成 structured local report 加一句清楚的错误信息。401 / 5xx / 超时同理。

**`aifd quota` 说 "No active MiniMax Coding Plan"**

key 有效但这把 key 名下没有在跑的 coding plan 订阅。确认 `MINIMAX_API_KEY` 是 coding-plan 的 key，而不是普通 API key（也不是你 `llm.api_key` 那把）。

**`aifd cosmos` 报 "No sessions found"**

窗口内没有 session。放宽窗口：`aifd cosmos --since 365`。

**Cursor 的 session 少了一些**

已知限制：cwd 靠 workspace hash 映射，实测覆盖约 80%；时间戳形式的 composer id 在磁盘上没有对应的 workspace 目录，映射不出 cwd。没映射上的数量会在 stderr 打一行。另外只有出现在 `bubbleId:*` 里（有真实对话内容）的 composer 才算 session —— 其余约 80% 的 `composerData` 行是草稿和迁移残留，Cursor 自己的 UI 也不显示。

---

## 🏗️ 架构与贡献

### 架构

三条分层原则：

1. **每个 AI 工具一个 adapter**，放在 `aifd/providers/` 下，都实现同一个 `Provider` Protocol。上层命令不知道 Claude 和 Cursor 的存储差异有多大。
2. **业务逻辑跟渲染分离**。`vault/` 和 `insights/` 只算数据，`render*.py` 只管 rich Table / JSON / HTML 三种出口。所以「加一个 `--json`」永远是几行。
3. **CLI 分三层**（`aifd ai session list`），给未来的 `session show` / `session resume` / `ai prompt` 留了名字空间。

```text
aifd/
├── cli/                         # CLI 层：只解析参数 + 调业务层 + 选渲染器
│   ├── __init__.py              # 顶层 `aifd` group（ai / cosmos / quota / vault）
│   ├── _logging.py              # 所有命令共享的 -v / -vv 日志配置
│   ├── _runner.py               # 共享的 provider-query 框架（v0.3）
│   ├── cosmos.py                # aifd cosmos                                v0.13-0.14
│   ├── quota.py                 # aifd quota / quota minimax                 v0.12
│   ├── ai/
│   │   ├── session.py           # aifd ai session list                       v0.1
│   │   ├── skill.py             # aifd ai skill list                         v0.2
│   │   ├── question.py          # aifd ai question list（+ HTML v0.3.1）      v0.3
│   │   ├── retro.py             # aifd ai today / weekly / monthly / retro    v0.5
│   │   ├── reflect.py           # aifd ai reflect                            v0.8
│   │   ├── habits.py            # aifd ai habits                             v0.9
│   │   ├── claude/skill.py      # aifd ai claude skill list                  v0.2.1
│   │   └── codex/skill.py       # aifd ai codex skill list                   v0.2.1
│   └── vault/
│       ├── scan.py              # aifd vault scan                            v0.4
│       ├── cost.py              # aifd vault cost                            v0.4
│       └── watch.py             # aifd vault watch + events + webhooks       v0.6-0.7
│
├── providers/                   # 每个 AI 工具一个 adapter
│   ├── base.py                  # Provider Protocol —— 新 provider 的契约
│   ├── registry.py              # PROVIDERS 列表；注册新 provider 的唯一入口
│   ├── _utils.py                # 共享正则 / skill 命名归一 / frontmatter 解析
│   ├── claude.py                # Claude Code（session / skill / question / token）
│   ├── codex.py                 # Codex（sqlite 主 + jsonl 兜底）
│   ├── opencode.py              # OpenCode                                   v0.10
│   └── cursor.py                # Cursor（跨 store JOIN + WAL 只读）           v0.11
│
├── insights/                    # AI Coach 业务逻辑                          v0.8-0.9
│   ├── activity.py              # session 聚合 + 公共 iter_sessions_in()
│   │                            #   （reflect / habits / cosmos 三处共用）
│   ├── reflection.py            # reflect 的 9 个维度计算
│   ├── reflection_prompt.py     # reflect prompt 组装 + secret 出口校验
│   ├── reflection_source.py     # reflect 的数据源适配
│   ├── habits.py                # habits 的 8 个维度计算
│   ├── habits_prompt.py         # habits prompt 组装
│   └── llm_client.py            # LiteLLM wrapper（100+ provider 路由 + 降级）
│
├── vault/                       # 数据主权业务逻辑                           v0.4-0.7
│   ├── scan.py                  # 10 个 regex detector + 熵检测 + 误报抑制
│   ├── prices.py                # model → USD 价格表
│   ├── cost.py                  # 聚合 token → $
│   ├── playbooks.py             # 11 类 secret 的 rotation 步骤库（中英双语）
│   ├── watch.py                 # daemon 主循环（watchdog 文件事件）
│   ├── watch_server.py          # 只绑 127.0.0.1 的 finding 详情 HTTP server
│   ├── watch_state.py           # ~/.aifd/ 下的原子状态文件读写
│   ├── events_db.py             # SQLite 事件流 + 状态机                     v0.7
│   ├── webhooks.py              # 出站推送 + retry + dead letter             v0.7
│   └── static/                  # watch web UI 单页 SPA
│
├── assets/                      # vendored force-graph 1.51.4（MIT），打进 wheel
├── config.py                    # ~/.aifd/config.yaml 读写 + env 优先级 + 0600
├── models.py                    # Session / SkillInvocation / SkillStats /
│                                # InstalledSkill / QuestionAnswer / TokenUsage /
│                                # CostRow / SensitiveMatch
├── paths.py                     # cwd 归一化（跨 provider 的目录比较）
├── aggregation.py               # skill 统计聚合                             v0.2
├── render.py                    # rich Table / JSON / HTML 渲染
├── render_cosmos.py             # cosmos 数据层 build_graph + 2D force-graph  v0.13
└── render_cosmos_25d.py         # cosmos 2.5D canvas 渲染（v0.14 默认）       v0.14
```

### 贡献一个新 provider

1. 新建 `aifd/providers/yourtool.py`，实现 `aifd/providers/base.py` 里的 `Provider` Protocol。
2. 把你的 provider 实例追加到 `aifd/providers/registry.py` 的 `PROVIDERS` 列表。
3. 在 `tests/conftest.py` 加一个 fixture factory（参考 `opencode_db` / `codex_db`），写 `tests/test_yourtool_provider.py`。
4. 确认 `uv run pytest`、`uv run ruff check aifd/ tests/`、`uv run mypy aifd/` 全过。

`aifd/providers/opencode.py`（v0.10）是「一个文件 + 一行注册」最干净的范例。
如果你的工具存储结构更别扭（session 和 cwd 分在两个 store、边写边读），参考 `cursor.py`（v0.11）—— 它把这类问题的处理方式都写在文件头的 docstring 里了。

**硬约束**：

- **单文件解析错误必须 silent skip**（log 在 `warning` 或 `debug` 级别），永远不能 raise —— 一个坏文件不能让整个列表挂掉。
- **只读**打开一切外部数据。活的应用（Cursor / OpenCode）在写 SQLite WAL，用 `mode=ro`，锁冲突重试一次后跳过。
- **不支持的能力返回空列表**，不要抛 `NotImplementedError` —— 上层是跨 provider 聚合的，一家不支持不该影响其他家。

### 开发

```bash
git clone https://github.com/xunull/aifd
cd aifd
uv sync

uv run pytest                       # 744 个测试
uv run pytest --cov=aifd            # 带覆盖率
uv run pytest -m live_api           # 真打 LLM API 的测试（需 provider key，默认跳过）
uv run ruff check aifd/ tests/      # lint
uv run mypy aifd/                   # 类型检查（strict）

uv run aifd ai session list         # 不装到 PATH 直接跑
```

仓库带 `.pre-commit-config.yaml`，挂的是 [gitleaks](https://github.com/gitleaks/gitleaks) —— 每次 commit 前扫暂存区，挡住误提交的 API key。一个扫 secret 的工具自己也该被 secret 扫描守着：

```bash
pre-commit install
```

### 测试与 CI

| 项 | 现状 |
|---|---|
| 测试数 | **744**（`uv run pytest`） |
| CI 矩阵 | ubuntu / macOS / Windows × Python 3.12 / 3.13 = **6 个组合**，`fail-fast: false` |
| 门禁 | `ruff check` → `mypy aifd/`（strict）→ `pytest --cov` 全绿才算过 |
| live API 测试 | 打 `live_api` 标记，默认跳过；需要 provider key + 显式 `pytest -m live_api` |
| 发布 | 打 `v*` tag 触发 `release.yml`，构建前先校验 tag 与 `pyproject.toml` 版本一致，不一致直接 fail |

mypy 是 **strict** 模式（`warn_unused_ignores` + `warn_return_any` 都开着），ruff 选了 `E, F, W, I, B, UP, RUF` 规则集，行宽 100。中文 prose（rotation playbook、LLM prompt）里的全角标点是刻意的，在 `pyproject.toml` 里按文件豁免了 `RUF001-003`。

#### Editable 安装的 dep trap

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

---

## 🧭 版本历程

一条主线：先能**查**，再能**算**，再能**防**，最后能**反思**和**看见**。

| 版本 | 带来了什么 | 一句话 |
|---|---|---|
| v0.1 | `aifd ai session list` | 按目录列 session —— 全部功能的地基 |
| v0.2 | `aifd ai skill list` | 跨工具 skill 统计；跨 provider 命名归一 |
| v0.2.1 | `ai claude/codex skill list` | 列出已装的 skill（user / plugin / system） |
| v0.3 | `aifd ai question list` | 复盘 AskUserQuestion 历史 + recommended hit rate |
| v0.3.1 | `--open` / `--html` / `--output` | 长 question 在终端看不全，弹浏览器看 |
| v0.4 | `aifd vault scan` / `cost` | secret / PII 扫描 + token → USD 估算 |
| v0.5 | `today` / `weekly` / `monthly` / `retro` | 活动 retrospective + 环比 + 月度投影 |
| v0.6 | `aifd vault watch` | 从事后查升级为事前防：常驻 daemon + macOS 通知 |
| v0.7 | `watch events` / `watch webhooks` | 持久化事件流（SQLite）+ 状态机 + 外部报警接入 |
| v0.8 | `aifd ai reflect` | AI Coach：每周 meta-cognitive 反思，经 LiteLLM 路由 |
| v0.9 | `aifd ai habits` | 60-90 天行为人格画像：你是什么类型的 AI 用户 |
| v0.10 | OpenCode provider | 第三个工具接入 |
| v0.11 | Cursor provider | 第四个工具接入（跨 store JOIN 的硬骨头） |
| v0.12 | `aifd quota` | MiniMax Coding Plan 5h 窗口剩余额度 |
| v0.13 | `aifd cosmos` | AI 史 → 力导向星系图，自包含 HTML |
| v0.13.1-0.13.2 | 视觉打磨 + 性能修复 | 辉光星点；去掉 `shadowBlur` 修卡死（单帧 5s → 1.6ms） |
| **v0.14** | **cosmos 2.5D 默认** | 鼠标拖拽旋转的立体星图；`--flat` 保留 2D |

完整变更记录见 [CHANGELOG.md](./CHANGELOG.md)，下一步计划见 [TODOS.md](./TODOS.md)。

---

## License

Apache-2.0 — 见 [LICENSE](./LICENSE)。

vendored 的 force-graph 1.51.4 是 MIT，license 原文在 [`aifd/assets/force-graph.LICENSE`](./aifd/assets/force-graph.LICENSE)。

## 相关文档

**命令规格**

- [`docs/ai-reflect.md`](./docs/ai-reflect.md) — `aifd ai reflect` 完整规格（9 个维度 + privacy invariant）
- [`docs/ai-habits.md`](./docs/ai-habits.md) — `aifd ai habits` 完整规格（8 个维度）
- [`docs/ai-retro.md`](./docs/ai-retro.md) — `aifd ai today / weekly / monthly / retro` 完整规格
- [`docs/vault.md`](./docs/vault.md) — `aifd vault` 整体设计
- [`docs/vault-watch.md`](./docs/vault-watch.md) — `aifd vault watch` 完整规格（含 Linux systemd 模板）
- [`docs/vault-events.md`](./docs/vault-events.md) — `aifd vault watch events / webhooks` 完整规格

**算法与实现**

- [`docs/question-extraction.md`](./docs/question-extraction.md) — `aifd ai question list` 的抽取算法与精度取舍
- [`docs/secret-scan.md`](./docs/secret-scan.md) — secret 检测器、误报抑制与安全 invariant
- [`docs/cost-calculation.md`](./docs/cost-calculation.md) — token 计价模型与各家 cache 语义差异
- [`docs/skill-detection.md`](./docs/skill-detection.md) — 跨工具 skill 调用识别与命名归一
- [`docs/vault-watch-lifecycle.md`](./docs/vault-watch-lifecycle.md) — daemon 生命周期、launchd 交互、崩溃恢复
- [`docs/vault-events-integrations.md`](./docs/vault-events-integrations.md) — webhook payload 格式与 Slack / PagerDuty / Datadog 接法

**项目维护**

- [`docs/release.md`](./docs/release.md) — 发版流程
- [`docs/claude-code-plugin-update.md`](./docs/claude-code-plugin-update.md) — Claude Code plugin 结构变更的适配记录
- [`CHANGELOG.md`](./CHANGELOG.md) — 版本变更
- [`TODOS.md`](./TODOS.md) — 路线图 + 已知 follow-up

## 反馈

Issues / discussions / PR 都欢迎：<https://github.com/xunull/aifd>

想加一个新 AI 工具的支持？从[贡献一个新 provider](#贡献一个新-provider) 开始，通常一个文件就够了。

[⬆ 回到顶部](#aifd)
