"""`aifd vault` command group — data sovereignty operations.

v0.4 ships two:
  aifd vault scan   PII / secret detection across all provider jsonl
  aifd vault cost   token + USD spend aggregation

v0.5+ (deferred to TODOS.md): export / sync / redact / encrypt.
"""

from __future__ import annotations

import click

from .cost import cost as cost_cmd
from .scan import scan as scan_cmd


@click.group()
def vault() -> None:
    """Data sovereignty: scan / cost (more in v0.5+)."""


vault.add_command(scan_cmd)
vault.add_command(cost_cmd)
