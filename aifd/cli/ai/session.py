"""`aifd ai session` group and `aifd ai session list` command.

Data flow (per design doc):

    user runs `aifd ai session list` in /Users/foo/bar
                    │
                    ▼
            cli.list_cmd()  ─── click parses --json / --provider
                    │
                    ▼
           normalize_cwd(Path.cwd())  ─── paths.py
                    │
                    ▼
             filter(PROVIDERS, --provider)
                    │
                    ▼
           ┌────────┴────────┐
        ClaudeProvider   CodexProvider
        .list_sessions   .list_sessions
           │                 │
           └────────┬────────┘
                    ▼
                 list[Session]
                    │
                    ▼
           render_sessions(rows, as_json)
                    │
                ┌───┴───┐
                ▼       ▼
            rich Table  JSON
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from aifd.cli._logging import configure_logging
from aifd.models import Session
from aifd.paths import normalize_cwd
from aifd.providers.registry import PROVIDERS
from aifd.render import render_sessions

logger = logging.getLogger("aifd")


@click.group()
def session() -> None:
    """Operations on AI sessions (list, ...).

    Future: show, resume, export.
    """


@session.command(name="list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON instead of a rich table (pipe-friendly).",
)
@click.option(
    "--provider",
    "providers",
    multiple=True,
    type=click.Choice([p.name for p in PROVIDERS], case_sensitive=False),
    help="Only include sessions from the given provider. Repeatable.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def list_cmd(as_json: bool, providers: tuple[str, ...], verbose: int) -> None:
    """List AI sessions for the current directory across all configured providers."""
    configure_logging(verbose)

    cwd = normalize_cwd(Path.cwd())
    logger.info("Listing sessions for cwd=%s", cwd)

    wanted = {x.lower() for x in providers}
    selected = [p for p in PROVIDERS if not wanted or p.name.lower() in wanted]
    rows: list[Session] = []
    for provider in selected:
        try:
            rows.extend(provider.list_sessions(cwd))
        except Exception as exc:
            logger.warning("Provider %s failed entirely: %s", provider.name, exc)

    # Sort by started_at desc, None last
    rows.sort(key=lambda s: (s.started_at is None, s.started_at), reverse=True)

    render_sessions(rows, cwd=cwd, as_json=as_json)


