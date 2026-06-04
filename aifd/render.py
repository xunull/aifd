"""Output rendering: rich Table for humans, JSON for pipes.

Designed so the same `list[Session]` works in both modes — the CLI just
flips `as_json`. JSON schema is stable across versions for downstream
consumers (jq, fzf, etc).
"""

from __future__ import annotations

import html
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from aifd.models import (
    CostRow,
    InstalledSkill,
    QuestionAnswer,
    SensitiveMatch,
    Session,
    SkillStats,
)
from aifd.providers._utils import split_recommended_suffix


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


_QUESTION_MAX = 70
_CHOSEN_MAX = 40
_NO_ANSWER = "—"


def render_question_answers(
    rows: Sequence[QuestionAnswer],
    scope_label: str,
    *,
    as_json: bool,
) -> None:
    """Render the AskUserQuestion list.

    scope_label is shown in the empty-state and in the trailing summary
    so the user knows whether they're looking at a global scan or a
    cwd-scoped slice.
    """
    if as_json:
        _render_question_answers_json(rows)
        return

    if not rows:
        Console().print(
            f"[dim]No AskUserQuestion calls found in[/dim] [bold]{scope_label}[/bold]"
        )
        return

    _render_question_answers_table(rows, scope_label)


def _render_question_answers_table(
    rows: Sequence[QuestionAnswer],
    scope_label: str,
) -> None:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Time", justify="right")
    table.add_column("Project", style="dim", overflow="ellipsis", max_width=30)
    table.add_column("Question", overflow="ellipsis", max_width=_QUESTION_MAX)
    table.add_column("Your Choice", overflow="ellipsis", max_width=_CHOSEN_MAX)
    table.add_column(
        "Recommended", style="dim", overflow="ellipsis", max_width=_CHOSEN_MAX
    )

    for qa in rows:
        # Strip the `(recommended)` suffix from the chosen label so the
        # column reads cleanly and matches the Recommended column when
        # the user picked the recommended option.
        chosen_clean = (
            split_recommended_suffix(qa.chosen_option)[0] if qa.chosen_option else ""
        )
        chosen_display = chosen_clean or _NO_ANSWER
        if qa.notes:
            chosen_display = f"{chosen_display} [dim](Other: {qa.notes[:40]})[/]"
        recommended_display = qa.recommended_option or _NO_ANSWER
        table.add_row(
            _relative_time(qa.ts) if qa.ts else "—",
            _truncate(qa.cwd.name or str(qa.cwd), 30),
            _truncate(qa.question, _QUESTION_MAX),
            _truncate(chosen_display, _CHOSEN_MAX + 30),  # extra for [dim] markup
            _truncate(recommended_display, _CHOSEN_MAX),
        )

    Console().print(table)

    # C3 summary footer: counts + recommended-choice hit rate + orphan count.
    # Hit rate denominator excludes rows without a recommendation (neutral-
    # posture AUQs) so the percentage isn't dragged down by un-flaggable
    # questions.
    total = len(rows)
    unanswered = sum(1 for qa in rows if qa.chosen_option is None)
    answered_with_rec = [
        qa for qa in rows if qa.recommended_option is not None and qa.chosen_option
    ]
    hits = sum(
        1
        for qa in answered_with_rec
        if _matches_recommended(qa.chosen_option or "", qa.recommended_option or "")
    )
    if answered_with_rec:
        denom = len(answered_with_rec)
        rate_text = (
            f" | recommended hit rate: {100 * hits / denom:.0f}% ({hits}/{denom})"
        )
    else:
        rate_text = ""
    Console().print(
        f"[dim]{total} question{'s' if total != 1 else ''} "
        f"in {scope_label}{rate_text} | {unanswered} unanswered[/dim]"
    )


