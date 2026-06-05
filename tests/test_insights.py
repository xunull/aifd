"""Tests for aifd.insights — activity report aggregation + diff + projection."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aifd.insights import (
    ActivityReport,
    Delta,
    ProjectionEstimate,
    compute_diff,
    compute_projection,
    previous_window,
    summarize_activity,
    window_for_monthly,
    window_for_today,
    window_for_weekly,
)
from aifd.models import Session, SkillInvocation, TokenUsage


class _FakeProvider:
    """In-test Provider implementation that yields hand-rolled fixtures.

    Bypasses jsonl/SQLite IO entirely — tests assemble the exact stream
    of Session / TokenUsage / SkillInvocation they want to assert against.
    """

    def __init__(
        self,
        name: str,
        sessions: list[Session],
        token_usages: list[TokenUsage],
        skill_invocations: list[SkillInvocation],
    ) -> None:
        self.name = name
        self._sessions = sessions
        self._token_usages = token_usages
        self._skill_invocations = skill_invocations

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        return [s for s in self._sessions if s.cwd == cwd]

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        if scope is None:
            return self._skill_invocations
        return [i for i in self._skill_invocations if i.cwd == scope]

    def list_token_usage(
        self, scope: Path | None = None
    ) -> Iterable[TokenUsage]:
        if scope is None:
            return self._token_usages
        return [u for u in self._token_usages if u.cwd == scope]

    def iter_all_sessions(self) -> Iterable[Session]:
        return self._sessions


# ---------- fixtures ----------


def _ts(hours: int, day: int = 5) -> datetime:
    """Build a deterministic tz-aware datetime in June 2026 for fixtures.

    `hours >= 24` rolls forward into the next day so tests can write
    `_ts(24)` to mean "end of day" without manually picking the next day.
    """
    base = datetime(2026, 6, day, 0, 0, 0, tzinfo=UTC)
    return base + timedelta(hours=hours)


def _session(
    sid: str,
    ts: datetime,
    *,
    title: str | None = "topic-default",
    provider: str = "claude",
    cwd_name: str = "p",
) -> Session:
    return Session(
        provider=provider,
        session_id=sid,
        cwd=Path(f"/x/{cwd_name}"),
        started_at=ts,
        event_count=10,
        source_path=Path(f"/x/{sid}.jsonl"),
        title=title,
    )


def _usage(
    sid: str,
    ts: datetime,
    *,
    provider: str = "claude",
    cost_input: int = 1000,
    cost_output: int = 500,
    model: str = "claude-opus-4-7",
) -> TokenUsage:
    return TokenUsage(
        provider=provider,
        session_id=sid,
        cwd=Path("/x/p"),
        ts=ts,
        model=model,
        input_tokens=cost_input,
        output_tokens=cost_output,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        reasoning_output_tokens=0,
        source_path=Path(f"/x/{sid}.jsonl"),
    )


def _skill(name: str, ts: datetime, *, provider: str = "claude") -> SkillInvocation:
    return SkillInvocation(
        skill_name=name,
        provider=provider,
        cwd=Path("/x/p"),
        ts=ts,
        source_path=Path("/x/source.jsonl"),
        is_gstack=False,
    )


# ---------- summarize_activity ----------


def test_summarize_activity_counts_active_sessions_not_just_started_in_window() -> None:
    """A session started BEFORE the window but still emitting tokens IN the
    window counts as 'active in the window' — matches user intuition that
    work continuing from yesterday is still today's activity.
    """
    window_start = _ts(0)  # today 00:00
    window_end = _ts(12)   # today noon
    yesterday = _ts(20, day=4)
    in_window = _ts(8)
    provider = _FakeProvider(
        name="claude",
        sessions=[_session("s1", yesterday, title="ongoing conv")],
        token_usages=[
            _usage("s1", yesterday),     # outside window
            _usage("s1", in_window),     # inside window
        ],
        skill_invocations=[],
    )
    report = summarize_activity(window_start, window_end, providers=[provider])
    assert report.session_count == 1
    assert report.cost_usd > 0  # only the in-window usage counts
    # Topic surfaces from the session's title
    assert ("ongoing conv", 1) in report.top_topics


def test_summarize_activity_empty_window() -> None:
    """No sessions / tokens / skills in window → all-zero report, no crash."""
    window_start = _ts(0)
    window_end = _ts(1)
    provider = _FakeProvider(
        name="claude",
        sessions=[_session("s1", _ts(20, day=4))],  # outside window
        token_usages=[_usage("s1", _ts(20, day=4))],  # outside window
        skill_invocations=[_skill("k1", _ts(20, day=4))],  # outside window
    )
    report = summarize_activity(window_start, window_end, providers=[provider])
    assert report.session_count == 0
    assert report.cost_usd == 0
    assert report.total_tokens == 0
    assert report.top_skills == []
    assert report.top_topics == []
    assert report.by_provider == []


def test_summarize_activity_groups_by_provider_sorted_by_cost_desc() -> None:
    in_window = _ts(8)
    claude_p = _FakeProvider(
        name="claude",
        sessions=[_session("c1", in_window, provider="claude")],
        token_usages=[_usage("c1", in_window, provider="claude", cost_input=10000)],
        skill_invocations=[],
    )
    codex_p = _FakeProvider(
        name="codex",
        sessions=[_session("x1", in_window, provider="codex")],
        token_usages=[
            _usage("x1", in_window, provider="codex", cost_input=100, model="gpt-5-codex"),
        ],
        skill_invocations=[],
    )
    report = summarize_activity(
        _ts(0), _ts(12), providers=[codex_p, claude_p]
    )
    assert len(report.by_provider) == 2
    # Higher cost first
    assert report.by_provider[0].provider == "claude"
    assert report.by_provider[1].provider == "codex"


def test_summarize_activity_top_skills_limited_and_sorted() -> None:
    in_window = _ts(8)
    invs = [_skill(f"skill-{i % 7}", in_window) for i in range(20)]
    provider = _FakeProvider(
        name="claude", sessions=[], token_usages=[], skill_invocations=invs
    )
    report = summarize_activity(
        _ts(0), _ts(12), providers=[provider]
    )
    # Capped at TOP_SKILLS_LIMIT (5), sorted by count DESC
    assert len(report.top_skills) == 5
    counts = [c for _name, c in report.top_skills]
    assert counts == sorted(counts, reverse=True)


def test_summarize_activity_topic_falls_back_to_cwd_when_title_missing() -> None:
    in_window = _ts(8)
    provider = _FakeProvider(
        name="claude",
        sessions=[_session("s1", in_window, title=None, cwd_name="my-proj")],
        token_usages=[_usage("s1", in_window)],
        skill_invocations=[],
    )
    report = summarize_activity(_ts(0), _ts(12), providers=[provider])
    assert report.top_topics == [("my-proj", 1)]


# ---------- compute_diff ----------


def test_compute_diff_with_prior() -> None:
    curr = ActivityReport(
        period_start=_ts(0),
        period_end=_ts(24),
        session_count=5,
        cost_usd=10.0,
        total_tokens=1000,
    )
    prev = ActivityReport(
        period_start=_ts(0, day=4),
        period_end=_ts(24, day=4),
        session_count=3,
        cost_usd=4.0,
        total_tokens=600,
    )
    d = compute_diff(curr, prev)
    assert d.has_prior is True
    assert d.cost_delta == 6.0
    assert d.session_delta == 2
    assert d.token_delta == 400


def test_compute_diff_no_prior_returns_has_prior_false() -> None:
    curr = ActivityReport(_ts(0), _ts(24), 5, 10.0, 1000)
    prev = ActivityReport(_ts(0, day=4), _ts(24, day=4), 0, 0.0, 0)
    d = compute_diff(curr, prev)
    assert d.has_prior is False
    # Deltas still computed, but renderer should suppress them
    assert d.cost_delta == 10.0


# ---------- compute_projection ----------


def test_compute_projection_div_by_zero_guard() -> None:
    """Period elapsed = 0 seconds → enough_data False, no division crash."""
    report = ActivityReport(_ts(0), _ts(0), 0, 0.0, 0)
    proj = compute_projection(report, now=_ts(0))
    assert proj.enough_data is False
    assert proj.monthly_usd == 0
    assert proj.hours_elapsed == 0


def test_compute_projection_too_short_window_returns_not_enough_data() -> None:
    """< 1 hour of elapsed window → enough_data False."""
    report = ActivityReport(_ts(0), _ts(24), 1, 5.0, 100)
    # Only 30 minutes have elapsed
    half_hour = _ts(0) + timedelta(minutes=30)
    proj = compute_projection(report, now=half_hour)
    assert proj.enough_data is False


def test_compute_projection_monthly_extrapolation() -> None:
    """$1 / hour for 5h elapsed -> $720/month projection (1*24*30)."""
    report = ActivityReport(_ts(0), _ts(24), 1, 5.0, 100)
    five_hours = _ts(5)
    proj = compute_projection(report, now=five_hours)
    assert proj.enough_data is True
    # $5 over 5h = $1/hr → $720/month
    assert abs(proj.monthly_usd - 720.0) < 0.01


# ---------- window helpers ----------


def test_window_for_today_starts_at_local_midnight() -> None:
    now = _ts(14)
    start, end = window_for_today(now)
    assert start == _ts(0)
    assert end == now


def test_window_for_weekly_is_rolling_7d() -> None:
    now = _ts(12)
    start, end = window_for_weekly(now)
    assert (end - start).days == 7


def test_window_for_monthly_starts_at_first_of_month() -> None:
    now = _ts(14)
    start, end = window_for_monthly(now)
    assert start == datetime(2026, 6, 1, tzinfo=UTC)
    assert end == now


def test_previous_window_shifts_by_span() -> None:
    start = _ts(0)
    end = _ts(24)
    prev_start, prev_end = previous_window(start, end)
    assert prev_end == start
    assert (prev_end - prev_start) == (end - start)


# ---------- types exported ----------


def test_report_dataclass_is_frozen() -> None:
    """ActivityReport must stay immutable so downstream code can cache it."""
    r = ActivityReport(_ts(0), _ts(24), 1, 1.0, 1)
    try:
        r.session_count = 99  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ActivityReport should be frozen")


def test_delta_and_projection_dataclasses_frozen() -> None:
    d = Delta(has_prior=True, cost_delta=1.0, session_delta=1, token_delta=10)
    p = ProjectionEstimate(enough_data=True, monthly_usd=100.0, hours_elapsed=5.0)
    for obj, field in ((d, "cost_delta"), (p, "monthly_usd")):
        try:
            setattr(obj, field, 999)
        except Exception:
            continue
        raise AssertionError(f"{type(obj).__name__} should be frozen")
