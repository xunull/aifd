"""Tests for 9 compute_* reflection dimensions (T4)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from aifd.insights.activity import ActivityReport, ProviderActivity
from aifd.insights.reflection import (
    ReflectionInput,
    collect_reflection_data,
    compute_compliance_ratio,
    compute_cost_trend_ratio,
    compute_plan_then_ship_ratio,
    compute_project_focus,
    compute_skill_diversity_ratio,
    compute_timing_distribution,
    compute_vibe_coding_score,
    compute_wins,
)
from aifd.insights.reflection_source import (
    NullSource,
    QuestionLogEntry,
    SkillEvent,
)
from aifd.models import Session


def _session(
    cwd: str = "/foo",
    hour: int = 10,
    event_count: int = 20,
    day: int = 5,
) -> Session:
    # Construct as local-tz so astimezone() in compute_timing is a no-op
    # (timing bucketing operates on local hour by design).
    local_tz = datetime.now().astimezone().tzinfo
    return Session(
        provider="claude",
        session_id=f"sid-{hour}-{day}",
        cwd=Path(cwd),
        started_at=datetime(2026, 6, day, hour, 0, tzinfo=local_tz),
        event_count=event_count,
        source_path=Path("/tmp/fake.jsonl"),
    )


def _qe(
    matched: bool = True, day: int = 5,
) -> QuestionLogEntry:
    return QuestionLogEntry(
        timestamp=datetime(2026, 6, day, 10, 0, tzinfo=UTC),
        skill="office-hours",
        question_id="q1",
        user_choice="A",
        recommended="A" if matched else "B",
    )


def _ev(
    skill: str, event: str = "completed",
    day: int = 5, outcome: str | None = None,
) -> SkillEvent:
    return SkillEvent(
        timestamp=datetime(2026, 6, day, 10, 0, tzinfo=UTC),
        skill=skill,
        event=event,
        outcome=outcome,
    )


# ---------- compute_compliance_ratio ----------


def test_compliance_all_matched() -> None:
    data = compute_compliance_ratio([_qe(True), _qe(True), _qe(True)])
    assert data is not None
    assert data.ratio == 1.0
    assert data.total_questions == 3
    assert data.matched_count == 3


def test_compliance_none_matched() -> None:
    data = compute_compliance_ratio([_qe(False), _qe(False)])
    assert data is not None
    assert data.ratio == 0.0


def test_compliance_mixed() -> None:
    data = compute_compliance_ratio([_qe(True), _qe(False), _qe(True), _qe(False)])
    assert data is not None
    assert data.ratio == 0.5


def test_compliance_empty_returns_none() -> None:
    assert compute_compliance_ratio([]) is None


def test_compliance_only_unknown_returns_none() -> None:
    e = QuestionLogEntry(
        timestamp=datetime(2026, 6, 5, tzinfo=UTC),
        skill="x", question_id="q1",
        user_choice=None, recommended="A",
    )
    assert compute_compliance_ratio([e]) is None


# ---------- compute_skill_diversity_ratio ----------


def test_diversity_all_unique() -> None:
    events = [_ev("a"), _ev("b"), _ev("c")]
    assert compute_skill_diversity_ratio(events) == 1.0


def test_diversity_one_skill() -> None:
    events = [_ev("a"), _ev("a"), _ev("a")]
    assert compute_skill_diversity_ratio(events) == 1 / 3


def test_diversity_empty_returns_none() -> None:
    assert compute_skill_diversity_ratio([]) is None


# ---------- compute_cost_trend_ratio ----------


def _report(cost: float, sessions: int = 5) -> ActivityReport:
    return ActivityReport(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 7, tzinfo=UTC),
        session_count=sessions,
        cost_usd=cost,
        total_tokens=10000,
        by_provider=[
            ProviderActivity(
                provider="claude", sessions=sessions,
                cost_usd=cost, total_tokens=10000,
            ),
        ],
        top_skills=[], top_topics=[],
    )


def test_cost_trend_up_returns_positive_ratio() -> None:
    this = _report(100.0)
    prev = _report(50.0)
    assert compute_cost_trend_ratio(this, prev) == 1.0  # 100% increase


def test_cost_trend_down_returns_negative_ratio() -> None:
    this = _report(50.0)
    prev = _report(100.0)
    assert compute_cost_trend_ratio(this, prev) == -0.5


def test_cost_trend_no_prev_returns_none() -> None:
    this = _report(100.0)
    assert compute_cost_trend_ratio(this, None) is None


def test_cost_trend_prev_zero_returns_none() -> None:
    """No div by zero."""
    this = _report(100.0)
    prev = _report(0.0, sessions=0)
    assert compute_cost_trend_ratio(this, prev) is None


# ---------- compute_timing_distribution ----------


def test_timing_distribution_4_buckets() -> None:
    sessions = [
        _session(hour=2, event_count=5),    # 0-6
        _session(hour=8, event_count=30),   # 6-12
        _session(hour=8, event_count=20),   # 6-12
        _session(hour=14, event_count=50),  # 12-18
        _session(hour=22, event_count=10),  # 18-24
    ]
    buckets = compute_timing_distribution(sessions)
    assert len(buckets) == 4
    by_label = {b.label: b for b in buckets}
    assert by_label["0-6"].session_count == 1
    assert by_label["6-12"].session_count == 2
    assert by_label["6-12"].avg_message_count == 25.0
    assert by_label["12-18"].session_count == 1
    assert by_label["18-24"].session_count == 1


def test_timing_empty_sessions_zero_buckets() -> None:
    buckets = compute_timing_distribution([])
    for b in buckets:
        assert b.session_count == 0
        assert b.avg_message_count == 0.0


# ---------- compute_project_focus ----------


def test_project_focus_returns_basename_not_path() -> None:
    sessions = [
        _session(cwd="/Users/quincy/projects/aifd"),
        _session(cwd="/Users/quincy/projects/aifd"),
        _session(cwd="/Users/quincy/projects/aifd"),
        _session(cwd="/Users/quincy/projects/other"),
    ]
    top, share = compute_project_focus(sessions)
    assert top == "aifd"  # basename only, no /Users/ leak
    assert share == 0.75


def test_project_focus_empty_returns_none() -> None:
    top, share = compute_project_focus([])
    assert top is None
    assert share is None


# ---------- compute_plan_then_ship_ratio ----------


def test_plan_then_ship_full_match() -> None:
    events = [
        _ev("plan-eng-review", day=4),
        _ev("ship", day=5),
        _ev("plan-eng-review", day=6),
        _ev("ship", day=7),
    ]
    assert compute_plan_then_ship_ratio(events) == 1.0


def test_plan_then_ship_no_plan() -> None:
    events = [_ev("ship", day=5), _ev("ship", day=6)]
    assert compute_plan_then_ship_ratio(events) == 0.0


def test_plan_then_ship_no_ships_returns_none() -> None:
    events = [_ev("plan-eng-review", day=5)]
    assert compute_plan_then_ship_ratio(events) is None


def test_plan_then_ship_plan_too_old() -> None:
    events = [
        _ev("plan-eng-review", day=1),    # too old
        _ev("ship", day=15),               # > 7 days later
    ]
    assert compute_plan_then_ship_ratio(events) == 0.0


# ---------- compute_vibe_coding_score ----------


def test_vibe_coding_high() -> None:
    """ship right after a 3-msg session = vibe."""
    sessions = [_session(hour=10, event_count=3, day=5)]
    events = [_ev("ship", day=5)]
    score = compute_vibe_coding_score(sessions, events)
    assert score == 1.0


def test_vibe_coding_low() -> None:
    """ship after a deep 30-msg session = not vibe."""
    sessions = [_session(hour=10, event_count=30, day=5)]
    events = [_ev("ship", day=5)]
    score = compute_vibe_coding_score(sessions, events)
    assert score == 0.0


def test_vibe_no_ships_returns_none() -> None:
    sessions = [_session(event_count=20, day=5)]
    events: list[SkillEvent] = []
    assert compute_vibe_coding_score(sessions, events) is None


# ---------- compute_wins ----------


def test_wins_top_3_clean() -> None:
    events = [
        _ev("ship", day=1, outcome="clean"),
        _ev("ship", day=2, outcome="clean"),
        _ev("plan-eng-review", day=3, outcome="clean"),
        _ev("ship", day=4, outcome="clean"),  # most recent
    ]
    wins = compute_wins(events)
    assert len(wins) == 3
    assert wins[0].date == "2026-06-04"
    assert wins[0].label == "ship"


def test_wins_skip_failed_outcomes() -> None:
    events = [
        _ev("ship", day=1, outcome="clean"),
        _ev("ship", day=2, outcome="failed"),  # skipped
    ]
    wins = compute_wins(events)
    assert len(wins) == 1


def test_wins_empty() -> None:
    wins = compute_wins([])
    assert wins == []


# ---------- collect_reflection_data orchestrator ----------


def test_collect_reflection_data_with_null_source(
) -> None:
    """When source has no data, dimensions that depend on it return None."""
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 7, tzinfo=UTC)
    with patch("aifd.insights.reflection.summarize_activity") as fake_act:
        fake_act.return_value = _report(50.0)
        input_data = collect_reflection_data(
            start, end, source=NullSource(),
        )
    assert isinstance(input_data, ReflectionInput)
    assert input_data.activity is not None
    assert input_data.compliance is None
    assert input_data.skill_diversity_ratio is None
    assert input_data.plan_then_ship_ratio is None
