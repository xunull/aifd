"""Tests for the Claude provider — D2 two-phase + D7 three-tier errors."""

from __future__ import annotations

from pathlib import Path

from aifd.providers.claude import ClaudeProvider


def test_lists_matching_session(claude_root, make_claude_session, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("sess-1", str(cwd), extra_events=5)

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))

    assert len(sessions) == 1
    assert sessions[0].provider == "claude"
    assert sessions[0].session_id == "sess-1"
    assert sessions[0].cwd == cwd
    assert sessions[0].started_at is not None
    # 2 meta lines + 1 cwd event + 5 extra = 8 events
    assert sessions[0].event_count == 8


def test_ignores_non_matching_cwd(claude_root, make_claude_session, tmp_path: Path) -> None:
    """File exists in candidate dir but its inner cwd points elsewhere."""
    cwd = tmp_path / "right"
    elsewhere = tmp_path / "wrong"
    cwd.mkdir()
    elsewhere.mkdir()
    # We craft the encoded dir to look like a hit for `cwd`, but the inner
    # jsonl's cwd field points to `elsewhere`. Phase 2 must reject it.
    encoded = str(cwd).replace("/", "-")
    project_dir = claude_root / encoded
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "fakeid.jsonl"
    import json

    with jsonl.open("w") as f:
        f.write(json.dumps({"type": "last-prompt"}) + "\n")
        f.write(json.dumps({"type": "user", "cwd": str(elsewhere)}) + "\n")

    provider = ClaudeProvider(root=claude_root)
    assert list(provider.list_sessions(cwd)) == []


def test_silent_skip_when_no_cwd_event(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    # Build a file that lives in `cwd`'s encoded dir but has no cwd event.
    encoded = str(cwd).replace("/", "-")
    project_dir = claude_root / encoded
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "empty.jsonl"
    import json

    with jsonl.open("w") as f:
        f.write(json.dumps({"type": "last-prompt"}) + "\n")
        f.write(json.dumps({"type": "permission-mode"}) + "\n")

    provider = ClaudeProvider(root=claude_root)
    assert list(provider.list_sessions(cwd)) == []


def test_malformed_line_does_not_break_file(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    """D7: a single bad line shouldn't disqualify the whole file."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = str(cwd).replace("/", "-")
    project_dir = claude_root / encoded
    project_dir.mkdir(parents=True)
    jsonl = project_dir / "mixed.jsonl"
    import json

    with jsonl.open("w") as f:
        f.write("{ not json\n")  # malformed
        f.write(json.dumps({"type": "last-prompt"}) + "\n")
        f.write(json.dumps({"type": "user", "cwd": str(cwd)}) + "\n")
        f.write("also broken {\n")
        f.write(json.dumps({"type": "assistant"}) + "\n")

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))
    assert len(sessions) == 1
    assert sessions[0].session_id == "mixed"


def test_root_missing_yields_nothing(tmp_path: Path) -> None:
    provider = ClaudeProvider(root=tmp_path / "does-not-exist")
    assert list(provider.list_sessions(tmp_path)) == []


def test_extracts_ai_title_when_present(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session("with-title", str(cwd), ai_title="Refactor the auth module")

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "Refactor the auth module"


def test_falls_back_to_user_text_when_no_ai_title(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session(
        "fallback",
        str(cwd),
        user_text="Please help me debug this race condition",
    )

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "Please help me debug this race condition"


def test_skips_system_injection_for_title(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    """Skill-injected user messages start with '<' or 'Base directory for' or
    'Caveat'. These should NOT be used as titles."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session(
        "sys", str(cwd), user_text="<local-command-caveat> noise content"
    )

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title is None


def test_ai_title_wins_over_user_text(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_claude_session(
        "both",
        str(cwd),
        ai_title="Concise AI title",
        user_text="A much longer original user message that we should not use",
    )

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "Concise AI title"


def test_path_containing_dash_resolves_correctly(
    claude_root, make_claude_session, tmp_path: Path
) -> None:
    """D2 reason: encoding is lossy for paths with '-'. Phase 2 must save us."""
    real_cwd = tmp_path / "some-project"
    real_cwd.mkdir()
    make_claude_session("real", str(real_cwd))

    # Create a noise project dir whose encoded name shares a prefix.
    other = tmp_path / "some" / "project"
    other.mkdir(parents=True)
    make_claude_session("other", str(other))

    provider = ClaudeProvider(root=claude_root)
    sessions = list(provider.list_sessions(real_cwd))

    ids = {s.session_id for s in sessions}
    # Phase 2 must filter out 'other' even though its dir name could
    # ambiguously resemble real_cwd's encoding.
    assert "real" in ids
    assert "other" not in ids
