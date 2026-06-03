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
