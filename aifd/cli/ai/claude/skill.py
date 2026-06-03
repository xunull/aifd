"""`aifd ai claude skill list` — list installed Claude Code skills."""

from __future__ import annotations

import click

from aifd.cli._logging import configure_logging
from aifd.providers.claude import ClaudeProvider
from aifd.render import render_installed_skills


@click.group()
def skill() -> None:
    """Inspect installed Claude skills."""


@skill.command(name="list")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON instead of a rich table.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def list_cmd(as_json: bool, verbose: int) -> None:
    """List skills installed for Claude Code.

    Scans both `~/.claude/skills/` (user-installed) and
    `~/.claude/plugins/cache/.../skills/` (plugin-installed).
    """
    configure_logging(verbose)
    provider = ClaudeProvider()
    skills = list(provider.list_installed_skills())
    render_installed_skills(skills, provider_label="claude", as_json=as_json)
