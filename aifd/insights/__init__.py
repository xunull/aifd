"""aifd.insights — activity summarization + reflection (v0.8).

v0.5 shipped `summarize_activity` (now in activity.py).
v0.8 adds reflection (LLM-powered weekly coach in reflection.py).
"""

from aifd.insights import activity as _activity
from aifd.insights.activity import (
    ActivityReport,
    Delta,
    ProjectionEstimate,
    ProviderActivity,
    compute_diff,
    compute_projection,
    previous_window,
    summarize_activity,
    window_for_monthly,
    window_for_today,
    window_for_weekly,
)

PROVIDERS = _activity.PROVIDERS  # type: ignore[attr-defined]

__all__ = [
    "PROVIDERS",
    "ActivityReport",
    "Delta",
    "ProjectionEstimate",
    "ProviderActivity",
    "compute_diff",
    "compute_projection",
    "previous_window",
    "summarize_activity",
    "window_for_monthly",
    "window_for_today",
    "window_for_weekly",
]