def _matches_recommended(chosen: str, recommended: str) -> bool:
    """Compare a chosen label against the recommendation tolerantly.

    multiSelect answers come back as a comma-joined list — count it a
    match if any selected item equals the recommended. We strip the
    `(recommended)` suffix from each candidate so a chosen label that
    still carries the suffix (e.g. "A) Add (推荐)") matches the
    recommended option that had its suffix stripped at parse time.
    """
    rec_norm = recommended.strip().lower()
    if not rec_norm:
        return False
    for part in chosen.split(","):
        part_clean = split_recommended_suffix(part.strip())[0].lower()
        if part_clean == rec_norm:
            return True
    return False


def _render_question_answers_json(rows: Sequence[QuestionAnswer]) -> None:
    payload = [
        {
            "question": qa.question,
            "options": list(qa.options),
            "recommended_option": qa.recommended_option,
            "chosen_option": qa.chosen_option,
            "notes": qa.notes,
            "ts": qa.ts.isoformat() if qa.ts else None,
            "cwd": str(qa.cwd),
            "provider": qa.provider,
            "session_id": qa.session_id,
            "source_path": str(qa.source_path),
            "tool_use_id": qa.tool_use_id,
        }
        for qa in rows
    ]
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


# Notion/Linear-style HTML reader for `aifd ai question list --html`.
# Built per v0.3 CEO plan D2=A (HTML static gen, no React/server). Design
# choices per D5=B: system-followed dark/light theme, 70ch max-width,
# Q-as-card layout, chosen=green / recommended=neutral-star. ALL user-derived
# text passes through html.escape() per D3=A — security is non-negotiable
# (the source data contains arbitrary user history including questions like
# 'how to sanitize <script>?' that would XSS without escaping).
_HTML_TEMPLATE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aifd · question retro · {scope_label}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #0e0e0e;
    --muted: #6b6b6b;
    --border: #e6e6e6;
    --card-bg: #fafafa;
    --accent: #2563eb;
    --chosen: #16a34a;
    --recommended: #6b7280;
    --orphan: #ea580c;
    --code-bg: #f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f0f10;
      --fg: #e6e6e6;
      --muted: #9ca3af;
      --border: #2a2a2c;
      --card-bg: #18181a;
      --accent: #60a5fa;
      --chosen: #4ade80;
      --recommended: #9ca3af;
      --orphan: #fb923c;
      --code-bg: #1f1f22;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ background: var(--bg); color: var(--fg); margin: 0; }}
  body {{
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
    padding: 32px 24px 80px;
  }}
  main {{ max-width: 70ch; margin: 0 auto; }}
  header.page {{
    border-bottom: 1px solid var(--border);
    padding-bottom: 16px;
    margin-bottom: 24px;
  }}
  header.page h1 {{
    font-size: 20px; font-weight: 600; margin: 0 0 4px;
    letter-spacing: -0.01em;
  }}
  header.page .meta {{ color: var(--muted); font-size: 13px; }}
  .summary {{
    display: flex; gap: 16px; flex-wrap: wrap;
    font-size: 13px; color: var(--muted);
    padding: 12px 16px; background: var(--card-bg);
    border: 1px solid var(--border); border-radius: 8px;
    margin-bottom: 24px;
  }}
  .summary strong {{ color: var(--fg); font-weight: 600; }}
  article.question {{
    border: 1px solid var(--border);
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
  }}
  article.question > header {{
    display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
    font-size: 12px; color: var(--muted);
    margin-bottom: 12px;
  }}
  article.question > header .when {{ font-variant-numeric: tabular-nums; }}
  article.question > header .project {{
    font-weight: 600; color: var(--fg);
  }}
  article.question .question-text {{
    font-size: 15px; line-height: 1.65;
    white-space: pre-wrap; overflow-wrap: anywhere;
    margin: 0 0 16px;
  }}
  article.question ul.options {{
    list-style: none; padding: 0; margin: 0 0 12px;
    display: flex; flex-direction: column; gap: 4px;
  }}
  article.question ul.options li {{
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 14px;
    display: flex; align-items: flex-start; gap: 8px;
    overflow-wrap: anywhere;
  }}
  article.question ul.options li.chosen {{
    background: rgba(22, 163, 74, 0.08);
    color: var(--fg);
  }}
  article.question ul.options li.chosen::before {{
    content: "✓"; color: var(--chosen); font-weight: 700;
    flex-shrink: 0;
  }}
  article.question ul.options li.recommended:not(.chosen) {{
    color: var(--muted);
  }}
  article.question ul.options li.recommended:not(.chosen)::before {{
    content: "★"; color: var(--recommended);
    flex-shrink: 0;
  }}
  article.question ul.options li:not(.chosen):not(.recommended)::before {{
    content: "·"; color: var(--muted); width: 1ch;
    flex-shrink: 0;
  }}
  article.question .notes {{
    font-size: 13px; color: var(--muted);
    background: var(--code-bg);
    border-radius: 6px;
    padding: 8px 12px;
    margin: 8px 0 12px;
  }}
  article.question .notes strong {{ color: var(--fg); }}
  article.question .orphan {{
    color: var(--orphan); font-size: 13px; font-style: italic;
    margin: 0 0 8px;
  }}
  article.question footer {{
    display: flex; gap: 12px; flex-wrap: wrap;
    font-size: 11px; color: var(--muted);
    padding-top: 10px;
    border-top: 1px dashed var(--border);
    margin-top: 12px;
    font-family: ui-monospace, SFMono-Regular, monospace;
  }}
  article.question footer .label {{ font-weight: 600; }}
  .empty {{
    text-align: center; color: var(--muted);
    padding: 64px 16px;
  }}
