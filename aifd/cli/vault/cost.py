"""`aifd vault cost` — token + USD spend aggregation.

Aggregates per-event TokenUsage from every Provider (Claude, Codex).
Groups by project / model / month / provider (--by). Prices from
`aifd/vault/prices.py`; unknown models show up with $0 attributed.
"""

from __future__ import annotations

import itertools
import logging

import click

from aifd.cli._logging import configure_logging
from aifd.providers.registry import PROVIDERS
from aifd.render import render_cost_rows
from aifd.vault.cost import aggregate_cost
from aifd.vault.prices import LAST_UPDATED, known_models

logger = logging.getLogger("aifd")


@click.command(name="cost")
@click.option(
    "--by",
    "group_by",
    type=click.Choice(["project", "model", "month", "provider"], case_sensitive=False),
    default="project",
    show_default=True,
    help="Aggregation key for the table rows.",
)
@click.option(
    "--provider",
    "providers_filter",
    multiple=True,
    type=click.Choice([p.name for p in PROVIDERS], case_sensitive=False),
    help="Only include the given provider. Repeatable.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="JSON output (pipe-friendly).",
)
@click.option(
    "--list-models",
    "list_models",
    is_flag=True,
    help="Print the priced model ids and exit. Use to verify your model "
    "is recognized (unknown ones show $0 with full token counts).",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def cost(
    group_by: str,
    providers_filter: tuple[str, ...],
    as_json: bool,
    list_models: bool,
    verbose: int,
) -> None:
    """Estimate token usage and USD spend across providers.

    Source data: Claude `message.usage`, Codex
    `event_msg.token_count.payload.info.total_token_usage`. Prices from
    the bundled table (verify date in the footer).
    """
    configure_logging(verbose)

    if list_models:
        click.echo("Priced models:")
        for m in known_models():
            click.echo(f"  {m}")
        return

    wanted = {x.lower() for x in providers_filter}
    selected = [p for p in PROVIDERS if not wanted or p.name.lower() in wanted]
    if not selected:
        raise click.UsageError("No providers matched the --provider filter.")

    usages = itertools.chain.from_iterable(
        p.list_token_usage(None) for p in selected
    )
    rows = aggregate_cost(usages, group_by=group_by)  # type: ignore[arg-type]
    render_cost_rows(
        rows,
        as_json=as_json,
        group_by=group_by,
        prices_last_updated=LAST_UPDATED,
    )
