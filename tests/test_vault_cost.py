"""Tests for aifd.vault.cost (token + USD aggregation)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aifd.models import TokenUsage
from aifd.vault.cost import aggregate_cost, compute_event_cost
from aifd.vault.prices import known_models, lookup_price


def _u(
    *,
    provider: str = "claude",
    model: str | None = "claude-opus-4-7",
    project: str = "proj",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    reasoning_output_tokens: int = 0,
    session_id: str = "s1",
    ts: datetime | None = None,
) -> TokenUsage:
    return TokenUsage(
        provider=provider,
        session_id=session_id,
        cwd=Path(f"/{project}"),
        ts=ts or datetime(2026, 6, 1, tzinfo=UTC),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
    )


# ---------- prices.lookup_price ----------


def test_lookup_price_exact_match() -> None:
    """Opus 4.5+ moved to $5/$25 tier per Anthropic's 2026 pricing update."""
    p = lookup_price("claude-opus-4-7")
    assert p is not None
    assert p["input"] == 5.00
    assert p["output"] == 25.00


def test_lookup_price_legacy_opus_4_1_keeps_old_rate() -> None:
    """Opus 4 / 4.1 retain $15/$75; the new rate only starts at 4.5."""
    p = lookup_price("claude-opus-4-1")
    assert p is not None
    assert p["input"] == 15.00
    assert p["output"] == 75.00


def test_lookup_price_prefix_strip_for_dated_variant() -> None:
    """`claude-opus-4-7-20251101` strips down to `claude-opus-4-7`."""
    p = lookup_price("claude-opus-4-7-20251101")
    assert p is not None
    assert p["input"] == 5.00


def test_lookup_price_unknown_returns_none() -> None:
    assert lookup_price("totally-fake-model-9000") is None


def test_lookup_price_none_input_returns_none() -> None:
    assert lookup_price(None) is None


def test_known_models_non_empty_and_sorted() -> None:
    ms = known_models()
    assert ms == sorted(ms)
    assert "claude-opus-4-7" in ms
    assert "gpt-5-codex" in ms


# ---------- compute_event_cost ----------


def test_compute_event_cost_input_only() -> None:
    cost = compute_event_cost(_u(input_tokens=1_000_000))  # 1M input
    # claude-opus-4-7: $5 / 1M input (post-4.5 pricing)
    assert cost == 5.0


def test_compute_event_cost_output_plus_reasoning() -> None:
    """Reasoning tokens billed at output rate."""
    cost = compute_event_cost(
        _u(model="gpt-5", output_tokens=1_000_000, reasoning_output_tokens=1_000_000)
    )
    # gpt-5: $10 output, $10 reasoning -> $20 total
    assert cost == 20.0


def test_compute_event_cost_cache_split() -> None:
    cost = compute_event_cost(
        _u(
            cache_creation_input_tokens=1_000_000,
            cache_read_input_tokens=1_000_000,
        )
    )
    # Opus 4.7: cache_write 6.25 + cache_read 0.50 = 6.75
    assert cost == 6.75


def test_compute_event_cost_unknown_model_returns_zero() -> None:
    """Unknown models still emit row with $0 (tokens visible, no $)."""
    assert compute_event_cost(_u(model="never-heard-of-it", input_tokens=1_000_000)) == 0.0


# ---------- aggregate_cost ----------


def test_aggregate_by_project_sums_within_bucket() -> None:
    rows = aggregate_cost(
        iter([
            _u(project="aifd", output_tokens=1_000_000),
            _u(project="aifd", output_tokens=1_000_000),
            _u(project="other", output_tokens=1_000_000),
        ]),
        group_by="project",
    )
    by_label = {r.label: r for r in rows}
    # Opus 4.7 output: $25 / 1M (post-4.5 pricing)
    assert by_label["aifd"].cost_usd == 50.0
    assert by_label["other"].cost_usd == 25.0


def test_aggregate_sorted_by_cost_desc() -> None:
    rows = aggregate_cost(
        iter([
            _u(project="small", input_tokens=1),
            _u(project="big", input_tokens=10_000_000),
            _u(project="medium", input_tokens=1_000_000),
        ]),
        group_by="project",
    )
    assert [r.label for r in rows] == ["big", "medium", "small"]


def test_aggregate_by_provider_splits_claude_from_codex() -> None:
    rows = aggregate_cost(
        iter([
            _u(provider="claude", project="aifd", output_tokens=1_000_000),
            _u(provider="codex", project="aifd", model="gpt-5", output_tokens=1_000_000),
        ]),
        group_by="provider",
    )
    providers = {r.provider for r in rows}
    assert providers == {"claude", "codex"}


def test_aggregate_same_project_different_providers_dont_merge() -> None:
    """Bucket key includes provider so a claude+codex `aifd` shows as 2 rows."""
    rows = aggregate_cost(
        iter([
            _u(provider="claude", project="aifd", output_tokens=1_000_000),
            _u(provider="codex", project="aifd", model="gpt-5", output_tokens=1_000_000),
        ]),
        group_by="project",
    )
    aifd_rows = [r for r in rows if r.label == "aifd"]
    assert len(aifd_rows) == 2


def test_aggregate_by_month() -> None:
    rows = aggregate_cost(
        iter([
            _u(ts=datetime(2026, 5, 15, tzinfo=UTC), output_tokens=1_000_000),
            _u(ts=datetime(2026, 6, 1, tzinfo=UTC), output_tokens=1_000_000),
            _u(ts=datetime(2026, 6, 20, tzinfo=UTC), output_tokens=1_000_000),
        ]),
        group_by="month",
    )
    labels = sorted(r.label for r in rows)
    assert labels == ["2026-05", "2026-06"]
    by = {r.label: r for r in rows}
    assert by["2026-06"].event_count == 2


def test_aggregate_unknown_model_keeps_tokens_zero_cost() -> None:
    rows = aggregate_cost(
        iter([_u(model="unknown-99", input_tokens=1_000_000)]),
        group_by="project",
    )
    assert rows[0].input_tokens == 1_000_000
    assert rows[0].cost_usd == 0.0


def test_aggregate_marks_multi_model_bucket_as_mixed() -> None:
    rows = aggregate_cost(
        iter([
            _u(model="claude-opus-4-7", output_tokens=1_000_000),
            _u(model="claude-sonnet-4-6", output_tokens=1_000_000),
        ]),
        group_by="project",
    )
    assert rows[0].model is not None
    assert rows[0].model.startswith("mixed")
