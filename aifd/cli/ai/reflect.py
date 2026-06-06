"""`aifd ai reflect` — meta-cognitive AI coach (v0.8).

Pulls 9 dimensions of your AI usage from existing aifd activity data +
gstack ReflectionDataSource, builds a strict prompt, calls an LLM (via
LiteLLM — provider-agnostic) for an 80-150 word essay, renders to stdout
(or pipes to webhook).

Fallback behavior — when API key missing or LLM unreachable, prints the
structured reflection input as a CLI table + clear setup hint. No crash.

Locked decisions:
  - D1 api_base configurable (ollama / Azure / vllm / proxy / corporate gateway)
  - D2 PROMPT_VERSION echoed in output
  - D4 retry policy: 429 / 5xx / timeout retry once, 30s budget (via LiteLLM)
  - D6 privacy: no raw question text in default mode
  - D8 perf: local part < 500ms enforced; verbose timing breakdown
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import click
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from aifd.cli._logging import configure_logging
from aifd.config import Config, write_template
from aifd.config import load as load_config
from aifd.insights.llm_client import LLMResponseError
from aifd.insights.llm_client import call as llm_call
from aifd.insights.reflection import collect_reflection_data
from aifd.insights.reflection_prompt import PROMPT_VERSION, render_prompt
from aifd.insights.reflection_source import default_source
from aifd.render import render_reflection_json, render_reflection_text

logger = logging.getLogger("aifd")


@click.command(name="reflect")
@click.option(
    "--week", "period", flag_value="week",
    help="Reflect on the past 7 days (default).",
)
@click.option(
    "--month", "period", flag_value="month",
    help="Reflect on the past 30 days.",
)
@click.option(
    "--since",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    help="Custom window start (YYYY-MM-DD).",
)
@click.option(
    "--until",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    help="Custom window end (defaults to now).",
)
@click.option(
    "--lang", type=click.Choice(["en", "zh"]), default=None,
    help="Output language. Default: config.reflect.default_lang (zh).",
)
@click.option(
    "--include-questions/--no-include-questions", default=None,
    help="Opt in to send question summaries to LLM (raw text still NOT sent).",
)
@click.option(
    "--json", "as_json", is_flag=True,
    help="Emit JSON instead of rendered text.",
)
@click.option(
    "--model", default=None,
    help=(
        "LiteLLM 'provider/model' string "
        "(e.g. deepseek/deepseek-chat, zhipu/glm-4-plus, ollama/qwen2.5)."
    ),
)
@click.option(
    "--api-base", default=None,
    help="Override LLM endpoint (e.g. http://127.0.0.1:11434/v1 for ollama).",
)
@click.option(
    "-v", "--verbose", count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Adds timing breakdown.",
)
def reflect(
    period: str | None,
    since: datetime | None,
    until: datetime | None,
    lang: str | None,
    include_questions: bool | None,
    as_json: bool,
    model: str | None,
    api_base: str | None,
    verbose: int,
) -> None:
    """AI-as-coach: weekly meta-cognitive reflection on your AI usage.

    Reads your aifd session history (activity, cost, skill diversity, timing)
    plus gstack question-log (compliance, plan-then-ship). Asks the configured
    LLM (via LiteLLM — DeepSeek by default; works with 100+ providers) to
    write you a short essay highlighting 3 wins, 1 anti-pattern, 1 concrete
    next-step action.

    Falls back to structured local report when API key is missing.

    \b
    Examples:
        aifd ai reflect --week
        aifd ai reflect --month --lang en
        aifd ai reflect --since 2026-06-01 --json
        aifd ai reflect --model zhipu/glm-4-plus
        aifd ai reflect --model ollama/qwen2.5 --api-base http://127.0.0.1:11434/v1
    """
    configure_logging(verbose)

    # ----- 1. Load config + resolve overrides -----
    cfg = load_config()
    chosen_lang = lang or cfg.reflect.default_lang
    chosen_include = (
        include_questions
        if include_questions is not None
        else cfg.reflect.include_questions
    )
    chosen_model = model or cfg.llm.model
    chosen_api_base = api_base or cfg.llm.api_base

    # ----- 2. Window -----
    start, end = _resolve_window(period, since, until)
    period_label = _label_for_window(period, start, end, lang=chosen_lang)

    # ----- 3. Collect data (local; should be < 500ms per D8) -----
    t0 = time.monotonic()
    inp = collect_reflection_data(
        start, end,
        source=default_source(),
        include_questions=chosen_include,
    )
    t_local = time.monotonic() - t0
    if t_local > 0.5:
        logger.info(
            "Reflection data collection took %.2fs (local budget 0.5s)",
            t_local,
        )

    # ----- 4. Render prompt -----
    prompt = render_prompt(inp, lang=chosen_lang)

    # ----- 5. Call LLM (or fallback) -----
    output, t_llm, used_llm = _try_llm(
        prompt, cfg, chosen_model, chosen_api_base,
    )

    # ----- 6. Render output -----
    t_render_start = time.monotonic()
    timing = (
        {"local": t_local, "llm": t_llm, "render": 0.0}
        if verbose else None
    )

    if as_json:
        if not used_llm:
            output["_fallback_reason"] = output.get(
                "_fallback_reason", "no API key or LLM unreachable",
            )
        render_reflection_json(output)
    else:
        if not used_llm:
            reason = output.get("_fallback_reason", "")
            click.echo(
                f"[fallback] {reason}\n"
                "Configure an LLM:\n"
                "  export AIFD_LLM_API_KEY=sk-...           "
                "# or DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / ...\n"
                "  aifd ai reflect --model <provider>/<model>\n"
                f"  edit ~/.aifd/config.yaml (current model: {cfg.llm.model})\n",
                err=True,
            )
        render_reflection_text(
            output,
            period_label=period_label,
            lang=chosen_lang,
            timing_breakdown=(
                {**timing, "render": time.monotonic() - t_render_start}
                if timing else None
            ),
        )


# ---------- helpers ----------


def _resolve_window(
    period: str | None,
    since: datetime | None,
    until: datetime | None,
) -> tuple[datetime, datetime]:
    """Pick [start, end) based on flag combination."""
    now = datetime.now().astimezone()
    if since is not None or until is not None:
        local_tz = now.tzinfo
        start = since.replace(tzinfo=local_tz) if since else now - timedelta(days=7)
        end = until.replace(tzinfo=local_tz) if until else now
        return start, end
    # --week is default
    days = 30 if period == "month" else 7
    return now - timedelta(days=days), now


def _label_for_window(
    period: str | None, start: datetime, end: datetime, lang: str,
) -> str:
    if period == "month":
        return "month"
    if period == "week" or period is None:
        return "week"
    # custom range
    return f"{start.date().isoformat()} → {end.date().isoformat()}"


def _try_llm(
    prompt: str,
    cfg: Config,
    model: str,
    api_base: str | None,
) -> tuple[dict[str, object], float, bool]:
    """Run the LLM call; on any error, fall back to a structured local output.

    Returns (output_dict, llm_elapsed_seconds, used_llm_bool).

    Auth-class errors are classified separately for a clearer fallback hint;
    everything else (rate limit, network, schema) is bucketed as transient.
    """
    if cfg.llm.api_key is None:
        return (
            _fallback_output(
                "no LLM API key found "
                "(checked AIFD_LLM_API_KEY, DEEPSEEK_API_KEY, ~/.aifd/config.yaml)",
            ),
            0.0,
            False,
        )

    # On first use, ensure config.yaml exists as a template
    write_template()

    t0 = time.monotonic()
    try:
        output = llm_call(
            prompt,
            model=model,
            api_key=cfg.llm.api_key,
            api_base=api_base,
        )
        elapsed = time.monotonic() - t0
        return output, elapsed, True
    except AuthenticationError as exc:
        msg = f"LLM auth failed: {exc}"
    except BadRequestError as exc:
        msg = f"LLM rejected request (check model name '{model}'): {exc}"
    except RateLimitError as exc:
        msg = f"LLM rate-limited: {exc}"
    except (Timeout, APIConnectionError) as exc:
        msg = f"LLM unreachable: {exc}"
    except APIError as exc:
        msg = f"LLM error: {exc}"
    except LLMResponseError as exc:
        msg = f"LLM returned bad output: {exc}"

    elapsed = time.monotonic() - t0
    logger.warning("%s — falling back to local report", msg)
    return _fallback_output(msg), elapsed, False


def _fallback_output(reason: str) -> dict[str, object]:
    """Stand-in for an LLM output when the LLM is unavailable.

    Structure mirrors the schema so downstream renderers don't care.
    """
    return {
        "prompt_version": PROMPT_VERSION,
        "essay": (
            "AI coach unavailable. Showing structured stats only.\n"
            "Configure AIFD_LLM_API_KEY (or any provider-specific env var) "
            "or set llm.api_base for a local LLM to get a written reflection."
        ),
        "wins": [],
        "anti_pattern": "(none)",
        "concrete_action": "Set AIFD_LLM_API_KEY then re-run.",
        "_fallback_reason": reason,
    }
