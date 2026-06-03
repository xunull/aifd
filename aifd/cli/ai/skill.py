"""`aifd ai skill` group and `aifd ai skill list` command.

Data flow:

    user runs `aifd ai skill list [--cwd] [--provider X] [--json]`
                    │
                    ▼
            cli.list_cmd parses flags
                    │
                    ▼
       scope = normalize_cwd(Path.cwd()) if --cwd else None
                    │
                    ▼
         selected = filter PROVIDERS by --provider
                    │
                    ▼
              ┌─────┴──────┐
              │            │
       ClaudeProvider   CodexProvider
       .list_skill_invocations(scope)
              │            │
              └─────┬──────┘
                    ▼
              list[SkillInvocation]
                    │
                    ▼
         aggregate_skill_stats()  ─── aifd/aggregation.py
                    │
                    ▼
              list[SkillStats]
                    │
                    ▼
         render_skill_stats(stats, scope_label, as_json)
                    │
                ┌───┴───┐
                ▼       ▼
            rich Table  JSON
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from aifd.aggregation import aggregate_skill_stats
from aifd.cli._logging import configure_logging
from aifd.models import SkillInvocation
from aifd.paths import normalize_cwd
from aifd.providers.registry import PROVIDERS
from aifd.render import render_skill_stats

logger = logging.getLogger("aifd")


@click.group()
def skill() -> None:
    """Operations on AI skills (list, ...).

    Future: show <skill>, timeline, stats.
    """


@skill.command(name="list")
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
    help="Only include invocations from the given provider. Repeatable.",
)
@click.option(
    "--cwd",
    "cwd_only",
    is_flag=True,
    help="Limit stats to the current working directory (default: global).",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def list_cmd(
    as_json: bool, providers: tuple[str, ...], cwd_only: bool, verbose: int
) -> None:
    """List skills used across Claude Code, Codex, and (v0.3) Cursor.

    Default scope is global. Use --cwd to limit to the current directory.
    """
    configure_logging(verbose)

    scope: Path | None = normalize_cwd(Path.cwd()) if cwd_only else None
    scope_label = f"in {scope}" if scope is not None else "globally"

    wanted = {x.lower() for x in providers}
    selected = [p for p in PROVIDERS if not wanted or p.name.lower() in wanted]

    invocations: list[SkillInvocation] = []
    for provider in selected:
        try:
            invocations.extend(provider.list_skill_invocations(scope))
        except Exception as exc:
            logger.warning(
                "Provider %s failed during skill extraction: %s", provider.name, exc
            )

    stats = aggregate_skill_stats(invocations)
    logger.info("Aggregated %d skills from %d invocations", len(stats), len(invocations))

    render_skill_stats(stats, scope_label=scope_label, as_json=as_json)


