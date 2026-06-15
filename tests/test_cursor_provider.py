"""Tests for the Cursor provider.

Cursor splits sessions (globalStorage) from cwd (workspaceStorage). These tests
exercise the cross-store join, the empty-shell filter (E3), hash-only cwd
mapping (E1), the unmapped/timestamp-wsid cases (E5), and early-return (E6).
"""

from __future__ import annotations

import sys
from pathlib import Path

from aifd.providers.cursor import CursorProvider, _safe_int

HASH_A = "a" * 32  # valid 32-hex workspace hash
HASH_B = "b" * 32


# ---------- _default_root (E2 cross-platform) ----------


def test_default_root_darwin(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    root = CursorProvider._default_root()
    assert root.parts[-3:] == ("Cursor", "User") or "Application Support" in str(root)
    assert str(root).endswith("Cursor/User")


def test_default_root_linux_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    root = CursorProvider._default_root()
    assert root == tmp_path / "cfg" / "Cursor" / "User"


def test_default_root_linux_no_xdg(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    root = CursorProvider._default_root()
    assert root == Path.home() / ".config" / "Cursor" / "User"


# ---------- list_sessions ----------


def test_lists_real_session_with_cwd(cursor_db, cursor_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("ses-1", name="Fix the bug", ws_id=HASH_A, bubbles=3)

    provider = CursorProvider(root=cursor_root)
    sessions = list(provider.list_sessions(cwd))

    assert len(sessions) == 1
    assert sessions[0].session_id == "ses-1"
    assert sessions[0].title == "Fix the bug"
    assert sessions[0].cwd == cwd
    assert sessions[0].provider == "cursor"
    assert sessions[0].event_count == 3  # bubble count


def test_empty_shell_filtered(cursor_db, cursor_root, tmp_path: Path) -> None:
    """E3: composer with no bubbles is a shell — must not appear."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("real", name="Real", ws_id=HASH_A, bubbles=2)
    cursor_db.add_composer("shell", name="Shell", ws_id=HASH_A, bubbles=0)

    provider = CursorProvider(root=cursor_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"real"}


def test_filters_by_cwd(cursor_db, cursor_root, tmp_path: Path) -> None:
    right = tmp_path / "right"
    wrong = tmp_path / "wrong"
    right.mkdir()
    wrong.mkdir()
    cursor_db.add_workspace(HASH_A, str(right))
    cursor_db.add_workspace(HASH_B, str(wrong))
    cursor_db.add_composer("ours", ws_id=HASH_A, bubbles=1)
    cursor_db.add_composer("theirs", ws_id=HASH_B, bubbles=1)

    provider = CursorProvider(root=cursor_root)
    ids = {s.session_id for s in provider.list_sessions(right)}
    assert ids == {"ours"}


def test_early_return_when_cwd_not_a_workspace(cursor_db, cursor_root, tmp_path: Path) -> None:
    """E6: querying a cwd that matches no workspace yields nothing (no scan)."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("ses-1", ws_id=HASH_A, bubbles=1)

    provider = CursorProvider(root=cursor_root)
    assert list(provider.list_sessions(other)) == []


def test_timestamp_wsid_unmapped_prints_count(
    cursor_db, cursor_root, tmp_path: Path, capsys
) -> None:
    """E5: a real session with timestamp-form wsid has no cwd → stderr count."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("mapped", ws_id=HASH_A, bubbles=1)
    # timestamp-form wsid: real session (has bubbles) but no disk workspace
    cursor_db.add_composer("orphan", ws_id="1781000000000", bubbles=5)

    provider = CursorProvider(root=cursor_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"mapped"}  # orphan not shown under this cwd

    err = capsys.readouterr().err
    assert "1 Cursor session" in err
    assert "no resolvable cwd" in err


def test_no_stderr_when_all_mapped(cursor_db, cursor_root, tmp_path: Path, capsys) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("ses-1", ws_id=HASH_A, bubbles=1)

    provider = CursorProvider(root=cursor_root)
    list(provider.list_sessions(cwd))
    assert "no resolvable cwd" not in capsys.readouterr().err


def test_missing_db_yields_nothing(tmp_path: Path) -> None:
    provider = CursorProvider(root=tmp_path / "no-cursor")
    assert list(provider.list_sessions(tmp_path)) == []


def test_started_at_from_created_at(cursor_db, cursor_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("s1", ws_id=HASH_A, bubbles=1, created_at=1780617600000)

    provider = CursorProvider(root=cursor_root)
    s = next(iter(provider.list_sessions(cwd)))
    assert s.started_at is not None
    assert s.started_at.year == 2026


def test_empty_name_title_none(cursor_db, cursor_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("s1", name="", ws_id=HASH_A, bubbles=1)

    provider = CursorProvider(root=cursor_root)
    assert next(iter(provider.list_sessions(cwd))).title is None


# ---------- iter_all_sessions (E3) ----------


def test_iter_all_includes_unmapped_real_sessions(cursor_db, cursor_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("mapped", ws_id=HASH_A, bubbles=2)
    cursor_db.add_composer("orphan", ws_id="1781000000000", bubbles=4)
    cursor_db.add_composer("shell", ws_id=HASH_A, bubbles=0)  # filtered

    provider = CursorProvider(root=cursor_root)
    sessions = {s.session_id: s for s in provider.iter_all_sessions()}
    assert set(sessions) == {"mapped", "orphan"}  # shell excluded, orphan kept
    assert sessions["mapped"].cwd == cwd
    assert str(sessions["orphan"].cwd) == "."  # Path("") sentinel


def test_iter_all_missing_db(tmp_path: Path) -> None:
    provider = CursorProvider(root=tmp_path / "no-db")
    assert list(provider.iter_all_sessions()) == []


# ---------- list_token_usage (best-effort) ----------


def test_token_usage_emits_when_tokencount_present(cursor_db, cursor_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    cursor_db.add_workspace(HASH_A, str(cwd))
    cursor_db.add_composer("with-tok", ws_id=HASH_A, bubbles=1, token_count=1234)
    cursor_db.add_composer("no-tok", ws_id=HASH_A, bubbles=1, token_count=None)
    cursor_db.add_composer("zero-tok", ws_id=HASH_A, bubbles=1, token_count=0)

    provider = CursorProvider(root=cursor_root)
    usages = {u.session_id: u for u in provider.list_token_usage()}
    assert set(usages) == {"with-tok"}
    assert usages["with-tok"].input_tokens == 1234
    assert usages["with-tok"].provider == "cursor"


def test_token_usage_scope_filter(cursor_db, cursor_root, tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    cursor_db.add_workspace(HASH_A, str(a))
    cursor_db.add_workspace(HASH_B, str(b))
    cursor_db.add_composer("in-a", ws_id=HASH_A, bubbles=1, token_count=100)
    cursor_db.add_composer("in-b", ws_id=HASH_B, bubbles=1, token_count=200)

    provider = CursorProvider(root=cursor_root)
    ids = {u.session_id for u in provider.list_token_usage(scope=a)}
    assert ids == {"in-a"}


def test_token_usage_missing_db(tmp_path: Path) -> None:
    provider = CursorProvider(root=tmp_path / "no-db")
    assert list(provider.list_token_usage()) == []


# ---------- no-op stubs ----------


def test_stubs_return_empty(cursor_root) -> None:
    provider = CursorProvider(root=cursor_root)
    assert list(provider.list_installed_skills()) == []
    assert list(provider.list_skill_invocations()) == []
    assert list(provider.list_question_answers()) == []


# ---------- _safe_int helper ----------


def test_safe_int() -> None:
    assert _safe_int(42) == 42
    assert _safe_int(3.9) == 3
    assert _safe_int(None) == 0
    assert _safe_int("x") == 0
    assert _safe_int(True) == 0  # bool guard
