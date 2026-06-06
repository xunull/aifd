"""`aifd vault` command group — data sovereignty operations.

v0.4 shipped scan + cost. v0.6 adds watch (real-time daemon).

  aifd vault scan    PII / secret detection across all provider jsonl
  aifd vault cost    token + USD spend aggregation
  aifd vault watch   real-time daemon: scan-on-write + macOS notification
"""

from __future__ import annotations

import click

from .cost import cost as cost_cmd
from .scan import scan as scan_cmd
from .watch import watch as watch_cmd


@click.group()
def vault() -> None:
    """Data sovereignty: scan / cost / watch."""


vault.add_command(scan_cmd)
vault.add_command(cost_cmd)
vault.add_command(watch_cmd)
