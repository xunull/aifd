"""Domain types.

D6 decision (v0.1): the row count field is `event_count`, NOT
`message_count`. A jsonl line is a stored event (hook, permission, user
message, assistant message, tool_use, etc.). Calling it `message_count`
would mislead users expecting "number of user/assistant turns".

v0.2 additions: SkillInvocation (one user `/skill` call event) and
SkillStats (aggregated view across providers and projects).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Session:
    """One AI coding session for a specific cwd.

    Attributes:
        provider: short id, "claude" / "codex" / (v0.2) "cursor".
        session_id: provider-native id (UUID for Claude/Codex).
        cwd: the working directory the session was started in.
        started_at: first event timestamp; None if unparseable.
        event_count: total events stored (jsonl lines for Claude/Codex).
        source_path: original storage path, for debug and future show/resume.
        title: a short human-readable name. For Claude this is the
            `ai-title` event when present, else the first non-system user
            prompt's leading text. For Codex it's the first user_message
            event's leading text. None when no usable text was found.
    """

    provider: str
    session_id: str
    cwd: Path
    started_at: datetime | None
    event_count: int
    source_path: Path
    title: str | None = None


@dataclass(frozen=True)
class SkillInvocation:
    """One user-initiated skill (slash command) call.

    Attributes:
        skill_name: normalized name with leading `/` and `gstack-` prefix
            stripped, e.g. `/gstack-office-hours` becomes `office-hours`.
            See `aifd.providers._utils.normalize_skill_name`.
        provider: "claude" | "codex" | (v0.3) "cursor".
        cwd: working directory where the skill was invoked.
        ts: invocation timestamp; None if unparseable.
        source_path: jsonl or db file the event was read from.
        is_gstack: whether the raw marker carried the `gstack-` namespace
            prefix. Used for display restoration only — aggregation still
            uses the normalized name so cross-provider sums work.
    """

    skill_name: str
    provider: str
    cwd: Path
    ts: datetime | None
    source_path: Path
    is_gstack: bool = False


@dataclass(frozen=True)
class SkillStats:
    """Aggregated usage stats for a single skill across providers and projects."""

    skill_name: str
    count_claude: int
    count_codex: int
    total: int
    unique_cwd_count: int
    last_used: datetime | None
    is_gstack: bool = False


@dataclass(frozen=True)
class QuestionAnswer:
    """One AskUserQuestion event and the user's recorded answer.

    A single AUQ tool_use call may carry 1-4 questions; per the v0.3 CEO
    plan, each question becomes its own QuestionAnswer row so retro
    reads naturally as "I was asked X, I chose Y" with no further unpacking.

    Attributes:
        question: the question text shown to the user.
        options: option labels in presentation order.
        recommended_option: option label parsed as recommended (the
            `(recommended)` suffix on exactly one option). None when no
            option carried the marker — common for neutral-posture or
            older AUQ formats.
        chosen_option: option label the user selected. None when the
            user interrupted the call or the session was compacted before
            an answer was recorded — observed in ~4% of real sessions.
        notes: free-text the user typed via the "Other" path. None when
            absent.
        ts: when the question was asked. None when unparseable.
        cwd: working directory at the time of the question (read from the
            jsonl event's `cwd` field — authoritative, not the directory
            encoding).
        provider: "claude" | (future) "cursor".
        session_id: provider-native session id (e.g. UUID stem).
        source_path: jsonl path the event was read from, for debug.
        tool_use_id: the AUQ tool_use id, used to pair to tool_result.
            Kept for debugging Q-A pairing; not user-facing.
    """

    question: str
    options: tuple[str, ...]
    recommended_option: str | None
    chosen_option: str | None
    notes: str | None
    ts: datetime | None
    cwd: Path
    provider: str
    session_id: str
    source_path: Path
    tool_use_id: str


@dataclass(frozen=True)
class TokenUsage:
    """Per-event token accounting extracted from a provider's session events.

    v0.4 base type for `aifd vault cost`. One row per measurable usage event:
    Claude assistant message's `usage` field, or Codex `event_msg.token_count`
    with `payload.info.total_token_usage`.

    All counts default to 0 so callers can sum without nil guards. `model`
    is None when the event predates Codex's `turn_context` (very early
    sessions) or Claude's model echo (rare).

    Attributes:
        provider: "claude" | "codex" | (future) "cursor".
        session_id: provider-native session id (jsonl stem / rollout uuid).
        cwd: working directory the session ran in (None when unknown).
        ts: event timestamp; None when unparseable.
        model: model identifier as the provider records it
            ("claude-opus-4-7", "gpt-4o", ...). None when absent.
        input_tokens: fresh input tokens (not cached).
        output_tokens: completion tokens.
        cache_creation_input_tokens: tokens that landed in the cache
            (Claude prompt-cache writes; counted at full input rate plus
            the cache-write premium per Anthropic pricing).
        cache_read_input_tokens: tokens served from cache; cheap.
            Codex calls these `cached_input_tokens` and aifd normalizes.
        reasoning_output_tokens: Codex / o1-style models' invisible
            reasoning tokens. Billed at output rate. 0 for Claude.
        source_path: jsonl path the event was read from (debug).
    """

    provider: str
    session_id: str
    cwd: Path | None
    ts: datetime | None
    model: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    source_path: Path | None = None


@dataclass(frozen=True)
class CostRow:
    """One row in the `aifd vault cost` output (project xmonth, or rolled up).

    Cost numbers in USD. Token counts summed across all events that rolled
    into this row. `model` is None for cross-model aggregations; populated
    when grouping by model.
    """

    label: str  # project name, "YYYY-MM", model id, or composite
    provider: str  # "claude" | "codex" | "mixed"
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    cost_usd: float
    event_count: int  # number of (assistant) events that contributed


@dataclass(frozen=True)
class SensitiveMatch:
    """One potential secret / PII finding from `aifd vault scan`.

    Reported per match (so a file with 3 distinct API keys yields 3 rows).
    The full secret value is NEVER stored on the dataclass — only a
    redacted snippet (first/last 4 chars) so output is safe to share.

    Attributes:
        file: jsonl path the match was found in.
        line: 1-indexed line number inside the file.
        category: detector category ("openai_key", "github_pat",
            "aws_access_key", "jwt", "email", "high_entropy", ...).
        snippet_redacted: short preview, e.g. "sk-pr…REDACTED…4f9a".
            Safe to print to a shared screen.
        confidence: 1-10 self-rated. Regex hits are 8-9; entropy-only
            heuristics are 4-6. Useful for filtering noisy output.
        full_length: length of the matched substring, so a reader can
            judge whether a 16-char hex string is a real token or a hash.
    """

    file: Path
    line: int
    category: str
    snippet_redacted: str
    confidence: int
    full_length: int


@dataclass(frozen=True)
class InstalledSkill:
    """One skill installed on disk in a provider's skills directory.

    Distinct from SkillInvocation — this counts what's *available to call*,
    not what's *been called*. The two answer different questions and read
    different data sources (filesystem vs jsonl/SQLite event streams).

    Attributes:
        name: skill identifier as it appears in the user-facing list. Comes
            from SKILL.md frontmatter `name:` field, falls back to the
            directory name if frontmatter is missing or unparseable.
        description: short description from frontmatter `description:` field,
            joined onto one line. Empty string if missing.
        provider: "claude" | "codex" | (v0.3) "cursor".
        source: where in the provider's storage the skill lives.
            - "user"   = installed by the user (e.g. ~/.claude/skills/foo)
            - "plugin" = pulled in via a plugin/marketplace
            - "system" = shipped by the tool itself (e.g. Codex .system/)
        source_path: the SKILL.md path the skill was read from.
        version: optional version from frontmatter. None if absent.
        plugin: when source == "plugin", the parent plugin's name (parsed
            from the path). None otherwise.
        is_symlink: True if the skill's directory is a symlink (vendored).
    """

    name: str
    description: str
    provider: str
    source: str
    source_path: Path
    version: str | None = None
    plugin: str | None = None
    is_symlink: bool = False
