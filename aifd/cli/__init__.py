"""Top-level CLI entry: `aifd`."""

from __future__ import annotations

import click

from aifd import __version__

from .ai import ai
from .cosmos import cosmos
from .quota import quota
from .vault import vault


@click.group()
@click.version_option(version=__version__, prog_name="aifd")
def cli() -> None:
    """aifd — query AI coding sessions across Claude Code, Codex, and Cursor.

    Run `aifd ai session list` in any project directory to see which AI tools
    have past sessions for that directory.
    """


cli.add_command(ai)
cli.add_command(cosmos)
cli.add_command(quota)
cli.add_command(vault)
