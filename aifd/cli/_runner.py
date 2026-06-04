"""Shared provider-query runner.

Extracted in v0.3 once cli/ai/question.py joined cli/ai/session.py with the
same boilerplate: configure logging, filter providers by --provider, iterate
each provider's extractor, swallow per-provider failures with a warning,
sort, hand off to a renderer. Stuffing that into one helper means later
commands (v0.3+ stats, search, ...) just plug in three callables instead
of re-deriving the harness.

The shared shape:

      ┌─────────────────────────────────────────────┐
      │ run_provider_query                          │
      │                                             │
      │  configure_logging(verbose)                 │
      │  scope_cwd = normalize_cwd(scope_cwd)       │
      │  selected = PROVIDERS filtered by name      │
      │  for p in selected:                         │
      │     try: rows += extractor(p, scope_cwd)    │
      │     except: logger.warning(...)             │
      │  rows.sort(key=sort_key, reverse=True)      │
      │  render_fn(rows, as_json)                   │
      └─────────────────────────────────────────────┘
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from aifd.cli._logging import configure_logging
from aifd.paths import normalize_cwd
from aifd.providers.base import Provider

logger = logging.getLogger("aifd")


def run_provider_query[T](
    *,
    providers_pool: Sequence[Provider],
    extractor: Callable[[Provider, Path | None], Iterable[T]],
    providers_filter: tuple[str, ...],
    scope_cwd: Path | None,
    sort_key: Callable[[T], Any],
    render_fn: Callable[[list[T], bool], None],
    as_json: bool,
    verbose: int,
    sort_reverse: bool = True,
) -> None:
    """Execute a provider query end-to-end.

    Args:
        providers_pool: sequence of provider instances to draw from.
            Callers pass their own module-local PROVIDERS sequence so
            tests can monkey-patch the caller's symbol without having to
            reach into _runner internals.
        extractor: called once per selected provider with (provider,
            normalized_scope_or_None). Returns an iterable of rows. The
            shape of the row is up to the caller — sessions, question
            answers, skill stats, etc.
        providers_filter: --provider option values (already lowercased
            via click.Choice case_sensitive=False). Empty tuple means
            "all providers".
        scope_cwd: when None, the extractor is called with None and is
            expected to do a global scan. When set, this runner normalizes
            it via paths.normalize_cwd and passes the normalized path.
        sort_key: stable sort key over T. Combined with sort_reverse to
            produce final row order before rendering.
        render_fn: takes (rows, as_json) and writes to stdout. Caller
            wraps the actual renderer in a closure that captures any
            additional context (cwd label, scope description, ...).
        as_json: forwarded to render_fn. Provided as a separate arg so
            the runner doesn't need to introspect render_fn's signature.
        verbose: -v count for configure_logging.
        sort_reverse: default True (newest-first), set False for ascending.
    """
    configure_logging(verbose)

    if scope_cwd is not None:
        scope_cwd = normalize_cwd(scope_cwd)
        logger.info("Querying scope cwd=%s", scope_cwd)
    else:
        logger.info("Querying scope=global")

    wanted = {x.lower() for x in providers_filter}
    selected = [p for p in providers_pool if not wanted or p.name.lower() in wanted]

    rows: list[T] = []
    for provider in selected:
        try:
            rows.extend(extractor(provider, scope_cwd))
        except Exception as exc:
            # D7 single-provider failure tier: warn + continue. One
            # broken provider must not break the whole listing.
            logger.warning("Provider %s failed entirely: %s", provider.name, exc)

    rows.sort(key=sort_key, reverse=sort_reverse)
    render_fn(rows, as_json)
