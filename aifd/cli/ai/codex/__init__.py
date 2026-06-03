"""`aifd ai codex` group — Codex specific operations."""

from __future__ import annotations

import click

from .skill import skill


@click.group()
def codex() -> None:
    """Codex specific commands."""


codex.add_command(skill)