</style>
</head>
<body>
<main>
"""

_HTML_TEMPLATE_TAIL = """\
</main>
</body>
</html>
"""


def render_question_answers_html(
    rows: Sequence[QuestionAnswer],
    scope_label: str,
    output_path: Path | None = None,
) -> str | None:
    """Render the AskUserQuestion list as a self-contained HTML page.

    If output_path is None, returns the HTML string (caller writes wherever
    they want — usually stdout for pipe-friendly use). If output_path is
    set, writes to that file and returns None.

    All user-derived strings are HTML-escaped (D3=A) so question text that
    contains literal `<script>` (e.g. "how do I sanitize <script>?")
    cannot run as HTML when the page is opened.
    """
    body_parts: list[str] = [_HTML_TEMPLATE_HEAD.format(scope_label=html.escape(scope_label))]
    body_parts.append(_render_page_header(scope_label, rows))

    if not rows:
        body_parts.append(
            f'<div class="empty">No AskUserQuestion calls found in '
            f'<strong>{html.escape(scope_label)}</strong>.</div>\n'
        )
    else:
        body_parts.append(_render_summary_card(rows, scope_label))
        for qa in rows:
            body_parts.append(_render_question_card(qa))

    body_parts.append(_HTML_TEMPLATE_TAIL)
    page = "".join(body_parts)

    if output_path is None:
        return page

    output_path.write_text(page, encoding="utf-8")
    return None


def _render_page_header(scope_label: str, rows: Sequence[QuestionAnswer]) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f'<header class="page">\n'
        f'  <h1>aifd · question retro</h1>\n'
        f'  <div class="meta">scope: <strong>{html.escape(scope_label)}</strong> · '
        f'{len(rows)} question{"s" if len(rows) != 1 else ""} · '
        f'generated {generated_at}</div>\n'
        f'</header>\n'
    )


def _render_summary_card(
    rows: Sequence[QuestionAnswer], scope_label: str
) -> str:
    total = len(rows)
    unanswered = sum(1 for qa in rows if qa.chosen_option is None)
    answered_with_rec = [
        qa for qa in rows if qa.recommended_option is not None and qa.chosen_option
    ]
    hits = sum(
        1
        for qa in answered_with_rec
        if _matches_recommended(qa.chosen_option or "", qa.recommended_option or "")
    )
    parts = [
        '<div class="summary">',
        f'  <span><strong>{total}</strong> total</span>',
    ]
    if answered_with_rec:
        denom = len(answered_with_rec)
        pct = 100 * hits / denom
        parts.append(
            f'  <span><strong>{pct:.0f}%</strong> '
            f'recommended hit rate ({hits}/{denom})</span>'
        )
    if unanswered:
        parts.append(f'  <span><strong>{unanswered}</strong> unanswered</span>')
    parts.append('</div>\n')
    return "\n".join(parts)


def _render_question_card(qa: QuestionAnswer) -> str:
    # ALL user-derived text MUST pass through html.escape() (D3=A).
    rel_time = _relative_time(qa.ts) if qa.ts else "—"
    project = qa.cwd.name or str(qa.cwd) if qa.cwd else "—"

    chosen_clean = (
        split_recommended_suffix(qa.chosen_option)[0] if qa.chosen_option else None
    )

    parts = [
        '<article class="question">',
        '  <header>',
        f'    <span class="when">{html.escape(rel_time)}</span>',
        f'    <span class="project">{html.escape(project)}</span>',
        '  </header>',
        f'  <p class="question-text">{html.escape(qa.question)}</p>',
    ]

    if qa.chosen_option is None:
        parts.append(
            '  <p class="orphan">No answer recorded — likely interrupted '
            'or compacted before the user replied.</p>'
        )

    if qa.options:
        parts.append('  <ul class="options">')
        for opt_label in qa.options:
            classes: list[str] = []
            if chosen_clean and opt_label == chosen_clean:
                classes.append("chosen")
            if qa.recommended_option and opt_label == qa.recommended_option:
                classes.append("recommended")
            class_attr = f' class="{" ".join(classes)}"' if classes else ""
            parts.append(f"    <li{class_attr}>{html.escape(opt_label)}</li>")
        parts.append("  </ul>")

    if chosen_clean and chosen_clean not in qa.options:
        # multiSelect answers ("A, B, C") won't match any single option;
        # show them as a separate row so the user still sees what was picked.
        parts.append(
            f'  <p class="notes"><strong>Selected:</strong> '
            f'{html.escape(chosen_clean)}</p>'
        )

    if qa.notes:
        parts.append(
            f'  <p class="notes"><strong>Other:</strong> '
            f'{html.escape(qa.notes)}</p>'
        )

    parts.extend([
        '  <footer>',
        f'    <span><span class="label">provider</span> {html.escape(qa.provider)}</span>',
        f'    <span><span class="label">cwd</span> {html.escape(str(qa.cwd))}</span>',
        f'    <span><span class="label">session</span> {html.escape(qa.session_id[:8])}</span>',
        '  </footer>',
        '</article>',
        '',
    ])
    return "\n".join(parts)


# -------------------- vault scan / vault cost rendering (v0.4) --------------------

_CONFIDENCE_STYLE: dict[int, str] = {
    10: "bold red",
    9: "red",
    8: "yellow",
    7: "yellow",
    6: "dim",
    5: "dim",
    4: "dim",
}


def render_scan_matches(
    matches: Sequence[SensitiveMatch],
    *,
    as_json: bool,
    min_confidence: int,
) -> None:
    """Render PII/secret findings to stdout.

    Filters by min_confidence at render time (caller decides default).
    JSON output is the raw record (incl. redacted snippet) — never the
    full secret value, which is not present in SensitiveMatch by design.
    """
    filtered = [m for m in matches if m.confidence >= min_confidence]

    if as_json:
        payload = [
            {
                "file": str(m.file),
                "line": m.line,
                "category": m.category,
                "snippet_redacted": m.snippet_redacted,
                "confidence": m.confidence,
                "full_length": m.full_length,
            }
            for m in filtered
        ]
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    console = Console()
    if not filtered:
        if matches:
            console.print(
                f"[dim]No findings at confidence >= {min_confidence}. "
                f"{len(matches)} lower-confidence matches suppressed; "
                f"use `--min-confidence N` to lower the threshold.[/dim]"
            )
        else:
            console.print("[dim]No potential secrets found. ✓[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Conf", justify="right")
    table.add_column("Category", style="green")
    table.add_column("Snippet")
    table.add_column("Len", justify="right", style="dim")
    table.add_column("File:Line", overflow="ellipsis", max_width=_SOURCE_MAX)

    for m in filtered:
        style = _CONFIDENCE_STYLE.get(m.confidence, "")
        table.add_row(
            f"[{style}]{m.confidence}/10[/]" if style else f"{m.confidence}/10",
            m.category,
            m.snippet_redacted,
            str(m.full_length),
            f"{m.file.name}:{m.line}",
        )

    console.print(table)
    # Footer: counts by category + total suppressed
    by_cat: dict[str, int] = {}
    for m in filtered:
        by_cat[m.category] = by_cat.get(m.category, 0) + 1
    suppressed = len(matches) - len(filtered)
    cats = " · ".join(f"{n} {k}" for k, n in sorted(by_cat.items(), key=lambda x: -x[1]))
    suppressed_text = (
        f" · {suppressed} low-confidence suppressed" if suppressed else ""
    )
    console.print(
        f"[dim]{len(filtered)} findings: {cats}{suppressed_text}[/dim]"
    )


def render_cost_rows(
    rows: Sequence[CostRow],
    *,
    as_json: bool,
    group_by: str,
    prices_last_updated: str,
) -> None:
    """Render the per-group cost breakdown.

    Footer shows: total spend + total events + the prices_last_updated
    date so users know when to re-verify against vendor pricing pages.
    """
    if as_json:
        payload = [
            {
                "label": r.label,
                "provider": r.provider,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cache_creation_input_tokens": r.cache_creation_input_tokens,
                "cache_read_input_tokens": r.cache_read_input_tokens,
                "reasoning_output_tokens": r.reasoning_output_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": round(r.cost_usd, 4),
                "event_count": r.event_count,
            }
            for r in rows
        ]
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return

    console = Console()
    if not rows:
        console.print("[dim]No token usage found.[/dim]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    header = group_by.capitalize() if group_by else "Group"
    table.add_column(header, overflow="ellipsis", max_width=40)
    table.add_column("Provider", style="green")
    table.add_column("Model", style="dim", overflow="ellipsis", max_width=24)
    table.add_column("Events", justify="right", style="dim")
    table.add_column("In (k)", justify="right")
    table.add_column("Cache (k)", justify="right", style="dim")
    table.add_column("Out (k)", justify="right")
    table.add_column("Cost ($)", justify="right", style="bold")

    for r in rows:
        table.add_row(
            r.label,
            r.provider,
            r.model or "—",
            f"{r.event_count}",
            f"{r.input_tokens / 1000:,.0f}",
            f"{r.cache_read_input_tokens / 1000:,.0f}",
            f"{(r.output_tokens + r.reasoning_output_tokens) / 1000:,.0f}",
            f"{r.cost_usd:,.2f}",
        )

    console.print(table)
    total = sum(r.cost_usd for r in rows)
    total_events = sum(r.event_count for r in rows)
    # Distinguish verified vs estimated rows so users see at a glance
    # which numbers to trust. Anthropic prices are scraped from the
    # vendor page; OpenAI rows are estimates (Cloudflare blocks our
    # WebFetch on openai.com). Tracked by provider — once OpenAI prices
    # get verified this needs to switch to per-row model verification.
    verified_cost = sum(r.cost_usd for r in rows if r.provider == "claude")
    estimated_cost = total - verified_cost
    if estimated_cost > 0.01:
        verification_note = (
            f"claude verified · codex est ${estimated_cost:,.2f}"
        )
    else:
        verification_note = "all verified"
    console.print(
        f"[dim]Total: [bold]${total:,.2f}[/bold] across "
        f"{total_events:,} events · prices as of {prices_last_updated} "
        f"({verification_note})[/dim]"
    )


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
