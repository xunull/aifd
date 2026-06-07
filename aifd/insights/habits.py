"""Long-term AI behaviour analysis for `aifd ai habits` (v0.9).

Computes 8 dimensions over a 60-90 day window to identify recurring
behavioural patterns — the "who am I as an AI user" portrait rather than
the weekly retrospective that `aifd ai reflect` provides.

Locked decisions from /plan-eng-review:
  D1 — late_night_ship_rate: 22h+ session followed by a ship within 24h
        (SkillEvent only — no git integration until v0.10)
  D2 — weekday distribution: session_count + vibe_rate only (no cost_usd)
  D3 — HabitsInput is a standalone dataclass, not inherited from ReflectionInput
  D5 — _hour_to_bucket extracted here with granularity param; reflection.py
        imports and calls with granularity=6

Performance: collect_habits_data materialises sessions + skill_events once,
then passes the lists to all compute_habit_* functions.  90-day window ≈
900 sessions for a heavy user — well within memory budget.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aifd.insights.activity import summarize_activity
from aifd.insights.reflection import _iter_sessions_in
from aifd.insights.reflection_source import (
    ReflectionDataSource,
    SkillEvent,
    default_source,
)
from aifd.models import Session

logger = logging.getLogger("aifd.insights.habits")

_LATE_NIGHT_HOUR = 22   # sessions starting at or after this hour are "late night"
_VIBE_MSG_THRESHOLD = 5  # event_count < this → vibe-coding session


# ---------- exported from here so reflection.py can import ----------


def _hour_to_bucket(hour: int, granularity: int = 6) -> str:
    """Map a 0-23 hour to a bucket label of the given granularity.

    granularity=6  → "0-6", "6-12", "12-18", "18-24"   (reflect default)
    granularity=2  → "0-2", "2-4", ..., "22-24"         (habits fine-grain)
    """
    if granularity not in (1, 2, 3, 4, 6, 8, 12):
        granularity = 6
    slot = (hour // granularity) * granularity
    return f"{slot}-{slot + granularity}"


# ---------- HabitsInput dataclass ----------


@dataclass(frozen=True)
class WeekdayStats:
    """Session activity summary for one day of the week."""

    weekday: int           # 0=Monday … 6=Sunday
    session_count: int
    vibe_rate: float       # fraction of vibe-coding sessions (event_count < threshold)
    avg_event_count: float


@dataclass(frozen=True)
class TimeslotStats:
    """Session activity summary for a 2-hour time slot."""

    label: str             # e.g. "22-24"
    session_count: int
    avg_event_count: float


@dataclass(frozen=True)
class HabitsInput:
    """All 8 habit dimensions packaged for prompt rendering.

    None on any dimension = "data unavailable". Prompt renders as "(no data)";
    LLM is instructed to skip that dimension rather than fabricate.
    """

    period_start: datetime
    period_end: datetime

    # D2: weekday distribution (session_count + vibe_rate per weekday)
    weekday_stats: list[WeekdayStats] = field(default_factory=list)

    # time-slot distribution (2h granularity)
    timeslot_stats: list[TimeslotStats] = field(default_factory=list)

    # session bimodal: short / long split
    short_session_share: float | None = None   # share with event_count < threshold
    long_session_avg_events: float | None = None

    # project switching frequency
    project_switch_median: float | None = None  # median daily distinct-cwd count

    # ship cadence
    ship_interval_median_days: float | None = None

    # D1: late-night session → next-day ship rate
    late_night_ship_rate: float | None = None

    # overplanning: office-hours sessions without a subsequent ship
    overplanning_rate: float | None = None

    # skill repetition: top skill's share of total invocations
    top_skill_share: float | None = None
    top_skill_name: str | None = None


# ---------- 8 compute_habit_* functions ----------


def compute_habit_weekday_distribution(
    sessions: list[Session],
    events: list[SkillEvent],
) -> list[WeekdayStats]:
    """Sessions and vibe-coding rate broken down by day of week (Mon=0).

    `events` is accepted but not yet consulted — D2 locked the weekday
    metric to session-count + vibe_rate. Reserving the signature lets us
    add ship-weighted variants without breaking call sites.
    """
    _ = events  # explicitly mark reserved param
    by_weekday: dict[int, list[int]] = defaultdict(list)
    for s in sessions:
        if s.started_at is None:
            continue
        try:
            local = s.started_at.astimezone()
        except (ValueError, OverflowError):
            continue
        by_weekday[local.weekday()].append(s.event_count or 0)

    result: list[WeekdayStats] = []
    for wd in range(7):
        counts = by_weekday.get(wd, [])
        if not counts:
            result.append(WeekdayStats(
                weekday=wd,
                session_count=0,
                vibe_rate=0.0,
                avg_event_count=0.0,
            ))
            continue
        vibe = sum(1 for c in counts if c < _VIBE_MSG_THRESHOLD)
        result.append(WeekdayStats(
            weekday=wd,
            session_count=len(counts),
            vibe_rate=vibe / len(counts),
            avg_event_count=sum(counts) / len(counts),
        ))
    return result


def compute_habit_timeslot_distribution(
    sessions: list[Session],
) -> list[TimeslotStats]:
    """Session count + avg event_count in 2-hour slots (local tz)."""
    granularity = 2
    slots: dict[str, list[int]] = {
        f"{h}-{h + granularity}": []
        for h in range(0, 24, granularity)
    }
    for s in sessions:
        if s.started_at is None:
            continue
        try:
            hour = s.started_at.astimezone().hour
        except (ValueError, OverflowError):
            continue
        label = _hour_to_bucket(hour, granularity)
        slots[label].append(s.event_count or 0)

    return [
        TimeslotStats(
            label=label,
            session_count=len(counts),
            avg_event_count=(sum(counts) / len(counts) if counts else 0.0),
        )
        for label, counts in slots.items()
    ]


def compute_habit_session_bimodal(
    sessions: list[Session],
) -> tuple[float | None, float | None]:
    """Returns (short_session_share, long_session_avg_events).

    "Short" = event_count < _VIBE_MSG_THRESHOLD (quick checks).
    "Long"  = event_count >= _VIBE_MSG_THRESHOLD (deep work).
    Returns (None, None) if insufficient data.
    """
    counts = [s.event_count or 0 for s in sessions]
    if not counts:
        return None, None
    short = [c for c in counts if c < _VIBE_MSG_THRESHOLD]
    long_ = [c for c in counts if c >= _VIBE_MSG_THRESHOLD]
    short_share = len(short) / len(counts)
    long_avg = sum(long_) / len(long_) if long_ else None
    return short_share, long_avg


def compute_habit_project_switch_frequency(
    sessions: list[Session],
) -> float | None:
    """Median number of distinct projects (cwd basename) touched per active day.

    Returns None when fewer than 5 active days in the window.
    """
    by_date: dict[str, set[str]] = defaultdict(set)
    for s in sessions:
        if s.started_at is None or not s.cwd:
            continue
        try:
            date_key = s.started_at.astimezone().strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            continue
        basename = s.cwd.name or str(s.cwd)
        by_date[date_key].add(basename)

    if len(by_date) < 5:
        return None
    daily_counts = [len(projects) for projects in by_date.values()]
    return statistics.median(daily_counts)


def compute_habit_ship_cadence(
    events: list[SkillEvent],
) -> float | None:
    """Median days between consecutive ship events.

    Returns None when fewer than 2 ship events in the window.
    """
    ship_times = sorted(
        e.timestamp
        for e in events
        if e.event == "completed" and e.skill == "ship"
    )
    if len(ship_times) < 2:
        return None
    gaps_days = [
        (ship_times[i + 1] - ship_times[i]).total_seconds() / 86400
        for i in range(len(ship_times) - 1)
    ]
    return statistics.median(gaps_days)


def compute_habit_late_night_ship_rate(
    sessions: list[Session],
    events: list[SkillEvent],
    *,
    late_hour: int = _LATE_NIGHT_HOUR,
    ship_window_hours: int = 24,
) -> float | None:
    """Fraction of late-night sessions (>=late_hour) followed by a ship
    within ship_window_hours.

    D1 decision: uses SkillEvent ship data only — no git integration.
    Returns None when fewer than 3 late-night sessions.
    """
    ship_times = [
        e.timestamp
        for e in events
        if e.event == "completed" and e.skill == "ship"
    ]
    if not ship_times:
        return None

    late_sessions = [
        s for s in sessions
        if s.started_at is not None
        and _local_hour(s.started_at) >= late_hour
    ]
    if len(late_sessions) < 3:
        return None

    window = timedelta(hours=ship_window_hours)
    matched = 0
    for s in late_sessions:
        assert s.started_at is not None
        cutoff = s.started_at + window
        if any(s.started_at <= t <= cutoff for t in ship_times):
            matched += 1
    return matched / len(late_sessions)


def compute_habit_overplanning_rate(
    events: list[SkillEvent],
) -> float | None:
    """Fraction of office-hours sessions NOT followed by a ship within 7 days.

    Returns None when fewer than 3 office-hours sessions.
    """
    oh_times = sorted(
        e.timestamp
        for e in events
        if e.event in ("completed", "started") and "office-hours" in e.skill
    )
    if len(oh_times) < 3:
        return None

    ship_times = [
        e.timestamp
        for e in events
        if e.event == "completed" and e.skill == "ship"
    ]
    window = timedelta(days=7)
    unmatched = 0
    for ot in oh_times:
        cutoff = ot + window
        if not any(ot <= t <= cutoff for t in ship_times):
            unmatched += 1
    return unmatched / len(oh_times)


def compute_habit_skill_repetition(
    events: list[SkillEvent],
) -> tuple[str | None, float | None]:
    """Top-skill name + its share of total skill invocations.

    High share → monocrop; low share → broad explorer.
    Returns (None, None) when fewer than 5 invocations.
    """
    invocations = [
        e.skill for e in events
        if e.event in ("completed", "started")
    ]
    if len(invocations) < 5:
        return None, None
    counts: Counter[str] = Counter(invocations)
    top_skill, top_count = counts.most_common(1)[0]
    return top_skill, top_count / len(invocations)


# ---------- orchestrator ----------


def collect_habits_data(
    start: datetime,
    end: datetime,
    *,
    source: ReflectionDataSource | None = None,
    project_root: Path | None = None,
) -> HabitsInput:
    """Gather all 8 habit dimensions for the [start, end) window.

    Pure function — no LLM call. Sessions and SkillEvents are materialised
    once and passed to each compute_habit_* function.
    """
    src = source if source is not None else default_source(project_root)

    # Materialise once — never pass iterators to multiple consumers
    sessions: list[Session] = []
    try:
        summarize_activity(start, end)  # validates provider availability
        sessions = list(_iter_sessions_in(start, end))
    except Exception as exc:
        logger.warning("session collection failed: %s", exc)

    skill_events: list[SkillEvent] = list(src.skill_events(start, end))

    weekday_stats = compute_habit_weekday_distribution(sessions, skill_events)
    timeslot_stats = compute_habit_timeslot_distribution(sessions)
    short_share, long_avg = compute_habit_session_bimodal(sessions)
    switch_median = compute_habit_project_switch_frequency(sessions)
    ship_cadence = compute_habit_ship_cadence(skill_events)
    late_ship_rate = compute_habit_late_night_ship_rate(sessions, skill_events)
    overplan = compute_habit_overplanning_rate(skill_events)
    top_skill, top_share = compute_habit_skill_repetition(skill_events)

    return HabitsInput(
        period_start=start,
        period_end=end,
        weekday_stats=weekday_stats,
        timeslot_stats=timeslot_stats,
        short_session_share=short_share,
        long_session_avg_events=long_avg,
        project_switch_median=switch_median,
        ship_interval_median_days=ship_cadence,
        late_night_ship_rate=late_ship_rate,
        overplanning_rate=overplan,
        top_skill_share=top_share,
        top_skill_name=top_skill,
    )


# ---------- helpers ----------


def _local_hour(dt: datetime) -> int:
    try:
        return dt.astimezone().hour
    except (ValueError, OverflowError):
        return dt.hour
