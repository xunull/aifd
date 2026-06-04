"""Tests for render_question_answers (Table + JSON + C3 summary footer)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aifd.models import QuestionAnswer
from aifd.render import (
    _matches_recommended,
    render_question_answers,
    render_question_answers_html,
)


def _qa(
    question: str = "Q",
    chosen: str | None = "A",
    recommended: str | None = "A",
    notes: str | None = None,
    options: tuple[str, ...] = ("A", "B"),
) -> QuestionAnswer:
    return QuestionAnswer(
        question=question,
        options=options,
        recommended_option=recommended,
        chosen_option=chosen,
        notes=notes,
        ts=datetime(2026, 6, 1, tzinfo=UTC),
        cwd=Path("/proj"),
        provider="claude",
        session_id="s1",
        source_path=Path("/proj/.claude/x.jsonl"),
        tool_use_id="tid",
    )


def test_render_empty(capsys: pytest.CaptureFixture[str]) -> None:
    render_question_answers([], scope_label="global", as_json=False)
    assert "No AskUserQuestion calls found" in capsys.readouterr().out


def test_render_empty_json_emits_array(capsys: pytest.CaptureFixture[str]) -> None:
    render_question_answers([], scope_label="global", as_json=True)
    assert json.loads(capsys.readouterr().out) == []


def test_render_table_shows_chosen_and_recommended(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_question_answers([_qa()], scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "Q" in out
    assert "A" in out
    # Footer with hit rate (chosen == recommended)
    assert "1 question in global" in out
    assert "100%" in out


def test_render_table_footer_hit_rate_partial(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _qa(question="Q1", chosen="A", recommended="A"),
        _qa(question="Q2", chosen="B", recommended="A"),  # divergent
        _qa(question="Q3", chosen="A", recommended="A"),
    ]
    render_question_answers(rows, scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "3 questions" in out
    # 2/3 chose recommended
    assert "67%" in out or "66%" in out  # depends on rounding
    assert "0 unanswered" in out


def test_render_table_footer_with_orphans(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        _qa(question="Q1", chosen=None, recommended="A"),  # orphan
        _qa(question="Q2", chosen="A", recommended="A"),
    ]
    render_question_answers(rows, scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "2 questions" in out
    assert "1 unanswered" in out
    # Hit rate denominator excludes orphan (1/1 = 100%)
    assert "100%" in out


def test_render_table_footer_no_recommendation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When no row has a recommendation, hit rate is omitted (no denominator)."""
    rows = [_qa(question="Q1", chosen="A", recommended=None)]
    render_question_answers(rows, scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "1 question in global" in out
    assert "recommended hit rate" not in out


def test_render_chosen_strips_recommended_suffix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When chosen label still carries the `(recommended)` suffix from the
    user's recorded answer text, the Table display strips it so it matches
    the Recommended column. Hit rate still counts the match."""
    rows = [_qa(chosen="A) Add (推荐)", recommended="A) Add")]
    render_question_answers(rows, scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "100%" in out


def test_render_json_full_record(capsys: pytest.CaptureFixture[str]) -> None:
    render_question_answers([_qa()], scope_label="global", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) == 1
    record = parsed[0]
    assert record["question"] == "Q"
    assert record["options"] == ["A", "B"]
    assert record["recommended_option"] == "A"
    assert record["chosen_option"] == "A"
    assert record["provider"] == "claude"
    assert record["session_id"] == "s1"
    assert record["tool_use_id"] == "tid"


def test_matches_recommended_exact() -> None:
    assert _matches_recommended("A) Ship", "A) Ship") is True


def test_matches_recommended_multiselect() -> None:
    """multiSelect chosen as 'A, B, C' — recommended A counts as match."""
    assert _matches_recommended("A, B, C", "A") is True
    assert _matches_recommended("A, B, C", "D") is False


def test_matches_recommended_strips_chosen_suffix() -> None:
    """User picked recommended option → chosen carries (推荐) suffix; recommended
    has it stripped at parse time. Strip both sides to match."""
    assert _matches_recommended("A) Add (推荐)", "A) Add") is True


def test_matches_recommended_empty_recommendation() -> None:
    assert _matches_recommended("A", "") is False


def test_notes_render_in_table(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_qa(notes="prefer dark mode")]
    render_question_answers(rows, scope_label="global", as_json=False)
    out = capsys.readouterr().out
    assert "Other:" in out
    assert "prefer dark mode" in out


# ---------------------------------------------------------------------------
# render_question_answers_html (v0.3.1 / CEO plan D2=A)
# ---------------------------------------------------------------------------


def test_html_render_returns_full_page_when_no_output() -> None:
    page = render_question_answers_html([_qa()], scope_label="global")
    assert page is not None
    assert page.startswith("<!DOCTYPE html>")
    assert "<html lang=" in page
    assert "</html>" in page.rstrip()


def test_html_render_empty_shows_friendly_state() -> None:
    page = render_question_answers_html([], scope_label="global")
    assert page is not None
    assert 'class="empty"' in page
    assert "No AskUserQuestion calls found" in page


def test_html_render_writes_to_output_path(tmp_path: Path) -> None:
    out = tmp_path / "q.html"
    result = render_question_answers_html(
        [_qa(question="Hi")], scope_label="global", output_path=out
    )
    assert result is None  # writes file, returns None
    content = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Hi" in content


def test_html_render_includes_summary_when_rows_present() -> None:
    rows = [_qa(chosen="A", recommended="A"), _qa(chosen="B", recommended="A")]
    page = render_question_answers_html(rows, scope_label="global")
    assert page is not None
    assert "<strong>2</strong> total" in page
    # 1 of 2 followed recommendation
    assert "50%" in page
    assert "1/2" in page


def test_html_render_xss_question_text_is_escaped() -> None:
    """CRITICAL regression: question text containing literal <script>
    must NOT render as a script tag. D3=A security gate."""
    malicious = '<script>window.pwned=true</script>'
    page = render_question_answers_html(
        [_qa(question=malicious)], scope_label="global"
    )
    assert page is not None
    assert "<script>window.pwned=true</script>" not in page
    assert "&lt;script&gt;" in page


def test_html_render_xss_in_options_escaped() -> None:
    """Same gate, options labels — they come from arbitrary AUQ payloads."""
    page = render_question_answers_html(
        [_qa(options=('<img src=x onerror=alert(1)>', "B"))],
        scope_label="global",
    )
    assert page is not None
    assert "<img src=x onerror=" not in page
    assert "&lt;img" in page


def test_html_render_xss_in_chosen_and_notes_escaped() -> None:
    page = render_question_answers_html(
        [_qa(chosen="<svg/onload=x>", notes="<iframe>boom</iframe>")],
        scope_label="global",
    )
    assert page is not None
    assert "<svg/onload=" not in page
    assert "<iframe>boom</iframe>" not in page
    assert "&lt;svg" in page
    assert "&lt;iframe&gt;" in page


def test_html_render_xss_in_scope_label_escaped() -> None:
    page = render_question_answers_html(
        [], scope_label='<script>alert(1)</script>'
    )
    assert page is not None
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_html_render_long_question_text_preserved_fully() -> None:
    """Verifies the original D1 pain point fix: 67% of real questions are
    > 200 chars; the longest in the dev set is 1673. HTML must show the
    whole thing, not truncate like the rich Table does."""
    big = "A" * 1700
    page = render_question_answers_html(
        [_qa(question=big)], scope_label="global"
    )
    assert page is not None
    assert big in page


def test_html_render_marks_chosen_option_with_class() -> None:
    page = render_question_answers_html(
        [_qa(chosen="A", recommended="A", options=("A", "B"))],
        scope_label="global",
    )
    assert page is not None
    # Class on the matching option <li>
    assert 'class="chosen recommended"' in page
    # The non-chosen option carries no marker class
    assert "<li>B</li>" in page


def test_html_render_orphan_question_shows_no_answer_state() -> None:
    page = render_question_answers_html(
        [_qa(chosen=None, recommended="A")], scope_label="global"
    )
    assert page is not None
    assert 'class="orphan"' in page
    assert "No answer recorded" in page


def test_html_render_multiselect_chosen_falls_through_to_selected_line() -> None:
    """When chosen is 'A, B' (multiSelect), no single option matches it;
    the renderer falls through to a 'Selected:' note so the value still shows."""
    page = render_question_answers_html(
        [_qa(chosen="A, B", recommended="A", options=("A", "B", "C"))],
        scope_label="global",
    )
    assert page is not None
    assert "Selected:" in page
    assert "A, B" in page
