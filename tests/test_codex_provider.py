"""Tests for the Codex provider.

Architecture: SQLite (state_5.sqlite) is the primary source; jsonl scan
is fallback. Tests cover both paths.
"""

from __future__ import annotations

from pathlib import Path

from aifd.providers.codex import CodexProvider

# ---------- SQLite-first (primary) path ----------


def test_sqlite_lists_matching_thread(codex_db, codex_root, tmp_path: Path) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("sess-1", str(cwd), title="Refactor auth module")

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))

    assert len(sessions) == 1
    assert sessions[0].session_id == "sess-1"
    assert sessions[0].title == "Refactor auth module"
    assert sessions[0].cwd == cwd
    assert sessions[0].provider == "codex"


def test_sqlite_filters_by_cwd(codex_db, codex_root, tmp_path: Path) -> None:
    cwd = tmp_path / "right"
    elsewhere = tmp_path / "wrong"
    cwd.mkdir()
    elsewhere.mkdir()
    codex_db("ours", str(cwd), title="In scope")
    codex_db("theirs", str(elsewhere), title="Out of scope")

    provider = CodexProvider(root=codex_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"ours"}


def test_sqlite_includes_archived_threads(
    codex_db, codex_root, tmp_path: Path
) -> None:
    """Spirit of `list everything for this cwd` — archived shows up too."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("active", str(cwd), archived=0)
    codex_db("archived", str(cwd), archived=1)

    provider = CodexProvider(root=codex_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"active", "archived"}


def test_sqlite_title_falls_back_to_preview(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("no-title", str(cwd), title="", preview="short preview text")

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "short preview text"


def test_sqlite_title_falls_back_to_first_user_message(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db(
        "no-title-no-preview",
        str(cwd),
        title="",
        preview="",
        first_user_message="please debug this race condition",
    )

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "please debug this race condition"


def test_sqlite_source_path_uses_rollout_path(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    rollout = "/Users/x/.codex/sessions/2026/06/02/rollout-abc.jsonl"
    codex_db("s1", str(cwd), rollout_path=rollout)

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert str(sessions[0].source_path) == rollout


def test_sqlite_started_at_uses_created_at_ms(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    # 2026-06-02T00:00:00 UTC
    codex_db("s1", str(cwd), created_at_ms=1780617600000)

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].started_at is not None
    assert sessions[0].started_at.year == 2026


def test_sqlite_orders_results_newest_first(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("old", str(cwd), created_at_ms=1_000_000)
    codex_db("new", str(cwd), created_at_ms=2_000_000)

    provider = CodexProvider(root=codex_root)
    ids = [s.session_id for s in provider.list_sessions(cwd)]
    assert ids == ["new", "old"]


# ---------- jsonl fallback path (no SQLite present) ----------


def test_jsonl_fallback_when_sqlite_absent(
    codex_root, make_codex_rollout, tmp_path: Path
) -> None:
    """No state_5.sqlite -> fall back to file scan."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_codex_rollout("sess-1", str(cwd))

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert len(sessions) == 1
    assert sessions[0].session_id == "sess-1"


def test_jsonl_fallback_picks_up_archived(
    codex_root, make_codex_rollout, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_codex_rollout("archived-1", str(cwd), archived=True)

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].session_id == "archived-1"


def test_jsonl_fallback_extracts_user_message_title(
    codex_root, make_codex_rollout, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_codex_rollout(
        "with-title",
        str(cwd),
        user_message="Add parallel test execution support",
    )

    provider = CodexProvider(root=codex_root)
    sessions = list(provider.list_sessions(cwd))
    assert sessions[0].title == "Add parallel test execution support"


def test_jsonl_fallback_handles_malformed_first_line(
    codex_root, make_codex_rollout, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    make_codex_rollout("bad", str(cwd), bad_first_line=True)

    provider = CodexProvider(root=codex_root)
    assert list(provider.list_sessions(cwd)) == []


def test_root_missing_yields_nothing(tmp_path: Path) -> None:
    provider = CodexProvider(root=tmp_path / "does-not-exist")
    assert list(provider.list_sessions(tmp_path)) == []


def test_sqlite_short_circuits_jsonl(
    codex_db, codex_root, make_codex_rollout, tmp_path: Path
) -> None:
    """If SQLite returns rows we MUST NOT also scan jsonl (would dedup wrong)."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("from-sqlite", str(cwd), title="SQLite version")
    # Also put a different-id rollout file under the same cwd. If both
    # paths ran, we'd see 2 sessions; SQLite-first means we only see 1.
    make_codex_rollout("from-jsonl-only", str(cwd))

    provider = CodexProvider(root=codex_root)
    ids = {s.session_id for s in provider.list_sessions(cwd)}
    assert ids == {"from-sqlite"}  # jsonl skipped because SQLite served the answer
