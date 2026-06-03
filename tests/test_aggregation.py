"""Tests for aifd.aggregation.aggregate_skill_stats."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aifd.aggregation import aggregate_skill_stats
from aifd.models import SkillInvocation


def _inv(
    skill: str, provider: str, cwd: str, ts: datetime | None = None
) -> SkillInvocation:
    return SkillInvocation(
        skill_name=skill,
        provider=provider,
        cwd=Path(cwd),
        ts=ts,
        source_path=Path(f"/fake/{skill}-{provider}.jsonl"),
    )


def test_empty_input_yields_empty_output() -> None:
    assert aggregate_skill_stats([]) == []


def test_single_invocation_one_stat() -> None:
    stats = aggregate_skill_stats([_inv("office-hours", "claude", "/p1")])
    assert len(stats) == 1
    s = stats[0]
    assert s.skill_name == "office-hours"
    assert s.count_claude == 1
    assert s.count_codex == 0
    assert s.total == 1
    assert s.unique_cwd_count == 1


def test_count_by_provider() -> None:
    invs = [
        _inv("office-hours", "claude", "/p1"),
        _inv("office-hours", "claude", "/p2"),
        _inv("office-hours", "codex", "/p1"),
    ]
    stats = aggregate_skill_stats(invs)
    s = next(s for s in stats if s.skill_name == "office-hours")
    assert s.count_claude == 2
    assert s.count_codex == 1
    assert s.total == 3


def test_unique_cwd_count_deduplicates() -> None:
    invs = [
        _inv("office-hours", "claude", "/p1"),
        _inv("office-hours", "claude", "/p1"),  # same cwd, same provider
        _inv("office-hours", "codex", "/p1"),  # same cwd, different provider
        _inv("office-hours", "claude", "/p2"),  # different cwd
    ]
    stats = aggregate_skill_stats(invs)
    assert stats[0].unique_cwd_count == 2  # only /p1 and /p2 distinct


def test_last_used_takes_max_timestamp() -> None:
    t1 = datetime(2026, 5, 1, tzinfo=UTC)
    t2 = datetime(2026, 6, 1, tzinfo=UTC)
    invs = [
        _inv("office-hours", "claude", "/p1", ts=t1),
        _inv("office-hours", "codex", "/p1", ts=t2),
    ]
    stats = aggregate_skill_stats(invs)
    assert stats[0].last_used == t2


def test_last_used_is_none_when_all_timestamps_missing() -> None:
    invs = [
        _inv("office-hours", "claude", "/p1", ts=None),
        _inv("office-hours", "codex", "/p1", ts=None),
    ]
    stats = aggregate_skill_stats(invs)
    assert stats[0].last_used is None


def test_is_gstack_or_aggregated() -> None:
    """ANY invocation with is_gstack=True flips the stat to is_gstack."""
    invs = [
        SkillInvocation(
            skill_name="office-hours",
            provider="codex",
            cwd=Path("/p1"),
            ts=None,
            source_path=Path("/c.jsonl"),
            is_gstack=False,  # Codex `[$office-hours]`
        ),
        SkillInvocation(
            skill_name="office-hours",
            provider="claude",
            cwd=Path("/p1"),
            ts=None,
            source_path=Path("/cl.jsonl"),
            is_gstack=True,  # Claude `/gstack-office-hours`
        ),
    ]
    stats = aggregate_skill_stats(invs)
    assert stats[0].is_gstack is True


def test_is_gstack_false_when_no_invocation_is_gstack() -> None:
    invs = [
        _inv("model", "claude", "/p1"),  # default is_gstack=False
    ]
    stats = aggregate_skill_stats(invs)
    assert stats[0].is_gstack is False


def test_sort_by_total_descending_then_name() -> None:
    invs = [
        _inv("zzz", "claude", "/p1"),  # total=1
        _inv("aaa", "claude", "/p1"),  # total=1
        _inv("mmm", "claude", "/p1"),  # total=3
        _inv("mmm", "claude", "/p2"),
        _inv("mmm", "codex", "/p3"),
    ]
    stats = aggregate_skill_stats(invs)
    # mmm first (total=3), then aaa and zzz alphabetical (total=1 each)
    assert [s.skill_name for s in stats] == ["mmm", "aaa", "zzz"]
