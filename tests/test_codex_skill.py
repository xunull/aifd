"""Tests for CodexProvider.list_skill_invocations (SQLite + jsonl fallback)."""

from __future__ import annotations

from pathlib import Path

from aifd.providers.codex import CodexProvider

# ---------- SQLite path ----------


def test_sqlite_extracts_skill_invocation(
    codex_db, codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("t1", str(cwd), skill="office-hours")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations())
    assert len(invs) == 1
    assert invs[0].skill_name == "office-hours"
    assert invs[0].provider == "codex"
    assert invs[0].cwd == cwd


def test_sqlite_ignores_non_skill_threads(
    codex_db, codex_root, tmp_path: Path
) -> None:
    """Threads where first_user_message doesn't start with `[$` are skipped."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("t1", str(cwd), first_user_message="just a regular question")
    codex_db("t2", str(cwd), skill="investigate")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations())
    assert [i.skill_name for i in invs] == ["investigate"]


def test_sqlite_scope_filter(codex_db, codex_root, tmp_path: Path) -> None:
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    codex_db("a1", str(cwd_a), skill="office-hours")
    codex_db("b1", str(cwd_b), skill="investigate")

    provider = CodexProvider(root=codex_root)
    invs_scoped = list(provider.list_skill_invocations(scope=cwd_a))
    assert [i.skill_name for i in invs_scoped] == ["office-hours"]


def test_sqlite_skill_name_normalized(
    codex_db, codex_root, tmp_path: Path
) -> None:
    """A Codex `[$gstack-office-hours]` should also normalize to `office-hours`."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("t1", str(cwd), skill="gstack-office-hours")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations())
    assert invs[0].skill_name == "office-hours"


# ---------- jsonl fallback path ----------


def _make_codex_rollout_with_skill(
    codex_root: Path, session_id: str, cwd: str, skill: str
) -> Path:
    """Build a Codex jsonl that mirrors what Codex writes when a user
    triggers a skill: session_meta first, then event_msg::user_message
    containing the [$skill] prefix.
    """
    import json

    sub = codex_root / "sessions" / "2026" / "06" / "02"
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"rollout-{session_id}.jsonl"

    meta = {
        "timestamp": "2026-06-01T10:00:00.000Z",
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "timestamp": "2026-06-01T10:00:00.000Z",
            "cwd": cwd,
        },
    }
    user_msg = {
        "timestamp": "2026-06-01T10:00:01.000Z",
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": f"[${skill}](/some/path.md) my question",
        },
    }
    with path.open("w") as f:
        f.write(json.dumps(meta) + "\n")
        f.write(json.dumps(user_msg) + "\n")
    return path


def test_jsonl_fallback_extracts_skill_when_sqlite_absent(
    codex_root, tmp_path: Path
) -> None:
    cwd = tmp_path / "proj"
    cwd.mkdir()
    _make_codex_rollout_with_skill(codex_root, "s1", str(cwd), "office-hours")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations())
    assert len(invs) == 1
    assert invs[0].skill_name == "office-hours"
    assert invs[0].provider == "codex"


def test_jsonl_fallback_scope_filter(codex_root, tmp_path: Path) -> None:
    cwd_a = tmp_path / "a"
    cwd_b = tmp_path / "b"
    cwd_a.mkdir()
    cwd_b.mkdir()
    _make_codex_rollout_with_skill(codex_root, "a1", str(cwd_a), "office-hours")
    _make_codex_rollout_with_skill(codex_root, "b1", str(cwd_b), "investigate")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations(scope=cwd_a))
    assert [i.skill_name for i in invs] == ["office-hours"]


def test_sqlite_short_circuits_jsonl_for_skills(
    codex_db, codex_root, tmp_path: Path
) -> None:
    """If SQLite returned rows we MUST NOT also scan jsonl (D3 short-circuit)."""
    cwd = tmp_path / "proj"
    cwd.mkdir()
    codex_db("from-sqlite", str(cwd), skill="office-hours")
    # Also drop a jsonl with a DIFFERENT skill. If both paths ran, we'd see 2.
    _make_codex_rollout_with_skill(codex_root, "from-jsonl-only", str(cwd), "investigate")

    provider = CodexProvider(root=codex_root)
    invs = list(provider.list_skill_invocations())
    assert {i.skill_name for i in invs} == {"office-hours"}


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    provider = CodexProvider(root=tmp_path / "nonexistent")
    assert list(provider.list_skill_invocations()) == []
