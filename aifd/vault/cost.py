"""Token + USD cost aggregation for `aifd vault cost`.

Takes the per-event TokenUsage stream from providers and rolls it up by
project / model / month. Calls the priced model table to compute USD;
unknown models still surface in the report (tokens counted, $0
attributed) so users see what's missing.

Aggregation key conventions:
- "project" = cwd.name (or full path if no parent)
- "model"   = TokenUsage.model verbatim
- "month"   = ts.strftime("%Y-%m"); rows without ts go into "unknown"

Per-provider semantics note:
- Claude rows are PER ASSISTANT MESSAGE (each event is incremental). Sum.
- Codex rows are PER SESSION (already collapsed by the provider to the
  cumulative max). Also safe to sum across sessions.

So the aggregator just sums — provider-side smoothing already happened.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Literal

from aifd.models import CostRow, TokenUsage
from aifd.vault.prices import lookup_price

logger = logging.getLogger("aifd.vault.cost")

GroupBy = Literal["project", "model", "month", "provider"]


def compute_event_cost(usage: TokenUsage) -> float:
    """Return USD cost for a single TokenUsage row, $0 if model is unknown."""
    price = lookup_price(usage.model)
    if price is None:
        return 0.0
    per_million = 1_000_000
    cost = 0.0
    cost += price["input"] * usage.input_tokens / per_million
    cost += (
        price["output"] * (usage.output_tokens + usage.reasoning_output_tokens)
        / per_million
    )
    cost += price["cache_write"] * usage.cache_creation_input_tokens / per_million
    cost += price["cache_read"] * usage.cache_read_input_tokens / per_million
    return cost


def aggregate_cost(
    usages: Iterable[TokenUsage],
    *,
    group_by: GroupBy = "project",
) -> list[CostRow]:
    """Roll up TokenUsage events into CostRows grouped by the requested key.

    Returned rows sorted by cost descending so the biggest spend lands
    at the top. Unknown models surface with cost=0 so the user sees
    their token volume and can fix the price table.
    """
    buckets: dict[tuple[str, str], _Bucket] = {}

    for u in usages:
        label = _label_for(u, group_by)
        # Bucket key combines label + provider so cross-provider rows
        # don't merge under the same label.
        key = (label, u.provider)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _Bucket(label=label, provider=u.provider, model=u.model)
            buckets[key] = bucket
        bucket.add(u)

    rows = [b.finalize() for b in buckets.values()]
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def _label_for(u: TokenUsage, group_by: GroupBy) -> str:
    if group_by == "project":
        if u.cwd is None:
            return "(unknown cwd)"
        return u.cwd.name or str(u.cwd)
    if group_by == "model":
        return u.model or "(unknown model)"
    if group_by == "month":
        return u.ts.strftime("%Y-%m") if u.ts else "(unknown)"
    if group_by == "provider":
        return u.provider
    return "(unknown)"


class _Bucket:
    """Mutable accumulator used inside the aggregation loop."""

    __slots__ = (
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cost",
        "events",
        "input_tokens",
        "label",
        "model",
        "models_seen",
        "output_tokens",
        "provider",
        "reasoning_output_tokens",
    )

    def __init__(self, label: str, provider: str, model: str | None) -> None:
        self.label = label
        self.provider = provider
        self.models_seen: set[str] = set()
        if model:
            self.models_seen.add(model)
        self.model: str | None = model
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0
        self.reasoning_output_tokens = 0
        self.cost = 0.0
        self.events = 0

    def add(self, u: TokenUsage) -> None:
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        self.cache_creation_input_tokens += u.cache_creation_input_tokens
        self.cache_read_input_tokens += u.cache_read_input_tokens
        self.reasoning_output_tokens += u.reasoning_output_tokens
        self.cost += compute_event_cost(u)
        self.events += 1
        if u.model:
            self.models_seen.add(u.model)

    def finalize(self) -> CostRow:
        model_display = (
            self.model
            if len(self.models_seen) == 1
            else (f"mixed ({len(self.models_seen)})" if self.models_seen else None)
        )
        total = (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
            + self.reasoning_output_tokens
        )
        return CostRow(
            label=self.label,
            provider=self.provider,
            model=model_display,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            reasoning_output_tokens=self.reasoning_output_tokens,
            total_tokens=total,
            cost_usd=self.cost,
            event_count=self.events,
        )
