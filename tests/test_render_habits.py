"""Tests for render_habits_text / render_habits_json (T6)."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from aifd.render import render_habits_json, render_habits_text


def _sample_output() -> dict[str, object]:
    return {
        "prompt_version": "v1",
        "patterns": [
            {
                "name": "周五放松崩",
                "evidence": "周五 vibe 比率 2.4x 工作日均值",
                "suggestion": "周五下午 5 点后不再开 plan review",
            },
            {
                "name": "深夜决策次日后悔",
                "evidence": "22 点后 session 仅 33% 当天 ship",
                "suggestion": "复杂架构推到次日早晨",
            },
        ],
    }


# ---------- render_habits_text ----------


def test_render_text_zh_includes_header_and_patterns() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(_sample_output(), period_days=90, lang="zh")
    out = buf.getvalue()
    assert "AI 行为人格" in out
    assert "90 天" in out
    assert "周五放松崩" in out
    assert "深夜决策次日后悔" in out
    assert "模式 1" in out
    assert "模式 2" in out


def test_render_text_en_uses_english_labels() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(_sample_output(), period_days=60, lang="en")
    out = buf.getvalue()
    assert "Your AI Habits" in out
    assert "last 60 days" in out
    assert "Pattern 1" in out


def test_render_text_shows_evidence_and_suggestion() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(_sample_output(), period_days=90, lang="zh")
    out = buf.getvalue()
    assert "周五 vibe 比率 2.4x 工作日均值" in out
    assert "周五下午 5 点后不再开 plan review" in out
    assert "建议" in out


def test_render_text_empty_patterns_shows_fallback_message() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(
            {"prompt_version": "v1", "patterns": []},
            period_days=90,
            lang="zh",
        )
    out = buf.getvalue()
    assert "没有识别出模式" in out


def test_render_text_includes_fallback_reason_when_present() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(
            {
                "prompt_version": "v1",
                "patterns": [],
                "_fallback_reason": "no LLM API key",
            },
            period_days=90,
            lang="zh",
        )
    out = buf.getvalue()
    assert "no LLM API key" in out


def test_render_text_with_timing_breakdown() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(
            _sample_output(),
            period_days=90,
            lang="zh",
            timing_breakdown={"local": 0.3, "llm": 4.1, "render": 0.05},
        )
    out = buf.getvalue()
    assert "local=" in out
    assert "llm=" in out
    assert "prompt_version: v1" in out


def test_render_text_no_timing_still_shows_prompt_version() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_text(_sample_output(), period_days=90, lang="zh")
    out = buf.getvalue()
    assert "prompt_version: v1" in out


# ---------- render_habits_json ----------


def test_render_json_round_trips() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_json(_sample_output())
    parsed = json.loads(buf.getvalue())
    assert parsed["prompt_version"] == "v1"
    assert len(parsed["patterns"]) == 2
    assert parsed["patterns"][0]["name"] == "周五放松崩"


def test_render_json_preserves_unicode_without_escaping() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_habits_json(_sample_output())
    # ensure_ascii=False means CJK is in the output verbatim
    assert "周五放松崩" in buf.getvalue()
