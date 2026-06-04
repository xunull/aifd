"""End-to-end CLI tests for `aifd ai question list`."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from aifd.cli import cli
from aifd.providers.claude import ClaudeProvider
from aifd.providers.codex import CodexProvider


def _answer_text(q: str, a: str) -> str:
    return f'Your questions have been answered: "{q}"="{a}". You can now continue.'


def test_question_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["ai", "question", "list", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output
    assert "--cwd" in result.output
    assert "--limit" in result.output
    assert "--all" in result.output


def test_question_list_empty_is_friendly(tmp_path: Path) -> None:
    runner = CliRunner()
    fake_root = tmp_path / "no-claude"
    fake_codex = tmp_path / "no-codex"
    with patch(
        "aifd.cli.ai.question.PROVIDERS",
        [ClaudeProvider(root=fake_root), CodexProvider(root=fake_codex)],
    ):
        result = runner.invoke(cli, ["ai", "question", "list"])
    assert result.exit_code == 0
    assert "No AskUserQuestion calls found" in result.output


def test_question_list_global_scan(
    tmp_path: Path, make_claude_session, claude_root: Path
) -> None:
    """No --cwd → global scan finds questions across all projects."""
    make_claude_session(
        "s1",
        "/proj-a",
        auq_calls=[
            {
                "id": "id-a",
                "questions": [
                    {"question": "From A", "options": [{"label": "X"}]}
                ],
                "answer_text": _answer_text("From A", "X"),
            }
        ],
    )
    make_claude_session(
        "s2",
        "/proj-b",
        auq_calls=[
            {
                "id": "id-b",
                "questions": [
                    {"question": "From B", "options": [{"label": "Y"}]}
                ],
                "answer_text": _answer_text("From B", "Y"),
            }
        ],
    )
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(cli, ["ai", "question", "list", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    questions = {row["question"] for row in parsed}
    assert questions == {"From A", "From B"}


def test_question_list_cwd_filter(
    tmp_path: Path, make_claude_session, claude_root: Path, monkeypatch
) -> None:
    """--cwd narrows to current directory only."""
    cwd = tmp_path / "here"
    cwd.mkdir()
    make_claude_session(
        "here-s",
        str(cwd),
        auq_calls=[
            {
                "id": "id-here",
                "questions": [
                    {"question": "Q-here", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Q-here", "A"),
            }
        ],
    )
    make_claude_session(
        "there-s",
        "/somewhere-else",
        auq_calls=[
            {
                "id": "id-there",
                "questions": [
                    {"question": "Q-there", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Q-there", "A"),
            }
        ],
    )
    monkeypatch.chdir(cwd)
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--cwd", "--json"]
        )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert {row["question"] for row in parsed} == {"Q-here"}


def test_question_list_limit_caps_rows(
    make_claude_session, claude_root: Path
) -> None:
    """--limit caps the row count after sort. --all overrides."""
    auq_calls = [
        {
            "id": f"id-{i}",
            "timestamp": f"2026-06-{i+1:02d}T10:00:00.000Z",
            "questions": [
                {"question": f"Q{i}", "options": [{"label": "A"}]}
            ],
            "answer_text": _answer_text(f"Q{i}", "A"),
        }
        for i in range(5)
    ]
    make_claude_session("s1", "/proj", auq_calls=auq_calls)

    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--limit", "2", "--json"]
        )
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert len(parsed) == 2  # capped

    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--all", "--json"]
        )
    parsed = json.loads(result.output)
    assert len(parsed) == 5  # uncapped


def test_question_list_provider_filter(
    make_claude_session, claude_root: Path, codex_root: Path
) -> None:
    """--provider codex returns 0 (Codex has no AUQ); --provider claude returns rows."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id-c",
                "questions": [
                    {"question": "claude q", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("claude q", "A"),
            }
        ],
    )
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS",
        [ClaudeProvider(root=claude_root), CodexProvider(root=codex_root)],
    ):
        result = runner.invoke(
            cli,
            ["ai", "question", "list", "--provider", "codex", "--json"],
        )
    assert json.loads(result.output) == []

    with patch(
        "aifd.cli.ai.question.PROVIDERS",
        [ClaudeProvider(root=claude_root), CodexProvider(root=codex_root)],
    ):
        result = runner.invoke(
            cli,
            ["ai", "question", "list", "--provider", "claude", "--json"],
        )
    assert len(json.loads(result.output)) == 1


