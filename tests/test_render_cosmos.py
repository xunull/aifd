"""Tests for `aifd cosmos` data assembly + HTML (aifd/render_cosmos.py).

Covers the /plan-eng-review decisions that only tests pin: E4 hub model (not
O(n²) clique), E5 basename-only privacy, E2 two-layer XSS (html.escape + JSON
`</` rewrite), composite node id (Codex outside-voice), and the 0/1-session
degenerate contract.

Browser E2E (E3 playwright — force-graph render + poster Safari cap) is deferred:
needs a browser install. Tracked as a TODO in the design doc (T6 / T8).
"""

from __future__ import annotations

import json
from pathlib import Path

from aifd.models import Session
from aifd.render_cosmos import (
    _escape_json_for_script,
    build_graph,
    render_cosmos_html,
)


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
        started_at=None,  # build_graph doesn't use started_at
        event_count=events,
        source_path=Path("/x/y.jsonl"),
        title=title,
    )


# ---------- E4: hub model, not clique ----------


def test_empty_sessions():
    assert build_graph([]) == {"nodes": [], "links": []}


def test_single_session_makes_star_plus_hub():
    g = build_graph([_session()])
    assert sorted(n["kind"] for n in g["nodes"]) == ["hub", "session"]
    assert len(g["links"]) == 1


def test_hub_model_is_linear_not_clique():
    # 4 sessions same cwd: hub model = 4 links (each → hub). A clique would be
    # 4*3/2 = 6. Asserting 4 pins that we did NOT build a full mesh.
    sessions = [_session(sid=f"s{i}") for i in range(4)]
    g = build_graph(sessions)
    hubs = [n for n in g["nodes"] if n["kind"] == "hub"]
    assert len(hubs) == 1
    assert len(g["links"]) == 4
    assert all(link["target"] == hubs[0]["id"] for link in g["links"])


# ---------- color = vibe temperature ----------


def test_low_events_is_vibe_cool():
    star = next(n for n in build_graph([_session(events=3)])["nodes"]
               if n["kind"] == "session")
    assert star["vibe"] is True


def test_high_events_is_warm():
    star = next(n for n in build_graph([_session(events=50)])["nodes"]
               if n["kind"] == "session")
    assert star["vibe"] is False


# ---------- composite node id (Codex outside-voice) ----------


def test_node_id_composite_avoids_cross_provider_collision():
    g = build_graph([_session(provider="claude", sid="X"),
                     _session(provider="codex", sid="X")])
    ids = {n["id"] for n in g["nodes"] if n["kind"] == "session"}
    assert ids == {"claude:X", "codex:X"}


# ---------- E5: basename-only privacy ----------


def test_basename_only_no_absolute_path():
    g = build_graph([_session(cwd="/Users/quincy/secret-proj")])
    star = next(n for n in g["nodes"] if n["kind"] == "session")
    assert star["project"] == "secret-proj"
    assert "/Users/quincy" not in json.dumps(g)


def test_same_basename_different_path_disambiguated():
    g = build_graph([_session(sid="a", cwd="/Users/quincy/x/app"),
                     _session(sid="b", cwd="/Users/quincy/y/app")])
    projects = {n["project"] for n in g["nodes"] if n["kind"] == "session"}
    assert len(projects) == 2  # hash suffix keeps the two `app` hubs distinct


# ---------- E2: two-layer XSS ----------


def test_xss_title_html_escaped():
    g = build_graph([_session(title="</script><script>alert(1)</script>")])
    star = next(n for n in g["nodes"] if n["kind"] == "session")
    assert "<script>" not in star["label"]
    assert "&lt;" in star["label"]


def test_escape_json_neutralizes_script_close():
    out = _escape_json_for_script({"x": "a</script>b"})
    assert "</script>" not in out
    assert "<\\/script>" in out


def test_none_title_falls_back():
    star = next(n for n in build_graph([_session(title=None)])["nodes"]
               if n["kind"] == "session")
    assert star["label"] == "(untitled)"


def test_title_home_path_redacted():
    # AI titles sometimes quote absolute paths — must not leak the username.
    g = build_graph([_session(title=f"fix {Path.home()}/secret/bug.py")])
    star = next(n for n in g["nodes"] if n["kind"] == "session")
    assert str(Path.home()) not in star["label"]
    assert "~/secret/bug.py" in star["label"]


# ---------- render_cosmos_html ----------


def test_render_html_contains_data_and_forcegraph():
    out = render_cosmos_html([_session()])
    assert "ForceGraph" in out  # vendored lib inlined
    assert "const DATA" in out


def test_render_html_empty_does_not_crash():
    out = render_cosmos_html([])
    assert "ForceGraph" in out
    assert "<!DOCTYPE html>" in out


def test_render_html_no_abspath_leak():
    out = render_cosmos_html([_session(cwd="/Users/quincy/very-secret")])
    assert "/Users/quincy" not in out


def test_render_html_escapes_page_title():
    out = render_cosmos_html([_session()], page_title="<script>x</script>")
    assert "<title><script>" not in out
    assert "&lt;script&gt;" in out
