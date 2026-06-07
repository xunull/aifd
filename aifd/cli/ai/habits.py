"""`aifd ai habits` — long-term AI behaviour portrait (v0.9).

Analyses 60-90 days of AI usage to surface recurring behavioural patterns
the user hasn't noticed themselves: weekday rhythms, deep-night sessions,
over-planning, skill repetition, project focus drift, etc.

Complements `aifd ai reflect` (weekly/monthly check-in):
  - reflect = "how was this week?"
  - habits  = "what kind of AI user am I?"

Fallback: when no API key is configured, prints the raw computed stats
as a structured table so the user still gets value.

Locked decisions (from /plan-eng-review):
  D1 late-night dimension: 22h+ session → next-day ship rate (SkillEvent only)
  D3 HabitsInput is an independent dataclass, not inherited from ReflectionInput
  D4 habits.default_days=90 from config; --since overrides
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
from aifd.config import load as load_config
from aifd.config import write_template
from aifd.insights.habits import collect_habits_data
from aifd.insights.habits_prompt import PROMPT_VERSION, render_habits_prompt
from aifd.insights.llm_client import LLMResponseError
from aifd.insights.llm_client import call as llm_call
from aifd.insights.reflection_source import default_source
from aifd.render import render_habits_json, render_habits_text

logger = logging.getLogger("aifd")


@click.command(name="habits")
@click.option(
    "--since",
    default=None,
    help=(
        "Analysis window start: date (YYYY-MM-DD) or shorthand like '60d', '90d'. "
        "Defaults to config.habits.default_days days ago (90)."
    ),
)
@click.option(
    "--lang", type=click.Choice(["en", "zh"]), default=None,
    help="Output language. Default: config.reflect.default_lang (zh).",
)
@click.option(
    "--json", "as_json", is_flag=True,
    help="Emit JSON instead of rendered text.",
)
@click.option(
    "--model", default=None,
    help="LiteLLM 'provider/model' string (e.g. deepseek/deepseek-chat).",
)
@click.option(
    "--api-base", default=None,
    help="Override LLM endpoint (e.g. http://127.0.0.1:11434/v1 for ollama).",
)
@click.option(
    "-v", "--verbose", count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG.",
)
def habits(
    since: str | None,
    lang: str | None,
    as_json: bool,
    model: str | None,
    api_base: str | None,
    verbose: int,
) -> None:
    """Long-term AI behaviour portrait: identify patterns you haven't noticed.

    Analyses 60-90 days of AI session history to surface behavioural patterns
    across weekdays, time-of-day, project focus, ship cadence, planning habits,
    and skill usage.

    Complements `aifd ai reflect` (weekly review) — run habits once a quarter
    or whenever you want a deeper self-assessment.

    \b
    Examples:
        aifd ai habits
        aifd ai habits --since 60d
        aifd ai habits --since 2026-01-01
        aifd ai habits --lang en --json
        aifd ai habits --model zhipu/glm-4-plus
    """
    configure_logging(verbose)

    cfg = load_config()
    chosen_lang = lang or cfg.reflect.default_lang
    chosen_model = model or cfg.llm.model
    chosen_api_base = api_base or cfg.llm.api_base

    # ----- Resolve time window -----
    end = datetime.now().astimezone()
    start = _parse_since(since, cfg.habits.default_days, end)

    # ----- Collect data (local) -----
    t0 = time.monotonic()
    inp = collect_habits_data(
        start, end,
        source=default_source(),
    )
    t_local = time.monotonic() - t0
    if t_local > 1.0:
        logger.info("Habits data collection took %.2fs", t_local)

    # ----- Render prompt -----
    prompt = render_habits_prompt(inp, lang=chosen_lang)

    # ----- Call LLM (or fallback) -----
    output, t_llm, used_llm = _try_llm(prompt, cfg, chosen_model, chosen_api_base)

    # ----- Render output -----
    t_render = time.monotonic()
    timing = (
        {"local": t_local, "llm": t_llm, "render": 0.0}
        if verbose else None
    )

    if as_json:
        if not used_llm:
            output["_fallback_reason"] = output.get(
                "_fallback_reason", "no API key or LLM unreachable",
            )
        render_habits_json(output)
    else:
        if not used_llm:
            reason = output.get("_fallback_reason", "")
            click.echo(
                f"[fallback] {reason}\n"
                "Configure an LLM:\n"
                "  export AIFD_LLM_API_KEY=sk-...  "
                "# or DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / ...\n"
                f"  edit ~/.aifd/config.yaml (current model: {cfg.llm.model})\n",
                err=True,
            )
        days = (end - start).days
        render_habits_text(
            output,
            period_days=days,
            lang=chosen_lang,
            timing_breakdown=(
                {**timing, "render": time.monotonic() - t_render}
                if timing else None
            ),
        )


# ---------- helpers ----------


def _parse_since(since: str | None, default_days: int, now: datetime) -> datetime:
    """Parse --since value to a start datetime.

    Accepts:
      None        → now - default_days
      "60d"       → now - 60 days
      "YYYY-MM-DD" → that date at midnight local tz
    """
    if since is None:
        return now - timedelta(days=default_days)
    if since.endswith("d") and since[:-1].isdigit():
        return now - timedelta(days=int(since[:-1]))
    try:
        local_tz = now.tzinfo
        dt = datetime.strptime(since, "%Y-%m-%d")
        return dt.replace(tzinfo=local_tz)
    except ValueError:
        logger.warning("Cannot parse --since %r; using default %d days", since, default_days)
        return now - timedelta(days=default_days)


def _try_llm(
    prompt: str,
    cfg: object,
    model: str,
    api_base: str | None,
) -> tuple[dict[str, object], float, bool]:
    """Call LLM; on any error fall back to structured no-LLM output."""
    from aifd.config import Config
    assert isinstance(cfg, Config)

    if cfg.llm.api_key is None:
        return (
            _fallback_output(
                "no LLM API key found "
                "(checked AIFD_LLM_API_KEY, DEEPSEEK_API_KEY, ~/.aifd/config.yaml)"
            ),
            0.0,
            False,
        )

    write_template()

    t0 = time.monotonic()
    try:
        output = llm_call(
            prompt,
            model=model,
            api_key=cfg.llm.api_key,
            api_base=api_base,
        )
        return output, time.monotonic() - t0, True
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
    """Structured output when LLM is unavailable."""
    return {
        "prompt_version": PROMPT_VERSION,
        "patterns": [],
        "_fallback_reason": reason,
    }
