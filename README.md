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

## License

Apache-2.0
