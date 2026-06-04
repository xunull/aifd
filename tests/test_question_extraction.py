"""Tests for ClaudeProvider.list_question_answers and related parsing."""

from __future__ import annotations

from pathlib import Path

from aifd.providers._utils import split_recommended_suffix
from aifd.providers.claude import ClaudeProvider, _parse_auq_answer_text


def _answer_text(pairs: list[tuple[str, str]], suffix: str = "") -> str:
    """Build the 'Your questions have been answered: "Q"="A", ...' shape."""
    parts = ", ".join(f'"{q}"="{a}"' for q, a in pairs)
    return f"Your questions have been answered: {parts}.{suffix}"


def test_split_recommended_suffix_english() -> None:
    assert split_recommended_suffix("A) Add (recommended)") == ("A) Add", True)


def test_split_recommended_suffix_chinese() -> None:
    assert split_recommended_suffix("A) 添加 (推荐)") == ("A) 添加", True)


def test_split_recommended_suffix_japanese() -> None:
    assert split_recommended_suffix("A) 追加 (推奨)") == ("A) 追加", True)


def test_split_recommended_suffix_absent() -> None:
    assert split_recommended_suffix("B) Skip") == ("B) Skip", False)


def test_split_recommended_suffix_brackets() -> None:
    # Some hosts use [recommended] instead of (recommended).
    assert split_recommended_suffix("A) Add [recommended]") == ("A) Add", True)


def test_parse_auq_answer_text_single() -> None:
    text = _answer_text([("What now?", "A) Ship")], " You can now continue.")
    answers, notes = _parse_auq_answer_text(text)
    assert answers == {"What now?": "A) Ship"}
    assert notes is None


def test_parse_auq_answer_text_multi() -> None:
    text = _answer_text(
        [("Q1", "A1"), ("Q2 with spaces", "B2"), ("Q3", "C3, D3")]
    )
    answers, _ = _parse_auq_answer_text(text)
    assert answers == {"Q1": "A1", "Q2 with spaces": "B2", "Q3": "C3, D3"}


def test_parse_auq_answer_text_with_other_notes() -> None:
    text = (
        'Your questions have been answered: "Q"="Other: prefer dark mode".'
        ' Other: prefer dark mode'
    )
    _, notes = _parse_auq_answer_text(text)
    assert notes == "prefer dark mode"


def test_parse_auq_answer_text_no_match() -> None:
    answers, notes = _parse_auq_answer_text("totally unrelated string")
    assert answers == {}
    assert notes is None


