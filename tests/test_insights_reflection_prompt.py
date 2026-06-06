"""Tests for reflection_prompt.py (T5).

Includes ★★★ PRIVACY INVARIANT tests using the v0.4 secret detector (D6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aifd.insights.activity import ActivityReport, ProviderActivity
from aifd.insights.reflection import (
    ComplianceData,
    ReflectionInput,
    TimingBucket,
    WinSummary,
)
from aifd.insights.reflection_prompt import PROMPT_VERSION, render_prompt
from aifd.vault.scan import _scan_line


def _full_input() -> ReflectionInput:
    return ReflectionInput(
        period_start=datetime(2026, 5, 30, tzinfo=UTC),
        period_end=datetime(2026, 6, 5, tzinfo=UTC),
        activity=ActivityReport(
            period_start=datetime(2026, 5, 30, tzinfo=UTC),
            period_end=datetime(2026, 6, 5, tzinfo=UTC),
            session_count=23,
            cost_usd=284.0,
            total_tokens=420000,
            by_provider=[
                ProviderActivity(
                    provider="claude", sessions=15,
                    cost_usd=200.0, total_tokens=300000,
                ),
            ],
            top_skills=[("plan-eng-review", 4)],
            top_topics=[("v0.7 events store", 5)],
        ),
        compliance=ComplianceData(
            total_questions=15, matched_count=13, ratio=13 / 15,
        ),
        skill_diversity_ratio=0.4,
        cost_trend_ratio=0.38,
        timing_buckets=[
            TimingBucket(label="0-6", session_count=2, avg_message_count=8),
            TimingBucket(label="6-12", session_count=5, avg_message_count=25),
            TimingBucket(label="12-18", session_count=12, avg_message_count=35),
            TimingBucket(label="18-24", session_count=4, avg_message_count=18),
        ],
        top_project="aifd",
        top_project_share=0.7,
        plan_then_ship_ratio=0.71,
        vibe_coding_score=0.14,
        wins=[
            WinSummary(label="ship", date="2026-06-05"),
            WinSummary(label="plan-eng-review", date="2026-06-04"),
            WinSummary(label="ship", date="2026-06-03"),
        ],
    )


# ---------- happy path ----------


def test_render_zh_default() -> None:
    prompt = render_prompt(_full_input(), lang="zh")
    assert "PROMPT_VERSION: v1" in prompt
    assert "Output language: zh" in prompt
    assert "OUTPUT strict JSON" in prompt
    assert "compliance_ratio: 87%" in prompt
    assert "aifd" in prompt
    # zh rules present
    assert "中文" in prompt
    assert "审视" in prompt  # forbidden-word reminder


def test_render_en() -> None:
    prompt = render_prompt(_full_input(), lang="en")
    assert "Output language: en" in prompt
    assert "delve, crucial" in prompt  # forbidden words listed


def test_render_unknown_lang_falls_back_to_zh() -> None:
    prompt = render_prompt(_full_input(), lang="ja")
    assert "Output language: zh" in prompt


# ---------- PROMPT_VERSION (D2) ----------


def test_prompt_version_constant_present() -> None:
    assert PROMPT_VERSION == "v1"


def test_prompt_includes_prompt_version() -> None:
    prompt = render_prompt(_full_input())
    assert f"PROMPT_VERSION: {PROMPT_VERSION}" in prompt


def test_prompt_requests_version_echo() -> None:
    """Output schema must ask LLM to echo prompt_version back."""
    prompt = render_prompt(_full_input())
    assert "prompt_version" in prompt
    assert "echo the PROMPT_VERSION" in prompt


# ---------- (no data) graceful handling ----------


def test_render_handles_all_none_dimensions() -> None:
    """When every dimension is None, prompt still renders with placeholders."""
    bare = ReflectionInput(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 7, tzinfo=UTC),
        # All else None / empty default
    )
    prompt = render_prompt(bare, lang="zh")
    assert "(no data)" in prompt
    assert "PROMPT_VERSION: v1" in prompt


def test_render_handles_partial_data() -> None:
    """Some dimensions have data, others None — both render correctly."""
    partial = ReflectionInput(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 7, tzinfo=UTC),
        activity=ActivityReport(
            period_start=datetime(2026, 6, 1, tzinfo=UTC),
            period_end=datetime(2026, 6, 7, tzinfo=UTC),
            session_count=10, cost_usd=50.0, total_tokens=100000,
            by_provider=[], top_skills=[], top_topics=[],
        ),
        # compliance, skill_diversity, etc. all None
    )
    prompt = render_prompt(partial)
    assert "sessions: 10" in prompt
    assert "compliance_ratio: (no data)" in prompt


# ---------- ★★★ PRIVACY INVARIANTS (D6) ----------
# Use v0.4 _DETECTORS to scan the rendered prompt.


def test_privacy_no_secret_patterns_in_prompt() -> None:
    """v0.4 detector scan: prompt must produce 0 SensitiveMatch.

    This is the load-bearing privacy test. If we accidentally surface a
    raw secret via some new compute_* function, this test fails.
    """
    prompt = render_prompt(_full_input())
    matches = list(_scan_line(
        Path("/fake"), 1, prompt, min_confidence=7,
        capture_context=False, line_truncated=False,
    ))
    assert matches == [], (
        f"Prompt contains {len(matches)} secret pattern(s): "
        f"{[m.category for m in matches]}"
    )


def test_privacy_no_absolute_path_in_prompt() -> None:
    """top_project should be a basename, never /Users/... or /home/..."""
    inp = _full_input()
    prompt = render_prompt(inp)
    assert "/Users/" not in prompt
    assert "/home/" not in prompt
    assert "/private/" not in prompt


def test_privacy_does_not_include_raw_question_text() -> None:
    """Default mode prompts contain aggregate stats, NOT question text."""
    inp = _full_input()
    prompt = render_prompt(inp)
    # Common AskUserQuestion template strings that should NEVER appear
    forbidden_starts = [
        "What's the strongest evidence",
        "Name the actual human",
        "Have you actually sat down",
    ]
    for forbidden in forbidden_starts:
        assert forbidden not in prompt, (
            f"Raw question text leaked: {forbidden!r}"
        )


def test_privacy_does_not_include_session_message_content() -> None:
    """Verify only metadata (counts, ratios) survives — no message bodies."""
    inp = _full_input()
    prompt = render_prompt(inp)
    # If someone added prompt.append(session.full_text) somewhere, you'd
    # see arbitrary user text. Sanity-check that we only have structured
    # numeric/categorical content.
    suspicious_substrings = [
        "I want to build",
        "Can you help me",
        "Here's my code:",
        '"role": "user"',
    ]
    for s in suspicious_substrings:
        assert s not in prompt


def test_privacy_invariant_with_realistic_pii_input() -> None:
    """Construct an input where every dimension is rendered, and confirm
    NOTHING resembling a secret survives. Most paranoid version of the
    above tests."""
    inp = _full_input()
    prompt = render_prompt(inp, lang="en")
    prompt += "\n" + render_prompt(inp, lang="zh")  # try both langs
    # Run v0.4 detectors over the combined output
    matches = list(_scan_line(
        Path("/fake"), 1, prompt, min_confidence=7,
        capture_context=False, line_truncated=False,
    ))
    # Also explicitly check several PII / secret string patterns
    assert "sk-" not in prompt  # OpenAI / Anthropic key prefix
    assert "ghp_" not in prompt  # GitHub PAT
    assert "AKIA" not in prompt  # AWS access key
    assert matches == []


# ---------- structure assertions ----------


def test_prompt_lists_all_9_dimensions() -> None:
    prompt = render_prompt(_full_input())
    expected_dimensions = [
        "compliance_ratio",
        "skill_diversity",
        "cost_trend",
        "timing_distribution",
        "top_project",
        "plan_then_ship",
        "vibe_coding_score",
        "top_wins",
        "sessions",
    ]
    for dim in expected_dimensions:
        assert dim in prompt, f"Missing dimension {dim!r} in prompt"


def test_prompt_includes_output_schema() -> None:
    prompt = render_prompt(_full_input())
    assert '"essay"' in prompt
    assert '"wins"' in prompt
    assert '"anti_pattern"' in prompt
    assert '"concrete_action"' in prompt
    assert '"prompt_version"' in prompt
