# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/) and this
project adheres to [Semantic Versioning](https://semver.org/).

## [0.4.1] - 2026-06-04

### Added

#### `aifd vault scan --web` — browser UI with redacted secrets in context

New flag opens a localhost-only HTTP server (`127.0.0.1`, kernel-picked
ephemeral port) that renders findings as an HTML page with:

- Per-category tabs (`anthropic_key`, `openai_key`, …, `high_entropy`),
  ordered by detector confidence DESC — most dangerous category first
- CSS-only tab switching (radio + sibling combinator) — zero JS
- Each finding shows ±200 chars of conversation context around the
  secret, with the leak highlighted via `<mark>`
- Expandable `<details>` block per finding for the full raw jsonl line
- JSON escape sequences (`\n` / `\t` / `\"` / `\uXXXX`) are decoded so
  conversation context reads naturally instead of showing literal `\n`
- Warning banner: "this page contains raw secrets; press Ctrl-C in the
  terminal when done"
- 16 KiB truncation badge surfaces when a scan-clipped line might have
  cut off `context_after`

Architecture: nothing is written to disk. Findings live in process
memory; the HTTP server dies on Ctrl-C and secrets drop with it. Server
binds 127.0.0.1 only — never reachable from another host on the LAN.
`SensitiveMatch` gained five optional fields (`context_before` /
`match_full` / `context_after` / `raw_line` / `line_truncated`) that
populate only when `capture_context=True` (via `--web`); all other
code paths continue to carry just `snippet_redacted`. See
`docs/secret-scan.md` Security section for the dual-mode posture.

`--web` and `--json` are mutually exclusive (interactive vs pipe).

#### Suppressor framework + 4 built-in FP filters

Scan now runs a post-match suppression layer before emitting matches.
Each suppressor is a named predicate with a debug-loggable reason
(`aifd vault scan -vv` surfaces every suppression). Built-in rules:

- **`escape_prefix`** — matches starting right after a literal `\` in
  the source line are dropped. Catches the `\n@click.group` /
  `\n@router.post` / `\n@pytest.fixture` class where the email regex's
  `\b` word boundary fires between the escape and the decorator's
  module name. Measured on 50-file sample: 80.8% of email matches.
- **`reserved_email_domain`** — RFC 2606 §3 SLDs (`example.com` /
  `.org` / `.net`) including subdomains (`api.example.com` etc, since
  RFC 2606 reserves "the labels that compose them") + §2 TLDs
  (`.test` / `.example` / `.invalid` / `.localhost`). Case-insensitive.
- **`noreply_local_part`** — `noreply@` / `no-reply@` / `do-not-reply@`
  / `donotreply@` (case-insensitive). SMTP sender-only convention;
  not PII for an individual.
- **`placeholder_email_domain`** — common doc/UI placeholder domains:
  `domain.com` / `email.com` / `yourdomain.com` / `yoursite.com` /
  `mysite.com`. No subdomain match (`api.email.com` is likely a real
  service endpoint, not a placeholder).

Cumulative impact on a real history: 953 email findings at v0.4.0 →
271 after all four suppressors land = **71.6% noise reduction**, zero
real-PII loss verified via regression tests.

### Improved

#### `aifd vault scan` ~9.5s on 832 MB jsonl (was ~14.5s, ~50s pre-v0.4)

OPT-3 prefix prefilter swapped its Python regex alternation for a
substring `in` loop (`_QUICK_PREFIX_LITERALS` + `_has_vendor_anchor`).
C `strstr` runs 3.4× faster than NFA alternation on the same workload
(micro-benchmark). End-to-end scan: 14.5s → 9.3s. Cumulative since
v0.3.x: ~5.4× wall-clock speedup.

DRY meta-test (`test_quick_prefix_covers_all_regex_detectors`) updated
to use the new substring helper. Detector list and prefilter literals
stay synchronized at test time.

### Fixed

- The RFC 2606 suppressor's first cut only matched exact SLDs
  (`example.com`); subdomains (`api.example.com`, `mail.example.org`)
  leaked through. Predicate now matches both the SLD itself and any
  subdomain of it, per spec wording ("the labels that compose them
  are reserved"). Regression test added.

### Performance

- `_has_vendor_anchor` substring loop: 3.4× faster than alternation
  regex on the hot path
- Suppressors add < 50 ms total on 1369 raw matches (negligible)
- Web HTML rendering: 1369 findings → 6 MB HTML in < 100 ms

### Documentation

- `docs/secret-scan.md` — new "⚠ --web 模式与安全 invariant" section
  documenting the dual-mode security posture of `SensitiveMatch`
- `TODOS.md` — added v0.5 candidates: `aifd vault scan --exclude REGEX`
  (user-configurable suppressors) and `--show-suppressed` (debug flag
  surfacing suppressed matches with reasons)

## [0.4.0] - 2026-06-04

### Added

`aifd vault` — new top-level command group for data-sovereignty
operations. v0.3 was "look at your AI history"; v0.4 starts treating
that history as your asset that you own, audit, and protect.

#### `aifd vault scan` — PII / secret detector

Walks every provider's jsonl (`~/.claude/projects`, `~/.codex/sessions`,
`~/.codex/archived_sessions`) looking for likely-secret patterns.
Output is safe to share: every snippet is redacted (first 4 + last 4
chars only), the full secret is never stored beyond the scan loop.

Detectors:
- Anthropic `sk-ant-`, OpenAI `sk-` / `sk-proj-`, GitHub `ghp_` /
  `github_pat_` / `ghs_`, AWS `AKIA*`, Slack `xox[baprs]-`, JWT
  (eyJ-prefixed) — confidence 8-10, all regex
- email addresses, bearer tokens — confidence 7
- high-entropy strings (Shannon ≥4.5, length 40-200) — confidence 4-6,
  noisy fallback for unknown secret formats; suppressed by default
  via `--min-confidence 7`

Flags:
- `--root PATH` (repeatable) — add a path to scan, file or directory
- `--no-default-roots` — only scan `--root` paths
- `--min-confidence N` (default 7) — suppress lower-confidence finds
- `--json` — full record (with redacted snippet), pipe-friendly
- `-v / -vv` — log verbosity

Real-world calibration: scanning my own history (32 Claude projects,
115 Codex sessions) surfaced 304 leaked OpenAI keys, 1 GitHub PAT, 918
emails, 4 JWTs. The 7-default threshold suppressed ~287K low-confidence
entropy hits (hashes, embeddings, etc.) that would have drowned the
real findings.

#### `aifd vault cost` — token + USD spend aggregation

Reads per-event token usage from both providers and rolls it up by
project / model / month / provider. Prices from a bundled table
(`aifd/vault/prices.py`), date-stamped so users know when to verify.

Data sources:
- Claude: `message.usage` on every assistant event (per-message
  incremental — sums cleanly)
- Codex: `event_msg.token_count.payload.info.total_token_usage` (per
  session cumulative — provider collapses to one row per session
  holding the cumulative max so the aggregator can still simply sum)

OpenAI schema reconciliation: `input_tokens` in OpenAI's payload
INCLUDES `cached_input_tokens`. The Codex provider subtracts cached
so our schema (and Claude's) consistently treats `input_tokens` as
fresh-input-only. Without this, cached tokens would be double-billed
at the full input rate.

Flags:
- `--by project|model|month|provider` (default project)
- `--provider claude|codex` — filter
- `--json` — pipe-friendly
- `--list-models` — show priced models so unknown ones are easy to spot
- `-v / -vv`

Bundled model prices cover Claude 4 family (opus / sonnet / haiku),
3.5 family, 3-opus + OpenAI gpt-5 / gpt-5.5 / gpt-4o / gpt-4o-mini /
o1 / o3 / codex-auto-review. Unknown models render with $0 attributed
so token volume is still visible.

#### Infrastructure

- `aifd/models.py`: `TokenUsage`, `CostRow`, `SensitiveMatch` dataclasses
- `aifd/vault/`: new package (`prices.py`, `cost.py`, `scan.py`)
- `aifd/cli/vault/`: new command group (`scan.py`, `cost.py`)
- `aifd/providers/base.py`: Protocol gains `list_token_usage(scope)
  -> Iterable[TokenUsage]` default returning `()` (matches v0.2/v0.3
  pattern)
- `aifd/providers/claude.py`, `codex.py`: both implement
  `list_token_usage` against their native schemas
- `aifd/render.py`: `render_scan_matches`, `render_cost_rows` (Table +
  JSON modes, color-coded confidence for scan, sorted-by-cost for cost)
- 42 new tests across `test_vault_scan.py` / `test_vault_cost.py` /
  `test_vault_cli.py` — total 237 passed, 0 ruff, 0 mypy

### Notes

- `aifd vault export` and `aifd vault sync` are deferred to v0.5+ per
  the v0.4 CEO plan; both are in TODOS.md with context. v0.5 candidate
  triggers: user reports wanting backup before any incident, or
  cross-machine migration.
- Model price table verified against vendor pages as of 2026-06-04.
  The CLI footer always shows this date so users know when to
  re-verify. To override locally without a release: copy
  `aifd/vault/prices.py` and patch (no `--config` flag yet — deferred
  to v0.5).

## [0.3.1] - 2026-06-03

### Added

- `aifd ai question list --open` — zero-friction browser view. Writes
  the HTML to a temp file and launches your default browser in one
  command. Solves the v0.3 Table pain point that 67% of real questions
  are longer than 200 characters and 12% exceed 500 (median 408) —
  terminals truncate, browsers don't. No `--output`, no `--html`, no
  thinking about a path.
- `aifd ai question list --output PATH` — persist HTML to a specific
  file. Combine with `--open` to also launch the browser. Implies
  HTML mode (no need to also pass `--html`).
- `aifd ai question list --html` — print the HTML page to stdout for
  pipes (`> out.html`, `| caddy file-server`, etc.).
- HTML layout is Notion / Linear style: one card per question,
  system-followed dark/light theme, 70ch max-width, chosen option
  highlighted green, recommended option marked with ★. Long question
  text wraps; multiSelect answers render as a separate "Selected:" row.
- ALL user-derived text passes through `html.escape()` — question /
  options / chosen / recommended / notes / cwd / source / scope_label —
  so a historic question like "how do I sanitize `<script>`?" cannot
  XSS the rendered page. Verified by regression tests in
  `tests/test_question_render.py`.

### Notes

- HTML / JSON modes are mutually exclusive; mixing them emits a
  one-line `click.UsageError`. The other knobs (`--html`, `--open`,
  `--output`) compose freely.
- File-write failures (e.g. read-only path) surface as
  `Error: cannot write to <path>: <reason>` on stderr with exit code 1.
  Per CLAUDE.md "zero silent failures + every error has a name".

## [0.3.0] - 2026-06-03

### Added

- `aifd ai question list` — retro of every `AskUserQuestion` call the AI
  asked you, paired with the option you selected. Reads Claude jsonl,
  finds `tool_use` blocks whose name matches
  `^(AskUserQuestion|mcp__.*__AskUserQuestion)$` (covers MCP host
  variants), then pairs each call's `tool_use_id` to the user's
  `tool_result` so the row carries both the question and the chosen
  answer. Orphan questions (~4% of real sessions — user interrupted or
  session compacted) emit with `chosen_option=None` and render as
  "no answer recorded" so they stay visible in the retro.
- `--cwd` flag to limit to the current directory (default is global,
  mirrors `aifd ai session list`).
- `--limit N` (default 50) plus `--all` to opt out, so the first run on
  a heavy-AUQ user doesn't dump thousands of rows.
- `--provider claude` filter; Codex returns an empty iterable because
  its `agent_message` events are free-form text with no structured
  question event (covered in `docs/question-extraction.md`).
- `--json` flag emits the full record including `options`, `notes`,
  `tool_use_id`, `source_path` for pipe / jq workflows.
- Summary footer: `N questions in <scope> | recommended hit rate: X%
  (M/N) | K unanswered`. Hit-rate denominator excludes orphans and
  rows with no recommendation, so the percentage reflects only the
  decisions that had a baseline.
- `aifd.models.QuestionAnswer` dataclass — one row per question (a
  single 1-4-question AUQ call yields multiple rows). Frozen, so it
  composes cleanly into v0.3+ stats / search.
- `aifd.cli._runner.run_provider_query` — shared harness extracted
  from `cli/ai/session.py` once the second multi-provider list command
  joined the file. session.py now delegates to it, so the v0.3+
  commands (stats, search, ...) plug in three callables instead of
  re-deriving the boilerplate.
- `aifd.providers._utils.split_recommended_suffix` recognises both
  English `(recommended)` and Chinese / Japanese / Korean / Spanish /
  French / German glosses (`(推荐)`, `(推奨)`, `(권장)`, ...). Driven
  by real-world data: every user-recorded session in the dev set used
  the localized suffix.
- `docs/question-extraction.md` — Chinese design doc covering the AUQ
  jsonl schema, `tool_use_id` pairing, multi-question splitting,
  orphan handling, and why Codex/brainstorm are deferred. Matches the
  v0.2.1 `docs/skill-detection.md` pattern.
- 45 new tests across `test_question_extraction.py` (provider unit),
  `test_question_render.py` (Table + footer + JSON), `test_question_cli.py`
  (end-to-end), `test_runner.py` (shared harness contract).

### Changed

- Provider Protocol gains `list_question_answers(scope) -> Iterable[QA]`
  default body returning `()`, matching the v0.2 pattern for
  `list_skill_invocations` and `list_installed_skills`. `CodexProvider`
  explicitly overrides with the same no-op shape because duck-typed
  classes don't inherit Protocol default bodies.
- `cli/ai/session.py` refactored to use `run_provider_query`. Behaviour
  identical (132 prior tests pass unchanged) but the harness is now
  shared with `aifd ai question list`.

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

[0.4.0]: https://github.com/xunull/aifd/releases/tag/v0.4.0
[0.3.1]: https://github.com/xunull/aifd/releases/tag/v0.3.1
[0.3.0]: https://github.com/xunull/aifd/releases/tag/v0.3.0
[0.2.1]: https://github.com/xunull/aifd/releases/tag/v0.2.1
[0.2.0]: https://github.com/xunull/aifd/releases/tag/v0.2.0
[0.1.0]: https://github.com/xunull/aifd/releases/tag/v0.1.0