def test_list_question_answers_single_call(
    make_claude_session, claude_root: Path
) -> None:
    """Happy path: one AUQ with one question matched to one answer."""
    make_claude_session(
        "sess-1",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_x",
                "questions": [
                    {
                        "question": "Should we ship?",
                        "options": [
                            {"label": "A) Yes (recommended)"},
                            {"label": "B) No"},
                        ],
                    }
                ],
                "answer_text": _answer_text([("Should we ship?", "A) Yes")]),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert len(rows) == 1
    qa = rows[0]
    assert qa.question == "Should we ship?"
    assert qa.options == ("A) Yes", "B) No")
    assert qa.recommended_option == "A) Yes"
    assert qa.chosen_option == "A) Yes"
    assert qa.tool_use_id == "toolu_x"
    assert qa.provider == "claude"
    assert qa.session_id == "sess-1"


def test_list_question_answers_multi_question_in_one_call(
    make_claude_session, claude_root: Path
) -> None:
    """A single AUQ tool_use with multiple questions emits one row per question
    with each question's own chosen answer."""
    make_claude_session(
        "sess-2",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_y",
                "questions": [
                    {
                        "question": "Q1",
                        "options": [{"label": "A1"}, {"label": "B1"}],
                    },
                    {
                        "question": "Q2",
                        "options": [{"label": "A2"}, {"label": "B2"}],
                    },
                ],
                "answer_text": _answer_text(
                    [("Q1", "A1"), ("Q2", "B2")]
                ),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert len(rows) == 2
    by_q = {qa.question: qa for qa in rows}
    assert by_q["Q1"].chosen_option == "A1"
    assert by_q["Q2"].chosen_option == "B2"


def test_list_question_answers_orphan_no_answer(
    make_claude_session, claude_root: Path
) -> None:
    """AUQ with no matching tool_result emits with chosen_option=None.

    Matches the observed 4.2% real-world orphan rate (interruption /
    compaction). User-facing this shows as 'no answer recorded' — not a
    bug, important retro signal.
    """
    make_claude_session(
        "sess-3",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_orphan",
                "questions": [
                    {
                        "question": "Was this asked?",
                        "options": [{"label": "A) Yes"}, {"label": "B) No"}],
                    }
                ],
                "answer_text": None,
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert len(rows) == 1
    assert rows[0].chosen_option is None
    assert rows[0].question == "Was this asked?"


def test_list_question_answers_empty_questions_skipped(
    make_claude_session, claude_root: Path
) -> None:
    """D5 decision: AUQ tool_use with empty questions array is silently skipped.

    Schema violation signal — not user-facing.
    """
    make_claude_session(
        "sess-4",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_empty",
                "questions": [],
                "answer_text": None,
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert rows == []


def test_list_question_answers_mcp_variant(
    make_claude_session, claude_root: Path
) -> None:
    """MCP host variants (mcp__foo__AskUserQuestion) are recognized."""
    make_claude_session(
        "sess-5",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_mcp",
                "tool_name": "mcp__conductor__AskUserQuestion",
                "questions": [
                    {
                        "question": "MCP question",
                        "options": [{"label": "A"}, {"label": "B"}],
                    }
                ],
                "answer_text": _answer_text([("MCP question", "A")]),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert len(rows) == 1
    assert rows[0].question == "MCP question"


def test_list_question_answers_chinese_recommended(
    make_claude_session, claude_root: Path
) -> None:
    """Chinese `(推荐)` suffix is detected as recommended."""
    make_claude_session(
        "sess-6",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_cn",
                "questions": [
                    {
                        "question": "选 A 还是 B?",
                        "options": [
                            {"label": "A) 选 A (推荐)"},
                            {"label": "B) 选 B"},
                        ],
                    }
                ],
                "answer_text": _answer_text(
                    [("选 A 还是 B?", "A) 选 A")]
                ),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert len(rows) == 1
    qa = rows[0]
    assert qa.recommended_option == "A) 选 A"
    assert qa.chosen_option == "A) 选 A"


def test_list_question_answers_multiselect_join(
    make_claude_session, claude_root: Path
) -> None:
    """multiSelect answer comes back as `A, B, C` literal — kept as-is."""
    make_claude_session(
        "sess-7",
        "/proj",
        auq_calls=[
            {
                "id": "toolu_multi",
                "questions": [
                    {
                        "question": "Pick many",
                        "options": [
                            {"label": "A"},
                            {"label": "B"},
                            {"label": "C"},
                        ],
                    }
                ],
                "answer_text": _answer_text([("Pick many", "A, B, C")]),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)
    rows = list(p.list_question_answers(Path("/proj")))
    assert rows[0].chosen_option == "A, B, C"


def test_list_question_answers_global_scope(
    make_claude_session, claude_root: Path
) -> None:
    """scope=None scans every project; scope=Path filters to one cwd."""
    make_claude_session(
        "s-here",
        "/here",
        auq_calls=[
            {
                "id": "id-here",
                "questions": [
                    {"question": "Q-here", "options": [{"label": "X"}]}
                ],
                "answer_text": _answer_text([("Q-here", "X")]),
            }
        ],
    )
    make_claude_session(
        "s-there",
        "/there",
        auq_calls=[
            {
                "id": "id-there",
                "questions": [
                    {"question": "Q-there", "options": [{"label": "Y"}]}
                ],
                "answer_text": _answer_text([("Q-there", "Y")]),
            }
        ],
    )
    p = ClaudeProvider(root=claude_root)

    global_rows = list(p.list_question_answers())
    assert {qa.question for qa in global_rows} == {"Q-here", "Q-there"}

    scoped_rows = list(p.list_question_answers(Path("/here")))
    assert [qa.question for qa in scoped_rows] == ["Q-here"]


def test_list_question_answers_default_protocol_for_codex(codex_root: Path) -> None:
    """CodexProvider returns empty — Codex has no structured AUQ."""
    from aifd.providers.codex import CodexProvider

    p = CodexProvider(root=codex_root)
    assert list(p.list_question_answers()) == []
    assert list(p.list_question_answers(Path("/anywhere"))) == []
