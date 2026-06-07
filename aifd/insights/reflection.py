"""Meta-cognitive reflection data computation for v0.8.

Computes 9 reflection dimensions from existing aifd activity data + the
gstack ReflectionDataSource (D3). Pure-python; no LLM call here — that
lives in llm_client.py + cli/ai/reflect.py.

Each compute_* function returns either a value or None. None means
"insufficient data for this dimension"; the prompt template surfaces
that as "(no data)" so the LLM doesn't hallucinate.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from aifd.insights.activity import ActivityReport, summarize_activity
from aifd.insights.reflection_source import (
    QuestionLogEntry,
    ReflectionDataSource,
    SkillEvent,
    default_source,
)
from aifd.models import Session

logger = logging.getLogger("aifd.insights.reflection")


# ---------- ReflectionInput dataclass (LLM prompt feed) ----------


@dataclass(frozen=True)
class ComplianceData:
    """How often did the user click the AI's `recommended` option."""

    total_questions: int
    matched_count: int
    ratio: float          # 0.0-1.0


@dataclass(frozen=True)
class TimingBucket:
    """Aggregate stats for one time-of-day bucket."""

    label: str            # "0-6", "6-12", "12-18", "18-24"
    session_count: int
    avg_message_count: float


@dataclass(frozen=True)
class WinSummary:
    """One notable outcome the LLM should highlight."""

    label: str            # short human description
    date: str             # ISO date


@dataclass(frozen=True)
class ReflectionInput:
    """All 9 dimensions packaged for prompt rendering.

    None on any dimension = "data unavailable for this period". The prompt
    renderer translates to `(no data)`; the LLM is instructed to skip that
    aspect rather than fabricate.
    """

    period_start: datetime
    period_end: datetime
    activity: ActivityReport | None = None
    compliance: ComplianceData | None = None
    skill_diversity_ratio: float | None = None
    cost_trend_ratio: float | None = None
    timing_buckets: list[TimingBucket] = field(default_factory=list)
    top_project: str | None = None
    top_project_share: float | None = None
    plan_then_ship_ratio: float | None = None
    vibe_coding_score: float | None = None
    wins: list[WinSummary] = field(default_factory=list)
    include_questions: bool = False


# ---------- 9 compute_* functions ----------


def compute_compliance_ratio(
    entries: Iterable[QuestionLogEntry],
) -> ComplianceData | None:
    """Fraction of questions where user_choice == recommended."""
    total = 0
    matched = 0
    for e in entries:
        m = e.user_matched_recommendation
        if m is None:
            continue
        total += 1
        if m:
            matched += 1
    if total == 0:
        return None
    return ComplianceData(
        total_questions=total,
        matched_count=matched,
        ratio=matched / total,
    )


def compute_skill_diversity_ratio(
    events: Iterable[SkillEvent],
) -> float | None:
    """distinct_skills / total_invocations. 1.0 = every call a new skill;
    0.05 = monocrop."""
    skills: list[str] = []
    for e in events:
        if e.event in ("completed", "started"):
            skills.append(e.skill)
    if not skills:
        return None
    return len(set(skills)) / len(skills)


def compute_cost_trend_ratio(
    this_period: ActivityReport,
    prev_period: ActivityReport | None,
) -> float | None:
    """(this - prev) / prev. Returns:
    - None if prev period is missing or had zero cost
    - positive ratio if cost went up
    - negative if cost dropped
    """
    if prev_period is None or prev_period.cost_usd <= 0:
        return None
    return (this_period.cost_usd - prev_period.cost_usd) / prev_period.cost_usd


def compute_timing_distribution(
    sessions: Iterable[Session],
    granularity: int = 6,
) -> list[TimingBucket]:
    """Bucket sessions by start-hour-of-day (LOCAL tz).

    granularity=6  → 4 buckets, used by `aifd ai reflect`
    granularity=2  → 12 buckets, used by `aifd ai habits`
    """
    buckets: dict[str, list[int]] = {
        f"{h}-{h + granularity}": []
        for h in range(0, 24, granularity)
    }
    for s in sessions:
        if s.started_at is None:
            continue
        # Use astimezone() to get local tz, then take .hour
        try:
            hour = s.started_at.astimezone().hour
        except (ValueError, OverflowError):
            continue
        label = _hour_to_bucket(hour, granularity)
        buckets[label].append(s.event_count or 0)

    return [
        TimingBucket(
            label=label,
            session_count=len(msg_counts),
            avg_message_count=(
                sum(msg_counts) / len(msg_counts) if msg_counts else 0.0
            ),
        )
        for label, msg_counts in buckets.items()
    ]


def _hour_to_bucket(hour: int, granularity: int = 6) -> str:
    """Delegates to habits._hour_to_bucket — single implementation."""
    from aifd.insights.habits import _hour_to_bucket as _htb
    return _htb(hour, granularity)


def compute_project_focus(
    sessions: Iterable[Session],
) -> tuple[str | None, float | None]:
    """Top-project basename + its share of all sessions.

    Privacy: returns BASENAME of cwd only, never absolute path (D2 invariant).
    None when there are no sessions or no project info.
    """
    cwd_counts: Counter[str] = Counter()
    total = 0
    for s in sessions:
        if not s.cwd:
            continue
        # Get basename only — never leak full path
        basename = s.cwd.name or str(s.cwd)
        cwd_counts[basename] += 1
        total += 1
    if total == 0:
        return None, None
    top_basename, top_count = cwd_counts.most_common(1)[0]
    return top_basename, top_count / total


