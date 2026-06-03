"""Output rendering: rich Table for humans, JSON for pipes.

Designed so the same `list[Session]` works in both modes — the CLI just
flips `as_json`. JSON schema is stable across versions for downstream
consumers (jq, fzf, etc).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from aifd.models import InstalledSkill, Session, SkillStats


def render_sessions(rows: Sequence[Session], cwd: Path, *, as_json: bool) -> None:
    """Render to stdout."""
    if as_json:
        _render_json(rows)
        return

    if not rows:
        # Friendly empty-state; not an error, exit code 0.
        Console().print(f"[dim]No AI sessions found in[/dim] [bold]{cwd}[/bold]")
        return

    _render_table(rows)


# Column width caps — keep the whole table on one screen.
# Title is the most useful info-per-pixel; give it room.
# Source is debug info; truncate it (full path is in --json output).
_TITLE_MAX = 60
_SOURCE_MAX = 40


def _render_table(rows: Sequence[Session]) -> None:
    """Default human-friendly output via rich.Table."""
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Provider", style="green")
    table.add_column("Session", style="dim")
    table.add_column("Started", justify="right")
    table.add_column("Events", justify="right")
    table.add_column("Title", overflow="ellipsis", max_width=_TITLE_MAX)
    table.add_column("Source", style="dim", overflow="ellipsis", max_width=_SOURCE_MAX)

    for s in rows:
        table.add_row(
            s.provider,
            _short_id(s.session_id),
            _relative_time(s.started_at) if s.started_at else "—",
            str(s.event_count),
            _truncate(s.title, _TITLE_MAX) if s.title else "—",
            _truncate(str(s.source_path), _SOURCE_MAX),
        )

    Console().print(table)


def _render_json(rows: Sequence[Session]) -> None:
    """Pipe-friendly JSON. Path -> str, datetime -> ISO 8601 with offset.

    JSON includes the FULL title (not truncated) — pipes downstream may
    want the whole thing for grep / search / display.
    """
    payload = [
        {
            "provider": s.provider,
            "session_id": s.session_id,
            "cwd": str(s.cwd),
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "event_count": s.event_count,
            "title": s.title,
            "source_path": str(s.source_path),
        }
        for s in rows
    ]
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _truncate(text: str, limit: int) -> str:
    """Hard cap with an ellipsis. Rich also does this, but we want the same
    text to appear in JSON-like contexts in the future."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def render_skill_stats(
    stats: Sequence[SkillStats], scope_label: str, *, as_json: bool
) -> None:
    """Render skill aggregation to stdout.

    scope_label appears in the empty-state message and helps the user
    confirm whether they're looking at global or cwd-scoped data.
    """
    if as_json:
        _render_skill_stats_json(stats)
        return

    if not stats:
        Console().print(f"[dim]No skill invocations found[/dim] [bold]{scope_label}[/bold]")
        return

    _render_skill_stats_table(stats)


def _render_skill_stats_table(stats: Sequence[SkillStats]) -> None:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Skill", overflow="ellipsis", max_width=_TITLE_MAX)
    table.add_column("Claude", justify="right", style="green")
    table.add_column("Codex", justify="right", style="cyan")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("Last Used", justify="right")
    table.add_column("Projects", justify="right", style="dim")

    for s in stats:
        # Restore the gstack- prefix in the display so users recognize their
        # own slash commands. Aggregation stays on the normalized name.
        display = f"gstack-{s.skill_name}" if s.is_gstack else s.skill_name
        table.add_row(
            _truncate(display, _TITLE_MAX),
            str(s.count_claude),
            str(s.count_codex),
            str(s.total),
            _relative_time(s.last_used) if s.last_used else "—",
            str(s.unique_cwd_count),
        )

    Console().print(table)


def _render_skill_stats_json(stats: Sequence[SkillStats]) -> None:
    payload = [
        {
            "skill_name": s.skill_name,
            "is_gstack": s.is_gstack,
            "count_claude": s.count_claude,
            "count_codex": s.count_codex,
            "total": s.total,
            "unique_cwd_count": s.unique_cwd_count,
            "last_used": s.last_used.isoformat() if s.last_used else None,
        }
        for s in stats
    ]
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


# Installed-skills rendering. Display sorted by (source, name) so
# user-installed group together, then plugin/system. Description column gets
# the lion's share of the width — it's what users scan.
_DESC_MAX = 80
_SOURCE_STYLE = {
    "user": "green",
    "plugin": "magenta",
    "system": "yellow",
}


def render_installed_skills(
    skills: Sequence[InstalledSkill],
    provider_label: str,
    *,
    as_json: bool,
) -> None:
    """Render the installed-skills table or JSON.

    `provider_label` appears in the empty-state message so users confirm
    which tool was scanned.
    """
    if as_json:
        _render_installed_skills_json(skills)
        return

    if not skills:
        Console().print(
            f"[dim]No installed skills found in[/dim] [bold]{provider_label}[/bold]"
        )
        return

    _render_installed_skills_table(skills)


def _render_installed_skills_table(skills: Sequence[InstalledSkill]) -> None:
    ordered = sorted(skills, key=lambda s: (s.source, s.name.lower()))

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Skill", overflow="ellipsis", max_width=_TITLE_MAX)
    table.add_column("Source")
    table.add_column("Description", overflow="ellipsis", max_width=_DESC_MAX)
    table.add_column("Version", justify="right", style="dim")
    table.add_column("Plugin", style="dim")

    for s in skills_with_pad(ordered):
        source_text = f"[{_SOURCE_STYLE.get(s.source, 'white')}]{s.source}[/]"
        if s.is_symlink:
            source_text += " [dim](symlink)[/]"
        table.add_row(
            _truncate(s.name, _TITLE_MAX),
            source_text,
            _truncate(s.description, _DESC_MAX) if s.description else "—",
            s.version or "—",
            s.plugin or "—",
        )

    Console().print(table)


def skills_with_pad(items: Sequence[InstalledSkill]) -> Sequence[InstalledSkill]:
    """Pass-through; kept as a hook for future visual grouping (blank row
    between source groups). For now returns the input unchanged."""
    return items


def _render_installed_skills_json(skills: Sequence[InstalledSkill]) -> None:
    payload = [
        {
            "name": s.name,
            "description": s.description,
            "provider": s.provider,
            "source": s.source,
            "source_path": str(s.source_path),
            "version": s.version,
            "plugin": s.plugin,
            "is_symlink": s.is_symlink,
        }
        for s in skills
    ]
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _short_id(session_id: str) -> str:
    """First 8 chars; fall back to whole id if shorter."""
    return session_id[:8] if len(session_id) > 8 else session_id


def _relative_time(dt: datetime) -> str:
    """Quick humanizer — minutes / hours / days. No external dep."""
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        # Naive datetime — assume UTC. Better than crashing.
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return dt.isoformat()
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"
