"""`aifd cosmos` — render your AI session history as a force-directed galaxy.

Decisions locked in /plan-eng-review (E1-E5). Data comes from the public
`activity.iter_sessions_in` (E1); node/link assembly + XSS-safe self-contained
HTML + the vendored force-graph live in `aifd.render_cosmos`. This module only
parses args, windows the data, and writes the file.
"""

from __future__ import annotations

import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import click

from aifd.insights.activity import iter_sessions_in
from aifd.render_cosmos import render_cosmos_html

_DEFAULT_DAYS = 90
_DEFAULT_OUTPUT = "aifd-cosmos.html"


@click.command(name="cosmos")
@click.option(
    "--since",
    "since_days",
    type=int,
    default=_DEFAULT_DAYS,
    metavar="N",
    help=f"Include sessions started in the last N days (default {_DEFAULT_DAYS}).",
)
@click.option(
    "--output",
    "output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=_DEFAULT_OUTPUT,
    help=f"Output HTML path (default {_DEFAULT_OUTPUT}).",
)
@click.option(
    "--open/--no-open",
    "open_browser",
    default=True,
    help="Open the generated HTML in your browser (default: open).",
)
def cosmos(since_days: int, output: Path, open_browser: bool) -> None:
    """Render your AI session history (last N days) as an interactive star galaxy.

    Each session is a star (radius = event count, cool = vibe-coding), each project
    a hub it orbits. Output is a self-contained HTML you can open offline.
    """
    # Same tz convention as `aifd ai habits/reflect` (aware, local) so the
    # started_at comparison inside iter_sessions_in never mixes naive/aware.
    end = datetime.now().astimezone()
    start = end - timedelta(days=max(since_days, 1))
    sessions = list(iter_sessions_in(start, end))
    if not sessions:
        raise click.ClickException(
            f"No sessions found in the last {since_days} days. "
            "Run some AI coding sessions first, or widen --since."
        )
    output.write_text(render_cosmos_html(sessions), encoding="utf-8")
    click.echo(f"✨ {len(sessions)} sessions → {output}")
    if open_browser:
        webbrowser.open(output.resolve().as_uri())
