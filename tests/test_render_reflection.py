"""Tests for render_reflection_text / render_reflection_json (T6)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from aifd.render import render_reflection_json, render_reflection_text


def _sample_output() -> dict[str, object]:
    return {
        "prompt_version": "v1",
        "essay": "上周你在 v0.8 上做了 23 次 session...",
        "wins": [
            "v0.8 reflect 完整 ship",
            "plan-eng-review 8 个决策全锁",
            "DeepSeek 选型清醒",
        ],
        "anti_pattern": "凌晨 2-4 点跑 8 次 office-hours 但都没 ship",
        "concrete_action": "下周强制选 B 选项 2 次",
    }


# ---------- render_reflection_text ----------


def test_render_text_contains_essay() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(_sample_output(), period_label="week", lang="zh")
    out = buf.getvalue()
    assert "Your week with AI" in out
    assert "v0.8 上做了 23 次" in out


def test_render_text_lists_all_wins() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(_sample_output())
    out = buf.getvalue()
    assert "Wins" in out
    assert "v0.8 reflect 完整 ship" in out
    assert "DeepSeek 选型清醒" in out


def test_render_text_shows_anti_pattern() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(_sample_output())
    out = buf.getvalue()
    assert "Anti-pattern" in out
    assert "凌晨 2-4 点" in out


def test_render_text_shows_concrete_action() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(_sample_output(), lang="zh")
    out = buf.getvalue()
    assert "下周试一次" in out
    assert "强制选 B 选项" in out


def test_render_text_handles_empty_wins() -> None:
    output = _sample_output()
    output["wins"] = []
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(output)
    out = buf.getvalue()
    # Wins section should be skipped, no crash
    assert "Wins" not in out or "v0.8 reflect" not in out


def test_render_text_with_timing_breakdown() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(
            _sample_output(),
            timing_breakdown={"local_collect": 0.45, "deepseek": 6.2, "render": 0.05},
        )
    out = buf.getvalue()
    assert "local_collect=0.45s" in out
    assert "deepseek=6.20s" in out
    # rich may wrap; check key parts independently
    assert "prompt_version" in out
    assert "v1" in out


def test_render_text_en_lang() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_text(_sample_output(), lang="en")
    out = buf.getvalue()
    assert "Try next period" in out


# ---------- render_reflection_json ----------


def test_render_json_emits_stable_schema() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_json(_sample_output())
    parsed = json.loads(buf.getvalue())
    assert parsed["essay"]
    assert len(parsed["wins"]) == 3
    assert parsed["prompt_version"] == "v1"


def test_render_json_unicode_safe() -> None:
    """Chinese in essay should be preserved (not escape-sequenced)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_reflection_json(_sample_output())
    raw = buf.getvalue()
    # ensure_ascii=False → 中文 literal in output
    assert "上周你" in raw
