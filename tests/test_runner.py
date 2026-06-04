"""Tests for the shared `aifd.cli._runner.run_provider_query` helper.

Validates the contract session.py and question.py both rely on:
- providers_filter narrows by name (case-insensitive)
- scope_cwd None means global scan
- per-provider exception is logged + swallowed (one bad provider doesn't
  break the listing)
- sort_key + sort_reverse control order
- render_fn receives the assembled rows
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from aifd.cli._runner import run_provider_query


class _StaticProvider:
    """Mock provider that returns canned rows."""

    def __init__(self, name: str, rows: list[int]) -> None:
        self.name = name
        self._rows = rows

    def extract(self, scope: Path | None) -> Iterable[int]:
        return iter(self._rows)


class _BrokenProvider:
    """Mock provider that raises on extract."""

    name = "broken"

    def extract(self, scope: Path | None) -> Iterable[int]:
        raise RuntimeError("boom")


def test_run_provider_query_aggregates_rows() -> None:
    captured: list[list[int]] = []

    def render(rows: list[int], as_json: bool) -> None:
        captured.append(rows)

    a = _StaticProvider("a", [3, 1, 2])
    b = _StaticProvider("b", [10])
    run_provider_query(
        providers_pool=[a, b],
        extractor=lambda p, _scope: p.extract(_scope),
        providers_filter=(),
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=render,
        as_json=False,
        verbose=0,
    )
    assert captured == [[10, 3, 2, 1]]  # default sort desc


def test_run_provider_query_filter_by_name() -> None:
    captured: list[list[int]] = []
    a = _StaticProvider("a", [1])
    b = _StaticProvider("b", [2])
    run_provider_query(
        providers_pool=[a, b],
        extractor=lambda p, _: p.extract(_),
        providers_filter=("B",),  # case-insensitive
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=lambda rows, _aj: captured.append(rows),
        as_json=False,
        verbose=0,
    )
    assert captured == [[2]]


def test_run_provider_query_handles_broken_provider(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One provider raising must not break the listing.

    configure_logging attaches a stderr StreamHandler with propagate=False,
    so we read the warning off captured stderr rather than caplog.
    """
    captured: list[list[int]] = []
    good = _StaticProvider("good", [42])
    bad = _BrokenProvider()
    run_provider_query(
        providers_pool=[good, bad],
        extractor=lambda p, _: p.extract(_),
        providers_filter=(),
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=lambda rows, _aj: captured.append(rows),
        as_json=False,
        verbose=0,
    )
    assert captured == [[42]]  # good provider still produced output
    err = capsys.readouterr().err
    assert "broken" in err and "boom" in err


def test_run_provider_query_scope_is_normalized(tmp_path: Path) -> None:
    """When scope_cwd is set, the extractor receives the normalized Path."""
    seen_scope: list[Path | None] = []

    def extractor(p: _StaticProvider, scope: Path | None) -> Iterable[int]:
        seen_scope.append(scope)
        return ()

    a = _StaticProvider("a", [])
    run_provider_query(
        providers_pool=[a],
        extractor=extractor,
        providers_filter=(),
        scope_cwd=tmp_path,
        sort_key=lambda n: n,
        render_fn=lambda rows, _: None,
        as_json=False,
        verbose=0,
    )
    assert seen_scope == [tmp_path.resolve()]


def test_run_provider_query_scope_none_means_global() -> None:
    """scope_cwd=None passes None straight through."""
    seen_scope: list[Path | None] = []

    def extractor(p: _StaticProvider, scope: Path | None) -> Iterable[int]:
        seen_scope.append(scope)
        return ()

    a = _StaticProvider("a", [])
    run_provider_query(
        providers_pool=[a],
        extractor=extractor,
        providers_filter=(),
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=lambda rows, _: None,
        as_json=False,
        verbose=0,
    )
    assert seen_scope == [None]


def test_run_provider_query_sort_ascending() -> None:
    """sort_reverse=False sorts ascending."""
    captured: list[list[int]] = []
    a = _StaticProvider("a", [3, 1, 2])
    run_provider_query(
        providers_pool=[a],
        extractor=lambda p, _: p.extract(_),
        providers_filter=(),
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=lambda rows, _aj: captured.append(rows),
        as_json=False,
        verbose=0,
        sort_reverse=False,
    )
    assert captured == [[1, 2, 3]]


def test_run_provider_query_render_receives_as_json() -> None:
    captured: list[bool] = []
    a = _StaticProvider("a", [1])
    run_provider_query(
        providers_pool=[a],
        extractor=lambda p, _: p.extract(_),
        providers_filter=(),
        scope_cwd=None,
        sort_key=lambda n: n,
        render_fn=lambda _rows, as_json: captured.append(as_json),
        as_json=True,
        verbose=0,
    )
    assert captured == [True]
