"""`aifd cosmos` rendering — turn AI session history into a force-directed galaxy.

A separate module from render.py (already large) per /plan-eng-review. cli/cosmos.py
handles args + file IO; this module does the pure data assembly + the self-contained
HTML.

Node / link model (E4): each session is a star, each cwd (project) is a hub node,
sessions link only to their hub — O(n) edges, NOT the O(n²) clique a same-cwd full
mesh would produce (200 sessions = 19,900 edges).

Visual mapping (verified against models.py):
  - star radius ∝ event_count (Session has event_count, not token).
  - star color = "vibe temperature": event_count < VIBE_THRESHOLD (habits.py's
    vibe-coding heuristic) → cool, higher → warm. event_count is each provider's
    jsonl event count and is NOT comparable across providers — an in-tool heuristic,
    not behavioral truth (Codex outside-voice). The UI hint says so.
  - hub node = one per cwd, sized by its session count.

Privacy (E5): cwd is shown basename-only (project folder name), never the absolute
path — a self-contained HTML / poster may be shared, and an absolute path leaks the
username and private project names. Same-basename different-path projects get a short
hash suffix to stay distinct.

Security (E2, two layers): every user-derived string (title, project, provider) is
html.escape'd before it enters the JSON (force-graph renders nodeLabel as innerHTML,
so an un-escaped `<img onerror>` title would XSS the tooltip); AND the injected JSON
has every `</` rewritten so a title containing `</script>` cannot break out of the
data <script> block. Poster export is deliberately deferred (Codex flagged the
devicePixelRatio monkeypatch as too brittle for v1).

Asset (T7): force-graph's UMD bundle is vendored at aifd/assets/force-graph.min.js and
inlined, so the output HTML is fully self-contained and offline-viewable.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections.abc import Iterable
from importlib import resources
from pathlib import Path

from aifd.models import Session

# event_count < this == a "vibe-coding" session (mirrors habits._VIBE_MSG_THRESHOLD).
VIBE_THRESHOLD = 5

_COOL = "#4f9dff"  # vibe-coding 冷蓝
_WARM = "#ff6b4f"  # 深聊 热红
_HUB = "#9b8cff"   # 项目 hub 紫


def _project_label(cwd: Path, seen: dict[str, str]) -> str:
    """basename-only project label (E5).

    Disambiguates same-name different-path projects with a short path hash so two
    `app` folders don't collapse into one hub.
    """
    name = cwd.name or str(cwd)
    full = str(cwd)
    prior = seen.get(name)
    if prior is None:
        seen[name] = full
        return name
    if prior == full:
        return name
    short = hashlib.sha1(full.encode("utf-8")).hexdigest()[:4]
    return f"{name}#{short}"


def _node_id(session: Session) -> str:
    """Composite (provider, session_id) — session_id alone collides across
    providers (Codex outside-voice)."""
    return f"{session.provider}:{session.session_id}"


def _hub_id(label: str) -> str:
    return f"hub:{label}"


def _redact_home(text: str) -> str:
    """Replace the user's home prefix with ~ in free text.

    Titles are AI-generated and sometimes quote absolute paths (e.g. "pipeline on
    /Users/alice/secret-proj"). E5 redacts cwd to basename; this extends the same
    privacy to title content so a shareable HTML / poster never leaks the username
    (Codex outside-voice #11).
    """
    home = str(Path.home())
    if home and home not in ("", "/"):
        return text.replace(home, "~")
    return text


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    return 0


def build_graph(sessions: Iterable[Session]) -> dict[str, list[dict[str, object]]]:
    """Assemble force-graph nodes + links from sessions (E4 hub model).

    Pure function — fully unit-tested. Degenerate inputs (0 or 1 session) produce a
    valid minimal graph, never an error (data-layer contract from /plan-eng-review).
    All display strings are html.escape'd here (E2 layer 1).
    """
    nodes: list[dict[str, object]] = []
    links: list[dict[str, object]] = []
    seen_labels: dict[str, str] = {}
    hub_counts: dict[str, int] = {}
    hub_label: dict[str, str] = {}

    for s in sessions:
        label = _project_label(s.cwd, seen_labels)  # raw basename, used for ids
        hid = _hub_id(label)
        hub_counts[hid] = hub_counts.get(hid, 0) + 1
        hub_label[hid] = label

        events = _safe_int(s.event_count)
        nodes.append(
            {
                "id": _node_id(s),
                "label": html.escape(_redact_home(s.title or "(untitled)")),
                "project": html.escape(label),
                "provider": html.escape(s.provider),
                "events": events,
                "vibe": events < VIBE_THRESHOLD,
                "kind": "session",
            }
        )
        links.append({"source": _node_id(s), "target": hid})

    for hid, count in hub_counts.items():
        nodes.append(
            {
                "id": hid,
                "label": html.escape(hub_label[hid]),
                "project": html.escape(hub_label[hid]),
                "events": 0,
                "count": count,
                "kind": "hub",
            }
        )
    return {"nodes": nodes, "links": links}


def _escape_json_for_script(data: object) -> str:
    """JSON safe to embed in a <script> block (E2 layer 2).

    json.dumps does NOT escape `</`, so a value with `</script>` would close the tag
    early. Rewriting `</` → `<\\/` is valid JSON and neutralizes the break-out.
    """
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _load_force_graph_js() -> str:
    """Inline the vendored force-graph UMD bundle (T7) for a self-contained file."""
    return (
        resources.files("aifd.assets")
        .joinpath("force-graph.min.js")
        .read_text(encoding="utf-8")
    )


def render_cosmos_html(
    sessions: Iterable[Session], *, page_title: str = "aifd cosmos"
) -> str:
    """Self-contained HTML: inlined force-graph + injected graph JSON.

    Poster export is deliberately NOT here — deferred to a spike (Codex flagged the
    devicePixelRatio monkeypatch as too brittle for v1).
    """
    graph = build_graph(list(sessions))
    n_sessions = sum(1 for n in graph["nodes"] if n.get("kind") == "session")
    return _HTML_TEMPLATE.format(
        title=html.escape(page_title),
        graph_json=_escape_json_for_script(graph),
        fg_js=_load_force_graph_js(),
        cool=_COOL,
        warm=_WARM,
        hub=_HUB,
        n_sessions=n_sessions,
        threshold=VIBE_THRESHOLD,
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; background: #05060a; color: #cdd3e0;
    font: 13px ui-monospace, monospace; overflow: hidden; }}
  #hint {{ position: fixed; top: 10px; left: 12px; z-index: 10;
    pointer-events: none; color: #aab2c5;
    background: rgba(5,6,10,.72); padding: 5px 11px; border-radius: 7px; }}
  #graph {{ width: 100vw; height: 100vh; }}
</style>
</head>
<body>
<div id="hint">{title} · {n_sessions} sessions · 冷=vibe(event&lt;{threshold}) \
暖=深聊 · 紫=项目 · event_count 跨工具不可比，仅本工具内部指标</div>
<div id="graph"></div>
<script>{fg_js}</script>
<script>
const DATA = {graph_json};
const COOL = "{cool}", WARM = "{warm}", HUB = "{hub}";
const el = document.getElementById('graph');
// hex → rgba(8 位 hex alpha 在部分 canvas 下解析失败,用 rgba 最稳)
function withAlpha(hex, a) {{
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${{(n >> 16) & 255}}, ${{(n >> 8) & 255}}, ${{n & 255}}, ${{a}})`;
}}
// 半径:深聊靠「亮」不靠「大」→ warm 半径克制；hub 大
function nodeRadius(n) {{
  return n.kind === 'hub' ? Math.max(2.5, Math.sqrt(n.count) * 1.8)
                          : Math.max(1.1, Math.sqrt(n.events + 1) * 0.85);
}}
// V1 辉光星点:lighter 叠加(重叠星互相提亮)+ shadowBlur 柔光 + 多层 radialGradient
function drawStar(n, ctx) {{
  if (n.x == null || n.y == null) return;
  const isHub = n.kind === 'hub';
  const color = isHub ? HUB : (n.vibe ? COOL : WARM);
  const r = nodeRadius(n);
  const glowR = r * (isHub ? 3.2 : (n.vibe ? 1.8 : 2.4));  // warm 光晕略大 = 靠亮突出
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';   // 颜色相加,重叠处自然发光辉映
  const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, glowR);
  g.addColorStop(0, withAlpha(color, 0.5));
  g.addColorStop(0.45, withAlpha(color, 0.14));
  g.addColorStop(1, withAlpha(color, 0));
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(n.x, n.y, glowR, 0, 6.2832); ctx.fill();
  ctx.shadowBlur = glowR * 0.45;
  ctx.shadowColor = color;
  ctx.fillStyle = isHub ? '#eef0ff' : color;  // hub 核心近白 = 最亮的星系核心
  ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 6.2832); ctx.fill();
  ctx.restore();
}}
const Graph = ForceGraph()(el)
  .backgroundColor('#05060a')
  .graphData(DATA)
  .nodeId('id')
  .nodeLabel(n => n.kind === 'hub'
     ? `${{n.project}} · ${{n.count}} sessions`
     : `${{n.label}} · ${{n.events}} events · ${{n.provider}}`)
  .nodeCanvasObject((n, ctx) => drawStar(n, ctx))
  .nodePointerAreaPaint((n, color, ctx) => {{
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(n.x, n.y, nodeRadius(n) + 2, 0, 6.2832); ctx.fill();
  }})
  .linkColor(() => 'rgba(120,130,160,0.16)')
  .linkWidth(0.5)
  .enableNodeDrag(true);
// V2 破甜甜圈:保持正常 charge(近邻散开不聚团)+ distanceMax 限制远距排斥
// (远处节点不互推,不被甩到外环)。distanceMax 才是破甜甜圈的正解,不是降强度。
Graph.d3Force('charge').strength(-30).distanceMax(120);
addEventListener('resize', () => Graph.width(innerWidth).height(innerHeight));
</script>
</body>
</html>
"""
