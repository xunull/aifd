"""Tests for the 8 compute_habit_* dimensions (T3)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from aifd.insights.habits import (
    HabitsInput,
    _hour_to_bucket,
    collect_habits_data,
    compute_habit_late_night_ship_rate,
    compute_habit_overplanning_rate,
    compute_habit_project_switch_frequency,
    compute_habit_session_bimodal,
    compute_habit_ship_cadence,
    compute_habit_skill_repetition,
    compute_habit_timeslot_distribution,
    compute_habit_weekday_distribution,
)
from aifd.insights.reflection_source import NullSource, SkillEvent
from aifd.models import Session

LOCAL_TZ = datetime.now().astimezone().tzinfo


def _session(
    cwd: str = "/foo",
    year: int = 2026,
    month: int = 4,   # April 2026 spans many weekdays
    day: int = 6,     # Monday
    hour: int = 10,
    event_count: int = 20,
) -> Session:
    return Session(
        provider="claude",
        session_id=f"sid-{year}-{month}-{day}-{hour}",
        cwd=Path(cwd),
        started_at=datetime(year, month, day, hour, 0, tzinfo=LOCAL_TZ),
        event_count=event_count,
        source_path=Path("/tmp/fake.jsonl"),
    )


def _evt(skill: str, day: int = 6, hour: int = 12, month: int = 4) -> SkillEvent:
    return SkillEvent(
        timestamp=datetime(2026, month, day, hour, 0, tzinfo=LOCAL_TZ),
        skill=skill,
        event="completed",
    )


# ---------- _hour_to_bucket parameterized ----------


def test_hour_to_bucket_default_granularity_6() -> None:
    assert _hour_to_bucket(0) == "0-6"
    assert _hour_to_bucket(5) == "0-6"
    assert _hour_to_bucket(6) == "6-12"
    assert _hour_to_bucket(23) == "18-24"


def test_hour_to_bucket_granularity_2() -> None:
    assert _hour_to_bucket(0, 2) == "0-2"
    assert _hour_to_bucket(1, 2) == "0-2"
    assert _hour_to_bucket(22, 2) == "22-24"
    assert _hour_to_bucket(23, 2) == "22-24"


def test_hour_to_bucket_invalid_granularity_falls_back_to_6() -> None:
    # Not in allowed list → falls back to 6
    assert _hour_to_bucket(10, 5) == "6-12"


# ---------- compute_habit_weekday_distribution ----------


def test_weekday_distribution_groups_by_weekday() -> None:
    # April 6 2026 is Monday (weekday=0), April 7 is Tuesday
    sessions = [
        _session(day=6, event_count=20),
        _session(day=6, event_count=10),
        _session(day=7, event_count=30),
    ]
    result = compute_habit_weekday_distribution(sessions, [])
    assert len(result) == 7
    monday = next(r for r in result if r.weekday == 0)
    tuesday = next(r for r in result if r.weekday == 1)
    assert monday.session_count == 2
    assert tuesday.session_count == 1
    assert monday.avg_event_count == 15.0
    assert tuesday.avg_event_count == 30.0


def test_weekday_distribution_vibe_rate() -> None:
    # 1 short, 1 long → vibe_rate = 0.5 on Monday
    sessions = [
        _session(day=6, event_count=2),   # short
        _session(day=6, event_count=50),  # long
    ]
    result = compute_habit_weekday_distribution(sessions, [])
    monday = next(r for r in result if r.weekday == 0)
    assert monday.vibe_rate == 0.5


def test_weekday_distribution_empty_sessions_returns_all_zero() -> None:
    result = compute_habit_weekday_distribution([], [])
    assert len(result) == 7
    assert all(r.session_count == 0 for r in result)
    assert all(r.vibe_rate == 0.0 for r in result)


# ---------- compute_habit_timeslot_distribution ----------


def test_timeslot_distribution_2h_granularity() -> None:
    sessions = [
        _session(hour=0, event_count=10),
        _session(hour=1, event_count=20),
        _session(hour=22, event_count=5),
    ]
    result = compute_habit_timeslot_distribution(sessions)
    # 24h / 2h = 12 buckets
    assert len(result) == 12
    early = next(r for r in result if r.label == "0-2")
    late = next(r for r in result if r.label == "22-24")
    assert early.session_count == 2
    assert early.avg_event_count == 15.0
    assert late.session_count == 1
    assert late.avg_event_count == 5.0


def test_timeslot_distribution_skips_session_without_started_at() -> None:
    s = Session(
        provider="claude",
        session_id="no-time",
        cwd=Path("/foo"),
        started_at=None,
        event_count=10,
        source_path=Path("/tmp/fake.jsonl"),
    )
    result = compute_habit_timeslot_distribution([s])
    assert all(r.session_count == 0 for r in result)


# ---------- compute_habit_session_bimodal ----------


def test_session_bimodal_returns_split_ratio_and_long_avg() -> None:
    sessions = [
        _session(event_count=2),   # short
        _session(event_count=3),   # short
        _session(event_count=20),  # long
        _session(event_count=40),  # long
    ]
    short_share, long_avg = compute_habit_session_bimodal(sessions)
    assert short_share == 0.5
    assert long_avg == 30.0


def test_session_bimodal_empty_returns_none_none() -> None:
    assert compute_habit_session_bimodal([]) == (None, None)


def test_session_bimodal_all_short_long_avg_is_none() -> None:
    sessions = [_session(event_count=2), _session(event_count=1)]
    short_share, long_avg = compute_habit_session_bimodal(sessions)
    assert short_share == 1.0
    assert long_avg is None


# ---------- compute_habit_project_switch_frequency ----------


def test_project_switch_median_returns_none_when_few_days() -> None:
    # Only 2 active days → below threshold of 5
    sessions = [
        _session(cwd="/a", day=6),
        _session(cwd="/b", day=7),
    ]
    assert compute_habit_project_switch_frequency(sessions) is None


def test_project_switch_median_per_day() -> None:
    # 5 days; days 6/7/8 see 2 distinct cwds; days 9/10 see 1 cwd each
    sessions = [
        _session(cwd="/a", day=6),
        _session(cwd="/b", day=6),
        _session(cwd="/a", day=7),
        _session(cwd="/b", day=7),
        _session(cwd="/c", day=8),
        _session(cwd="/d", day=8),
        _session(cwd="/a", day=9),
        _session(cwd="/a", day=10),
    ]
    # 5 days: [2, 2, 2, 1, 1] → median = 2
    assert compute_habit_project_switch_frequency(sessions) == 2


# ---------- compute_habit_ship_cadence ----------


def test_ship_cadence_median_days() -> None:
    # 3 ships across day 6, 8, 12 → gaps [2, 4] → median = 3
    events = [
        _evt("ship", day=6),
        _evt("ship", day=8),
        _evt("ship", day=12),
    ]
    result = compute_habit_ship_cadence(events)
    assert result == 3.0


def test_ship_cadence_returns_none_when_under_2_ships() -> None:
    assert compute_habit_ship_cadence([_evt("ship", day=6)]) is None
    assert compute_habit_ship_cadence([]) is None


# ---------- compute_habit_late_night_ship_rate (D1 — uses SkillEvent only) ----------


def test_late_night_ship_rate_matches_within_24h() -> None:
    # 3 late-night sessions on day 6, 7, 8 (22h)
    # Ships at day 6 23h, day 7 5h (next day from day 7? — within 24h), no day 9 ship
    sessions = [
        _session(day=6, hour=22),
        _session(day=7, hour=22),
        _session(day=8, hour=22),
    ]
    events = [
        SkillEvent(
            timestamp=datetime(2026, 4, 6, 23, 0, tzinfo=LOCAL_TZ),
            skill="ship",
            event="completed",
        ),
        SkillEvent(
            timestamp=datetime(2026, 4, 8, 5, 0, tzinfo=LOCAL_TZ),  # within 24h of day 7 22h
            skill="ship",
            event="completed",
        ),
    ]
    rate = compute_habit_late_night_ship_rate(sessions, events)
    # day 6 → matched, day 7 → matched, day 8 → not matched
    assert rate == 2 / 3


def test_late_night_ship_rate_returns_none_when_few_sessions() -> None:
    sessions = [_session(day=6, hour=22), _session(day=7, hour=22)]
    events = [_evt("ship", day=6, hour=23)]
    assert compute_habit_late_night_ship_rate(sessions, events) is None


def test_late_night_ship_rate_returns_none_when_no_ships() -> None:
    sessions = [
        _session(day=6, hour=22),
        _session(day=7, hour=22),
        _session(day=8, hour=22),
    ]
    assert compute_habit_late_night_ship_rate(sessions, []) is None


# ---------- compute_habit_overplanning_rate ----------


def test_overplanning_rate_high_when_no_subsequent_ships() -> None:
    # 3 office-hours, 0 ships
    events = [
        _evt("office-hours", day=6),
        _evt("office-hours", day=7),
        _evt("office-hours", day=8),
    ]
    assert compute_habit_overplanning_rate(events) == 1.0


def test_overplanning_rate_zero_when_ship_always_follows() -> None:
    events = [
        _evt("office-hours", day=6),
        _evt("office-hours", day=7),
        _evt("office-hours", day=8),
        _evt("ship", day=9),  # one ship within 7d covers all 3 office-hours
    ]
    assert compute_habit_overplanning_rate(events) == 0.0


def test_overplanning_rate_returns_none_when_few_oh_sessions() -> None:
    assert compute_habit_overplanning_rate([]) is None
    assert compute_habit_overplanning_rate(
        [_evt("office-hours", day=6), _evt("office-hours", day=7)]
    ) is None


# ---------- compute_habit_skill_repetition ----------


def test_skill_repetition_returns_top_name_and_share() -> None:
    events = [
        _evt("ship"),
        _evt("ship"),
        _evt("ship"),
        _evt("review"),
        _evt("office-hours"),
    ]
    top, share = compute_habit_skill_repetition(events)
    assert top == "ship"
    assert share == 0.6


def test_skill_repetition_returns_none_under_5_invocations() -> None:
    events = [_evt("ship"), _evt("review")]
    assert compute_habit_skill_repetition(events) == (None, None)


# ---------- collect_habits_data orchestrator ----------


def test_collect_habits_data_returns_populated_input() -> None:
    """End-to-end with mocked session iterator and NullSource."""
    sessions = [
        _session(cwd="/proj-a", day=6, hour=10, event_count=20),
        _session(cwd="/proj-a", day=7, hour=14, event_count=30),
    ]
    start = datetime(2026, 4, 1, tzinfo=LOCAL_TZ)
    end = datetime(2026, 4, 30, tzinfo=LOCAL_TZ)

    with (
        patch("aifd.insights.habits.summarize_activity") as mock_sa,
        patch("aifd.insights.habits._iter_sessions_in", return_value=iter(sessions)),
    ):
        mock_sa.return_value = None  # only existence matters
        result = collect_habits_data(start, end, source=NullSource())

    assert isinstance(result, HabitsInput)
    assert result.period_start == start
    assert result.period_end == end
    assert len(result.weekday_stats) == 7
    assert len(result.timeslot_stats) == 12


def test_collect_habits_data_resilient_to_summarize_failure() -> None:
    """If summarize_activity raises, we get empty sessions but no crash."""
    start = datetime(2026, 4, 1, tzinfo=LOCAL_TZ)
    end = datetime(2026, 4, 30, tzinfo=LOCAL_TZ)

    with patch(
        "aifd.insights.habits.summarize_activity",
        side_effect=RuntimeError("provider blew up"),
    ):
        result = collect_habits_data(start, end, source=NullSource())

    assert isinstance(result, HabitsInput)
    assert result.short_session_share is None  # no sessions → bimodal returns None
