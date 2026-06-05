"""`aifd ai today / weekly / monthly / retro` — activity summary commands.

All four commands are thin sugar over `aifd.insights.summarize_activity`.
The shared `_run_retro` closure picks a time window, runs the backend, and
hands the report to `render_activity_report`. Each subcommand passes a
different period_label for the header + chooses the right time window.

Data flow (mirrors the design doc):

      user types `aifd ai today`
              │
              ▼
       _run_retro(window=today, label='today')
              │
              ▼
       summarize_activity(start, end)
              │
              ├── compute_diff(prev window)
              └── compute_projection(now)
              │
              ▼
       render_activity_report(report, delta, projection, label, as_json)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import click

from aifd.cli._logging import configure_logging
from aifd.insights import (
    compute_diff,
    compute_projection,
    previous_window,
    summarize_activity,
    window_for_monthly,
    window_for_today,
    window_for_weekly,
)
from aifd.render import render_activity_report

logger = logging.getLogger("aifd")


def _run_retro(
    start: datetime,
    end: datetime,
    *,
    period_label: str,
    as_json: bool,
    verbose: int,
) -> None:
    """Shared dispatcher: aggregate window, diff against previous, project, render."""
    configure_logging(verbose)
    logger.info(
        "Activity report: window=[%s, %s) label=%s",
        start.isoformat(timespec="seconds"),
        end.isoformat(timespec="seconds"),
        period_label,
    )
    report = summarize_activity(start, end)
    prev_start, prev_end = previous_window(start, end)
    prev_report = summarize_activity(prev_start, prev_end)
    delta = compute_diff(report, prev_report)
    # Pass `now` only for windows that include "now" as their endpoint —
    # i.e. today / weekly / monthly. The custom retro range may end in the
    # past, in which case projection from the literal window is correct.
    now_for_proj = datetime.now(UTC) if period_label != "custom" else end
    projection = compute_projection(report, now=now_for_proj)
    render_activity_report(
        report,
        delta=delta,
        projection=projection,
        period_label=period_label,
        as_json=as_json,
    )


def _common_opts(fn: click.decorators.FC) -> click.decorators.FC:
    """Apply --json + -v/-vv to each retro subcommand uniformly."""
    fn = click.option(
        "--json",
        "as_json",
        is_flag=True,
        help="Emit a stable JSON schema (pipe-friendly).",
    )(fn)
    fn = click.option(
        "-v",
        "--verbose",
        count=True,
        help="Increase log verbosity. -v=INFO, -vv=DEBUG.",
    )(fn)
    return fn


@click.command(name="today")
@_common_opts
def today(as_json: bool, verbose: int) -> None:
    """Activity summary for today (local midnight → now)."""
    now = datetime.now().astimezone()
    start, end = window_for_today(now)
    _run_retro(
        start, end, period_label="today", as_json=as_json, verbose=verbose
    )


@click.command(name="weekly")
@_common_opts
def weekly(as_json: bool, verbose: int) -> None:
    """Activity summary for the past 7 days (rolling)."""
    now = datetime.now().astimezone()
    start, end = window_for_weekly(now)
    _run_retro(
        start, end, period_label="weekly", as_json=as_json, verbose=verbose
    )


@click.command(name="monthly")
@_common_opts
def monthly(as_json: bool, verbose: int) -> None:
    """Activity summary for the current calendar month."""
    now = datetime.now().astimezone()
    start, end = window_for_monthly(now)
    _run_retro(
        start, end, period_label="monthly", as_json=as_json, verbose=verbose
    )


@click.command(name="retro")
@click.option(
    "--since",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    required=True,
    help="Inclusive start of the window (YYYY-MM-DD or ISO 8601).",
)
@click.option(
    "--until",
    type=click.DateTime(formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]),
    default=None,
    help="Exclusive end of the window. Defaults to `now`.",
)
@_common_opts
def retro(
    since: datetime,
    until: datetime | None,
    as_json: bool,
    verbose: int,
) -> None:
    """Activity summary for a custom date range."""
    # Click parses naive datetimes; assume the user's local tz so window
    # boundaries align with intuition.
    local_tz = datetime.now().astimezone().tzinfo
    start = since.replace(tzinfo=local_tz)
    if until is None:
        end = datetime.now().astimezone()
    else:
        end = until.replace(tzinfo=local_tz)
    if end <= start:
        raise click.UsageError(
            f"--until ({end.isoformat()}) must be after --since ({start.isoformat()})"
        )
    _run_retro(
        start, end, period_label="custom", as_json=as_json, verbose=verbose
    )


# Suppress the unused-import warning when `timedelta` is referenced only
# for documentation purposes (window helpers compute their own offsets).
_ = timedelta
