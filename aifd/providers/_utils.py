"""Shared helpers used across provider implementations.

Extracted after the eng review found `_normalize_title` and `_parse_ts`
duplicated across claude.py and codex.py. Future providers (Cursor) and
the new skill-invocation parsers reuse these directly.
"""

from __future__ import annotations

import re
from datetime import datetime


def normalize_title(text: str) -> str:
    """Collapse whitespace so titles fit on one Table row."""
    return " ".join(text.split())


def parse_iso_ts(s: str) -> datetime | None:
    """Parse ISO 8601 timestamps. Tolerates trailing `Z`.

    Returns None on any parse failure (e.g. empty, malformed).
    """
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# A skill invocation marker is the user's slash-command alias. Examples:
#   `/model`             -> "model"
#   `/gstack-office-hours` -> "office-hours" (gstack- prefix stripped)
#   `office-hours`       -> "office-hours" (Codex form, no leading slash)
#
# Cross-provider normalization rationale: Claude writes `/gstack-foo` while
# Codex writes `foo`. Without normalization, `office-hours` and
# `gstack-office-hours` would count as distinct skills, defeating the
# value of cross-provider aggregation.
_GSTACK_PREFIX = "gstack-"


def normalize_skill_name(raw: str) -> str:
    """Strip leading slash and the `gstack-` prefix when present.

    Cross-provider names align: Claude `/gstack-office-hours` and Codex
    `office-hours` both become `office-hours`.
    """
    name = raw.strip()
    if name.startswith("/"):
        name = name[1:]
    if name.startswith(_GSTACK_PREFIX):
        name = name[len(_GSTACK_PREFIX):]
    return name


def is_gstack_name(raw: str) -> bool:
    """Whether the raw marker came from the gstack skill namespace.

    Detects both Claude-form `/gstack-foo` and prefix-only `gstack-foo`.
    Used for display: aggregation stays cross-provider via
    normalize_skill_name, but the Table renders gstack skills with the
    prefix restored so users recognize their own slash-commands.
    """
    name = raw.strip()
    if name.startswith("/"):
        name = name[1:]
    return name.startswith(_GSTACK_PREFIX)


# Marker regexes. Compiled at import time so per-line scans are cheap.
CLAUDE_COMMAND_RE = re.compile(r"<command-name>([^<]+)</command-name>")
CODEX_SKILL_RE = re.compile(r"^\[\$([^\]]+)\]")


# Frontmatter parsing — handwritten so we don't ship PyYAML as a runtime dep.
# Only extracts top-level scalar fields (name / description / version). Multi-
# line `|` blocks are joined to a single normalized line. List values and
# nested maps are ignored — they exist in SKILL.md (e.g. `allowed-tools:`) but
# none of them are interesting for "what's installed" listings.
_FRONTMATTER_KEYS = {"name", "description", "version"}


def parse_skill_frontmatter(text: str) -> dict[str, str]:
    """Extract a small fixed set of scalar fields from a SKILL.md frontmatter.

    The accepted shape is the standard `---` ... `---` block at the top of
    the file. Any non-matching content (no frontmatter, no closing `---`,
    junk lines) is tolerated — the function returns whatever it could
    extract, defaulting to {}.

    Supported value forms:
      key: value           -> {"key": "value"}
      key: "value"         -> {"key": "value"}  (quotes stripped)
      key: |               -> {"key": "first second"}  (joined + collapsed)
        first
        second
      key:                 -> ignored (no value)
      key:                 -> ignored (list / nested)
        - item
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    # Find closing `---`
    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end == -1:
        return {}

    body = lines[1:end]
    out: dict[str, str] = {}

    i = 0
    while i < len(body):
        line = body[i]
        stripped = line.rstrip()
        # Skip blank or comment lines
        if not stripped.strip() or stripped.lstrip().startswith("#"):
            i += 1
            continue
        # Skip indented lines — they're continuation of a multi-line value
        # we already consumed, or part of a list/map we're ignoring.
        if line[:1] in (" ", "\t"):
            i += 1
            continue

        # Top-level `key:` or `key: value`
        sep = stripped.find(":")
        if sep <= 0:
            i += 1
            continue
        key = stripped[:sep].strip()
        rest = stripped[sep + 1 :].strip()

        if key not in _FRONTMATTER_KEYS:
            i += 1
            continue

        if rest == "|" or rest == ">":
            # Multi-line block — collect indented following lines.
            parts: list[str] = []
            j = i + 1
            while j < len(body):
                nxt = body[j]
                if nxt.strip() == "":
                    j += 1
                    continue
                if nxt[:1] not in (" ", "\t"):
                    break
                parts.append(nxt.strip())
                j += 1
            out[key] = " ".join(parts)
            i = j
            continue

        if not rest:
            # `key:` with no inline value and no `|` — could be a list/map
            # below. Skip the key entirely; aifd doesn't surface list fields.
            i += 1
            continue

        # Inline scalar. Strip surrounding quotes if present.
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in ('"', "'"):
            rest = rest[1:-1]
        out[key] = rest
        i += 1

    return out
