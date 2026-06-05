"""`aifd ai` command group — operations across AI coding tools."""

from __future__ import annotations

import click

from .claude import claude
from .codex import codex
from .question import question
from .retro import monthly, retro, today, weekly
from .session import session
from .skill import skill


@click.group()
def ai() -> None:
    """Operations across AI coding tools (Claude Code, Codex, Cursor)."""


ai.add_command(session)
ai.add_command(skill)
ai.add_command(question)
ai.add_command(claude)
ai.add_command(codex)
# v0.5 retro / activity summary
ai.add_command(today)
ai.add_command(weekly)
ai.add_command(monthly)
ai.add_command(retro)
