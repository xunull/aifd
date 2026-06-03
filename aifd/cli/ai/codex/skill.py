"""`aifd ai codex skill list` — list installed Codex skills."""

from __future__ import annotations

import click

from aifd.cli._logging import configure_logging
from aifd.providers.codex import CodexProvider
from aifd.render import render_installed_skills


@click.group()
def skill() -> None:
    """Inspect installed Codex skills."""


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
    """List skills installed for Codex.

    Scans `~/.codex/skills/`, including the `.system/` directory of
    Codex's built-in skills (marked source="system").
    """
    configure_logging(verbose)
    provider = CodexProvider()
    skills = list(provider.list_installed_skills())
    render_installed_skills(skills, provider_label="codex", as_json=as_json)
