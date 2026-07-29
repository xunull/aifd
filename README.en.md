# aifd

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/aifd.svg)](https://pypi.org/project/aifd/)

**English** | [简体中文](./README.md)

> An AI coding history browser across Claude Code / Codex / OpenCode / Cursor + secret scanning + LLM coach.
> Answer questions like "my directories / the skills I've used / what AI asked me / how much I spent / what kind of AI user am I" with a single command.

Every AI coding tool stores its history in its own private format. `aifd` aggregates data from every tool **from your point of view**: by directory, by skill, by question, by spend, by behavior pattern -- not by tool.

```text
query → compute → scan → watch → reflect → see
session / skill / question → cost / token → secret / PII → live daemon → AI Coach → star map
```

**Three facts** that decide whether this is for you:

1. **Read-only, offline, local.** aifd never writes to your AI tools' data directories, and needs no network -- unless you explicitly run `aifd ai reflect` / `habits` (calls an LLM) or `aifd quota` (checks your subscription).
2. **Full secret values never appear in any output.** Scan results, JSON, logs, webhook payloads, LLM prompts -- all carry redacted snippets only (first 4 + last 4 chars).
3. **Adding a new AI tool = one file + one line of registration.** See [Contribute a new provider](#contribute-a-new-provider).

Current version **v0.14.0**, Python 3.12+, 744 tests running across 3 operating systems × 2 Python versions.

---

## 📑 Table of Contents

### ✨ [Highlights (8 screenshots)](#-highlights-gif-style)

### 🚀 [Quick Start](#-quick-start)
- [Install](#-install) · [One-minute try](#-one-minute-try)

### 📋 [Full command tree](#-full-command-tree)

### 🔍 [Query - list your history](#-query---list-your-history)
| Command | One-liner | Version |
|---|---|---|
| [`aifd ai session list`](#aifd-ai-session-list---list-sessions-by-directory) | List all AI sessions in the current directory | v0.1 |
| [`aifd ai question list`](#aifd-ai-question-list---review-the-questions-ai-asked-you) | Review AskUserQuestion history + recommended hit rate | v0.3 |
| [`aifd ai skill list`](#aifd-ai-skill-list---cross-tool-skill-usage-stats) | Cross-tool skill usage stats + top ranking | v0.2 |
| [`aifd ai claude skill list`](#aifd-ai-claude-skill-list--aifd-ai-codex-skill-list---list-installed-skills) / [`aifd ai codex skill list`](#aifd-ai-claude-skill-list--aifd-ai-codex-skill-list---list-installed-skills) | List installed Claude / Codex skills | v0.2.1 |

### 📊 [Compute - activity retrospective](#-compute---activity-retrospective)
| Command | One-liner | Version |
|---|---|---|
| [`aifd ai today`](#aifd-ai-today--weekly--monthly--retro---activity-retrospective) | Today's activity summary (session / cost / token / skill) | v0.5 |
| [`aifd ai weekly`](#aifd-ai-today--weekly--monthly--retro---activity-retrospective) | Rolling 7-day window | v0.5 |
| [`aifd ai monthly`](#aifd-ai-today--weekly--monthly--retro---activity-retrospective) | Current-month activity summary | v0.5 |
| [`aifd ai retro --since YYYY-MM-DD`](#aifd-ai-today--weekly--monthly--retro---activity-retrospective) | Custom-range retrospective | v0.5 |

### 🔐 [Scan - secret / PII leak prevention](#-scan---secret--pii-leak-prevention)
| Command | One-liner | Version |
|---|---|---|
| [`aifd vault scan`](#aifd-vault-scan---scan-for-pii--secret-leaks) | One-shot scan of all session jsonl for secret / PII | v0.4 |
| [`aifd vault cost`](#aifd-vault-cost---estimate-token-usage--usd-spend) | Estimate token usage + USD spend (with history trend) | v0.4 |
| [`aifd vault watch`](#aifd-vault-watch---real-time-secret-detection-daemon) | Background daemon: scan new session lines for secrets in real time + macOS notification | v0.6 |
| [`aifd vault watch events`](#aifd-vault-watch-events---persistent-event-stream) | Persistent event stream (SQLite) + web UI + state machine | v0.7 |
| [`aifd vault watch webhooks`](#aifd-vault-watch-webhooks---external-alerting-integration) | Push webhooks to Slack / PagerDuty / Datadog | v0.7 |

### 🧘 [Reflect - AI Coach](#-reflect---ai-coach)
| Command | One-liner | Version |
|---|---|---|
| [`aifd ai reflect`](#aifd-ai-reflect---ai-coach-let-the-llm-see-how-you-use-ai) | Weekly, have the LLM write an 80-150 word meta-cognitive reflection | v0.8 |
| [`aifd ai habits`](#aifd-ai-habits---long-term-ai-behavior-persona) | 60-90 day long-term behavior persona (what kind of AI user are you) | v0.9 |

### 🌌 [See - turn your AI history into a star map](#-see---turn-your-ai-history-into-a-star-map)
| Command | One-liner | Version |
|---|---|---|
| [`aifd cosmos`](#aifd-cosmos---a-drag-to-rotate-25d-star-map) | Generate a drag-to-rotate 2.5D star map (self-contained HTML, works offline) | v0.13 → v0.14 |

### 📉 [Quota - subscription usage](#-quota---subscription-usage)
| Command | One-liner | Version |
|---|---|---|
| [`aifd quota`](#aifd-quota---minimax-coding-plan-5h-quota) | MiniMax Coding Plan 5-hour rolling-window remaining quota | v0.12 |

### 🛠️ [Configuration and runtime](#%EF%B8%8F-configuration-and-runtime)
- [Full `~/.aifd/config.yaml` schema](#full-aifdconfigyaml-schema) · [Config precedence](#config-precedence) · [What aifd writes to disk](#what-aifd-writes-to-disk) · [Common flags](#common-flags) · [Current support matrix](#current-support-matrix)

### 🔒 [Data sources and privacy](#-data-sources-and-privacy)
- [What files aifd reads](#what-files-aifd-reads) · [Privacy invariants](#privacy-invariants) · [When aifd touches the network](#when-aifd-touches-the-network)

### ❓ [Troubleshooting](#-troubleshooting)

### 🏗️ [Architecture and contributing](#%EF%B8%8F-architecture-and-contributing)
- [Architecture](#architecture) · [Contribute a new provider](#contribute-a-new-provider) · [Development](#development) · [Tests and CI](#tests-and-ci) · [The editable-install dep trap](#the-editable-install-dep-trap)

### 🧭 [Version timeline](#-version-timeline)

---

## ✨ Highlights (gif style)

Eight commands, eight different questions. Every output below is real (numbers scrubbed).

**1. List sessions by directory (v0.1)**

```text
$ aifd ai session list                # run inside any project directory
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Provider ┃ Session  ┃ Started ┃ Events ┃ Title            ┃ Source           ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ claude   │ bbfc1d21 │  2h ago │    781 │ Install Claude … │ ~/.claude/p…     │
│ codex    │ 019e7d19 │  1d ago │      0 │ 审计计划完成情况 │ ~/.codex/se…     │
│ opencode │ ses_148b │ 15h ago │      0 │ 查找出站连接代码 │ ~/.local/sh…     │
└──────────┴──────────┴─────────┴────────┴──────────────────┴──────────────────┘
```
*(the CLI prints in Chinese; titles are pulled verbatim from your real sessions)*

**2. Review the questions AI asked you (v0.3)**

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
*(question and choice text are echoed from your real history, so they show up in Chinese here)*

**3. Cross-tool skill usage stats (v0.2)**

```text
$ aifd ai skill list                  # global by default; --cwd limits to the current directory
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Skill           ┃ Claude ┃ Codex ┃ Total ┃ Last Used ┃ Projects ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ plan-ceo-review │      9 │    32 │    41 │    2h ago │       11 │
│ office-hours    │     13 │    20 │    33 │   11h ago │       17 │
│ model           │     16 │     0 │    16 │    4h ago │       11 │
└─────────────────┴────────┴───────┴───────┴───────────┴──────────┘
```

**4. Activity retrospective for today / this week / custom range (v0.5)**

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

There's also `aifd ai weekly` / `monthly` / `retro --since YYYY-MM-DD`, all supporting `--json`. See `docs/ai-retro.md` for details.

**5. Real-time secret detection + webhook push (v0.6 → v0.7)**

```text
$ aifd vault watch install            # launchd auto-start
$ aifd vault watch events list        # persistent event stream
$ aifd vault watch webhooks add --url https://hooks.slack.com/...
```

A background daemon watches session jsonl files; the moment a new line lands it scans for secrets, and on a hit it pushes a macOS notification + persists to SQLite + pushes a webhook to Slack/PagerDuty. See the [`aifd vault watch`](#aifd-vault-watch---real-time-secret-detection-daemon) section.

**6. AI Coach - weekly reflection (v0.8)**

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
*(the LLM writes in your configured language; `--lang en` produces English)*

**7. AI behavior persona - long-term patterns (v0.9)**

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
*(LLM output; use `--lang en` for English)*

`reflect` answers "how was this week"; `habits` answers "**what kind of AI user am I**". LLM routing goes through [LiteLLM](https://github.com/BerriAI/litellm) across 100+ providers (DeepSeek / Zhipu / Tongyi / Ark / Anthropic / OpenAI / Gemini / ollama / vLLM / Azure). See [`aifd ai reflect`](#aifd-ai-reflect---ai-coach-let-the-llm-see-how-you-use-ai) / [`aifd ai habits`](#aifd-ai-habits---long-term-ai-behavior-persona).

**8. Your AI universe - a drag-to-rotate star map (v0.13 → v0.14)**

```text
$ aifd cosmos
✨ 1106 sessions → aifd-cosmos.html
```

```text
              ·  ✦        ·
        ✦   ·      ●aifd        ·   ✦          ← purple hub = a project
   ·        ✦   ·   ·  ✦   ·        ·
      ●gstack   ·  ✦  ·      ●dotfiles  ✦      ← blue star = vibe-coding
   ✦     ·   ✦      ·    ✦      ·   ·          ← red star = deep session
        ·       ✦        ·      ✦
   [ hold and drag → the cloud rotates around its axis ]
```

Every session is a star (radius = event count, cool blue = vibe-coding, warm red = deep session); every project is a hub it orbits.
**Hold the mouse and drag to rotate** (2.5D is the v0.14 default; `--flat` returns to the v0.13 2D force-graph).
Output is 66KB of self-contained HTML -- works offline, zero network calls, and cwd shows only the basename so sharing a screenshot leaks no project names.
See [`aifd cosmos`](#aifd-cosmos---a-drag-to-rotate-25d-star-map).

---

## 🚀 Quick Start

### 📦 Install

```bash
# Recommended: pipx (isolated venv, tool-level install)
pipx install aifd

# Or: uv tool (recommended for uv users)
uvx aifd ai session list   # one-off trial run
uv tool install aifd       # persistent install

# Or: pip (no venv isolation, may conflict with project deps)
pip install aifd
```

Requires **Python 3.12+**.

### ⚡ One-minute try

Run it in any project directory that has AI session history:

```bash
# 1. See which AI sessions you've run in this project
aifd ai session list

# 2. See total activity over the past 7 days (cost / token / top skills)
aifd ai weekly

# 3. Scan all sessions for leaked secrets
aifd vault scan

# 4. Review AskUserQuestion history + recommended hit rate
aifd ai question list --cwd --limit 10

# 5. Render your AI history as a drag-to-rotate star map
aifd cosmos
```

All five need **zero configuration and no API key** -- they read the AI tool data already on your machine.

The **AI Coach (`reflect` / `habits`)** is the only thing that needs an LLM API key; see [Full `~/.aifd/config.yaml` schema](#full-aifdconfigyaml-schema).
`aifd quota` needs a MiniMax coding-plan key (a different credential from the LLM key).

**None of them printed anything?** Most likely aifd doesn't support the tool you use yet, or the current directory has no history. Jump to [Troubleshooting](#-troubleshooting).

---

## 📋 Full command tree

Every command in v0.14. Four top-level groups: `ai` (cross-tool query and reflection), `vault` (data sovereignty), `cosmos` (visualization), `quota` (subscription usage).

```text
aifd
├── ai                                  operations across AI tools
│   ├── session list                    list sessions for the current dir       v0.1
│   ├── skill list                      cross-tool skill usage stats            v0.2
│   ├── question list                   review AskUserQuestion history (+HTML)  v0.3
│   ├── claude skill list               list installed Claude skills            v0.2.1
│   ├── codex skill list                list installed Codex skills             v0.2.1
│   ├── today                           today's activity summary                v0.5
│   ├── weekly                          rolling 7-day window                    v0.5
│   ├── monthly                         current-month activity summary          v0.5
│   ├── retro --since/--until           custom-range retrospective              v0.5
│   ├── reflect                         weekly meta-cognitive reflection (LLM)  v0.8
│   └── habits                          60-90 day behavior persona (LLM)        v0.9
│
├── vault                               data sovereignty: scan / cost / watch
│   ├── scan                            one-shot secret / PII scan              v0.4
│   ├── cost                            token usage + USD estimate              v0.4
│   └── watch                           real-time secret detection daemon       v0.6
│       ├── install / uninstall         register / remove launchd autostart (macOS)
│       ├── start / stop / status       start-stop + pid / port / catches today
│       ├── tail                        follow ~/.aifd/watch.log
│       ├── events                      persistent finding event stream         v0.7
│       │   ├── list / show             list / inspect one (with rotation playbook)
│       │   ├── ack / mute / resolve    state-machine transitions
│       │   └── export                  export NDJSON
│       └── webhooks                    external alerting integration           v0.7
│           ├── add / delete / list     create, remove, list
│           ├── test                    send a test event (must pass to enable)
│           ├── enable / disable        toggle one webhook
│           └── list-dead-letter        failed-delivery queue + retry-dead-letter
│
├── cosmos                              AI history → rotatable 2.5D star map    v0.13 → v0.14
│
└── quota                               subscription usage (defaults to MiniMax) v0.12
    └── minimax                         MiniMax Coding Plan 5h window
```

`--help` works at every level: `aifd vault watch events --help`.

---

## 📚 Full command reference

Below, commands are grouped into six buckets: **query → compute → scan → reflect → see → quota**. Each section opens with a one-liner + when to use it, followed by detailed flags and examples.

---

## 🔍 Query - list your history

### `aifd ai question list` - review the questions AI asked you

> **When to use:** You want to see every question AI asked you, what you picked, and whether it matched the recommendation.  
> **Version:** v0.3 (HTML rendering v0.3.1)

The most interesting command. It lists every question Claude Code asked in each `AskUserQuestion` tool call, along with your choice. **Main uses:**

- "What key decisions did AI ask me about last week? What did I pick for each?"
- "What fraction of the time did I follow the recommended option vs go against it?"
- "Last time in another project I was asked about topic X -- what did I choose then?"

#### Basic usage

```bash
# Global: list every question AI asked across all projects (latest 50 by default)
aifd ai question list

# Limit to the current directory
aifd ai question list --cwd

# All history, no pagination
aifd ai question list --all

# Specify the number of entries to show
aifd ai question list --limit 100
```

#### View in the browser (recommended - v0.3.1)

A terminal Table is unfriendly to long question text (in testing, 67% of questions exceed 200 chars, the longest 1673 chars) -- you can't see it all. The single `--open` flag pops a browser open:

```bash
# Simplest form: write a temp file + auto-open the browser (recommended for daily use)
aifd ai question list --cwd --open

# View all history
aifd ai question list --all --open

# Persist to a specific file (no browser)
aifd ai question list --cwd --output decisions.html

# Persist + open the browser at the same time
aifd ai question list --cwd --output decisions.html --open
```

The HTML page is a Notion / Linear-style reading view: one card per question, follows the system theme, max 70ch width, a green `✓` marks your choice, a gray `★` marks the recommended one. All user text runs through `html.escape()`, so even history containing a `<script>` string won't cause XSS.

#### JSON output and piping

```bash
# JSON output (includes the full record: options / notes / tool_use_id / source_path)
aifd ai question list --cwd --json | jq

# Find the questions where you went against the recommendation
aifd ai question list --all --json | \
  jq '.[] | select(.recommended_option != null and (.chosen_option | contains(.recommended_option) | not)) | .question'

# Compute cross-project preferences (pipe to jq for aggregation)
aifd ai question list --all --json | jq 'group_by(.cwd) | map({cwd: .[0].cwd, count: length})'

# Pipe HTML to your own static server
aifd ai question list --all --html > public/decisions.html
```

#### Other filter flags

```bash
# Claude only (Codex / OpenCode return empty for now - see "Tool support" below)
aifd ai question list --provider claude

# verbose logging (see extraction details)
aifd ai question list --cwd -v
```

#### What the columns mean

| Column | Meaning |
|---|---|
| **Time** | Relative time the question was asked |
| **Project** | Directory name of the cwd where the question was asked |
| **Question** | Question text (truncated in Table mode; use `--open` or `--json` for the full text) |
| **Your Choice** | The option label you picked. multiSelect is joined with `, ` |
| **Recommended** | The option the model recommended (the one marked `(recommended)` / `(推荐)`) |

The footer at the bottom shows:

- `N questions in <scope>` - total count and scope
- `recommended hit rate: X% (M/N)` - how often you followed the recommendation (the denominator excludes "no recommendation" and "no answer")
- `K unanswered` - interrupted / compacted-away without an answer (about 4% in testing)

#### Flag mutual-exclusion rules

| Flag combo | Behavior |
|---|---|
| no output flag | rich Table (default) |
| `--json` | JSON to stdout |
| `--html` | HTML to stdout (for piping) |
| `--open` | write HTML to a temp file + open browser |
| `--output PATH` | write HTML to PATH (implies HTML mode, no browser) |
| `--output PATH --open` | write HTML to PATH + open browser |
| `--json` + any HTML mode | error (mutually exclusive) |

#### Tool support

Claude Code only. Codex's `agent_message` and the OpenCode / Cursor messages are all free text with no structured "ask the user" event -- so `--provider codex` / `--provider opencode` / `--provider cursor` always returns empty (empty, not an error). Extending to this kind of plain-text questioning requires heuristic extraction, which introduces noise, so the roadmap choice is **precision first**. For the detailed reasoning see [`docs/question-extraction.md`](./docs/question-extraction.md) and [TODOS.md](./TODOS.md).

### `aifd ai session list` - list sessions by directory

> **When to use:** Inside a project directory, see which AI sessions you've run before (when they started, how many events they used).  
> **Version:** v0.1 (foundation)

```bash
# list all AI sessions in the current directory
aifd ai session list

# JSON output
aifd ai session list --json | jq '.[] | .session_id'

# filter by provider
aifd ai session list --provider claude
aifd ai session list --provider codex
aifd ai session list --provider opencode
aifd ai session list --provider cursor
```

| Column | Meaning |
|---|---|
| **Provider** | Which AI tool |
| **Session** | Session id prefix (short enough to read, long enough not to collide) |
| **Started** | Relative start time |
| **Events** | Event count for that session. **Not comparable across tools** -- each vendor's jsonl has different event granularity |
| **Title** | Auto-extracted conversation title |
| **Source** | Which file the data came from (abbreviated) |

By default it **exactly matches** the current directory and does not recurse into subdirectories. Recursive scanning (`-r`) is on the roadmap. To look across directories, use `aifd ai skill list` (global by default) or `aifd ai weekly`.

All four providers support this command, but Cursor has a known ~80% cwd mapping rate -- see [Troubleshooting](#-troubleshooting).

### `aifd ai skill list` - cross-tool skill usage stats

> **When to use:** You want to see which skills you use most across Claude + Codex combined, when you last used each, and across how many projects.  
> **Version:** v0.2

```bash
# Global skill usage (all Claude projects + all Codex threads)
aifd ai skill list

# Limit to the current project
aifd ai skill list --cwd

# JSON output
aifd ai skill list --json | jq '.[] | select(.total > 5)'

# filter by provider
aifd ai skill list --provider claude
```

| Column | Meaning |
|---|---|
| **Claude / Codex / Total** | Invocation count per tool + the sum |
| **Last Used** | Relative time of the most recent invocation |
| **Projects** | The number of **distinct** directories where this skill was used (high = a general cross-project tool; low = single-project specific) |

Defaults to **global** -- a single project usually has few skill invocations; the cross-project pattern is the interesting part. To see "which skills I used building this project", add `--cwd`.

Cross-provider name normalization: Claude's `/gstack-office-hours` and Codex's `[$office-hours]` both aggregate into `office-hours`.

### `aifd ai claude skill list` / `aifd ai codex skill list` - list installed skills

> **When to use:** You want to see which skills your current Claude Code / Codex has installed (listed separately by the three sources: user / plugin / system).  
> **Version:** v0.2.1

```bash
# Which skills the current Claude Code has installed
aifd ai claude skill list

# The same query for Codex
aifd ai codex skill list

# JSON filtering
aifd ai claude skill list --json | jq '.[] | select(.source == "plugin")'
aifd ai codex skill list --json | jq '.[] | select(.source == "system") | .name'
```

Columns: **Skill / Source / Description / Version / Plugin**.

Source distinguishes where a skill came from:

| Source | Meaning |
|---|---|
| **user** | Installed by you (`~/.claude/skills/...` or `~/.codex/skills/...`) |
| **plugin** | Installed via marketplace (Claude only) |
| **system** | Bundled with the tool (Codex's built-in `.system/`) |

A skill with the same name from different sources shows as two rows -- intentional, so you can see exactly where it's installed.

---

## 📊 Compute - activity retrospective

### `aifd ai today` / `weekly` / `monthly` / `retro` - activity retrospective

> **When to use:** You want to see "how much work did I do with AI today / this week / this month / a custom range, and how much did I spend".  
> **Version:** v0.5

```bash
aifd ai today                              # today (local midnight → now)
aifd ai weekly                             # rolling 7-day window
aifd ai monthly                            # this month (local start-of-month → now)
aifd ai retro --since 2026-05-01 --until 2026-05-31
aifd ai retro --since 7d                   # 7d / 14d / 90d shorthand
aifd ai retro --json                       # pipe-friendly

# See docs/ai-retro.md for details
```

Example output:

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

Includes: session / cost / token stats, by-provider breakdown, top skills, top topics (auto-extracted conversation topics), delta vs the previous period, and a monthly projection.

---

## 🔐 Scan - secret / PII leak prevention

### `aifd vault scan` - scan for PII / secret leaks

> **When to use:** Audit periodically -- check whether your AI history accidentally has a pasted API key / token / internal email.  
> **Version:** v0.4

Run it periodically to check whether your AI history accidentally contains a pasted API key, token, internal email, etc.:

```bash
# Scan all provider history by default, confidence >= 7 (shows regex hits only)
aifd vault scan

# JSON output (includes a redacted snippet, never the full secret)
aifd vault scan --json | jq

# Add entropy detection (confidence 4, will have noise)
aifd vault scan --min-confidence 4

# Scan a specific path only
aifd vault scan --no-default-roots --root /path/to/scan
```

**Safety guarantee**: the full secret value never appears in output / JSON / logs. The `SensitiveMatch` dataclass only stores a redacted snippet (first 4 + last 4 chars). You can paste it straight to a colleague for debugging without leaking the real secret.

**Detectors and confidence**

| Category | Matches | Confidence |
|---|---|---|
| `anthropic_key` | `sk-ant-…` | 10 |
| `openai_key` | `sk-…` / `sk-proj-…` | 10 |
| `github_pat` | `ghp_…` | 10 |
| `github_fine_grained_pat` | `github_pat_…` | 10 |
| `github_app_token` | `ghs_…` | 10 |
| `aws_access_key` | `AKIA…` | 9 |
| `slack_token` | `xoxb/xoxa/xoxp/xoxr/xoxs-…` | 9 |
| `jwt` | three-part `eyJ….….…` | 8 |
| `bearer_token` | `Bearer <20+ chars>` | 7 |
| `email` | Email addresses | 7 |
| `high_entropy` | High-entropy strings (only with `--min-confidence 4`) | 4 |

The default threshold is **7**, so only the ten regex detectors above fire. Entropy detection has to be opted into by lowering the threshold, because it is noisy on real data (base64 fragments, hashes, UUIDs).

False-positive suppressors drop matches that clearly aren't leaks: escape prefixes, reserved domains (`example.com` and friends), `noreply`-style local parts, and placeholder email domains.

**Performance**: a cheap substring pass first decides whether a line could match any vendor prefix at all; if not, the whole 10-detector regex loop is skipped. On 260K lines of real jsonl only 8.2% contain any vendor prefix, which cuts 92% of detector work.

For the mechanics, suppression rules, and safety invariants see [`docs/vault.md`](./docs/vault.md) and [`docs/secret-scan.md`](./docs/secret-scan.md).

### `aifd vault cost` - estimate token usage + USD spend

> **When to use:** You want to see how many tokens and how much money you spent over a period / in the currently-running session; broken down by provider / month / project.  
> **Version:** v0.4

```bash
# Group by project (default)
aifd vault cost

# By model
aifd vault cost --by model

# By month
aifd vault cost --by month

# By provider
aifd vault cost --by provider

# JSON output
aifd vault cost --by project --json | jq

# See which models are in the price table (debug unknown models)
aifd vault cost --list-models
```

The output includes a full token breakdown (fresh input / cache read / output / reasoning) + USD estimate + a prices last_updated date at the bottom.

| Column | Meaning |
|---|---|
| **In (k)** | Fresh input tokens (thousands) |
| **Cache (k)** | Cache read tokens (thousands, much cheaper) |
| **Out (k)** | Output + reasoning tokens (thousands) |
| **Cost ($)** | USD estimate for that row |
| **Model** | A single model shows its real name; multiple models show `mixed (N)` |

An unknown model (not in the price table) shows token counts but cost = $0, making it easy to spot which ones need a table update.

### `aifd vault watch` - real-time secret detection daemon

> **When to use:** A background resident that watches Claude / Codex session jsonl -- the moment a new line lands it scans for secrets, and on a hit immediately pushes a macOS notification.  
> **Version:** v0.6 (daemon) → v0.7 (events store + webhooks)

`vault scan` is after-the-fact; `vault watch` is preventative -- a resident daemon watches each Claude / Codex session jsonl, runs the same detection the moment a new line lands, and pushes a macOS notification on a real secret. Clicking the notification opens a `127.0.0.1` page where the secret is highlighted in its conversation context.

**Typical workflow (macOS):**

```bash
# 1. One-time install: register the launchd .plist, auto-start on boot
aifd vault watch install

# 2. Check status (pid / port / how many caught today / how many jsonl tracked)
aifd vault watch status
aifd vault watch status --json     # for scripts

# 3. View the real-time log
aifd vault watch tail

# 4. Run in the foreground when debugging (Ctrl-C to exit, log straight to stdout)
aifd vault watch start --foreground -vv

# 5. Temporarily stop the daemon
aifd vault watch stop

# 6. Fully uninstall (stop the daemon + delete the .plist)
aifd vault watch uninstall
```

**Strongly recommended** to install `terminal-notifier` first:

```bash
brew install terminal-notifier
```

Without it, it falls back to `osascript`, and **clicking the notification opens macOS's built-in "Script Editor"** instead of opening a browser to the finding URL -- a known limitation of the `osascript display notification` AppleScript command (no custom click callback). `aifd vault watch status` shows which backend is currently in use.

**First run**: after the daemon starts it sends a test notification "Watch daemon started — notifications working." **If you don't see it**, go to System Settings → Notifications → Terminal / terminal-notifier and allow it, then `aifd vault watch stop && aifd vault watch start`.

**Integration with `aifd ai today`**: the number of secrets the daemon caught gets an extra line at the bottom of the daily / weekly / monthly activity report:

```text
🛡 vault watch: 3 secrets caught this period (run `aifd vault watch status` for details)
```

**Safety invariants** (see `docs/secret-scan.md`):

- The HTTP server binds only `127.0.0.1` (not `0.0.0.0`) -- other machines on the LAN can never reach it
- The token in the notification URL is `secrets.token_urlsafe(32)` (~256-bit, unguessable)
- `~/.aifd/watch-state.json` stores only `category` + redacted snippet; the full secret never hits disk
- The state file is written atomically with `tmp + rename` -- a mid-write SIGKILL won't leave half a JSON
- `fcntl.flock` prevents two daemons running at once

**Linux**: the `install` subcommand is macOS-only (launchd). On Linux, run `aifd vault watch daemon` via `systemctl --user`; see the `.service` template in `docs/vault-watch.md`.

### `aifd vault watch events` - persistent event stream

> **When to use:** v0.7 upgrades each finding from a transient in-memory notification to a persistent SQLite event stream. Use it to query history in a web UI / manage status / read the rotation playbook.  
> **Version:** v0.7

```bash
aifd vault watch events list                       # list all findings
aifd vault watch events list --status new          # new findings only
aifd vault watch events list --category openai_key
aifd vault watch events list --json                # pipe-friendly

aifd vault watch events show <fingerprint>         # single-finding details + rotation playbook
aifd vault watch events ack <fingerprint>          # mark acknowledged
aifd vault watch events mute <fingerprint> --hours 24
aifd vault watch events resolve <fingerprint>      # mark resolved
aifd vault watch events export --format ndjson > findings.ndjson
```

Example:

```text
$ aifd vault watch events list
208 finding(s) total, showing 50
STATUS  CAT          SNIPPET        COUNT  LAST SEEN            FINGERPRINT
new     openai_key   sk-J…oNwP          3  2026-06-05T17:01    abc123def456…
new     github_pat   ghp_…ejyW          1  2026-06-05T17:02    7e8a9b0c1d2e…
```

Features:

- **State machine** - `new` / `acknowledged` / `resolved` / `muted` (24h or permanent); after `resolved`, reappearance auto re-opens
- **Same secret across files = same issue** - fingerprint hashed by `category + redacted_snippet`
- **Rotation playbook library** - 11 secret classes (`openai_key` / `anthropic_key` / `github_pat` / `github_oauth` / `aws_access_key` / `aws_secret` / `slack_token` / `jwt` / `gcp_service_account` / `email` / `high_entropy`) + a generic fallback; bilingual en + zh; each carries a vendor dashboard link, revocation steps, and a severity rating
- **Web UI** - the daemon serves a single-page SPA bound to `127.0.0.1` only; clicking a notification jumps straight to that finding highlighted in its conversation context

`aifd vault watch events show <fingerprint>` prints the rotation playbook alongside the finding -- so after a leak you don't have to go hunting through vendor docs for "how do I revoke this key".

See [`docs/vault-events.md`](./docs/vault-events.md) and [`docs/vault-events-integrations.md`](./docs/vault-events-integrations.md).

### `aifd vault watch webhooks` - external alerting integration

> **When to use:** You want to push findings to Slack / PagerDuty / Datadog / your own monitoring system.  
> **Version:** v0.7

```bash
aifd vault watch webhooks add --url https://hooks.slack.com/services/T/B/X \
    --on new_finding --category openai_key --category github_pat
aifd vault watch webhooks test <id>          # must pass test before you can enable
aifd vault watch webhooks enable <id>        # disabled by default (avoids misconfigured leaks)
aifd vault watch webhooks list
aifd vault watch webhooks delete <id>
aifd vault watch webhooks list-dead-letter   # failed-delivery queue
aifd vault watch webhooks retry-dead-letter
```

Safety invariants: disabled by default, must pass `test` before you can enable, the payload never contains the full secret (only fingerprint + redacted snippet), retries are capped + there's a dead-letter queue.

---

## 🧘 Reflect - AI Coach

### `aifd ai reflect` - AI Coach: let the LLM see how you use AI

> **When to use:** Once a week -- turn the session / cost / question / skill / ship history that aifd has accumulated back on yourself as a mirror, and have the LLM write an 80-150 word meta-cognitive reflection.  
> **Version:** v0.8 (LiteLLM multi-provider)

aifd v0.8 flips every "do stuff" tool around -- it lets aifd look at how you used AI this week and has the LLM write an 80-150 word meta-cognitive reflection. One line a week, ~$0.001/run.

**First-time setup** (pick one of three):

```bash
# Option 1: environment variable (most direct)
export DEEPSEEK_API_KEY=sk-xxxxxxxxx      # or ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ...
aifd ai reflect --week

# Option 2: ~/.aifd/config.yaml (recommended for the long term)
aifd ai reflect           # auto-generates a template on the first run
$EDITOR ~/.aifd/config.yaml   # fill in llm.api_key + llm.model
# the file is auto chmod 600

# Option 3: temporary prefix (not written to env / not stored in history)
DEEPSEEK_API_KEY=sk-xxx aifd ai reflect --week
AIFD_LLM_API_KEY=sk-xxx aifd ai reflect --model zhipu/glm-4-plus
```

Get a DeepSeek key from https://platform.deepseek.com/api_keys (or switch to any LiteLLM [provider](https://docs.litellm.ai/docs/providers)). Priority: `AIFD_LLM_*` env > provider-native env (`DEEPSEEK_API_KEY` etc.) > config.yaml > built-in default.

**Daily use:**

```bash
aifd ai reflect                                # default --week, zh
aifd ai reflect --month                        # 30-day review
aifd ai reflect --month --lang en              # English output
aifd ai reflect --since 2026-06-01             # custom window
aifd ai reflect --since 2026-06-01 --until 2026-06-07
aifd ai reflect --json                         # pipe-friendly
aifd ai reflect -v                             # verbose: show timing breakdown
aifd ai reflect --include-questions            # opt-in: feed the question summary to the LLM
```

**Switch the LLM backend** (any LiteLLM provider):

```bash
# Chinese providers - each uses LiteLLM's provider/model format
aifd ai reflect --model zhipu/glm-4-plus
aifd ai reflect --model dashscope/qwen-plus            # Alibaba Tongyi
aifd ai reflect --model ark/ep-xxxxx                   # Volcengine Ark (endpoint_id)
aifd ai reflect --model moonshot/moonshot-v1-32k       # Kimi

# International providers
aifd ai reflect --model anthropic/claude-sonnet-4
aifd ai reflect --model openai/gpt-4o
aifd ai reflect --model gemini/gemini-2.0-flash

# Local ollama / self-hosted vLLM / Azure / company proxy
aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
aifd ai reflect --model openai/qwen2.5 --api-base https://vllm.internal/v1

# Or set llm.model / llm.api_base in ~/.aifd/config.yaml
```

**Config file** (the first `aifd ai reflect` run auto-generates `~/.aifd/config.yaml`, permissions auto `chmod 600`):

```yaml
llm:
  # LiteLLM 'provider/model' format - switching providers only changes this line
  model: deepseek/deepseek-chat
  # API key. Leave empty to let LiteLLM read the provider's native env var
  # (DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY /
  #  ANTHROPIC_API_KEY / OPENAI_API_KEY / MOONSHOT_API_KEY / GROQ_API_KEY ...)
  api_key: sk-xxxxxxxxx
  # Fill in for self-hosted / proxy; leave empty for hosted providers to use the default endpoint
  api_base:

reflect:
  default_lang: zh           # en | zh
  include_questions: false   # true = feed the question summary to the LLM (still does not send the original text)
```

For the complete schema including `habits:` and `minimax:`, see [Full `~/.aifd/config.yaml` schema](#full-aifdconfigyaml-schema).

The yaml form for each provider:

```yaml
# DeepSeek (default)
llm: { model: deepseek/deepseek-chat, api_key: sk-... }

# Zhipu GLM
llm: { model: zhipu/glm-4-plus, api_key: ... }

# Alibaba Tongyi Qianwen (DashScope)
llm: { model: dashscope/qwen-plus, api_key: sk-... }

# Volcengine Ark (the model field takes the inference endpoint id, not the model name)
llm: { model: ark/ep-xxxxxxxx, api_key: ... }

# Moonshot Kimi
llm: { model: moonshot/moonshot-v1-32k, api_key: sk-... }

# Anthropic Claude
llm: { model: anthropic/claude-sonnet-4, api_key: sk-ant-... }

# OpenAI
llm: { model: openai/gpt-4o, api_key: sk-... }

# Local ollama (api_key can be empty, api_base is required)
llm:
  model: ollama/qwen2.5
  api_base: http://127.0.0.1:11434/v1

# Self-hosted vLLM / OpenAI-compatible proxy
llm:
  model: openai/qwen2.5
  api_key: any-non-empty-string
  api_base: https://vllm.internal/v1
```

**Priority**: `AIFD_LLM_*` env > provider-native env > `~/.aifd/config.yaml` > default.
If you were already using `DEEPSEEK_API_KEY` in the v0.8 pre-release, nothing changes -- it's auto-compatible.

**9 reflection dimensions** (what aifd looks at):

| Dimension | What it says |
|---|---|
| Activity | sessions / cost / tokens / by-provider |
| Compliance ratio | How often you followed the recommendation on AskUserQuestion |
| Skill diversity | distinct skills / total invocations |
| Cost trend | This week's spend change vs last week |
| Timing distribution | 4 time-of-day buckets, showing when you're most productive |
| Project focus | Your deepest project + its share (**basename only**) |
| Plan-then-ship | The fraction of ships with a plan-eng-review in the prior 7 days |
| Vibe-coding score | The fraction of ships with < 5 messages before the ship |
| Top wins | Recent clean ships + plan-eng-review |

**Privacy invariants** (hard guarantee):

- raw question answer text is never sent
- session message content is never sent
- the full cwd path is never sent (basename only)
- anything matching a v0.4 detector secret pattern is never sent (render_prompt runs `_scan_line` as a backstop check, 0 SensitiveMatch = test pass)
- `--include-questions` is opt-in and even then only sends the summary, **not** the original text

**Fallback**: no API key / 401 auth / 5xx / timeout → degrades to a structured local report + a clear error message, no crash. For the full spec see `docs/ai-reflect.md`.

### `aifd ai habits` - long-term AI behavior persona

> **When to use:** Once a quarter -- have the LLM look at 60-90 days of your session data and identify long-term behavior patterns you **don't notice yourself** (like "Friday wind-down crash", "late-night decisions regretted the next day", "over-planner").  
> **Version:** v0.9

`reflect` answers "how was this week"; `habits` answers "**what kind of AI user am I**".
It analyzes 60-90 days of session data and has the LLM identify behavior patterns you **don't notice yourself**.

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
*(LLM output; use `--lang en` for English)*

How it divides labor with `reflect`:

| | `aifd ai reflect` | `aifd ai habits` |
|---|---|---|
| Time window | 7-30 days | 60-90 days |
| Frequency | Weekly | Quarterly or on demand |
| LLM task | Write a reflection essay | Name patterns + numeric evidence |

```bash
aifd ai habits                              # default 90 days
aifd ai habits --since 60d
aifd ai habits --since 2026-01-01
aifd ai habits --lang en --json
aifd ai habits --model zhipu/glm-4-plus     # any LiteLLM provider
```

Add a `habits:` section to `~/.aifd/config.yaml` (auto-generated on first run):

```yaml
habits:
  default_days: 90
```

8 dimensions (day-of-week distribution / time-of-day distribution / session bimodality / project-switch frequency / ship interval / late-night ship rate / over-planning rate / skill repetition rate), sharing the LiteLLM routing layer and the D6 privacy invariant with `reflect`. For the full spec see `docs/ai-habits.md`.

---

## 🌌 See - turn your AI history into a star map

### `aifd cosmos` - a drag-to-rotate 2.5D star map

> **When to use:** You want to see the shape of your last few months with AI at a glance -- which projects carried the load, which were one-offs, how deep sessions and vibe-coding split. Or you just want a picture worth sharing.
> **Version:** v0.13 (2D force-graph) → **v0.14 (rotatable 2.5D, new default)**

```bash
aifd cosmos                            # last 90 days, generate + auto-open browser
aifd cosmos --since 30                 # last 30 days
aifd cosmos --since 365                # last year
aifd cosmos --output ~/my-cosmos.html  # custom output path
aifd cosmos --no-open                  # generate only (CI / remote machines)
aifd cosmos --flat                     # back to the v0.13 2D force-graph
```

Output:

```text
✨ 1106 sessions → aifd-cosmos.html
```

**Flag reference**

| Flag | Default | Meaning |
|---|---|---|
| `--since N` | `90` | Include only sessions started in the last N days (min 1) |
| `--output PATH` | `aifd-cosmos.html` | HTML output path |
| `--open` / `--no-open` | `--open` | Whether to open a browser after generating |
| `--flat` | off | Render the v0.13 2D force-graph instead of the default 2.5D |

**Visual encoding**

| Element | Meaning |
|---|---|
| Star radius | That session's event count (bigger = more interaction) |
| Cool blue | Vibe-coding (short session, event count under the threshold) |
| Warm red | Deep session (long session) |
| Purple hub | A project directory; its sessions orbit it |
| Drag | Rotate the whole cloud around its axis (horizontal + vertical), with perspective and depth |
| Hover | Show that session's provider / title / event count |

**2.5D vs 2D (`--flat`)**

| | Default 2.5D (v0.14) | `--flat` 2D (v0.13) |
|---|---|---|
| Interaction | Drag to rotate + slow auto-spin | Force layout, zoom, drag nodes |
| Rendering | Hand-written canvas 2D + CPU trig rotation | vendored force-graph 1.51.4 (MIT, inlined) |
| Dependencies | Zero vendored lib, no WebGL needed | Inlined force-graph |
| Good for | The "my AI universe" feel, screenshots | Reading topology between projects |

v0.14 is **2.5D rather than true 3D** for measured reasons: a spike showed real 3D (Three.js + bloom) inevitably smears on dense data (six passes all came out washed out or foggy), WebGL blanks out in locked-down environments, and it costs 600KB of CDN. What people actually wanted was "a solid thing I can rotate" -- and rotation is trigonometry plus perspective projection, not a GPU privilege. A thousand points on canvas is milliseconds of CPU.

**Design constraints**

- **Privacy**: cwd shows basename only, and home paths inside session titles are redacted to `~` -- sharing a screenshot or the HTML never leaks your username or private project names
- **Self-contained**: all JS is inlined into the HTML (~66KB), viewable offline, zero runtime network dependency
- **Two layers of XSS protection**: user content goes through `html.escape()` plus `</` escaping inside the JSON blob
- **Link model**: project hub nodes (sessions link to their hub rather than to each other), so edges are O(n) not O(n²) -- a project with hundreds of sessions doesn't explode
- **Node ids** use a composite `(provider, session_id)` key so ids can't collide across tools
- `event_count` is **not comparable across tools** (each vendor's jsonl event granularity differs); it's an aifd-internal relative measure
- Poster / PNG export isn't built yet (force-graph has no export API and `devicePixelRatio` is too fragile) -- a later spike

**Nothing rendered?** When no session falls inside the window, `aifd cosmos` fails with a clear message telling you to widen `--since`, instead of writing a blank HTML.

---

## 📉 Quota - subscription usage

### `aifd quota` - MiniMax Coding Plan 5h quota

> **When to use:** You're coding on a MiniMax Coding Plan subscription and want to check how much of the current 5-hour rolling window is left, so you don't get cut off mid-task.
> **Version:** v0.12

```bash
aifd quota            # defaults to MiniMax
aifd quota minimax    # explicit (equivalent)
```

Output:

```text
MiniMax 5h: 剩 99%，3h27m 后重置
```
*(the CLI prints this line in Chinese)*

Configuring the key -- **this is not the LLM key**. `llm.api_key` is the model key powering `reflect` / `habits` (DeepSeek by default); this is your MiniMax coding-plan subscription credential, usually a completely different one. aifd never falls back to `llm.api_key`:

```bash
export MINIMAX_API_KEY=your-key           # env takes priority
```

```yaml
# Or ~/.aifd/config.yaml
minimax:
  api_key: your-key
```

**Safety by design**: the MiniMax key is a Bearer credential, built into the `Authorization` header only at the call site. Every error path uses `raise ... from None` to cut the exception chain, because httpx's original exception can carry the full request (including the Bearer key). The result: the key never reaches an error message, traceback, or log -- and note that aifd's own `vault scan` lists `Bearer <key>` as a secret pattern.

**Other behavior**

- The query does not consume your prompt quota
- A valid key with no active plan gets a clear "No active MiniMax Coding Plan" message
- The row is selected by `model_name == "general"`, never by array index (`model_remains[]` order isn't guaranteed, so taking `[0]` could hand you the video window)
- The countdown uses the server-provided `remains_time`, not your local clock, so clock skew can't corrupt the reading

> best-effort: MiniMax's usage endpoint is undocumented. If they change the response format, the command says "update aifd" instead of raising a stack trace.

---

## 🛠️ Configuration and runtime

### Full `~/.aifd/config.yaml` schema

Only `aifd ai reflect` / `aifd ai habits` / `aifd quota` need configuration. Everything else is zero-config.

The first run of `aifd ai reflect` generates a commented template and `chmod 600`s it. If the file's permissions are too open (group / other readable), aifd warns but does not block.

```yaml
llm:
  # LiteLLM 'provider/model' form -- switching providers is this one line
  model: deepseek/deepseek-chat
  # API key. Leave empty to let LiteLLM read the provider's native env var
  # (DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY /
  #  ANTHROPIC_API_KEY / OPENAI_API_KEY / MOONSHOT_API_KEY / GROQ_API_KEY ...)
  api_key: sk-xxxxxxxxx
  # Fill in for self-hosted / proxy / ollama / Azure; leave empty for hosted providers
  api_base:

reflect:
  default_lang: zh           # en | zh, output language for `aifd ai reflect`
  include_questions: false   # true = feed question summaries to the LLM (still never raw text)

habits:
  default_days: 90           # default analysis window for `aifd ai habits`; < 1 resets to 90

minimax:
  # MiniMax Coding Plan key used by `aifd quota`.
  # A separate credential from llm.api_key above -- aifd never cross-falls-back.
  api_key:
```

**Fault tolerance**: file missing → all defaults. YAML fails to parse → warn + defaults, no crash. A section that isn't a mapping → that section falls back to defaults.

### Config precedence

| Setting | Precedence (left wins) |
|---|---|
| LLM key | `AIFD_LLM_API_KEY` → `DEEPSEEK_API_KEY` (v0.8 compat) → `llm.api_key` |
| LLM model | `AIFD_LLM_MODEL` → `llm.model` → `deepseek/deepseek-chat` |
| LLM api_base | `AIFD_LLM_API_BASE` → `llm.api_base` → provider default endpoint |
| MiniMax key | `MINIMAX_API_KEY` → `minimax.api_key` (**never** falls back to `llm.api_key`) |
| Provider-native keys | Discovered by LiteLLM itself when `llm.api_key` is empty (`ZHIPUAI_API_KEY` etc.) |

Command-line flags (`--model` / `--api-base` / `--lang` / `--since`) beat every source above, for that run only.

aifd deliberately does **not** shadow provider-native env vars -- LiteLLM discovers them when `api_key` is `None`, and if aifd grabbed them first you could no longer switch providers by swapping an env var.

### What aifd writes to disk

All aifd state lives under `~/.aifd/`. **aifd never writes to your AI tools' data directories** -- `~/.claude/`, `~/.codex/` and friends are opened read-only.

| Path | Written by | Contents |
|---|---|---|
| `~/.aifd/config.yaml` | You (template generated by aifd on first run) | LLM / reflect / habits / minimax config, `chmod 600` |
| `~/.aifd/webhooks.yaml` | You | Targets for `vault watch webhooks` |
| `~/.aifd/watch-state.json` | daemon | Per-file scan progress + daily catch counters. **Stores category + redacted snippet only** |
| `~/.aifd/findings.db` | daemon | SQLite persistent finding event stream (v0.7) |
| `~/.aifd/watch.pid` / `watch.port` | daemon | pid + HTTP port; `flock` prevents double-start |
| `~/.aifd/watch.log` | daemon | stdout / stderr when running in the background |
| `~/Library/LaunchAgents/*.plist` | `vault watch install` | macOS autostart (`uninstall` removes it) |
| `aifd-cosmos.html` | `aifd cosmos` | Self-contained star map in the current directory (path configurable) |

Every state file is written atomically via `tmp + rename` -- a SIGKILL mid-write can't leave half a JSON behind.

### Common flags

```bash
aifd --version
aifd --help                 # --help works at every level
aifd vault watch events --help

aifd ai session list -v     # INFO logging
aifd ai session list -vv    # DEBUG logging
aifd ai retro --json        # almost every command supports --json
```

`--json` exists for pipes: every query command emits a stable JSON schema you can pipe straight into `jq`.

### Current support matrix

**AI tools × capabilities**

| Tool | session | token/cost | skill invocations | question | Data source |
|---|---|---|---|---|---|
| **Claude Code** | ✅ | ✅ | ✅ | ✅ | `~/.claude/projects/{encoded-cwd}/*.jsonl` |
| **Codex** | ✅ | ✅ | ✅ | ➖ | `~/.codex/state_5.sqlite` + `~/.codex/sessions/` fallback |
| **OpenCode** (v0.10) | ✅ | ✅ | ➖ | ➖ | `~/.local/share/opencode/opencode.db` |
| **Cursor** (v0.11) | ✅ | ✅ | ➖ | ➖ | `globalStorage/state.vscdb` + `workspaceStorage/` |

➖ = that tool has no corresponding structured data; the command returns empty rather than erroring. Codex's `agent_message` and the OpenCode messages are free text with no structured "ask the user" event; covering plain-text questioning would need heuristic extraction and would introduce noise, so the roadmap picks **precision first**. Reasoning in [`docs/question-extraction.md`](./docs/question-extraction.md).

**Installed-skill listing** (`aifd ai claude skill list` / `aifd ai codex skill list`) covers Claude Code and Codex today; OpenCode's skill directory (`~/.config/opencode/skills`) is recognized but not yet wired into the CLI.

**What makes Cursor special**: the other three store cwd as a first-class field and can do `WHERE directory = ?` directly. Cursor splits sessions (globalStorage) from cwd (workspaceStorage) into two stores that don't reference each other, so a cross-store JOIN is required and the read can't be narrowed by cwd at the SQL layer. In practice hash mapping covers about 80% of real sessions (timestamp-form ids have no matching workspace directory on disk); the unmapped count is printed as one stderr line. Cursor is also a live Electron app writing its SQLite WAL while we read, so it's opened `mode=ro`, retried once on lock contention, then silently skipped. Windows path support isn't built yet -- see [TODOS.md](./TODOS.md).

**LLM providers (via LiteLLM)**

| Provider | `reflect` / `habits` | Notes |
|---|---|---|
| DeepSeek (default), Zhipu GLM, Alibaba DashScope, Volcengine Ark, Moonshot Kimi | ✅ | Chinese-ecosystem providers, `provider/model` form |
| OpenAI, Anthropic, Gemini, Groq, Together, Fireworks | ✅ | |
| ollama / vLLM / Azure OpenAI / company OpenAI-compatible proxy | ✅ | Needs `--api-base` or `llm.api_base` |

In principle all 100+ LiteLLM providers work -- aifd maintains no provider list of its own, it just forwards the `provider/model` string.

---

## 🔒 Data sources and privacy

### What files aifd reads

aifd opens every path below **read-only**. It does not create, modify, or delete your AI tool data.

| Tool | Session data | Installed skills |
|---|---|---|
| Claude Code | `~/.claude/projects/{encoded-cwd}/*.jsonl` | `~/.claude/skills/`, `~/.claude/plugins/cache/` |
| Codex | `~/.codex/state_5.sqlite` (primary) + `~/.codex/sessions/` (fallback) | `~/.codex/skills/` |
| OpenCode | `~/.local/share/opencode/opencode.db` | `~/.config/opencode/skills/` |
| Cursor (macOS) | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` + `workspaceStorage/` | — |
| Cursor (Linux) | `$XDG_CONFIG_HOME/Cursor/User/` (or `~/.config/Cursor/User/`) | — |
| Cursor (Windows) | `%APPDATA%/Cursor/User/` -- **not supported yet**, see TODOS.md | — |

**A single file that fails to parse must be silently skipped** (logged at `warning` / `debug`), never raised -- one bad file cannot take down the whole table. This is a hard constraint at the provider layer and an acceptance criterion for new provider PRs.

### Privacy invariants

These are hard guarantees, each with tests behind it:

1. **Full secret values never leave the detector.** The `SensitiveMatch` dataclass stores a redacted snippet only (first 4 + last 4 chars). Terminal output, `--json`, `watch.log`, `watch-state.json`, `findings.db`, webhook payloads -- redacted snippet only. You can paste `aifd vault scan --json` output straight to a colleague.
2. **The LLM prompt contains none of your content.** `reflect` / `habits` send aggregated statistical dimensions only:
   - No session message content
   - No raw AskUserQuestion text and no raw answers
   - No full cwd paths (**basename only**)
   - `--include-questions` is opt-in and still sends summaries only, **never** raw text
   - `render_prompt` runs a `_scan_line` backstop at the exit: if any v0.4 detector pattern appears in the prompt, the test fails
3. **The HTTP server binds `127.0.0.1` only**, not `0.0.0.0` -- other machines on the LAN cannot reach the findings page. The token in the notification URL is `secrets.token_urlsafe(32)` (~256 bits, unguessable).
4. **Shareable artifacts are already redacted.** In the HTML from `aifd cosmos` and `aifd ai question list --output`, cwd is basename-only and home paths are redacted to `~`; all user text goes through `html.escape()`, so a `<script>` string in your history can't XSS.
5. **Webhooks send fingerprint + redacted snippet only**, and are disabled by default until a `test` succeeds -- so a mistyped URL can't push alerts somewhere wrong.

### When aifd touches the network

aifd is offline by default. Only these three cases make a network request, and you trigger all of them explicitly:

| Command | Destination | What goes out |
|---|---|---|
| `aifd ai reflect` / `aifd ai habits` | Your configured LLM provider | Aggregated dimensions (see invariant 2 above), ~$0.001 per run |
| `aifd quota` | MiniMax usage endpoint | One Bearer header, no body |
| `aifd vault watch webhooks` | Your configured webhook URL | fingerprint + category + redacted snippet |

Every other command -- `session list` / `skill list` / `question list` / `today` / `weekly` / `monthly` / `retro` / `vault scan` / `vault cost` / `cosmos` -- makes **zero network requests**. The HTML `cosmos` generates inlines all its JS, so opening it fires no requests either.

---

## ❓ Troubleshooting

**`aifd ai session list` shows nothing**

It **exactly matches** the current directory by default and does not recurse. Make sure you're in the directory where you actually ran AI sessions. `aifd ai session list -vv` shows DEBUG logs including which paths it scanned and what it skipped. To look across directories use `aifd ai skill list` (global by default) or `aifd ai weekly`.

**`aifd ai question list` returns empty for Codex / OpenCode / Cursor**

Expected, not a bug. Only Claude Code has structured `AskUserQuestion` tool-call events. See [Current support matrix](#current-support-matrix).

**Some `aifd vault cost` rows show $0 with a non-zero token count**

That model isn't in the price table. Run `aifd vault cost --list-models` to see what is, then file an issue (or a PR) adding it to `aifd/vault/prices.py`. aifd deliberately shows the tokens rather than guessing at a price.

**`vault watch` is installed but no notifications arrive**

In order:

1. `aifd vault watch status` -- is the daemon running? Which notify backend is it using?
2. If `terminal-notifier` isn't installed, `brew install terminal-notifier`. The `osascript` fallback makes **clicking a notification open Script Editor** instead of a browser -- a known limitation of AppleScript's `display notification` (no custom click callback).
3. System Settings → Notifications → allow Terminal / terminal-notifier, then `aifd vault watch stop && aifd vault watch start`.
4. Still nothing? Run it in the foreground and read the log: `aifd vault watch start --foreground -vv`.

On first start the daemon sends a "Watch daemon started — notifications working." test notification. Not seeing that one means a notification permission problem, not a detection problem.

**`aifd vault watch install` fails on Linux**

`install` / `uninstall` are macOS-only (they use launchd). On Linux run `aifd vault watch daemon` under `systemctl --user`; the `.service` template is in [`docs/vault-watch.md`](./docs/vault-watch.md). The detection logic itself is cross-platform (watchdog wraps inotify).

**`ModuleNotFoundError: No module named 'litellm'` (but `uv run aifd` works)**

The editable-install dep trap. See [The editable-install dep trap](#the-editable-install-dep-trap).

**`aifd ai reflect` says there's no API key**

Set an env var (`export DEEPSEEK_API_KEY=sk-...`) or edit `llm.api_key` in `~/.aifd/config.yaml`. The first `aifd ai reflect` run generates the template file. Precedence is in [Config precedence](#config-precedence).

Missing keys don't crash it -- it degrades to a structured local report plus a clear error message. Same for 401 / 5xx / timeout.

**`aifd quota` says "No active MiniMax Coding Plan"**

The key is valid but has no running coding-plan subscription attached. Check that `MINIMAX_API_KEY` is the coding-plan key rather than a regular API key (and not your `llm.api_key`).

**`aifd cosmos` reports "No sessions found"**

No sessions inside the window. Widen it: `aifd cosmos --since 365`.

**Some Cursor sessions are missing**

Known limitation: cwd is resolved through workspace hash mapping, which covers about 80% in practice; timestamp-form composer ids have no matching workspace directory on disk so no cwd can be derived. The unmapped count is printed on stderr. Also, only composers appearing in `bubbleId:*` (real conversation content) count as sessions -- the other ~80% of `composerData` rows are drafts and migration residue that Cursor's own UI doesn't show either.

---

## 🏗️ Architecture and contributing

### Architecture

Three layering principles:

1. **One adapter per AI tool**, under `aifd/providers/`, all implementing the same `Provider` Protocol. Commands upstream never learn how differently Claude and Cursor store their data.
2. **Business logic separated from rendering.** `vault/` and `insights/` only compute; `render*.py` owns the three outputs (rich Table / JSON / HTML). That's why "add a `--json`" is always a few lines.
3. **Three CLI layers** (`aifd ai session list`), leaving namespace for a future `session show` / `session resume` / `ai prompt`.

```text
aifd/
├── cli/                         # CLI layer: parse args, call business layer, pick a renderer
│   ├── __init__.py              # top-level `aifd` group (ai / cosmos / quota / vault)
│   ├── _logging.py              # shared -v / -vv logging config
│   ├── _runner.py               # shared provider-query framework            v0.3
│   ├── cosmos.py                # aifd cosmos                                v0.13-0.14
│   ├── quota.py                 # aifd quota / quota minimax                 v0.12
│   ├── ai/
│   │   ├── session.py           # aifd ai session list                       v0.1
│   │   ├── skill.py             # aifd ai skill list                         v0.2
│   │   ├── question.py          # aifd ai question list (+ HTML v0.3.1)      v0.3
│   │   ├── retro.py             # aifd ai today / weekly / monthly / retro   v0.5
│   │   ├── reflect.py           # aifd ai reflect                            v0.8
│   │   ├── habits.py            # aifd ai habits                             v0.9
│   │   ├── claude/skill.py      # aifd ai claude skill list                  v0.2.1
│   │   └── codex/skill.py       # aifd ai codex skill list                   v0.2.1
│   └── vault/
│       ├── scan.py              # aifd vault scan                            v0.4
│       ├── cost.py              # aifd vault cost                            v0.4
│       └── watch.py             # aifd vault watch + events + webhooks       v0.6-0.7
│
├── providers/                   # one adapter per AI tool
│   ├── base.py                  # Provider Protocol -- the contract for new providers
│   ├── registry.py              # PROVIDERS list; the single registration point
│   ├── _utils.py                # shared regex / skill name normalization / frontmatter
│   ├── claude.py                # Claude Code (session / skill / question / token)
│   ├── codex.py                 # Codex (sqlite primary + jsonl fallback)
│   ├── opencode.py              # OpenCode                                   v0.10
│   └── cursor.py                # Cursor (cross-store JOIN + read-only WAL)  v0.11
│
├── insights/                    # AI Coach business logic                    v0.8-0.9
│   ├── activity.py              # session aggregation + public iter_sessions_in()
│   │                            #   (shared by reflect / habits / cosmos)
│   ├── reflection.py            # reflect's 9 dimension calculations
│   ├── reflection_prompt.py     # reflect prompt assembly + secret exit check
│   ├── reflection_source.py     # reflect data-source adapter
│   ├── habits.py                # habits' 8 dimension calculations
│   ├── habits_prompt.py         # habits prompt assembly
│   └── llm_client.py            # LiteLLM wrapper (100+ provider routing + fallback)
│
├── vault/                       # data-sovereignty business logic            v0.4-0.7
│   ├── scan.py                  # 10 regex detectors + entropy + FP suppression
│   ├── prices.py                # model → USD price table
│   ├── cost.py                  # aggregate token → $
│   ├── playbooks.py             # rotation steps for 11 secret classes (en + zh)
│   ├── watch.py                 # daemon main loop (watchdog file events)
│   ├── watch_server.py          # finding-detail HTTP server, 127.0.0.1 only
│   ├── watch_state.py           # atomic state file read/write under ~/.aifd/
│   ├── events_db.py             # SQLite event stream + state machine         v0.7
│   ├── webhooks.py              # outbound push + retry + dead letter         v0.7
│   └── static/                  # watch web UI single-page SPA
│
├── assets/                      # vendored force-graph 1.51.4 (MIT), shipped in the wheel
├── config.py                    # ~/.aifd/config.yaml I/O + env precedence + 0600
├── models.py                    # Session / SkillInvocation / SkillStats /
│                                # InstalledSkill / QuestionAnswer / TokenUsage /
│                                # CostRow / SensitiveMatch
├── paths.py                     # cwd normalization (cross-provider dir comparison)
├── aggregation.py               # skill stats aggregation                    v0.2
├── render.py                    # rich Table / JSON / HTML rendering
├── render_cosmos.py             # cosmos data layer build_graph + 2D force-graph  v0.13
└── render_cosmos_25d.py         # cosmos 2.5D canvas rendering (v0.14 default)    v0.14
```

### Contribute a new provider

1. Create `aifd/providers/yourtool.py`, implementing the `Provider` Protocol in `aifd/providers/base.py`.
2. Append your provider instance to the `PROVIDERS` list in `aifd/providers/registry.py`.
3. Add a fixture factory in `tests/conftest.py` (see `opencode_db` / `codex_db`) and write `tests/test_yourtool_provider.py`.
4. Make sure `uv run pytest`, `uv run ruff check aifd/ tests/`, and `uv run mypy aifd/` all pass.

`aifd/providers/opencode.py` (v0.10) is the cleanest example of "one file + one line of registration".
If your tool's storage is more awkward (sessions and cwd in two stores, written while you read), look at `cursor.py` (v0.11) -- its module docstring spells out how each of those problems was handled.

**Hard constraints:**

- **Single-file parse errors must silent-skip** (logged at `warning` or `debug` level), never raise -- one bad file must not take down the whole list.
- **Open all external data read-only.** Live apps (Cursor / OpenCode) are writing their SQLite WAL, so use `mode=ro`, retry once on lock contention, then skip.
- **Return an empty list for unsupported capabilities**, don't raise `NotImplementedError` -- the layer above aggregates across providers, and one tool's gap shouldn't affect the others.

### Development

```bash
git clone https://github.com/xunull/aifd
cd aifd
uv sync

uv run pytest                       # 744 tests
uv run pytest --cov=aifd            # with coverage
uv run pytest -m live_api           # tests that hit a real LLM API (needs a key, skipped by default)
uv run ruff check aifd/ tests/      # lint
uv run mypy aifd/                   # type check (strict)

uv run aifd ai session list         # run without installing to PATH
```

The repo ships a `.pre-commit-config.yaml` wired to [gitleaks](https://github.com/gitleaks/gitleaks) -- it scans the staging area before every commit and blocks accidentally committed API keys. A tool that scans for secrets should be guarded by secret scanning itself:

```bash
pre-commit install
```

### Tests and CI

| Item | Status |
|---|---|
| Test count | **744** (`uv run pytest`) |
| CI matrix | ubuntu / macOS / Windows × Python 3.12 / 3.13 = **6 combinations**, `fail-fast: false` |
| Gates | `ruff check` → `mypy aifd/` (strict) → `pytest --cov`, all green or it doesn't pass |
| Live API tests | Marked `live_api`, skipped by default; need a provider key + an explicit `pytest -m live_api` |
| Release | A `v*` tag triggers `release.yml`, which fails the build if the tag and the `pyproject.toml` version disagree |

mypy runs in **strict** mode (`warn_unused_ignores` and `warn_return_any` both on); ruff uses the `E, F, W, I, B, UP, RUF` rule sets at line length 100. Fullwidth punctuation in Chinese prose (rotation playbooks, LLM prompts) is intentional and exempted per-file from `RUF001-003` in `pyproject.toml`.

#### The editable-install dep trap

If you put a dev build of `aifd` on your PATH with `uv tool install --editable .` (or `pipx install -e .`), watch out:

- **Source changes take effect automatically** -- editable mode points straight at the repo, so editing `.py` doesn't require a reinstall.
- **But deps do NOT auto-sync** -- `uv sync` only updates the project's `.venv`, it doesn't touch the tool's isolated venv (`~/Library/Application Support/uv/tools/aifd/` or pipx's `~/.local/pipx/venvs/aifd/`).

So: **whenever deps in `pyproject.toml` change (add, remove, bump) → you must reinstall once**:

```bash
uv tool install --reinstall --editable .     # uv tool
pipx reinstall aifd                          # pipx
```

The error usually looks like `ModuleNotFoundError: No module named 'litellm'` (it runs fine under `uv run`, but running `aifd` directly on the command line can't import it) -- that means the new dep isn't installed in the tool venv.

---

## 🧭 Version timeline

One through-line: first **query**, then **compute**, then **prevent**, and finally **reflect** and **see**.

| Version | What it added | One-liner |
|---|---|---|
| v0.1 | `aifd ai session list` | List sessions by directory -- the foundation everything else sits on |
| v0.2 | `aifd ai skill list` | Cross-tool skill stats; cross-provider name normalization |
| v0.2.1 | `ai claude/codex skill list` | List installed skills (user / plugin / system) |
| v0.3 | `aifd ai question list` | Review AskUserQuestion history + recommended hit rate |
| v0.3.1 | `--open` / `--html` / `--output` | Long questions don't fit a terminal table, so open a browser |
| v0.4 | `aifd vault scan` / `cost` | secret / PII scanning + token → USD estimation |
| v0.5 | `today` / `weekly` / `monthly` / `retro` | Activity retrospective + period-over-period deltas + monthly projection |
| v0.6 | `aifd vault watch` | From after-the-fact query to prevention: resident daemon + macOS notifications |
| v0.7 | `watch events` / `watch webhooks` | Persistent event stream (SQLite) + state machine + external alerting |
| v0.8 | `aifd ai reflect` | AI Coach: weekly meta-cognitive reflection, routed through LiteLLM |
| v0.9 | `aifd ai habits` | 60-90 day behavior persona: what kind of AI user you are |
| v0.10 | OpenCode provider | Third tool supported |
| v0.11 | Cursor provider | Fourth tool supported (the cross-store JOIN was the hard part) |
| v0.12 | `aifd quota` | MiniMax Coding Plan 5h window remaining quota |
| v0.13 | `aifd cosmos` | AI history → force-directed galaxy, self-contained HTML |
| v0.13.1-0.13.2 | Visual polish + perf fix | Glowing stars; dropped `shadowBlur` to fix a freeze (5s → 1.6ms per frame) |
| **v0.14** | **cosmos 2.5D by default** | Drag-to-rotate star map; `--flat` keeps the 2D view |

Full change log in [CHANGELOG.md](./CHANGELOG.md); what's next in [TODOS.md](./TODOS.md).

---

## License

Apache-2.0 - see [LICENSE](./LICENSE).

The vendored force-graph 1.51.4 is MIT; its license text is at [`aifd/assets/force-graph.LICENSE`](./aifd/assets/force-graph.LICENSE).

## Related docs

**Command specs**

- [`docs/ai-reflect.md`](./docs/ai-reflect.md) - full spec for `aifd ai reflect` (9 dimensions + privacy invariants)
- [`docs/ai-habits.md`](./docs/ai-habits.md) - full spec for `aifd ai habits` (8 dimensions)
- [`docs/ai-retro.md`](./docs/ai-retro.md) - full spec for `aifd ai today / weekly / monthly / retro`
- [`docs/vault.md`](./docs/vault.md) - overall `aifd vault` design
- [`docs/vault-watch.md`](./docs/vault-watch.md) - full spec for `aifd vault watch` (includes the Linux systemd template)
- [`docs/vault-events.md`](./docs/vault-events.md) - full spec for `aifd vault watch events / webhooks`

**Algorithms and implementation**

- [`docs/question-extraction.md`](./docs/question-extraction.md) - extraction algorithm and precision trade-offs for `aifd ai question list`
- [`docs/secret-scan.md`](./docs/secret-scan.md) - detectors, false-positive suppression, safety invariants
- [`docs/cost-calculation.md`](./docs/cost-calculation.md) - token pricing model and per-vendor cache semantics
- [`docs/skill-detection.md`](./docs/skill-detection.md) - cross-tool skill invocation detection and name normalization
- [`docs/vault-watch-lifecycle.md`](./docs/vault-watch-lifecycle.md) - daemon lifecycle, launchd interaction, crash recovery
- [`docs/vault-events-integrations.md`](./docs/vault-events-integrations.md) - webhook payload format and Slack / PagerDuty / Datadog wiring

**Project maintenance**

- [`docs/release.md`](./docs/release.md) - release process
- [`docs/claude-code-plugin-update.md`](./docs/claude-code-plugin-update.md) - notes on adapting to Claude Code plugin structure changes
- [`CHANGELOG.md`](./CHANGELOG.md) - version changes
- [`TODOS.md`](./TODOS.md) - roadmap + known follow-ups

## Feedback

Issues / discussions / PRs all welcome: <https://github.com/xunull/aifd>

Want support for another AI tool? Start at [Contribute a new provider](#contribute-a-new-provider) -- it's usually one file.

[⬆ Back to top](#aifd)
