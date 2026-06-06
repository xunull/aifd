"""Output rendering: rich Table for humans, JSON for pipes.

Designed so the same `list[Session]` works in both modes — the CLI just
flips `as_json`. JSON schema is stable across versions for downstream
consumers (jq, fzf, etc).
"""

from __future__ import annotations

import html
import json
import re
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


_SCAN_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aifd vault scan · {n_matches} findings</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #ffffff;
    --fg: #0e0e0e;
    --muted: #6b6b6b;
    --border: #e6e6e6;
    --card-bg: #fafafa;
    --code-bg: #f3f4f6;
    --warn-bg: #fef3c7;
    --warn-border: #f59e0b;
    --warn-fg: #92400e;
    --mark-bg: #fecaca;
    --mark-border: #dc2626;
    --mark-fg: #7f1d1d;
    --conf-10: #b91c1c;
    --conf-9: #c2410c;
    --conf-8: #ca8a04;
    --conf-7: #ca8a04;
    --conf-low: #6b7280;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f0f10;
      --fg: #e6e6e6;
      --muted: #9ca3af;
      --border: #2a2a2c;
      --card-bg: #18181a;
      --code-bg: #1f1f22;
      --warn-bg: #422006;
      --warn-border: #fbbf24;
      --warn-fg: #fde68a;
      --mark-bg: #7f1d1d;
      --mark-border: #fca5a5;
      --mark-fg: #fee2e2;
      --conf-10: #f87171;
      --conf-9: #fb923c;
      --conf-8: #facc15;
      --conf-7: #facc15;
      --conf-low: #9ca3af;
    }
  }
  * { box-sizing: border-box; }
  html, body { background: var(--bg); color: var(--fg); margin: 0; }
  body {
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
          "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif;
    padding: 24px 24px 80px;
  }
  main { max-width: 1100px; margin: 0 auto; }
  header.page h1 {
    font-size: 20px; font-weight: 600; margin: 0 0 4px;
  }
  header.page .meta { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .warning {
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
    color: var(--warn-fg);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 24px;
    font-size: 13px;
    line-height: 1.55;
  }
  .warning strong { font-weight: 700; }
  .summary {
    display: flex; gap: 16px; flex-wrap: wrap;
    font-size: 13px; color: var(--muted);
    padding: 12px 16px; background: var(--card-bg);
    border: 1px solid var(--border); border-radius: 8px;
    margin-bottom: 24px;
  }
  .summary strong { color: var(--fg); font-weight: 600; }
  section.file {
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 16px;
    background: var(--card-bg);
    overflow: hidden;
  }
  section.file > h2 {
    font-size: 13px;
    font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, monospace;
    margin: 0;
    padding: 12px 18px;
    background: var(--code-bg);
    border-bottom: 1px solid var(--border);
    overflow-wrap: anywhere;
  }
  section.file > h2 .count {
    color: var(--muted); font-weight: 500; margin-left: 8px;
  }
  article.match {
    padding: 14px 18px;
    border-top: 1px solid var(--border);
  }
  article.match:first-of-type { border-top: none; }
  article.match > header {
    display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap;
    font-size: 12px;
    margin-bottom: 8px;
  }
  .badge {
    font-family: ui-monospace, SFMono-Regular, monospace;
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--code-bg);
    color: var(--fg);
    font-weight: 600;
    font-size: 11px;
  }
  .badge.line { color: var(--muted); font-weight: 500; }
  .badge.conf-10 { color: #fff; background: var(--conf-10); }
  .badge.conf-9 { color: #fff; background: var(--conf-9); }
  .badge.conf-8, .badge.conf-7 { color: #fff; background: var(--conf-8); }
  .badge.conf-low { color: #fff; background: var(--conf-low); }
  .badge.trunc {
    color: var(--warn-fg);
    background: var(--warn-bg);
    border: 1px solid var(--warn-border);
  }
  .context {
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 12.5px;
    line-height: 1.55;
    background: var(--code-bg);
    border-radius: 6px;
    padding: 10px 12px;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
  }
  mark.leak {
    background: var(--mark-bg);
    color: var(--mark-fg);
    border: 1px solid var(--mark-border);
    border-radius: 3px;
    padding: 0 2px;
    font-weight: 700;
  }
  details.raw {
    margin-top: 8px;
    font-size: 12px;
  }
  details.raw summary {
    color: var(--muted);
    cursor: pointer;
    user-select: none;
  }
  details.raw[open] summary { margin-bottom: 6px; }
  details.raw pre {
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 11.5px;
    background: var(--code-bg);
    border-radius: 6px;
    padding: 10px 12px;
    max-height: 280px;
    overflow: auto;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    word-break: break-word;
    margin: 0;
  }
  .empty {
    text-align: center; color: var(--muted);
    padding: 64px 16px;
  }
  /* ----- tabs (CSS-only, radio-driven) ----- */
  .tab-radio { position: absolute; opacity: 0; pointer-events: none; }
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    padding: 8px;
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 16px;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .tab {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    padding: 6px 12px;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    background: transparent;
    cursor: pointer;
    user-select: none;
    border: 1px solid transparent;
    transition: background 0.12s, color 0.12s, border-color 0.12s;
  }
  .tab:hover { background: var(--code-bg); color: var(--fg); }
  .tab .count {
    font-weight: 500;
    color: var(--muted);
    font-size: 11px;
    font-variant-numeric: tabular-nums;
  }
  .panel { display: none; }
  /* TAB_DYNAMIC_CSS_PLACEHOLDER */
</style>
</head>
<body>
<main>
"""

_SCAN_HTML_TAIL = """\
</main>
</body>
</html>
"""


def _confidence_class(c: int) -> str:
    if c >= 10:
        return "conf-10"
    if c == 9:
        return "conf-9"
    if c >= 7:
        return "conf-8"
    return "conf-low"


# Map of detector category → max confidence the detector emits. Sourced from
# `_DETECTORS` in aifd.vault.scan so adding a new detector automatically
# propagates here (no second list to maintain). `high_entropy` isn't in
# _DETECTORS — it's the fallback layer that tops out at confidence 6.
def _build_category_confidence() -> dict[str, int]:
    from aifd.vault.scan import _DETECTORS
    cmap = {cat: conf for cat, _pat, conf in _DETECTORS}
    cmap["high_entropy"] = 6
    return cmap


_CATEGORY_CONFIDENCE: dict[str, int] = _build_category_confidence()


def _category_sort_key(category: str) -> tuple[int, str]:
    """Sort categories highest-confidence first; entropy and unknown go last.

    The negation makes Python's stable sort put the most-dangerous category
    at index 0 (anthropic_key / openai_key / github_pat at conf 10), with
    bearer_token + email at conf 7, then high_entropy at conf 6. Unknown
    categories get conf 0 and sink to the bottom. Alphabetical tiebreak
    keeps the order deterministic across runs.
    """
    conf = _CATEGORY_CONFIDENCE.get(category, 0)
    return (-conf, category)


def _scan_tabs_css() -> str:
    """Generate the per-category CSS rules for the tab pattern.

    Two rules per category: (1) active-tab visual when its hidden radio is
    checked, (2) panel visibility when its hidden radio is checked. Built
    from `_CATEGORY_CONFIDENCE` so new detectors light up automatically.

    Output is comma-separated to keep the byte budget small (~1 KiB total
    across all 11 categories).
    """
    cats = sorted(_CATEGORY_CONFIDENCE, key=_category_sort_key)
    label_selectors = ",\n  ".join(
        f'#t-{c}:checked ~ .tabs label[for="t-{c}"]' for c in cats
    )
    panel_selectors = ",\n  ".join(
        f"#t-{c}:checked ~ #p-{c}" for c in cats
    )
    return (
        f"  {label_selectors} {{\n"
        "    background: var(--code-bg);\n"
        "    color: var(--fg);\n"
        "    border-color: var(--border);\n"
        "  }\n"
        f"  {panel_selectors} {{ display: block; }}\n"
    )


# JSON string escapes per RFC 8259 §7. The scanner reads jsonl line-by-line
# as raw text, so the captured chunks contain the literal two-char `\n`
# sequence (backslash + 'n') rather than a real newline — that's what
# users were seeing as ugly `\\n` noise in the web view. Unescaping at
# render time turns the text back into something human-readable while
# the CSS `white-space: pre-wrap` on `.context` honors the real newlines.
_JSONL_ESCAPE_RE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')

_JSONL_ESCAPE_MAP: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _unescape_jsonl_chunk(s: str) -> str:
    """Decode standard JSON string escapes inside a chunk of jsonl text.

    Incomplete escapes at chunk boundaries (e.g. a trailing `\\`) are
    left as-is — the regex only matches well-formed escapes, so partial
    sequences fall through untouched. This matters because the windowed
    context slices the source line without escape-awareness.
    """
    def _sub(m: re.Match[str]) -> str:
        token = m.group(1)
        if token.startswith("u"):
            try:
                return chr(int(token[1:], 16))
            except ValueError:
                # Defensive: regex already guarantees 4 hex digits, but
                # surrogate pairs etc. could still hiccup. Leave raw.
                return m.group(0)
        return _JSONL_ESCAPE_MAP[token]
    return _JSONL_ESCAPE_RE.sub(_sub, s)


def render_scan_matches_html(matches: Sequence[SensitiveMatch]) -> str:
    """Render scan findings as a self-contained HTML page.

    Findings are grouped into one tab per detector category (anthropic_key,
    openai_key, github_pat, …). Tabs are ordered by detector confidence
    (most dangerous first), the first tab is selected by default, and
    empty categories are hidden. Within each tab, matches are grouped by
    source jsonl file. Each match shows its surrounding ~200 chars of
    conversation context with the secret highlighted via `<mark>`, plus
    an expandable raw jsonl line.

    Every user-derived string is `html.escape`-d so a secret like
    `</mark><script>` cannot break out of the highlight or inject script.

    Caller is responsible for serving the returned string from a
    localhost-only HTTP server — the page contains raw secrets and must
    never be written to disk or served on a non-loopback interface. See
    `aifd/cli/vault/scan.py` --web for the only authorized caller.
    """
    head = _SCAN_HTML_HEAD.replace(
        "{n_matches}", str(len(matches))
    ).replace(
        "/* TAB_DYNAMIC_CSS_PLACEHOLDER */", _scan_tabs_css(),
    )
    parts: list[str] = [head]
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    parts.append(
        '<header class="page">\n'
        '  <h1>aifd vault scan</h1>\n'
        f'  <div class="meta">{html.escape(generated_at)} · {len(matches)} '
        f'finding{"" if len(matches) == 1 else "s"}</div>\n'
        '</header>\n'
    )
    parts.append(
        '<div class="warning">\n'
        '<strong>⚠ This page contains raw secrets.</strong> The aifd vault '
        'scan --web server holds the matched values in process memory and '
        'serves them only on 127.0.0.1. Press <kbd>Ctrl-C</kbd> in the '
        'terminal when done to drop them. Do not share this URL, leave the '
        'tab open on a shared machine, or screenshot the page.\n'
        '</div>\n'
    )

    if not matches:
        parts.append('<div class="empty">No findings ✓</div>\n')
        parts.append(_SCAN_HTML_TAIL)
        return "".join(parts)

    # Group by category for the tab structure.
    by_category: dict[str, list[SensitiveMatch]] = {}
    for m in matches:
        by_category.setdefault(m.category, []).append(m)
    ordered_cats = sorted(by_category.keys(), key=_category_sort_key)

    # Overall summary stays for at-a-glance totals; sorted by tab order
    # (same as severity) so the visual flow is consistent.
    cats_summary = " · ".join(
        f"<strong>{len(by_category[c])}</strong> {html.escape(c)}"
        for c in ordered_cats
    )
    parts.append(f'<div class="summary">{cats_summary}</div>\n')

    # Hidden radios first — `~` general sibling combinator requires the
    # checked input to appear BEFORE the panel in document order. First
    # category gets `checked`.
    for i, cat in enumerate(ordered_cats):
        attr_checked = " checked" if i == 0 else ""
        parts.append(
            f'<input type="radio" name="cat" '
            f'id="t-{html.escape(cat)}" class="tab-radio"{attr_checked}>\n'
        )

    # Visible tab bar (labels for the hidden radios).
    parts.append('<nav class="tabs" role="tablist">\n')
    for cat in ordered_cats:
        n = len(by_category[cat])
        parts.append(
            f'  <label for="t-{html.escape(cat)}" class="tab" role="tab">'
            f'{html.escape(cat)} '
            f'<span class="count">{n}</span></label>\n'
        )
    parts.append('</nav>\n')

    # Panels — one per category. Inside each, file-grouped sections.
    for cat in ordered_cats:
        cat_matches = by_category[cat]
        parts.append(f'<div class="panel" id="p-{html.escape(cat)}" role="tabpanel">\n')
        by_file: dict[Path, list[SensitiveMatch]] = {}
        for m in cat_matches:
            by_file.setdefault(m.file, []).append(m)
        for file_path, file_matches in by_file.items():
            n = len(file_matches)
            parts.append(
                '<section class="file">\n'
                f'  <h2>{html.escape(str(file_path))}'
                f'<span class="count">{n} finding{"" if n == 1 else "s"}</span></h2>\n'
            )
            for m in file_matches:
                parts.append(_render_scan_match_article(m))
            parts.append('</section>\n')
        parts.append('</div>\n')

    parts.append(_SCAN_HTML_TAIL)
    return "".join(parts)


def _render_scan_match_article(m: SensitiveMatch) -> str:
    conf_class = _confidence_class(m.confidence)
    badge_trunc = (
        '<span class="badge trunc" title="Source line was clipped at 16 KiB '
        'before scan; context_after may be incomplete.">line truncated</span>\n'
        if m.line_truncated
        else ""
    )
    if m.match_full is None:
        # Defensive: render without context if caller forgot capture_context.
        # Should never happen in --web mode; we still escape every string.
        context_html = (
            f'<p class="context">{html.escape(m.snippet_redacted)}</p>'
        )
    else:
        # Two-step decode: unescape JSON string escapes (\\n → real
        # newline, \\" → ", \\uXXXX → unicode), then html.escape for
        # XSS safety. CSS `white-space: pre-wrap` on .context turns the
        # real newlines into visible line breaks.
        before = html.escape(_unescape_jsonl_chunk(m.context_before or ""))
        after = html.escape(_unescape_jsonl_chunk(m.context_after or ""))
        full = html.escape(_unescape_jsonl_chunk(m.match_full))
        context_html = (
            f'<pre class="context">{before}'
            f'<mark class="leak">{full}</mark>'
            f'{after}</pre>'
        )
    raw_block = ""
    if m.raw_line is not None:
        raw_block = (
            '\n  <details class="raw">\n'
            '    <summary>Show raw jsonl line</summary>\n'
            f'    <pre>{html.escape(_unescape_jsonl_chunk(m.raw_line))}</pre>\n'
            '  </details>'
        )
    return (
        '<article class="match">\n'
        '  <header>\n'
        f'    <span class="badge line">line {m.line}</span>\n'
        f'    <span class="badge">{html.escape(m.category)}</span>\n'
        f'    <span class="badge {conf_class}">conf {m.confidence}/10</span>\n'
        f'    {badge_trunc}'
        '  </header>\n'
        f'  {context_html}{raw_block}\n'
        '</article>\n'
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


# ---------- Activity report (v0.5: aifd ai today / weekly / monthly / retro) ----------

# Avoid a top-of-file import cycle: render.py is the renderer for many
# subsystems and insights.py imports providers; deferring the import to
# the function body keeps module load order simple.

_PERIOD_LABEL: dict[str, str] = {
    "today": "Today",
    "weekly": "Past 7 days",
    "monthly": "This month",
    "custom": "Custom range",
}


def render_activity_report(
    report: object,
    *,
    delta: object | None = None,
    projection: object | None = None,
    period_label: str = "custom",
    as_json: bool = False,
    watch_catches: int | None = None,
) -> None:
    """Render a `summarize_activity` ActivityReport to stdout.

    JSON mode emits a stable schema (also documented in docs/ai-retro.md)
    that future tooling (MCP server, scripts) can rely on.
    """
    from aifd.insights import ActivityReport as _AR
    from aifd.insights import Delta as _Delta
    from aifd.insights import ProjectionEstimate as _Proj

    if not isinstance(report, _AR):
        raise TypeError(f"render_activity_report expects ActivityReport, got {type(report)}")
    typed_delta = delta if isinstance(delta, _Delta) else None
    typed_proj = projection if isinstance(projection, _Proj) else None

    if as_json:
        payload = activity_report_as_dict(
            report, delta=typed_delta, projection=typed_proj,
        )
        if watch_catches is not None:
            payload["watch_catches"] = watch_catches
        json.dump(
            payload, sys.stdout, indent=2, ensure_ascii=False, default=str,
        )
        sys.stdout.write("\n")
        return

    console = Console()
    header = _PERIOD_LABEL.get(period_label, "Custom range")
    period_str = (
        f"{report.period_start.strftime('%Y-%m-%d %H:%M')} → "
        f"{report.period_end.strftime('%Y-%m-%d %H:%M')}"
    )
    console.print(f"[bold cyan]═══ {header} ═══[/] [dim]{period_str}[/dim]")
    console.print()

    if report.session_count == 0 and report.cost_usd == 0:
        console.print("[dim]No AI activity in this window.[/dim]")
        return

    # Headline numbers
    cost_color = (
        "red" if report.cost_usd >= 5
        else "yellow" if report.cost_usd >= 1
        else "white"
    )
    console.print(
        f"  [bold]{report.session_count}[/] sessions · "
        f"[bold {cost_color}]${report.cost_usd:,.2f}[/] · "
        f"[dim]{report.total_tokens:,} tokens[/dim]"
    )

    # Provider split
    if report.by_provider:
        parts = []
        for pa in report.by_provider:
            parts.append(f"{pa.provider} {pa.sessions} sess · ${pa.cost_usd:,.2f}")
        console.print(f"  [dim]{' · '.join(parts)}[/dim]")

    # Top skills
    if report.top_skills:
        skills_str = " · ".join(
            f"[green]{name}[/] x{count}" for name, count in report.top_skills
        )
        console.print(f"  [dim]top skills:[/] {skills_str}")

    # Top topics
    if report.top_topics:
        console.print("  [dim]top topics:[/]")
        for topic, count in report.top_topics:
            label = topic[:64] + ("…" if len(topic) > 64 else "")
            multi = f" x{count}" if count > 1 else ""
            console.print(f"    · {label}{multi}")

    # Comparison + projection
    if typed_delta is not None or typed_proj is not None:
        console.print()
    if typed_delta is not None:
        if typed_delta.has_prior:
            cost_sign = "+" if typed_delta.cost_delta >= 0 else ""
            sess_sign = "+" if typed_delta.session_delta >= 0 else ""
            console.print(
                f"  [dim]vs previous:[/] "
                f"[bold]{cost_sign}${typed_delta.cost_delta:,.2f}[/] cost · "
                f"[bold]{sess_sign}{typed_delta.session_delta}[/] sessions"
            )
        else:
            console.print("  [dim]vs previous: no prior data[/dim]")
    if typed_proj is not None:
        if typed_proj.enough_data:
            console.print(
                f"  [dim]→ at this pace, monthly projection:[/] "
                f"[bold]${typed_proj.monthly_usd:,.2f}[/] "
                f"[dim](based on {typed_proj.hours_elapsed:.1f}h)[/dim]"
            )
        else:
            console.print(
                "  [dim]→ projection: (too early, <1h of data)[/dim]"
            )

    if watch_catches is not None and watch_catches > 0:
        plural = "" if watch_catches == 1 else "s"
        console.print()
        console.print(
            f"  [bold yellow]🛡 vault watch:[/] "
            f"[bold]{watch_catches}[/] secret{plural} caught this period "
            f"[dim](run `aifd vault watch status` for details)[/dim]"
        )


def activity_report_as_dict(
    report: object,
    *,
    delta: object | None = None,
    projection: object | None = None,
) -> dict[str, object]:
    """Serialize ActivityReport (+ optional Delta / Projection) to plain dict.

    Schema is stable across versions; downstream consumers (jq, MCP server
    in future) can rely on key names. Datetimes serialize to ISO 8601.
    """
    from aifd.insights import ActivityReport as _AR
    from aifd.insights import Delta as _Delta
    from aifd.insights import ProjectionEstimate as _Proj

    if not isinstance(report, _AR):
        raise TypeError(
            f"activity_report_as_dict expects ActivityReport, got {type(report)}"
        )

    payload: dict[str, object] = {
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "session_count": report.session_count,
        "cost_usd": round(report.cost_usd, 4),
        "total_tokens": report.total_tokens,
        "by_provider": [
            {
                "provider": pa.provider,
                "sessions": pa.sessions,
                "cost_usd": round(pa.cost_usd, 4),
                "total_tokens": pa.total_tokens,
            }
            for pa in report.by_provider
        ],
        "top_skills": [
            {"skill": name, "count": count}
            for name, count in report.top_skills
        ],
        "top_topics": [
            {"topic": topic, "count": count}
            for topic, count in report.top_topics
        ],
    }
    if isinstance(delta, _Delta):
        payload["delta"] = {
            "has_prior": delta.has_prior,
            "cost_delta": round(delta.cost_delta, 4),
            "session_delta": delta.session_delta,
            "token_delta": delta.token_delta,
        }
    if isinstance(projection, _Proj):
        payload["projection"] = {
            "enough_data": projection.enough_data,
            "monthly_usd": round(projection.monthly_usd, 4),
            "hours_elapsed": round(projection.hours_elapsed, 2),
        }
    return payload


# ---------- v0.8 reflection (Coach mode) ----------


def render_reflection_text(
    output: dict[str, object],
    period_label: str = "this period",
    lang: str = "zh",
    timing_breakdown: dict[str, float] | None = None,
) -> None:
    """Render an LLM reflection essay to stdout.

    `output` is the LLM's validated JSON output dict
    (essay/wins/anti_pattern/concrete_action/prompt_version).
    `timing_breakdown` (optional) is rendered when --verbose passed:
    {"local": 0.4, "llm": 6.2, "render": 0.1}
    """
    console = Console()
    essay = str(output.get("essay", ""))
    wins = output.get("wins") or []
    anti = str(output.get("anti_pattern", ""))
    action = str(output.get("concrete_action", ""))
    pv = str(output.get("prompt_version", ""))

    header = (
        f"═══ Your {period_label} with AI ═══"
    )
    console.print(f"[bold cyan]{header}[/]")
    console.print()
    console.print(essay)
    console.print()

    if isinstance(wins, list) and wins:
        console.print("  [bold green]🏆 Wins[/]")
        for w in wins:
            console.print(f"    · {w}")
        console.print()

    if anti:
        console.print("  [bold yellow]⚠ Anti-pattern[/]")
        console.print(f"    · {anti}")
        console.print()

    if action:
        title = "Try next period" if lang == "en" else "下周试一次"
        console.print(f"  [bold]→ {title}:[/] {action}")
        console.print()

    if timing_breakdown:
        parts = [
            f"{k}={v:.2f}s" for k, v in timing_breakdown.items()
        ]
        meta = "  ".join(parts)
        console.print(f"[dim]  timing: {meta}  ·  prompt_version: {pv}[/dim]")


def render_reflection_json(output: dict[str, object]) -> None:
    """Pipe-friendly JSON output to stdout. Schema is stable for tooling."""
    json.dump(output, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
