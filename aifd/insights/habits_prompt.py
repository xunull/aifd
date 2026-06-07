"""Prompt rendering for `aifd ai habits` (v0.9).

Builds the LLM prompt that asks for long-term behavioural PATTERN IDENTIFICATION
rather than a periodic reflection essay.

Key differences from reflection_prompt.py:
  - LLM task: name patterns, not write an essay
  - Output: JSON array of patterns (name + evidence + suggestion)
  - Data: 8 long-term dimensions, not 9 periodic dimensions

Privacy invariant (D6 from reflect, inherited here):
  - No raw question text, no absolute cwd paths, no session content
  - Only counts, ratios, basenames, ISO dates
  - Verified by tests that run _scan_line across rendered prompts
"""

from __future__ import annotations

from aifd.insights.habits import HabitsInput

PROMPT_VERSION = "v1"

_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def render_habits_prompt(inp: HabitsInput, lang: str = "zh") -> str:
    """Build the LLM prompt for one habits analysis run."""
    if lang not in ("en", "zh"):
        lang = "zh"
    data_section = _render_data_section(inp)
    rules = _RULES_EN if lang == "en" else _RULES_ZH
    return _SYSTEM_FRAME.format(
        prompt_version=PROMPT_VERSION,
        data_section=data_section,
        rules=rules,
        lang=lang,
        output_schema=_OUTPUT_SCHEMA,
    )


# ---------- prompt template ----------


_SYSTEM_FRAME = """You are a behavioural analyst for an AI developer's coding habits.
Read the structured long-term data and identify 3-5 recurring behavioural PATTERNS.

PROMPT_VERSION: {prompt_version}

DATA (aggregate stats only — no personal content, no file paths):
{data_section}

RULES:
{rules}

OUTPUT strict JSON in this exact schema (no other keys):
{output_schema}

Output language: {lang}.
"""

_OUTPUT_SCHEMA = """{
  "prompt_version": "<echo the PROMPT_VERSION value above verbatim>",
  "patterns": [
    {
      "name": "<short label, 4-8 words, e.g. '周五放松崩'>",
      "evidence": "<1-2 sentences with concrete numbers from the data>",
      "suggestion": "<one specific, actionable recommendation>"
    }
  ]
}"""

_RULES_EN = """- Identify 3-5 PATTERNS the user probably hasn't noticed themselves.
- Each pattern MUST cite at least one concrete number from the data above.
- Do NOT invent patterns not supported by the data.
- Name each pattern memorably (4-8 words), like a behaviour archetype.
- One suggestion per pattern — specific, not generic.
- If a dimension shows "(no data)", skip it entirely.
- No AI vocabulary: do NOT use "delve, crucial, robust, comprehensive,
  nuanced, multifaceted, furthermore, moreover, additionally, pivotal".
- Address the user as "you" in evidence and suggestion text."""

_RULES_ZH = """- 识别 3-5 个用户自己没意识到的行为「模式」。
- 每个模式必须引用上面数据中的至少一个具体数字。
- 不要编造数据中没有支撑的模式。
- 每个模式给一个好记的名字（4-8 字），像一个行为人格标签。
- 每个模式给一条具体可执行的建议，不要模糊建议。
- 如果某个维度显示「(no data)」，跳过不要用。
- 禁用 AI 词汇：审视、积极、有效、整合、综合、显著、深入、深刻。
- evidence 和 suggestion 中用「你」称呼。"""


# ---------- data section rendering ----------


def _render_data_section(inp: HabitsInput) -> str:
    """Render 8 habit dimensions to key-value lines for the prompt.

    Privacy invariant: no raw question text, no absolute cwd paths,
    no session content. Only counts, ratios, basenames, ISO dates.
    """
    lines: list[str] = []
    lines.append(
        f"- period: {inp.period_start.date().isoformat()} "
        f"→ {inp.period_end.date().isoformat()}"
    )

    # Weekday distribution
    if inp.weekday_stats:
        parts = [
            f"{_WEEKDAY_NAMES[s.weekday]}:"
            f"sess={s.session_count}"
            f",vibe={s.vibe_rate:.0%}"
            for s in inp.weekday_stats
            if s.session_count > 0
        ]
        if parts:
            lines.append(f"- weekday_distribution: {', '.join(parts)}")
        else:
            lines.append("- weekday_distribution: (no data)")
    else:
        lines.append("- weekday_distribution: (no data)")

    # Timeslot distribution — only show non-zero slots
    if inp.timeslot_stats:
        active = [s for s in inp.timeslot_stats if s.session_count > 0]
        if active:
            parts = [
                f"{s.label}h:sess={s.session_count},avg_events={s.avg_event_count:.0f}"
                for s in active
            ]
            lines.append(f"- timeslot_distribution: {', '.join(parts)}")
        else:
            lines.append("- timeslot_distribution: (no data)")
    else:
        lines.append("- timeslot_distribution: (no data)")

    # Session bimodal
    if inp.short_session_share is not None:
        long_avg = (
            f", long_avg_events={inp.long_session_avg_events:.0f}"
            if inp.long_session_avg_events is not None else ""
        )
        lines.append(
            f"- session_split: short(<{5}_events)={inp.short_session_share:.0%}"
            f"{long_avg}"
        )
    else:
        lines.append("- session_split: (no data)")

    # Project switching
    if inp.project_switch_median is not None:
        lines.append(
            f"- project_switch_median_per_day: {inp.project_switch_median:.1f}"
        )
    else:
        lines.append("- project_switch_median_per_day: (no data)")

    # Ship cadence
    if inp.ship_interval_median_days is not None:
        lines.append(
            f"- ship_interval_median_days: {inp.ship_interval_median_days:.1f}"
        )
    else:
        lines.append("- ship_interval_median_days: (no data)")

    # Late-night ship rate (D1)
    if inp.late_night_ship_rate is not None:
        lines.append(
            f"- late_night_ship_rate: {inp.late_night_ship_rate:.0%} "
            f"(sessions starting 22h+ that had a ship within 24h)"
        )
    else:
        lines.append("- late_night_ship_rate: (no data)")

    # Overplanning
    if inp.overplanning_rate is not None:
        lines.append(
            f"- overplanning_rate: {inp.overplanning_rate:.0%} "
            f"(office-hours sessions without a ship within 7 days)"
        )
    else:
        lines.append("- overplanning_rate: (no data)")

    # Skill repetition
    if inp.top_skill_name is not None and inp.top_skill_share is not None:
        lines.append(
            f"- top_skill: {inp.top_skill_name} "
            f"({inp.top_skill_share:.0%} of invocations)"
        )
    else:
        lines.append("- top_skill: (no data)")

    return "\n".join(lines)
