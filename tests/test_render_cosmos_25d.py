"""Tests for `aifd cosmos` 2.5D renderer (aifd/render_cosmos_25d.py).

Covers: data assembly (color / size / deterministic 3D position), the source-over
white-screen guard (the regression where a `lighter` clear accumulated to white over
seconds), the 0/1-session degenerate contract, privacy (reuses build_graph's basename
+ home redaction), and an XSS-escaped page title.
"""

from __future__ import annotations

from pathlib import Path

from aifd.models import Session
from aifd.render_cosmos import _COOL, _HUB, _WARM
from aifd.render_cosmos_25d import build_points, render_cosmos_25d_html


def _session(
    provider: str = "claude",
    sid: str = "s1",
    cwd: str = "/Users/quincy/proj-a",
    events: int = 10,
    title: str | None = "fix the bug",
) -> Session:
    return Session(
        provider=provider,
        session_id=sid,
        cwd=Path(cwd),
        started_at=None,
        event_count=events,
        source_path=Path("/x/y.jsonl"),
        title=title,
    )


# ---------- data assembly ----------


def test_empty_sessions_no_points() -> None:
    assert build_points([]) == []


def test_single_session_makes_star_plus_hub() -> None:
    pts = build_points([_session()])
    assert len(pts) == 2  # 1 session star + 1 hub
    for p in pts:
        assert {"x", "y", "z", "c", "s", "info"} <= set(p)


def test_low_events_is_vibe_cool() -> None:
    stars = [p for p in build_points([_session(events=2)]) if p["c"] != _HUB]
    assert len(stars) == 1 and stars[0]["c"] == _COOL


def test_high_events_is_warm() -> None:
    stars = [p for p in build_points([_session(events=50)]) if p["c"] != _HUB]
    assert len(stars) == 1 and stars[0]["c"] == _WARM


def test_hub_is_purple() -> None:
    hubs = [p for p in build_points([_session()]) if p["c"] == _HUB]
    assert len(hubs) == 1


def test_positions_are_deterministic() -> None:
    a = [(p["x"], p["y"], p["z"]) for p in build_points([_session()])]
    b = [(p["x"], p["y"], p["z"]) for p in build_points([_session()])]
    assert a == b  # same id -> same position, reproducible across calls


def test_3d_positions_in_range() -> None:
    pts = build_points(
        [_session(), _session(sid="s2", cwd="/Users/quincy/proj-b", events=3)]
    )
    for p in pts:
        for key in ("x", "y", "z"):
            v = p[key]
            assert isinstance(v, float) and -1.5 <= v <= 1.5  # hub [-1,1] + spread


# ---------- HTML render ----------


def test_render_is_25d_not_forcegraph() -> None:
    out = render_cosmos_25d_html([_session()])
    assert "const PTS" in out
    assert "ForceGraph()" not in out  # 2.5D is canvas, not the force-graph lib
    assert "<!DOCTYPE html>" in out


def test_render_white_screen_guard() -> None:
    """Regression: a `lighter` clear accumulates to white over seconds. The clear
    MUST switch to source-over first; only star points use lighter."""
    out = render_cosmos_25d_html([_session()])
    assert "source-over" in out  # opaque clear each frame, not lighter accumulation
    assert "lighter" in out  # star points still additively glow


def test_render_empty_does_not_crash() -> None:
    out = render_cosmos_25d_html([])
    assert "const PTS" in out
    assert "<!DOCTYPE html>" in out


def test_render_no_abspath_leak() -> None:
    out = render_cosmos_25d_html(
        [_session(cwd="/Users/quincy/very-secret", title="/Users/quincy/x")]
    )
    assert "/Users/quincy" not in out  # basename-only + home redaction (build_graph)


def test_render_escapes_page_title() -> None:
    out = render_cosmos_25d_html([_session()], page_title="<script>x</script>")
    assert "<title><script>" not in out
    assert "&lt;script&gt;" in out
