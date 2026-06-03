# aifd

Two ways to look at your AI coding history across Claude Code, Codex, and (soon) Cursor:

**1. Per-directory session listing**

```text
$ aifd ai session list                # in any project directory
┏━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┓
┃ Provider ┃ Session  ┃ Started ┃ Events ┃ Title            ┃ Source           ┃
┡━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━┩
│ claude   │ bbfc1d21 │  2h ago │    781 │ Install Claude … │ ~/.claude/p…     │
│ codex    │ 019e7d19 │  1d ago │      0 │ 审计计划完成情况 │ ~/.codex/se…     │
└──────────┴──────────┴─────────┴────────┴──────────────────┴──────────────────┘
```

**2. Cross-tool skill usage stats (v0.2)**

```text
$ aifd ai skill list                  # default global, --cwd to limit
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Skill           ┃ Claude ┃ Codex ┃ Total ┃ Last Used ┃ Projects ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━┩
│ plan-ceo-review │      9 │    32 │    41 │    2h ago │       11 │
│ office-hours    │     13 │    20 │    33 │   11h ago │       17 │
│ model           │     16 │     0 │    16 │    4h ago │       11 │
└─────────────────┴────────┴───────┴───────┴───────────┴──────────┘
```

Every AI coding tool stores history in its own private format. That makes
"which AI sessions have I had in this project?" and "what skills do I actually
use day-to-day?" questions with no single answer — until now. `aifd` reads
each tool's storage from the user's perspective ("this directory", "these
skills"), not the vendor's perspective ("my history").

## Install

```bash
# with pipx (recommended)
pipx install aifd

# or with uv
uvx aifd ai session list   # one-shot
uv tool install aifd       # persistent

# or with pip
pip install aifd
```

Requires Python 3.12+.

## Usage

### `aifd ai session list` — sessions in the current directory

```bash
# list everything for the current directory
aifd ai session list

# JSON output, pipe-friendly
aifd ai session list --json | jq '.[] | .session_id'

# filter by provider
aifd ai session list --provider claude
aifd ai session list --provider codex
```

The match is **exact** by default: shows sessions whose recorded cwd equals
the current directory. Recursive scanning (`-r`) is on the roadmap.

### `aifd ai skill list` — cross-tool skill usage stats (v0.2)

```bash
# global skill usage across every Claude project + every Codex thread
aifd ai skill list

# limit to the current project
aifd ai skill list --cwd

# JSON for piping into jq / fzf / your scripts
aifd ai skill list --json | jq '.[] | select(.total > 5)'

# only one provider
aifd ai skill list --provider claude
```

Output columns:
- **Claude / Codex / Total** — how many times you invoked this skill in each tool
- **Last Used** — relative time of the most recent invocation
- **Projects** — how many *distinct* directories you've used this skill in (high
  = cross-project work flow; low = focused on one project)

Default scope is **global** because a single project usually has only a handful
of skill calls — the cross-project pattern is the interesting data. Use `--cwd`
when you want "what skills did I use building *this* project."

Skill names are normalized across providers: Claude's `/gstack-office-hours`
and Codex's `[$office-hours]` both aggregate as `office-hours`.

### `aifd ai claude skill list` / `aifd ai codex skill list` — installed skills

```bash
# what skills are installed for Claude Code
aifd ai claude skill list

# what skills are installed for Codex
aifd ai codex skill list

# JSON for filtering / scripting
aifd ai claude skill list --json | jq '.[] | select(.source == "plugin")'
aifd ai codex skill list --json | jq '.[] | select(.source == "system") | .name'
```

Output columns: **Skill / Source / Description / Version / Plugin**.

Sources distinguish where the skill came from:
- **user** — installed by you (`~/.claude/skills/...` or `~/.codex/skills/...`)
- **plugin** — pulled in via a marketplace plugin (Claude only)
- **system** — shipped by the tool itself (Codex `.system/` built-ins)

Same-name skills from different sources show as two rows — by design, so you
see exactly what's installed where.

### Common flags

```bash
aifd --version
aifd ai session list -v     # INFO logging
aifd ai session list -vv    # DEBUG logging
```

## What's supported

| Tool         | MVP (v0.1) | Notes |
|--------------|------------|-------|
| Claude Code  | ✅          | Reads `~/.claude/projects/{encoded-cwd}/*.jsonl` |
| Codex        | ✅          | Reads `~/.codex/sessions/` and `~/.codex/archived_sessions/` |
| Cursor       | ⏳ v0.2     | Needs SQLite + workspace-hash reverse lookup (see [TODOS.md](./TODOS.md)) |

## Architecture

Each AI tool has its own adapter under `aifd/providers/`. Adding a new provider is
one file + one line in `aifd/providers/registry.py`. The CLI is organized in three
layers (`aifd ai session list`) to leave room for `session show`, `session resume`,
`ai prompt`, and other future commands.

```text
aifd/
├── cli/
│   ├── _logging.py          # Shared logging setup for all CLI commands
│   └── ai/
│       ├── session.py       # `aifd ai session list`
│       ├── skill.py         # `aifd ai skill list` (cross-tool usage stats, v0.2)
│       ├── claude/skill.py  # `aifd ai claude skill list` (installed skills, v0.2.1)
│       └── codex/skill.py   # `aifd ai codex skill list` (installed skills, v0.2.1)
├── providers/
│   ├── base.py              # Provider Protocol every adapter must implement
│   ├── _utils.py            # Shared regex, normalization, frontmatter parser
│   ├── claude.py            # Claude Code adapter
│   ├── codex.py             # Codex adapter
│   └── registry.py          # Where you'd add a new provider
├── aggregation.py           # Per-skill stat reduction (v0.2)
├── models.py                # Session + SkillInvocation + SkillStats + InstalledSkill
├── paths.py                 # cwd normalization
└── render.py                # rich Table + JSON output
```

## Contributing a provider

1. Add `aifd/providers/yourtool.py` implementing the `Provider` Protocol from `aifd/providers/base.py`.
2. Append your provider instance to `PROVIDERS` in `aifd/providers/registry.py`.
3. Add fixtures under `tests/fixtures/yourtool/` and a `test_yourtool_provider.py`.
4. Make sure `uv run pytest`, `uv run ruff check aifd/ tests/`, and `uv run mypy aifd/` all pass.

Single-file parse errors must be silently skipped (logged at `warning` or `debug`),
never raised — one bad file must not break the listing.

## Development

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
