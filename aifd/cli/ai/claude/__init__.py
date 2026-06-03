"""`aifd ai claude` group — Claude Code specific operations."""

from __future__ import annotations

import click

from .skill import skill


@click.group()
def claude() -> None:
    """Claude Code specific commands."""


claude.add_command(skill)