def test_question_list_sort_newest_first(
    make_claude_session, claude_root: Path
) -> None:
    """Rows sort by timestamp desc, so newest is first."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id-old",
                "timestamp": "2026-01-01T10:00:00.000Z",
                "questions": [
                    {"question": "old", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("old", "A"),
            },
            {
                "id": "id-new",
                "timestamp": "2026-06-01T10:00:00.000Z",
                "questions": [
                    {"question": "new", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("new", "A"),
            },
        ],
    )
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--json"]
        )
    parsed = json.loads(result.output)
    assert [row["question"] for row in parsed] == ["new", "old"]


# ---------------------------------------------------------------------------
# --html / --output / --open  (v0.3.1)
# ---------------------------------------------------------------------------


def test_question_list_html_stdout(
    make_claude_session, claude_root: Path
) -> None:
    """--html prints a self-contained HTML page to stdout."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id1",
                "questions": [
                    {"question": "Why?", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Why?", "A"),
            }
        ],
    )
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--html"]
        )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("<!DOCTYPE html>")
    assert "Why?" in result.output


def test_question_list_html_output_file(
    tmp_path: Path, make_claude_session, claude_root: Path
) -> None:
    """--html --output writes HTML to the file and prints path on stderr."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id1",
                "questions": [
                    {"question": "Why?", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Why?", "A"),
            }
        ],
    )
    out = tmp_path / "q.html"
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli,
            ["ai", "question", "list", "--html", "--output", str(out)],
        )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "<!DOCTYPE html>" in out.read_text(encoding="utf-8")
    # `Wrote <path>` is on stderr in click 8.4+ (stderr captured separately)
    assert f"Wrote {out}" in result.stderr


def test_question_list_html_and_json_mutex() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli, ["ai", "question", "list", "--html", "--json"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_question_list_output_alone_implies_html(
    tmp_path: Path, make_claude_session, claude_root: Path
) -> None:
    """--output alone (no --html) is fine; it implies HTML mode."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id1",
                "questions": [
                    {"question": "Q", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Q", "A"),
            }
        ],
    )
    out = tmp_path / "q.html"
    runner = CliRunner()
    with patch(
        "aifd.cli.ai.question.PROVIDERS", [ClaudeProvider(root=claude_root)]
    ):
        result = runner.invoke(
            cli, ["ai", "question", "list", "--output", str(out)]
        )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "<!DOCTYPE html>" in out.read_text(encoding="utf-8")


def test_question_list_output_unwritable_path_friendly_error(
    tmp_path: Path,
) -> None:
    """D4=A: write failure surfaces as a one-line error + exit 1, not a
    Python traceback."""
    runner = CliRunner()
    # A directory that does not exist and cannot be created mid-flight
    # because the parent is a file.
    parent_as_file = tmp_path / "blocker"
    parent_as_file.write_text("not a directory")
    target = parent_as_file / "q.html"  # writing inside a file → OSError
    result = runner.invoke(
        cli,
        ["ai", "question", "list", "--html", "--output", str(target)],
    )
    assert result.exit_code == 1
    # Friendly error goes to stderr (separate stream in click 8.4+).
    err = result.stderr
    assert "Error: cannot write to" in err
    assert str(target) in err


def test_question_list_open_calls_webbrowser(
    tmp_path: Path, make_claude_session, claude_root: Path
) -> None:
    """--open invokes webbrowser.open with the file:// URI."""
    make_claude_session(
        "s1",
        "/proj",
        auq_calls=[
            {
                "id": "id1",
                "questions": [
                    {"question": "Q", "options": [{"label": "A"}]}
                ],
                "answer_text": _answer_text("Q", "A"),
            }
        ],
    )
    out = tmp_path / "q.html"
    runner = CliRunner()
    with (
        patch(
            "aifd.cli.ai.question.PROVIDERS",
            [ClaudeProvider(root=claude_root)],
        ),
        patch("aifd.cli.ai.question.webbrowser.open") as wb_open,
    ):
        result = runner.invoke(
            cli,
            [
                "ai",
                "question",
                "list",
                "--html",
                "--output",
                str(out),
                "--open",
            ],
        )
    assert result.exit_code == 0, result.output
    assert wb_open.called
    called_url = wb_open.call_args[0][0]
    assert called_url.startswith("file://")
    assert called_url.endswith("q.html")
