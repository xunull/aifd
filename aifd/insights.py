"""Activity insights — backend for `aifd ai today` / `weekly` / `monthly` / `retro`.

Aggregates per-period summaries from the existing read layer:
- Session list (cwd, title, started_at)  — built in v0.2
- TokenUsage stream (cost + tokens)      — built in v0.4 (vault cost)
- SkillInvocation stream                 — built in v0.2

Pipeline:

    [start, end)
        │
        ▼
    each Provider.list_sessions / .list_token_usage / .list_skill_invocations
        │  filter by ts in [start, end)
        ▼
    ActivityReport
        ├── compute_diff(prev_report)  → Delta
        └── compute_projection(now)    → ProjectionEstimate

The report dataclass is intentionally flat + JSON-serializable so the same
shape can feed the rich-Table renderer, `--json` output, and (future) the
`aifd mcp serve` MCP tool that exposes activity to Claude.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from aifd.models import Session, SkillInvocation, TokenUsage
from aifd.providers.base import Provider
from aifd.providers.registry import PROVIDERS
from aifd.vault.cost import compute_event_cost

# Top-N caps so the report stays compact regardless of period span.
_TOP_SKILLS_LIMIT = 5
_TOP_TOPICS_LIMIT = 5


@dataclass(frozen=True)
class ProviderActivity:
    """Per-provider slice of an ActivityReport."""

    provider: str
    sessions: int
    cost_usd: float
    total_tokens: int


@dataclass(frozen=True)
class ActivityReport:
    """One window's worth of AI-tool activity summary.

    Attributes:
        period_start, period_end: half-open window [start, end) for which
            the report was computed. Always timezone-aware datetimes.
        session_count: total sessions that started within the window.
        cost_usd: USD spend from TokenUsage events whose ts ∈ window.
        total_tokens: sum of input + output + cache + reasoning tokens
            from those events.
        by_provider: list of per-provider slices, sorted by cost DESC.
        top_skills: list of (skill_name, count) tuples, top-N most-used.
        top_topics: list of (topic_text, count) tuples — drawn from
            Session.title (first user prompt's leading text). When two
            sessions share a title, they collapse into one row with
            count=2; usually count=1 since titles vary.
    """

    period_start: datetime
    period_end: datetime
    session_count: int
    cost_usd: float
    total_tokens: int
    by_provider: list[ProviderActivity] = field(default_factory=list)
    top_skills: list[tuple[str, int]] = field(default_factory=list)
    top_topics: list[tuple[str, int]] = field(default_factory=list)


@dataclass(frozen=True)
class Delta:
    """Difference between a current ActivityReport and a previous one.

    Each delta is current minus previous. `has_prior` is False when the
    previous window contained zero activity — the renderer uses this to
    show "no prior" instead of an apparent "+100% session count" lie.
    """

    has_prior: bool
    cost_delta: float
    session_delta: int
    token_delta: int


@dataclass(frozen=True)
class ProjectionEstimate:
    """Monthly cost forecast extrapolated from the current report's run rate.

    `enough_data` is False when the period elapsed is too short (< 1 hour
    of wall-clock) for a meaningful forecast — guards against div-by-zero
    AND against showing a wildly inflated number after one tiny session.
    """

    enough_data: bool
    monthly_usd: float
    hours_elapsed: float


# ---------- aggregation ----------


def summarize_activity(
    start: datetime,
    end: datetime,
    *,
    providers: Iterable[Provider] | None = None,
) -> ActivityReport:
    """Build an ActivityReport for the half-open window [start, end).

    Pulls from every registered Provider (Claude, Codex, …). Each provider's
    `list_sessions`, `list_token_usage`, `list_skill_invocations` is called
    with no scope filter (global), then filtered down to the time window
    here. This trades a small amount of overhead for a uniform per-window
    code path — providers don't need to know about time semantics.

    `providers=None` uses the module-level `PROVIDERS` registry resolved
    at CALL time (not def time) so tests can monkeypatch
    `aifd.insights.PROVIDERS` without re-importing.
    """
    if providers is None:
        providers = PROVIDERS
    # Phase 1: collect token usages in window. These are the canonical
    # "this happened" events — a session started yesterday but still
    # emitting tokens today counts as "today's activity".
    token_usages: list[TokenUsage] = []
    skill_invocations: list[SkillInvocation] = []
    for p in providers:
        for u in p.list_token_usage(scope=None):
            if u.ts is not None and start <= u.ts < end:
                token_usages.append(u)
        for inv in p.list_skill_invocations(scope=None):
            if inv.ts is not None and start <= inv.ts < end:
                skill_invocations.append(inv)

    # Distinct (provider, session_id) tuples are "sessions active in window".
    # Matches user intuition: 3 conversations had activity today, no matter
    # which day each conversation originally started on.
    active_session_keys: set[tuple[str, str]] = {
        (u.provider, u.session_id) for u in token_usages
    }

    # Phase 2: look up Session objects for the active IDs so we can surface
    # topics. Walks providers ONCE; cheap compared to the token scan.
    active_sessions: list[Session] = []
    for p in providers:
        for s in _iter_all_sessions(p):
            if (s.provider, s.session_id) in active_session_keys:
                active_sessions.append(s)

    cost = sum(compute_event_cost(u) for u in token_usages)
    total_tokens = sum(
        u.input_tokens
        + u.output_tokens
        + u.cache_creation_input_tokens
        + u.cache_read_input_tokens
        + u.reasoning_output_tokens
        for u in token_usages
    )

    by_provider = _slice_by_provider(active_session_keys, token_usages)

    skill_counter: Counter[str] = Counter(
        inv.skill_name for inv in skill_invocations
    )
    top_skills = skill_counter.most_common(_TOP_SKILLS_LIMIT)

    topic_counter: Counter[str] = Counter()
    for s in active_sessions:
        topic = _session_topic(s)
        if topic:
            topic_counter[topic] += 1
    top_topics = topic_counter.most_common(_TOP_TOPICS_LIMIT)

    return ActivityReport(
        period_start=start,
        period_end=end,
        session_count=len(active_session_keys),
        cost_usd=cost,
        total_tokens=total_tokens,
        by_provider=by_provider,
        top_skills=top_skills,
        top_topics=top_topics,
    )


def _iter_all_sessions(p: Provider) -> Iterable[Session]:
    """Walk every session a provider knows about, ignoring cwd scope.

    The Protocol contract is cwd-scoped — `list_sessions(cwd)` returns
    sessions whose recorded cwd equals that path. For a global retro we
    need every session, regardless of cwd. Claude + Codex both expose
    `iter_all_sessions`; third-party providers without it get excluded
    from the report (the protocol-level guarantee is preserved).
    """
    fn = getattr(p, "iter_all_sessions", None)
    if callable(fn):
        yield from fn()


def _slice_by_provider(
    active_session_keys: set[tuple[str, str]], token_usages: list[TokenUsage]
) -> list[ProviderActivity]:
    """Group session keys + token_usages by provider name; sort by cost DESC."""
    session_counts: Counter[str] = Counter(
        provider for provider, _sid in active_session_keys
    )
    cost_by_provider: dict[str, float] = {}
    tokens_by_provider: dict[str, int] = {}
    for u in token_usages:
        cost_by_provider[u.provider] = cost_by_provider.get(
            u.provider, 0.0
        ) + compute_event_cost(u)
        tokens_by_provider[u.provider] = tokens_by_provider.get(u.provider, 0) + (
            u.input_tokens
            + u.output_tokens
            + u.cache_creation_input_tokens
            + u.cache_read_input_tokens
            + u.reasoning_output_tokens
        )

    names = set(session_counts) | set(cost_by_provider)
    out = [
        ProviderActivity(
            provider=name,
            sessions=session_counts.get(name, 0),
            cost_usd=cost_by_provider.get(name, 0.0),
            total_tokens=tokens_by_provider.get(name, 0),
        )
        for name in names
    ]
    out.sort(key=lambda pa: (-pa.cost_usd, pa.provider))
    return out


def _session_topic(s: Session) -> str | None:
    """Extract the topic label for a session.

    Prefers `Session.title` (the v0.2 first-user-prompt extract). Falls
    back to the cwd basename when title is None so a topic still appears
    in the top-topics list. Returns None only when the cwd basename is
    also empty (vanishingly rare).
    """
    if s.title:
        return s.title.strip() or None
    name = s.cwd.name if s.cwd else None
    return name or None


# ---------- diff + projection ----------


def compute_diff(curr: ActivityReport, prev: ActivityReport) -> Delta:
    """Return Delta(curr - prev).

    A prev report with zero sessions and zero cost is treated as "no prior
    data" — the renderer should show "vs previous: no prior" rather than
    pretending the deltas are zero (which would be misleading for a brand
    new user with no history).
    """
    has_prior = prev.session_count > 0 or prev.cost_usd > 0
    return Delta(
        has_prior=has_prior,
        cost_delta=curr.cost_usd - prev.cost_usd,
        session_delta=curr.session_count - prev.session_count,
        token_delta=curr.total_tokens - prev.total_tokens,
    )


def compute_projection(
    report: ActivityReport, *, now: datetime | None = None
) -> ProjectionEstimate:
    """Project this report's cost run rate to a 30-day month.

    `enough_data=False` when the elapsed window is < 1 hour — too short
    to extrapolate honestly. Caller decides whether to render an "(too
    early)" placeholder or skip the line entirely.

    The window for elapsed time is `min(now, period_end) - period_start`
    so an `aifd ai today` run at 09:00 projects from 9 hours of data, not
    from the full 24-hour window. Projecting a full week or month uses
    the literal window since by then `now == period_end` will typically
    hold or the period is closed retroactively.
    """
    cutoff = min(now, report.period_end) if now is not None else report.period_end
    elapsed = cutoff - report.period_start
    hours_elapsed = elapsed.total_seconds() / 3600.0
    if hours_elapsed < 1.0:
        return ProjectionEstimate(
            enough_data=False, monthly_usd=0.0, hours_elapsed=hours_elapsed
        )
    rate_per_hour = report.cost_usd / hours_elapsed
    monthly = rate_per_hour * 24.0 * 30.0
    return ProjectionEstimate(
        enough_data=True,
        monthly_usd=monthly,
        hours_elapsed=hours_elapsed,
    )


# ---------- helpers for time-window arithmetic ----------


def window_for_today(now: datetime) -> tuple[datetime, datetime]:
    """Window [local_midnight, now) for `aifd ai today`."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight, now


def window_for_weekly(now: datetime) -> tuple[datetime, datetime]:
    """Rolling 7-day window. Not ISO week — "past week" matches intuition."""
    return now - timedelta(days=7), now


def window_for_monthly(now: datetime) -> tuple[datetime, datetime]:
    """Window [first-of-month, now) using `now`'s tz."""
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return first, now


def previous_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Shift a [start, end) window backwards by its own length.

    For today (e.g. 24h span) the previous window is yesterday at the
    same hour-of-day. For weekly (7d span) it's the 7d period before that.
    Used by `compute_diff` callers to get a comparable prior period.
    """
    span = end - start
    return start - span, start
