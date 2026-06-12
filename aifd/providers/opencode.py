"""OpenCode provider.

Storage layout:
    PRIMARY: ~/.local/share/opencode/opencode.db  (XDG_DATA_HOME convention)
             table `session` — one row per session
             columns: id, directory (=cwd), title, time_created (ms epoch),
                      model (JSON), parent_id,
                      tokens_input, tokens_output, tokens_reasoning,
                      tokens_cache_read, tokens_cache_write

    SKILLS: ~/.config/opencode/skills/{name}/SKILL.md
            (XDG_CONFIG_HOME convention)

Design decisions (locked in /plan-eng-review):
  D1 — Sub-sessions (parent_id != NULL) are included — not filtered.
  D2 — Only token counts tracked; cost field is 0 in practice, skipped.
  D3 — list_installed_skills() implemented; list_skill_invocations() returns ().
  D4 — iter_all_sessions() implemented for aifd ai retro / habits.

D7 error handling (consistent with Codex):
  - SQLite open / query failure → warning + return empty
  - Row with missing/invalid directory → silent skip
  - Skill directory with no SKILL.md → silent skip
"""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation, TokenUsage
from aifd.paths import cwd_equal, normalize_cwd
from aifd.providers._utils import (
    normalize_title,
    parse_opencode_model,
    parse_skill_frontmatter,
)

logger = logging.getLogger("aifd.providers.opencode")


