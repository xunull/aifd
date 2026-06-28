"""`aifd cosmos` 2.5D 渲染 — canvas 伪 3D 星图，鼠标拖拽旋转（v0.14 新 default）。

2D force-graph 版保留在 ``render_cosmos.render_cosmos_html``（``aifd cosmos --flat``）。

为什么 2.5D 不是真 3D：spike 实证（design doc 20260628-3dcosmos）——用户要「转动立体
星图」的交互而非 GPU bloom 质感；旋转是三角函数 + 透视投影，不是 GPU 特权，canvas CPU
算上千点毫秒级；真 3D（Three+bloom）的 bloom × 密集数据本质冲突（6 版都糊）+ WebGL 在
受限环境黑屏 + 600KB CDN。canvas 2.5D：自包含无 vendored lib、到处能跑、可自主迭代。

数据层复用 ``render_cosmos.build_graph``（nodes/links + basename 隐私 + XSS escape 都在
那）。本模块只加：确定性 3D 位置（hub 聚类）+ color/size 映射 + canvas 自包含 HTML。

性能（卡死 + 白屏两次教训）：每帧 ``source-over`` 清屏，防 ``lighter`` 累积成白；GPU 不
参与（纯 canvas 2D + CPU 旋转）；ship 前真实浏览器跑满 15 秒+ 验证不白不卡（test gate）。
"""

from __future__ import annotations

import hashlib
import html
from collections.abc import Iterable
from math import sqrt

from aifd.models import Session
from aifd.render_cosmos import (
    _COOL,
    _HUB,
    _WARM,
    VIBE_THRESHOLD,
    _escape_json_for_script,
    build_graph,
)

_SPREAD = 0.32  # session 围绕其 hub 的确定性扰动半径