def compute_plan_then_ship_ratio(
    events: Iterable[SkillEvent],
    plan_to_ship_window: timedelta = timedelta(days=7),
) -> float | None:
    """Fraction of ship events preceded by a plan-eng-review within window.

    Returns None if zero ships in the period.
    """
    ev_list = sorted(events, key=lambda e: e.timestamp)
    plan_times: list[datetime] = [
        e.timestamp for e in ev_list
        if e.event == "completed" and "plan-eng-review" in e.skill
    ]
    ship_events = [
        e for e in ev_list
        if e.event == "completed" and e.skill == "ship"
    ]
    if not ship_events:
        return None
    matched = 0
    for ship_ev in ship_events:
        # any prior plan within window
        cutoff = ship_ev.timestamp - plan_to_ship_window
        if any(cutoff <= pt <= ship_ev.timestamp for pt in plan_times):
            matched += 1
    return matched / len(ship_events)


def compute_vibe_coding_score(
    sessions: Iterable[Session],
    events: Iterable[SkillEvent],
    *,
    short_msg_threshold: int = 5,
) -> float | None:
    """Fraction of ships where the most-recent session before the ship had
    fewer than `short_msg_threshold` messages.

    Higher = more "1-shot vibe ship"; lower = deliberation before ship.
    None if no ships in window.
    """
    s_list = sorted(sessions, key=lambda s: s.started_at or datetime.min)
    ship_events = sorted(
        (e for e in events if e.event == "completed" and e.skill == "ship"),
        key=lambda e: e.timestamp,
    )
    if not ship_events:
        return None
    vibe_count = 0
    for ship_ev in ship_events:
        # Find the most recent session that started before this ship
        prior_session: Session | None = None
        for s in reversed(s_list):
            if s.started_at is None:
                continue
            if s.started_at <= ship_ev.timestamp:
                prior_session = s
                break
        if prior_session is None:
            continue
        if (prior_session.event_count or 0) < short_msg_threshold:
            vibe_count += 1
    return vibe_count / len(ship_events)


def compute_wins(
    events: Iterable[SkillEvent],
    limit: int = 3,
) -> list[WinSummary]:
    """Top wins = recent clean ship events + clean plan-eng-review entries."""
    candidates: list[WinSummary] = []
    for e in events:
        if e.event != "completed" or e.outcome != "clean":
            continue
        label = e.skill
        candidates.append(WinSummary(
            label=label,
            date=e.timestamp.date().isoformat(),
        ))
    # Most recent first
    candidates.sort(key=lambda w: w.date, reverse=True)
    return candidates[:limit]


# ---------- Orchestrator ----------


def collect_reflection_data(
    start: datetime,
    end: datetime,
    *,
    source: ReflectionDataSource | None = None,
    project_root: Path | None = None,
    include_questions: bool = False,
) -> ReflectionInput:
    """Gather all 9 dimensions for the [start, end) window.

    Pure function — no LLM call. Caller passes the result to render_prompt.
    Robust to missing data: each dimension independently None-safe.
    """
    src = source if source is not None else default_source(project_root)

    # Activity (v0.5 reuse) — wraps providers
    try:
        activity = summarize_activity(start, end)
    except Exception as exc:
        logger.warning("summarize_activity failed: %s", exc)
        activity = None

    # Previous-period activity (for cost trend) — same window length, shifted
    prev_activity: ActivityReport | None = None
    if activity is not None:
        window_len = end - start
        try:
            prev_activity = summarize_activity(start - window_len, start)
        except Exception as exc:
            logger.debug("prev period summarize failed: %s", exc)

    # Sessions list (for project focus + timing)
    sessions = (
        list(_iter_sessions_in(start, end)) if activity is not None else []
    )

    # Source-driven dimensions
    questions = list(src.question_log(start, end))
    skill_events = list(src.skill_events(start, end))

    compliance = compute_compliance_ratio(questions)
    skill_div = compute_skill_diversity_ratio(skill_events)
    cost_trend = (
        compute_cost_trend_ratio(activity, prev_activity)
        if activity is not None else None
    )
    timing = compute_timing_distribution(sessions)
    top_project, top_share = compute_project_focus(sessions)
    plan_then_ship = compute_plan_then_ship_ratio(skill_events)
    vibe = compute_vibe_coding_score(sessions, skill_events)
    wins = compute_wins(skill_events)

    return ReflectionInput(
        period_start=start,
        period_end=end,
        activity=activity,
        compliance=compliance,
        skill_diversity_ratio=skill_div,
        cost_trend_ratio=cost_trend,
        timing_buckets=timing,
        top_project=top_project,
        top_project_share=top_share,
        plan_then_ship_ratio=plan_then_ship,
        vibe_coding_score=vibe,
        wins=wins,
        include_questions=include_questions,
    )


def _iter_sessions_in(
    start: datetime, end: datetime,
) -> Iterable[Session]:
    """Stream sessions in the window from every provider.

    Reuses activity._iter_all_sessions which handles provider feature
    detection (`iter_all_sessions` attr-or-fallback).
    """
    from aifd.insights import activity as _act
    for p in _act.PROVIDERS:  # type: ignore[attr-defined]
        for s in _act._iter_all_sessions(p):
            if s.started_at is None:
                continue
            if start <= s.started_at < end:
                yield s