class OpenCodeProvider:
    name = "opencode"

    def __init__(
        self,
        root: Path | None = None,
        skills_root: Path | None = None,
    ) -> None:
        """Args:
            root: directory containing opencode.db. Defaults to the
                XDG_DATA_HOME-based path (~/.local/share/opencode).
                Tests inject a temp directory.
            skills_root: directory containing per-skill subdirs with SKILL.md.
                Defaults to ~/.config/opencode/skills.
        """
        if root is None:
            root = self._default_root()
        self.root = root
        self.skills_root = skills_root or self._default_skills_root()

    @staticmethod
    def _default_root() -> Path:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        if xdg:
            return Path(xdg) / "opencode"
        return Path.home() / ".local" / "share" / "opencode"

    @staticmethod
    def _default_skills_root() -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg:
            return Path(xdg) / "opencode" / "skills"
        return Path.home() / ".config" / "opencode" / "skills"

    def _db_path(self) -> Path:
        return self.root / "opencode.db"

    # ------------------------------------------------------------------
    # list_sessions
    # ------------------------------------------------------------------

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        target = normalize_cwd(cwd)
        db_path = self._db_path()
        if not db_path.is_file():
            logger.debug("OpenCode DB not found at %s", db_path)
            return
        try:
            yield from self._query_sessions(db_path, target)
        except sqlite3.Error as exc:
            logger.warning("OpenCode SQLite error listing sessions: %s", exc)

    def _query_sessions(
        self, db_path: Path, target: Path | None
    ) -> Iterator[Session]:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            if target is not None:
                rows = conn.execute(
                    """
                    SELECT id, directory, title, time_created
                    FROM session
                    WHERE directory = ?
                    ORDER BY time_created DESC
                    """,
                    (str(target),),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, directory, title, time_created
                    FROM session
                    ORDER BY time_created DESC
                    """,
                ).fetchall()
        finally:
            conn.close()

        for row in rows:
            dir_raw = row["directory"]
            if not isinstance(dir_raw, str) or not dir_raw:
                continue
            session_cwd = Path(dir_raw)
            # Defensive re-check: WHERE used normalized string; cwd_equal
            # handles symlinks / case differences that the string match missed.
            if target is not None and not cwd_equal(normalize_cwd(session_cwd), target):
                continue
            yield _row_to_session(row, session_cwd, db_path, self.name)

    # ------------------------------------------------------------------
    # iter_all_sessions  (used by aifd ai retro / habits)
    # ------------------------------------------------------------------

    def iter_all_sessions(self) -> Iterator[Session]:
        db_path = self._db_path()
        if not db_path.is_file():
            return
        try:
            yield from self._query_sessions(db_path, target=None)
        except sqlite3.Error as exc:
            logger.warning("OpenCode global SQLite error: %s", exc)

    # ------------------------------------------------------------------
    # list_token_usage
    # ------------------------------------------------------------------

    def list_token_usage(
        self, scope: Path | None = None
    ) -> Iterable[TokenUsage]:
        """Yield one TokenUsage per session that has non-zero token counts.

        OpenCode stores cumulative session totals directly on the session
        row — no per-event scanning needed (unlike Codex jsonl).
        D2: cost field is skipped (0 in practice); only token counts emitted.
        """
        db_path = self._db_path()
        if not db_path.is_file():
            return

        target = normalize_cwd(scope) if scope is not None else None
        uri = f"file:{db_path}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=5.0)
            try:
                conn.row_factory = sqlite3.Row
                if target is not None:
                    rows = conn.execute(
                        """
                        SELECT id, directory, model, time_created,
                               tokens_input, tokens_output, tokens_reasoning,
                               tokens_cache_read, tokens_cache_write
                        FROM session
                        WHERE directory = ?
                          AND (tokens_input > 0 OR tokens_output > 0)
                        ORDER BY time_created DESC
                        """,
                        (str(target),),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, directory, model, time_created,
                               tokens_input, tokens_output, tokens_reasoning,
                               tokens_cache_read, tokens_cache_write
                        FROM session
                        WHERE tokens_input > 0 OR tokens_output > 0
                        ORDER BY time_created DESC
                        """,
                    ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("OpenCode token_usage SQLite error: %s", exc)
            return

        for row in rows:
            dir_raw = row["directory"]
            if not isinstance(dir_raw, str) or not dir_raw:
                continue
            session_cwd = Path(dir_raw)
            if target is not None and not cwd_equal(
                normalize_cwd(session_cwd), target
            ):
                continue

            session_id = row["id"]
            if not isinstance(session_id, str):
                session_id = ""

            model_raw = row["model"]
            model = (
                parse_opencode_model(model_raw)
                if isinstance(model_raw, str)
                else None
            )

            yield TokenUsage(
                provider=self.name,
                session_id=session_id,
                cwd=session_cwd,
                ts=_ms_to_dt(row["time_created"]),
                model=model,
                input_tokens=_safe_int(row["tokens_input"]),
                output_tokens=_safe_int(row["tokens_output"]),
                cache_creation_input_tokens=_safe_int(row["tokens_cache_write"]),
                cache_read_input_tokens=_safe_int(row["tokens_cache_read"]),
                reasoning_output_tokens=_safe_int(row["tokens_reasoning"]),
                source_path=db_path,
            )

    # ------------------------------------------------------------------
    # list_installed_skills
    # ------------------------------------------------------------------

    def list_installed_skills(self) -> Iterable[InstalledSkill]:
        """Scan ~/.config/opencode/skills/ for SKILL.md files.

        D3: list_skill_invocations() returns () — OpenCode has no
        structured skill-invocation marker equivalent to Claude's
        <command-name> or Codex's [$skill].
        """
        if not self.skills_root.is_dir():
            logger.debug("OpenCode skills root not found: %s", self.skills_root)
            return

        try:
            entries = list(self.skills_root.iterdir())
        except OSError as exc:
            logger.warning(
                "Cannot list OpenCode skills root %s: %s", self.skills_root, exc
            )
            return

        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            skill = self._read_skill(entry)
            if skill is not None:
                yield skill

    def _read_skill(self, skill_dir: Path) -> InstalledSkill | None:
        md_path = skill_dir / "SKILL.md"
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            return None

        fields = parse_skill_frontmatter(text)
        name = (fields.get("name") or skill_dir.name).strip()
        if not name:
            return None
        description = (fields.get("description") or "").strip()
        version = fields.get("version")

        is_symlink = False
        try:
            is_symlink = skill_dir.is_symlink()
        except OSError:
            pass

        return InstalledSkill(
            name=name,
            description=description,
            provider=self.name,
            source="user",
            source_path=md_path,
            version=version,
            plugin=None,
            is_symlink=is_symlink,
        )

    # ------------------------------------------------------------------
    # No-op stubs (D3)
    # ------------------------------------------------------------------

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        return ()

    def list_question_answers(
        self, scope: Path | None = None
    ) -> Iterable[QuestionAnswer]:
        return ()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _row_to_session(
    row: sqlite3.Row, cwd: Path, db_path: Path, provider: str
) -> Session:
    session_id = row["id"]
    if not isinstance(session_id, str):
        session_id = ""

    title_raw = row["title"]
    title = (
        normalize_title(title_raw)
        if isinstance(title_raw, str) and title_raw.strip()
        else None
    )

    return Session(
        provider=provider,
        session_id=session_id,
        cwd=cwd,
        started_at=_ms_to_dt(row["time_created"]),
        event_count=0,
        source_path=db_path,
        title=title,
    )


def _ms_to_dt(ms: object) -> datetime | None:
    if not isinstance(ms, int) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _safe_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