def _h(key: str, salt: int) -> float:
    """确定性 [0, 1) 伪随机：同 key 永远同位置，布局可复现、跨进程稳定。"""
    digest = hashlib.md5(f"{salt}:{key}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0x100000000


def _int(value: object, default: int) -> int:
    """build_graph 存的 events/count 已是 int；其他一律退回 default。"""
    return value if isinstance(value, int) else default


def _hover(node: dict[str, object]) -> str:
    """悬浮信息。字段已在 build_graph 里 html.escape 过；tooltip 用 innerHTML 安全显示。"""
    if node.get("kind") == "hub":
        return f'{node.get("project", "")} · {_int(node.get("count"), 0)} sessions'
    return (
        f'{node.get("label", "")} · {_int(node.get("events"), 0)} events'
        f' · {node.get("provider", "")}'
    )


def build_points(sessions: Iterable[Session]) -> list[dict[str, object]]:
    """build_graph + 给每个 node 算 color / size / 确定性 3D 位置（hub 聚类）。

    退化输入（0 / 1 session）产生有效的空 / 最小点集，不报错（复用 build_graph 契约）。
    """
    graph = build_graph(sessions)
    nodes = graph["nodes"]
    links = graph["links"]

    hub_pos: dict[str, tuple[float, float, float]] = {}
    for node in nodes:
        if node["kind"] == "hub":
            hid = str(node["id"])
            hub_pos[hid] = (_h(hid, 1) * 2 - 1, _h(hid, 2) * 2 - 1, _h(hid, 3) * 2 - 1)
    sess_hub = {str(link["source"]): str(link["target"]) for link in links}

    points: list[dict[str, object]] = []
    for node in nodes:
        nid = str(node["id"])
        if node["kind"] == "hub":
            x, y, z = hub_pos[nid]
            color = _HUB
            size = max(2.5, sqrt(_int(node.get("count"), 1)) * 1.8)
        else:
            hx, hy, hz = hub_pos.get(sess_hub.get(nid, ""), (0.0, 0.0, 0.0))
            x = hx + (_h(nid, 1) - 0.5) * _SPREAD
            y = hy + (_h(nid, 2) - 0.5) * _SPREAD
            z = hz + (_h(nid, 3) - 0.5) * _SPREAD
            color = _COOL if node.get("vibe") else _WARM
            size = max(1.1, sqrt(_int(node.get("events"), 0) + 1) * 0.85)
        points.append(
            {
                "x": round(x, 3),
                "y": round(y, 3),
                "z": round(z, 3),
                "c": color,
                "s": round(size, 2),
                "info": _hover(node),
            }
        )
    return points


def render_cosmos_25d_html(
    sessions: Iterable[Session], page_title: str = "aifd cosmos"
) -> str:
    """组装自包含的 2.5D canvas HTML（无 vendored lib，离线可看）。"""
    points = build_points(sessions)
    return _HTML_TEMPLATE.format(
        title=html.escape(page_title),
        n=len(points),
        threshold=VIBE_THRESHOLD,
        data=_escape_json_for_script(points),
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}</title><style>
  html, body {{ margin: 0; background: #05060a; overflow: hidden; }}
  #hint {{ position: fixed; top: 10px; left: 12px; color: #aab2c5;
    font: 13px ui-monospace, monospace; background: rgba(5,6,10,.72);
    padding: 5px 11px; border-radius: 7px; z-index: 10; pointer-events: none; }}
  #tip {{ position: fixed; display: none; background: rgba(10,12,20,.93);
    color: #dfe4f0; font: 12px ui-monospace, monospace; padding: 4px 8px;
    border-radius: 5px; z-index: 11; pointer-events: none; max-width: 380px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  #c {{ display: block; cursor: grab; }}
  #c:active {{ cursor: grabbing; }}
</style></head><body>
<div id="hint">{title} · {n} 星 · 冷=vibe(event&lt;{threshold}) 暖=深聊 紫=项目 · 拖拽旋转</div>
<div id="tip"></div>
<canvas id="c"></canvas>
<script>
const PTS = {data};
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const tip = document.getElementById('tip');
let W, H, cx, cy;
function rs() {{ W = cv.width = innerWidth; H = cv.height = innerHeight; cx = W/2; cy = H/2; }}
rs(); addEventListener('resize', rs);
function hexA(x, a) {{ const n = parseInt(x.slice(1), 16);
  return 'rgba(' + ((n>>16)&255) + ',' + ((n>>8)&255) + ',' + (n&255) + ',' + a + ')'; }}

// 旋转状态：yaw 绕竖轴、pitch 绕横轴；拖拽控制，松手缓动 + 缓慢自转（阻尼）。
let yaw = 0.6, pitch = -0.15, vYaw = 0, vPitch = 0, drag = false, lx = 0, ly = 0, mX = -1, mY = -1;
cv.addEventListener('mousedown', e => {{ drag = true; lx = e.clientX; ly = e.clientY; }});
addEventListener('mouseup', () => drag = false);
addEventListener('mousemove', e => {{ mX = e.clientX; mY = e.clientY;
  if (!drag) return;
  vYaw = (e.clientX - lx) * 0.006; vPitch = (e.clientY - ly) * 0.006;
  yaw += vYaw; pitch = Math.max(-1.35, Math.min(1.35, pitch + vPitch));
  lx = e.clientX; ly = e.clientY; }});

let proj = [];
function frame() {{
  if (drag) {{ vYaw *= 0.8; vPitch *= 0.8; }}
  else {{ yaw += 0.0015 + vYaw; pitch = Math.max(-1.35, Math.min(1.35, pitch + vPitch));
    vYaw *= 0.92; vPitch *= 0.92; }}
  const SC = Math.min(W, H) * 0.40, F = 3.6;
  const cyw = Math.cos(yaw), syw = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  ctx.globalCompositeOperation = 'source-over';   // 覆盖清屏，防 lighter 累积成白
  ctx.fillStyle = '#05060a'; ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'lighter';       // 星点叠加发光
  proj = PTS.map((p, i) => {{
    const x1 = p.x*cyw - p.z*syw, z1 = p.x*syw + p.z*cyw;   // 绕竖轴(yaw)
    const y2 = p.y*cp - z1*sp, z2 = p.y*sp + z1*cp;          // 绕横轴(pitch)
    const ps = F / (F - z2);                                  // 透视：近大远小
    return {{ px: cx + x1*SC*ps, py: cy + y2*SC*ps, r: p.s*ps, rz: z2, c: p.c, i }};
  }});
  proj.sort((a, b) => a.rz - b.rz);   // 远的先画（景深遮挡顺序）
  for (const q of proj) {{
    const d = (q.rz + 1.8) / 3.6, a = Math.max(0.06, 0.08 + d*0.42), gR = q.r * 2.4;
    const g = ctx.createRadialGradient(q.px, q.py, 0, q.px, q.py, gR);
    g.addColorStop(0, hexA(q.c, 0.5*a));
    g.addColorStop(0.45, hexA(q.c, 0.13*a));
    g.addColorStop(1, hexA(q.c, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(q.px, q.py, gR, 0, 6.2832); ctx.fill();
    ctx.fillStyle = hexA(q.c, a); ctx.beginPath(); ctx.arc(q.px, q.py, q.r, 0, 6.2832); ctx.fill();
  }}
  if (mX >= 0 && !drag) {{   // hover：找鼠标最近的投影点，显示 tooltip
    let best = -1, bd = 13;
    for (const q of proj) {{ const dd = Math.hypot(q.px - mX, q.py - mY);
      if (dd < bd) {{ bd = dd; best = q.i; }} }}
    if (best >= 0) {{ tip.style.display = 'block'; tip.style.left = (mX+13)+'px';
      tip.style.top = (mY+13)+'px'; tip.innerHTML = PTS[best].info; }}
    else tip.style.display = 'none';
  }} else tip.style.display = 'none';
  requestAnimationFrame(frame);
}}
frame();
</script></body></html>
"""
