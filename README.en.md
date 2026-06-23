# aifd

[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/aifd.svg)](https://pypi.org/project/aifd/)

**English** | [简体中文](./README.md)

> An AI coding history browser across Claude Code / Codex / OpenCode / Cursor + secret scanning + LLM coach.
> Answer questions like "my directories / the skills I've used / what AI asked me / how much I spent / what kind of AI user am I" with a single command.

Every AI coding tool stores its history in its own private format. `aifd` aggregates data from every tool **from your point of view**: by directory, by skill, by question, by spend, by behavior pattern -- not by tool.

```text
查 → 扫 → 算 → 盯 → 反思
session / skill / question  →  secret / PII  →  cost / token  →  实时 daemon  →  AI Coach
```

---

## 📑 Table of Contents

### ✨ [Highlights (7 screenshots)](#-highlights-gif-style)

### 🚀 [Quick Start](#-quick-start)
- [Install](#-install) · [One-minute try](#-one-minute-try)

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

### 🛠️ [Configuration and runtime](#%EF%B8%8F-configuration-and-runtime)
- [LLM config (`~/.aifd/config.yaml`)](#llm-config-aifdconfigyaml) · [Common flags](#common-flags) · [Current support matrix](#current-support-matrix)

### 🏗️ [Architecture and contributing](#%EF%B8%8F-architecture-and-contributing)
- [Architecture](#architecture) · [Contribute a new provider](#contribute-a-new-provider) · [Development](#development) · [The editable-install dep trap](#the-editable-install-dep-trap)

---

## ✨ Highlights (gif style)

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
```

To use the **AI Coach (reflect / habits)** you also need an LLM API key -- see [LLM config](#llm-config-aifdconfigyaml).

---

## 📚 Full command reference

Below, commands are grouped into four buckets: **query → compute → scan → reflect**. Each section opens with a one-liner + when to use it, followed by detailed flags and examples.

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

Claude Code only. Codex's `agent_message` and OpenCode's messages are all free text with no structured "ask the user" event -- so `--provider codex` / `--provider opencode` always returns empty. Extending to this kind of plain-text questioning requires heuristic extraction, which introduces noise, so the roadmap choice is **precision first**. For the detailed reasoning see [docs/question-extraction.md](./docs/question-extraction.md) and [TODOS.md](./TODOS.md).

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
```

By default it **exactly matches** the current directory. Recursive scanning (`-r`) is on the roadmap.

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

Detection support: Anthropic / OpenAI / GitHub PAT / AWS access key / Slack token / JWT / email / high-entropy strings. For the detailed mechanics see [docs/vault.md](./docs/vault.md).

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
- **Rotation playbook library** - 8 core vendors (openai / anthropic / github / aws / slack / jwt / gcp...) + a generic fallback; bilingual en + zh; with vendor dashboard links + steps

See [`docs/vault-events.md`](./docs/vault-events.md).

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

**The full `~/.aifd/config.yaml` schema** (auto-generated on the first `aifd ai reflect` run, with permissions auto `chmod 600`):

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

## 🛠️ Configuration and runtime

### LLM config (`~/.aifd/config.yaml`)

Both `aifd ai reflect` and `aifd ai habits` need an LLM API key. For the config location and schema, see the "full `~/.aifd/config.yaml` schema" subsection in the [`aifd ai reflect`](#aifd-ai-reflect---ai-coach-let-the-llm-see-how-you-use-ai) section.

**Priority:** `AIFD_LLM_*` env > provider-native env (`DEEPSEEK_API_KEY` / `ZHIPUAI_API_KEY` / ...) > `~/.aifd/config.yaml` > default (`deepseek/deepseek-chat`).

### `aifd quota` - MiniMax Coding Plan 5h quota (v0.12)

When you're coding on a MiniMax Coding Plan subscription, check how much of the current 5-hour rolling window you have left at any time, so you don't get cut off mid-task by running over:

```bash
aifd quota            # defaults to MiniMax
aifd quota minimax    # explicit (equivalent)
```

Output:

```text
MiniMax 5h: 剩 99%，3h27m 后重置
```
*(the CLI prints in Chinese)*

Configure the key (separate from the LLM key -- this is your coding-plan subscription key, not the reflect/habits LLM key):

```bash
export MINIMAX_API_KEY=your-key           # env takes priority
```

```yaml
# Or ~/.aifd/config.yaml
minimax:
  api_key: your-key
```

`aifd quota` is a group command that defaults to MiniMax; in the future `aifd quota <provider>` can add other subscriptions. The MiniMax key never appears in any error message (safety by design). The query does not consume your prompt quota.

> best-effort: MiniMax's usage endpoint is undocumented; if they change the response format, the command prompts "update aifd" instead of crashing.

### Common flags

```bash
aifd --version
aifd ai session list -v     # INFO logging
aifd ai session list -vv    # DEBUG logging
aifd ai retro --json        # almost every command supports --json
```

### Current support matrix

| Tool | Status | Notes |
|---|---|---|
| Claude Code | ✅ | Reads `~/.claude/projects/{encoded-cwd}/*.jsonl` |
| Codex | ✅ | Reads `~/.codex/state_5.sqlite` + `~/.codex/sessions/` as fallback |
| OpenCode | ✅ v0.10 | Reads `~/.local/share/opencode/opencode.db` (SQLite); session / token supported, skill invocations and questions return empty for now |
| Cursor | ✅ v0.11 | Reads `globalStorage/state.vscdb` + `workspaceStorage/` (cross-store JOIN); sessions supported (hash mapping ~80%, empty-shell filtering), listed by directory; skill invocations and questions return empty |

| LLM provider (via LiteLLM) | Command support |
|---|---|
| DeepSeek (default), Zhipu GLM, Alibaba Tongyi, Volcengine Ark, Moonshot Kimi | ✅ reflect / habits |
| OpenAI, Anthropic, Gemini, Groq, Together, Fireworks | ✅ reflect / habits |
| ollama / vLLM / Azure OpenAI / company OpenAI-compatible proxy | ✅ (use `--api-base`) |

---

## 🏗️ Architecture and contributing

### Architecture

One adapter per AI tool lives under `aifd/providers/`. Adding a provider = one file + one line of registration. The CLI is three layers (`aifd ai session list`), leaving room for future commands like `session show` / `session resume` / `ai prompt`.

```text
aifd/
├── cli/
│   ├── _logging.py          # logging config shared by all CLI commands
│   ├── _runner.py           # shared provider-query framework (v0.3)
│   ├── ai/
│   │   ├── session.py       # aifd ai session list (v0.1)
│   │   ├── skill.py         # aifd ai skill list (v0.2)
│   │   ├── question.py      # aifd ai question list (v0.3 + HTML v0.3.1)
│   │   ├── retro.py         # aifd ai today / weekly / monthly / retro (v0.5)
│   │   ├── reflect.py       # aifd ai reflect (v0.8)
│   │   ├── habits.py        # aifd ai habits (v0.9)
│   │   ├── claude/skill.py  # aifd ai claude skill list (v0.2.1)
│   │   └── codex/skill.py   # aifd ai codex skill list (v0.2.1)
│   └── vault/
│       ├── scan.py          # aifd vault scan (PII/secret scan, v0.4)
│       ├── cost.py          # aifd vault cost (token + $, v0.4)
│       └── watch.py         # aifd vault watch (daemon + events + webhooks, v0.6-0.7)
├── providers/
│   ├── base.py              # Provider Protocol, every new provider must implement it
│   ├── _utils.py            # shared regex / name normalization / frontmatter parsing
│   ├── claude.py            # Claude Code adapter
│   ├── codex.py             # Codex adapter
│   ├── opencode.py          # OpenCode adapter (v0.10)
│   └── registry.py          # where you register a new provider
├── insights/                # v0.8-0.9 AI Coach business logic
│   ├── activity.py          # session aggregation (shared by reflect / habits)
│   ├── reflection.py        # reflect dimension calculations
│   ├── habits.py            # habits dimension calculations
│   └── llm_client.py        # LiteLLM wrapper (100+ provider routing)
├── vault/                   # v0.4-0.7 business logic
│   ├── prices.py            # model → USD price table
│   ├── cost.py              # aggregate token → $
│   ├── scan.py              # PII/secret detector
│   ├── watch.py / watch_server.py / events_db.py / webhooks.py  # real-time daemon + event stream + push
│   └── playbooks.py         # secret rotation step library
├── aggregation.py           # skill stats aggregation (v0.2)
├── models.py                # Session / SkillInvocation / SkillStats / InstalledSkill / QuestionAnswer / TokenUsage / CostRow / SensitiveMatch
├── paths.py                 # cwd normalization
└── render.py                # rich Table / JSON / HTML rendering
```

### Contribute a new provider

1. Create `aifd/providers/yourtool.py`, implementing the `Provider` Protocol in `aifd/providers/base.py`.
2. Append your provider instance to the `PROVIDERS` list in `aifd/providers/registry.py`.
3. Add a fixture factory in `tests/conftest.py` (see `opencode_db` / `codex_db`) and write `tests/test_yourtool_provider.py`.
4. Make sure `uv run pytest`, `uv run ruff check aifd/ tests/`, and `uv run mypy aifd/` all pass.

The recent `aifd/providers/opencode.py` (v0.10) is a complete example of "one file + one line of registration".

**Single-file parse errors must silent-skip** (logged at `warning` or `debug` level), never raise -- one bad file must not take down the whole list.

### Development

```bash
git clone https://github.com/xunull/aifd
cd aifd
uv sync
uv run pytest
uv run ruff check aifd/ tests/
uv run mypy aifd/
```

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

## License

Apache-2.0 - see [LICENSE](./LICENSE).

## Related docs

- [`docs/ai-reflect.md`](./docs/ai-reflect.md) - full spec for `aifd ai reflect`
- [`docs/ai-habits.md`](./docs/ai-habits.md) - full spec for `aifd ai habits`
- [`docs/ai-retro.md`](./docs/ai-retro.md) - full spec for `aifd ai today / weekly / monthly / retro`
- [`docs/vault-watch.md`](./docs/vault-watch.md) - full spec for `aifd vault watch`
- [`docs/vault-events.md`](./docs/vault-events.md) - full spec for `aifd vault watch events / webhooks`
- [`docs/question-extraction.md`](./docs/question-extraction.md) - extraction algorithm for `aifd ai question list`
- [`docs/secret-scan.md`](./docs/secret-scan.md) - secret scan safety invariants
- [`CHANGELOG.md`](./CHANGELOG.md) - version changes
- [`TODOS.md`](./TODOS.md) - roadmap + known follow-ups

## Feedback

Issues / discussions / PRs all welcome: <https://github.com/xunull/aifd>

[⬆ Back to top](#aifd)
