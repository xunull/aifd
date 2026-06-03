"""Shared pytest fixtures."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path

import pytest


def _encode_cwd(cwd: str) -> str:
    return cwd.replace("/", "-")


def write_jsonl(path: Path, lines: Iterable[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for line in lines:
            if isinstance(line, str):
                f.write(line + "\n")
            else:
                f.write(json.dumps(line) + "\n")


@pytest.fixture
def claude_root(tmp_path: Path) -> Path:
    """Empty Claude root; tests populate as needed via `make_claude_session`."""
    root = tmp_path / "claude" / "projects"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def make_claude_session(claude_root: Path):
    """Factory: create a Claude jsonl with the given cwd in the right directory."""

    def _factory(
        session_id: str,
        cwd: str,
        *,
        extra_events: int = 0,
        bad_lines: int = 0,
        no_cwd_event: bool = False,
        timestamp: str = "2026-06-01T10:00:00.000Z",
        ai_title: str | None = None,
        user_text: str | None = None,
        skills: list[str] | None = None,
    ) -> Path:
        project_dir = claude_root / _encode_cwd(cwd)
        jsonl = project_dir / f"{session_id}.jsonl"

        lines: list[dict | str] = [
            {"type": "last-prompt", "sessionId": session_id, "leafUuid": "x"},
            {"type": "permission-mode", "permissionMode": "default"},
        ]
        if not no_cwd_event:
            lines.append(
                {
                    "parentUuid": None,
                    "type": "user",
                    "cwd": cwd,
                    "gitBranch": "main",
                    "sessionId": session_id,
                    "timestamp": timestamp,
                    "message": {"content": user_text or "Hello"},
                }
            )
        # Add slash-command markers as additional user messages
        for skill_name in skills or []:
            lines.append(
                {
                    "type": "user",
                    "cwd": cwd,
                    "sessionId": session_id,
                    "timestamp": timestamp,
                    "message": {
                        "content": f"<command-name>{skill_name}</command-name>\nbody"
                    },
                }
            )
        if ai_title is not None:
            lines.append(
                {"type": "ai-title", "aiTitle": ai_title, "sessionId": session_id}
            )
        for i in range(extra_events):
            lines.append({"type": "assistant", "timestamp": timestamp, "n": i})
        for _ in range(bad_lines):
            lines.append("{not valid json")

        write_jsonl(jsonl, lines)
        return jsonl

    return _factory


@pytest.fixture
def codex_root(tmp_path: Path) -> Path:
    """Empty Codex root; tests populate as needed."""
    return tmp_path / "codex"


@pytest.fixture
def claude_skills_root(tmp_path: Path) -> Path:
    """Empty Claude user-installed skills root."""
    p = tmp_path / "claude_skills"
    p.mkdir()
    return p


@pytest.fixture
def claude_plugins_root(tmp_path: Path) -> Path:
    """Empty Claude plugin cache root."""
    p = tmp_path / "claude_plugins"
    p.mkdir()
    return p


@pytest.fixture
def codex_skills_root(tmp_path: Path) -> Path:
    """Empty Codex skills root."""
    p = tmp_path / "codex_skills"
    p.mkdir()
    return p


def write_skill_md(
    skill_dir: Path,
    *,
    name: str | None = None,
    description: str | None = None,
    version: str | None = None,
    extra_frontmatter: str = "",
    no_frontmatter: bool = False,
) -> Path:
    """Write a SKILL.md with the given frontmatter under skill_dir.

    `no_frontmatter=True` skips the `---` block entirely (degenerate
    case test). `extra_frontmatter` is raw lines inserted after the
    parsed fields (e.g. for list-value fields like allowed-tools).
    """
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / "SKILL.md"
    if no_frontmatter:
        md.write_text("Body without frontmatter.\n", encoding="utf-8")
        return md

    lines: list[str] = ["---"]
    if name is not None:
        lines.append(f"name: {name}")
    if description is not None:
        lines.append(f"description: {description}")
    if version is not None:
        lines.append(f"version: {version}")
    if extra_frontmatter:
        lines.append(extra_frontmatter.rstrip())
    lines.append("---")
    lines.append("")
    lines.append("Body content.")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


# Minimal schema mirroring ~/.codex/state_5.sqlite — just the columns
# CodexProvider reads. NOT NULL DEFAULT '' lets tests omit optional cols.
_CODEX_DB_SCHEMA = """
CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    rollout_path TEXT NOT NULL,
    cwd TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    first_user_message TEXT NOT NULL DEFAULT '',
    preview TEXT NOT NULL DEFAULT '',
    created_at_ms INTEGER,
    archived INTEGER NOT NULL DEFAULT 0
);
"""


@pytest.fixture
def codex_db(codex_root: Path):
    """Factory: create state_5.sqlite under codex_root, return a thread-inserter.

    The inserter signature: insert(id, cwd, *, title='', preview='',
    first_user_message='', archived=0, rollout_path=None, created_at_ms=0).
    """
    codex_root.mkdir(parents=True, exist_ok=True)
    db_path = codex_root / "state_5.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(_CODEX_DB_SCHEMA)
    conn.commit()
    conn.close()

    def _insert(
        id: str,
        cwd: str,
        *,
        title: str = "",
        preview: str = "",
        first_user_message: str = "",
        archived: int = 0,
        rollout_path: str | None = None,
        created_at_ms: int = 1717200000000,
        skill: str | None = None,
    ) -> None:
        # When `skill` is provided, build the `[$skill]` first_user_message
        # exactly the way Codex writes it. Lets tests stay concise.
        if skill is not None and not first_user_message:
            first_user_message = f"[${skill}](/path/to/skill.md) followup"
        c = sqlite3.connect(db_path)
        c.execute(
            "INSERT INTO threads(id, rollout_path, cwd, title, first_user_message, "
            "preview, created_at_ms, archived) VALUES (?,?,?,?,?,?,?,?)",
            (
                id,
                rollout_path or f"/fake/rollout-{id}.jsonl",
                cwd,
                title,
                first_user_message,
                preview,
                created_at_ms,
                archived,
            ),
        )
        c.commit()
        c.close()

    return _insert


@pytest.fixture
def make_codex_rollout(codex_root: Path):
    """Factory: create a Codex rollout-*.jsonl in sessions/ or archived_sessions/."""

    def _factory(
        session_id: str,
        cwd: str,
        *,
        archived: bool = False,
        timestamp: str = "2026-06-01T10:00:00.000Z",
        extra_events: int = 0,
        bad_first_line: bool = False,
        user_message: str | None = None,
    ) -> Path:
        if archived:
            sub = codex_root / "archived_sessions"
        else:
            sub = codex_root / "sessions" / "2026" / "06" / "01"
        sub.mkdir(parents=True, exist_ok=True)

        path = sub / f"rollout-{timestamp.replace(':', '-')}-{session_id}.jsonl"

        meta = {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": timestamp,
                "cwd": cwd,
                "originator": "test",
            },
        }
        lines: list[dict | str] = [meta]
        if bad_first_line:
            lines = ["{not valid json"]
        if user_message is not None:
            lines.append(
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": user_message},
                }
            )
        for i in range(extra_events):
            lines.append({"type": "user_msg", "n": i})

        write_jsonl(path, lines)
        return path

    return _factory
