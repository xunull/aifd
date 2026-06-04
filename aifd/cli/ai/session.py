"""`aifd ai session` group and `aifd ai session list` command.

Data flow (v0.3, refactored to use _runner.py):

    user runs `aifd ai session list` in /Users/foo/bar
                    │
                    ▼
            list_cmd()  ─── click parses --json / --provider / -v
                    │
                    ▼
            run_provider_query(extractor, providers, scope_cwd, ...)
                    │
                    ▼  (inside the runner)
           ┌────────┴────────┐
        ClaudeProvider   CodexProvider
        .list_sessions   .list_sessions
           │                 │
           └────────┬────────┘
                    ▼
                 list[Session]  (sorted by started_at desc)
                    │
                    ▼
           render_sessions(rows, cwd, as_json)
                    │
                ┌───┴───┐
                ▼       ▼
            rich Table  JSON

The boilerplate that used to live in this file (filter providers, swallow
per-provider failures, sort) moved to aifd.cli._runner so v0.3+ commands
share the same shape. session.py's job is to wire the closure: which
extractor, which sort key, which renderer.
"""

from __future__ import annotations

from pathlib import Path

import click

from aifd.cli._runner import run_provider_query
from aifd.models import Session
from aifd.providers.base import Provider
from aifd.providers.registry import PROVIDERS
from aifd.render import render_sessions


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
    cwd = Path.cwd()

    def extractor(provider: Provider, scope: Path | None) -> list[Session]:
        # session list is always cwd-scoped — scope is guaranteed non-None
        # here because we pass Path.cwd() below. The Provider Protocol
        # types it as Path so we assert non-None for mypy.
        assert scope is not None
        return list(provider.list_sessions(scope))

    def render_fn(rows: list[Session], json_mode: bool) -> None:
        # Capture cwd in the closure so the runner doesn't need to know
        # about renderer-specific labels.
        render_sessions(rows, cwd=cwd, as_json=json_mode)

    run_provider_query(
        providers_pool=PROVIDERS,
        extractor=extractor,
        providers_filter=providers,
        scope_cwd=cwd,
        sort_key=lambda s: (s.started_at is None, s.started_at),
        render_fn=render_fn,
        as_json=as_json,
        verbose=verbose,
    )
