# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.2.1] - 2026-06-03

### Added

- `aifd ai claude skill list` — list all skills installed for Claude Code.
  Scans both `~/.claude/skills/` (user-installed) and
  `~/.claude/plugins/cache/.../skills/` (plugin-installed). Each row carries a
  `Source` column distinguishing user / plugin entries and surfaces the plugin
  name + version for the latter.
- `aifd ai codex skill list` — list all skills installed for Codex. Scans
  `~/.codex/skills/` and `.system/`. Built-in Codex skills (imagegen,
  skill-creator, etc.) appear with `source="system"`.
- `aifd/providers/_utils.py` `parse_skill_frontmatter` — handwritten YAML
  frontmatter parser, no PyYAML runtime dependency. Extracts `name`,
  `description`, `version`. Tolerates missing / malformed frontmatter.
- `InstalledSkill` dataclass in `aifd/models.py`. Provider Protocol gains a
  default `list_installed_skills()` returning `()` so third-party providers
  without a skills directory inherit no-op behavior.
- Shared `aifd/cli/_logging.py` `configure_logging()` helper. Replaces three
  duplicated `_configure_logging` definitions across `session.py`,
  `skill.py`, and the new per-provider commands.
- `docs/skill-detection.md` — technical reference for how skill markers and
  installed-skill discovery work across Claude jsonl, Codex SQLite, and the
  filesystem scans.

### Changed

- README updated with new command examples (`aifd ai claude/codex skill list`),
  architecture diagram now shows the v0.2.1 layout (`cli/_logging.py`,
  `cli/ai/claude/`, `cli/ai/codex/`).

## [0.2.0] - 2026-06-02

### Added

- `aifd ai skill list` — aggregates skill (slash-command) invocations across
  Claude Code and Codex into a single cross-tool view. Columns: skill name,
  per-provider counts, total, last-used relative time, distinct project count.
- `--cwd` flag to limit aggregation to the current directory. Default is global.
- `--provider claude|codex` flag to filter by source tool.
- `--json` flag for pipe-friendly output.
- `aifd/aggregation.py` — pure `aggregate_skill_stats(invocations) -> [stats]`
  function. Lives outside `cli/` so v0.3 `aifd ai stats` can reuse without
  coupling to a command's flag layout.
- `aifd/providers/_utils.py` — shared regexes (`CLAUDE_COMMAND_RE`,
  `CODEX_SKILL_RE`), `normalize_title`, `parse_iso_ts`,
  `normalize_skill_name` (strips `/` and `gstack-` prefix for cross-provider
  alignment), `is_gstack_name` for display restoration.
- `SkillInvocation` and `SkillStats` dataclasses with `is_gstack` flag.
  Aggregation OR-combines `is_gstack` so any tool's `/gstack-foo` flips the
  stat. Renderer restores `gstack-` prefix in the Table display while JSON
  keeps the normalized name plus `"is_gstack": bool` field.
- Codex provider extracts skill invocations from the `state_5.sqlite`
  `threads.first_user_message LIKE '[$%'` query (primary) with rollout-jsonl
  fallback when SQLite is unavailable.
- Claude provider extracts `<command-name>` markers from user-typed messages
  only; the `type=="user"` filter rejects assistant echoes and documentation
  strings that contain the literal marker text.

### Changed

- Codex provider migrated to **SQLite-first** architecture for session
  listing (`state_5.sqlite` `threads` table). jsonl scan remains as fallback
  for older Codex installs. Surfaces AI-generated `title` + `first_user_message`
  fields the jsonl path never had access to.
- `Session.message_count` renamed to `Session.event_count` to honestly
  describe the unit (jsonl lines / Codex events, not user/assistant turns).
- Session listing now displays an AI-generated title column when available
  (Claude `ai-title` event, Codex `threads.title`).

## [0.1.0] - 2026-06-01

### Added

- `aifd ai session list` — list AI sessions in the current directory across
  Claude Code and Codex.
- Provider Protocol (`typing.Protocol` + `@runtime_checkable`) with two
  initial implementations.
- Claude provider: two-phase cwd matching (directory-name encoding +
  authoritative jsonl cwd field) to handle paths containing `-` correctly.
- Codex provider: scans both `~/.codex/sessions/` and
  `~/.codex/archived_sessions/`.
- Three-tier error handling: IO error → warning skip file, JSON parse error →
  debug skip line, no matching event → silent skip. Single bad file never
  breaks the listing.
- `paths.normalize_cwd` + `cwd_equal` with OSError fallback for broken
  symlinks (Python 3.13 macOS) and case-insensitive matching on
  HFS+/APFS/NTFS.
- `--json`, `--provider`, `--verbose` flags.
- pytest + ruff + mypy strict + GitHub Actions CI matrix
  (Python 3.12+3.13 × Linux/macOS/Windows).
- GitHub Actions release workflow targeting PyPI Trusted Publisher.

[0.2.1]: https://github.com/xunull/aifd/releases/tag/v0.2.1
[0.2.0]: https://github.com/xunull/aifd/releases/tag/v0.2.0
[0.1.0]: https://github.com/xunull/aifd/releases/tag/v0.1.0
