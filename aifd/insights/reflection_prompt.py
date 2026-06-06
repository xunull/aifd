"""Prompt rendering for `aifd ai reflect` (T5).

Renders ReflectionInput → strict prompt string for DeepSeek's chat
completions endpoint. Output: JSON-mode response_format requires we ask
for JSON in the prompt body too.

D2 invariant — PROMPT_VERSION is baked in and echoed back; downstream
caller validates it round-trips so future prompt changes are auditable.

D6 invariant — privacy: raw question text, absolute paths, secret patterns
NEVER appear in the prompt. Verified by tests that run the v0.4 secret
detector across rendered prompts.
"""

from __future__ import annotations

from aifd.insights.reflection import ReflectionInput

PROMPT_VERSION = "v1"


def render_prompt(input: ReflectionInput, lang: str = "zh") -> str:
    """Build the full LLM prompt for one reflection.

    `lang` controls the OUTPUT language (en or zh). The DATA section is
    always English (machine-readable) but the LLM is instructed to write
    the user-facing essay in `lang`.
    """
    if lang not in ("en", "zh"):
        lang = "zh"
    data_section = _render_data_section(input)
    rules = _RULES_EN if lang == "en" else _RULES_ZH
    return _SYSTEM_FRAME.format(
        prompt_version=PROMPT_VERSION,
        data_section=data_section,
        rules=rules,
        lang=lang,
        output_schema=_OUTPUT_SCHEMA,
    )


# ---------- prompt template fragments ----------


_SYSTEM_FRAME = """You are a meta-cognitive coach for the user's AI usage.
Read the structured data and write a SHORT reflection.

PROMPT_VERSION: {prompt_version}

DATA:
{data_section}

RULES:
{rules}

OUTPUT strict JSON in this exact schema (no other keys):
{output_schema}

Output language: {lang}.
"""

_OUTPUT_SCHEMA = """{
  "prompt_version": "<echo the PROMPT_VERSION value above verbatim>",
  "essay": "<one paragraph, 80-150 words, in the requested language>",
  "wins": ["<short>", "<short>", "<short>"],
  "anti_pattern": "<one-line anti-pattern>",
  "concrete_action": "<one-line specific action for next period>"
}"""

_RULES_EN = """- Write ONE paragraph, 80-150 words, in English.
- DIRECT. Address the user as "you".
- NO AI vocabulary: do NOT use "delve, crucial, robust, comprehensive,
  nuanced, multifaceted, furthermore, moreover, additionally, pivotal,
  landscape, tapestry, underscore, foster, showcase, intricate, vibrant,
  fundamental, significant".
- 3 wins, each one short line referencing the data above.
- One anti-pattern the user should know.
- One concrete next-period action (specific, not generic).
- No filler. No throat-clearing.
- If a dimension shows "(no data)", do not invent — skip that aspect."""

_RULES_ZH = """- 写一段，80-150 字，中文。
- 直接，用「你」称呼。
- 禁用 AI 词汇：审视、积极、有效、整合、综合、显著、深入、
  显著地、值得探讨、本质上、深刻、卓越、生态、维度、范畴。
- 列出 3 个 win，每个一行，引用上面数据。
- 指出 1 个 anti-pattern，用户该意识到的。
- 给一个下周可执行的具体动作（不是模糊建议）。
- 没有套话。直接说。
- 如果某个维度显示「(no data)」，不要编造，跳过那一面。"""


# ---------- data section rendering ----------


def _render_data_section(input: ReflectionInput) -> str:
    """Render the 9 dimensions into key: value lines for the prompt.

    Privacy invariant (D6): no raw question text, no absolute cwd path, no
    session-message content. Only counts, ratios, basenames, ISO dates.
    """
    lines: list[str] = []
    period_start = input.period_start.date().isoformat()
    period_end = input.period_end.date().isoformat()
    lines.append(f"- period: {period_start} → {period_end}")

    if input.activity is not None:
        lines.append(
            f"- sessions: {input.activity.session_count}, "
            f"cost: ${input.activity.cost_usd:.2f}, "
            f"tokens: {input.activity.total_tokens}",
        )
    else:
        lines.append("- sessions: (no data)")

    if input.compliance is not None:
        lines.append(
            f"- compliance_ratio: {input.compliance.ratio:.0%} "
            f"({input.compliance.matched_count} of "
            f"{input.compliance.total_questions} questions)"
        )
    else:
        lines.append("- compliance_ratio: (no data)")

    if input.skill_diversity_ratio is not None:
        lines.append(
            f"- skill_diversity: {input.skill_diversity_ratio:.0%} "
            "(distinct / total invocations)"
        )
    else:
        lines.append("- skill_diversity: (no data)")

    if input.cost_trend_ratio is not None:
        sign = "+" if input.cost_trend_ratio >= 0 else ""
        lines.append(
            f"- cost_trend: {sign}{input.cost_trend_ratio:.0%} vs prev period"
        )
    else:
        lines.append("- cost_trend: (no data)")

    if input.timing_buckets:
        timing_summary = ", ".join(
            f"{b.label}h: {b.session_count} sess (avg {b.avg_message_count:.0f} msg)"
            for b in input.timing_buckets if b.session_count > 0
        )
        if timing_summary:
            lines.append(f"- timing_distribution: {timing_summary}")
        else:
            lines.append("- timing_distribution: (no sessions)")
    else:
        lines.append("- timing_distribution: (no data)")

    if input.top_project is not None and input.top_project_share is not None:
        lines.append(
            f"- top_project: {input.top_project} "
            f"({input.top_project_share:.0%} of sessions)"
        )
    else:
        lines.append("- top_project: (no data)")

    if input.plan_then_ship_ratio is not None:
        lines.append(
            f"- plan_then_ship: {input.plan_then_ship_ratio:.0%} of ships "
            "had plan-eng-review prior"
        )
    else:
        lines.append("- plan_then_ship: (no data)")

    if input.vibe_coding_score is not None:
        lines.append(
            f"- vibe_coding_score: {input.vibe_coding_score:.0%} of ships "
            "had <5 msg session (1.0=all vibe, 0=deliberate)"
        )
    else:
        lines.append("- vibe_coding_score: (no data)")

    if input.wins:
        wins_brief = "; ".join(f"{w.date}:{w.label}" for w in input.wins)
        lines.append(f"- top_wins: {wins_brief}")
    else:
        lines.append("- top_wins: (no data)")

    return "\n".join(lines)
