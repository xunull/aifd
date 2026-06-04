"""Codex provider.

Storage layout (corrected after /investigate finding):

  PRIMARY: ~/.codex/state_5.sqlite, table `threads`
      Columns: id, rollout_path, cwd, title, first_user_message,
               archived, created_at_ms, model, git_branch, ...
      AI-generated title is in `title` (100% populated in practice).
      An index on (archived, cwd, created_at_ms DESC, id DESC) makes
      cwd-scoped queries effectively O(log N + matches).

  FALLBACK: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
            ~/.codex/archived_sessions/rollout-*.jsonl
      Used only when state_5.sqlite is missing (older Codex versions
      or fresh installs). The fallback scans files and reads each
      jsonl's first session_meta event for cwd.

D7 three-tier error handling stays:
  - SQLite open / query failure -> warning + fall back to jsonl scan
  - Single jsonl IOError -> warning skip the file
  - Malformed first line -> debug skip the file
  - File OK but cwd doesn't match -> silent skip
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation
from aifd.paths import cwd_equal, normalize_cwd
from aifd.providers._utils import (
    CODEX_SKILL_RE,
    is_gstack_name,
    normalize_skill_name,
    normalize_title,
    parse_iso_ts,
    parse_skill_frontmatter,
)

logger = logging.getLogger("aifd.providers.codex")

_STATE_DB_NAMES = ("state_5.sqlite", "state.sqlite")


class CodexProvider:
    name = "codex"

    def __init__(
        self,
        root: Path | None = None,
        skills_root: Path | None = None,
    ) -> None:
        """Args:
            root: parent of `sessions/`, `archived_sessions/`, and the
                state SQLite (`state_5.sqlite`). Defaults to ~/.codex.
                Tests inject a fixture path.
            skills_root: ~/.codex/skills. Defaults to standard location.
        """
        if root is None:
            root = self._default_root()
        self.root = root
        self.skills_root = skills_root or (Path.home() / ".codex" / "skills")

    @staticmethod
    def _default_root() -> Path:
        return Path.home() / ".codex"

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        target = normalize_cwd(cwd)

        db_path = self._find_state_db()
        if db_path is not None:
            yielded_any = False
            try:
                for session in self._query_sqlite(db_path, target):
                    yielded_any = True
                    yield session
                return
            except sqlite3.Error as exc:
                logger.warning(
                    "Codex SQLite query failed (%s), falling back to jsonl scan: %s",
                    db_path,
                    exc,
                )
                # Fall through to jsonl scan only if SQLite errored out
                # without yielding anything. Partial results are not safe
                # to combine with a second pass.
                if yielded_any:
                    return

        yield from self._jsonl_fallback(target)

    def _find_state_db(self) -> Path | None:
        for name in _STATE_DB_NAMES:
            candidate = self.root / name
            if candidate.is_file():
                return candidate
        return None

    def _query_sqlite(self, db_path: Path, target: Path) -> Iterator[Session]:
        """Read threads matching the target cwd.

        Opens read-only via URI to coexist with a running Codex process
        (which holds write locks on the WAL). `mode=ro` blocks accidental
        writes; `immutable=0` so we still see committed updates.
        """
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            # Default WAL behavior: readers don't block on writers. No
            # special PRAGMA needed in read-only mode.
            conn.row_factory = sqlite3.Row
            # The index idx_threads_archived_cwd_created_at_ms makes this fast.
            # We don't filter by `archived` so users see archived sessions too,
            # matching the spirit of "list everything for this cwd".
            rows = conn.execute(
                """
                SELECT id, rollout_path, cwd, title, first_user_message,
                       created_at_ms, archived, preview
                FROM threads
                WHERE cwd = ?
                ORDER BY created_at_ms DESC, id DESC
                """,
                (str(target),),
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            row_cwd_raw = row["cwd"]
            if not isinstance(row_cwd_raw, str):
                continue
            session_cwd = Path(row_cwd_raw)
            # Defensive: the WHERE matched literal string, but normalize_cwd
            # could still disagree (e.g. trailing slashes). Cheap recheck.
            if not cwd_equal(normalize_cwd(session_cwd), target):
                continue

            title = _pick_title(row["title"], row["preview"], row["first_user_message"])
            started_at = _ms_to_dt(row["created_at_ms"])
            rollout = row["rollout_path"]
            source_path = Path(rollout) if isinstance(rollout, str) and rollout else db_path

            # event_count is not in the threads schema; counting lines would
            # defeat the speed win. Use 0 to mean "unknown from SQLite".
            yield Session(
                provider=self.name,
                session_id=row["id"] if isinstance(row["id"], str) else "",
                cwd=session_cwd,
                started_at=started_at,
                event_count=0,
                source_path=source_path,
                title=title,
            )

    def _jsonl_fallback(self, target: Path) -> Iterator[Session]:
        """Pre-SQLite Codex installs and bare directory layouts."""
        seen_ids: set[str] = set()
        for rollout in self._all_rollout_files():
            session = self._parse_rollout_file(rollout, target)
            if session is None:
                continue
            if session.session_id in seen_ids:
                continue
            seen_ids.add(session.session_id)
            yield session

    def _all_rollout_files(self) -> Iterator[Path]:
        for sub in ("sessions", "archived_sessions"):
            base = self.root / sub
            if not base.is_dir():
                logger.debug("Codex %s not present at %s", sub, base)
                continue
            try:
                yield from base.rglob("rollout-*.jsonl")
            except OSError as exc:
                logger.warning("Cannot walk Codex %s: %s", base, exc)

    def _parse_rollout_file(self, path: Path, target: Path) -> Session | None:
        try:
            f = path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Codex file %s: %s", path, exc)
            return None

        first_line = ""
        event_count = 0
        first_user_message: str | None = None

        try:
            with f:
                for line_no, raw in enumerate(f, start=1):
                    if not raw.strip():
                        continue
                    event_count += 1
                    if line_no == 1:
                        first_line = raw
                        continue
                    if first_user_message is None:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        payload = (
                            event.get("payload") if isinstance(event, dict) else None
                        )
                        if (
                            isinstance(event, dict)
                            and event.get("type") == "event_msg"
                            and isinstance(payload, dict)
                            and payload.get("type") == "user_message"
                        ):
                            msg = payload.get("message")
                            if isinstance(msg, str) and msg.strip():
                                first_user_message = msg
        except OSError as exc:
            logger.warning("IO error reading %s: %s", path, exc)
            return None

        if not first_line.strip():
            return None

        try:
            meta = json.loads(first_line)
        except json.JSONDecodeError as exc:
            logger.debug("Codex %s: malformed first line: %s", path, exc)
            return None

        payload = meta.get("payload") if isinstance(meta, dict) else None
        if not isinstance(payload, dict):
            return None

        raw_cwd = payload.get("cwd")
        if not isinstance(raw_cwd, str) or not raw_cwd:
            return None

        session_cwd = Path(raw_cwd)
        if not cwd_equal(normalize_cwd(session_cwd), target):
            return None

        session_id = payload.get("id")
        if not isinstance(session_id, str):
            session_id = path.stem

        ts_str = payload.get("timestamp") or meta.get("timestamp")
        started_at = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None

        return Session(
            provider=self.name,
            session_id=session_id,
            cwd=session_cwd,
            started_at=started_at,
            event_count=event_count,
            source_path=path,
            title=normalize_title(first_user_message) if first_user_message else None,
        )

    def list_installed_skills(self) -> Iterable[InstalledSkill]:
        """Enumerate Codex's installed skills.

        Codex puts user-installed skills in `~/.codex/skills/{name}/`
        and its own bundled "system" skills under `.system/{name}/`.
        Some entries (notably `codex-primary-runtime/`) are runtime
        sentinels with no SKILL.md — those silent skip.

        D5 decision: include .system entries, mark source="system".
        D6: no dedup.
        """
        if not self.skills_root.is_dir():
            logger.debug("Codex skills root does not exist: %s", self.skills_root)
            return

        try:
            entries = list(self.skills_root.iterdir())
        except OSError as exc:
            logger.warning("Cannot list Codex skills root %s: %s", self.skills_root, exc)
            return

        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            # .system/ is a sub-tree, not a skill itself — descend.
            if entry.name == ".system":
                yield from self._scan_system_skills(entry)
                continue
            skill = self._read_skill(entry, source="user")
            if skill is not None:
                yield skill

    def _scan_system_skills(self, system_dir: Path) -> Iterator[InstalledSkill]:
        try:
            entries = list(system_dir.iterdir())
        except OSError as exc:
            logger.warning("Cannot list Codex .system %s: %s", system_dir, exc)
            return
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            skill = self._read_skill(entry, source="system")
            if skill is not None:
                yield skill

    def _read_skill(
        self, skill_dir: Path, *, source: str
    ) -> InstalledSkill | None:
        """Build an InstalledSkill from a directory containing SKILL.md.

        Silent skip on missing/unreadable SKILL.md — covers the runtime
        sentinel directories like `codex-primary-runtime/` that have no
        SKILL.md.
        """
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
            source=source,
            source_path=md_path,
            version=version,
            plugin=None,
            is_symlink=is_symlink,
        )

    def list_question_answers(
        self, scope: Path | None = None
    ) -> Iterable[QuestionAnswer]:
        """Codex has no structured AskUserQuestion tool — return empty.

        Codex's agent_message events are free-form text. Structured Q+A
        extraction would need a separate opt-in heuristic provider
        (see v0.3 TODOS). Returning empty keeps `aifd ai question list`
        working when --provider isn't filtered to claude.
        """
        return ()

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        """Extract `[$skill-name]` invocations from Codex threads.

        SQLite-first: each row in `threads` where `first_user_message`
        begins with `[$...]` is one skill invocation. Falls back to jsonl
        scan when state_5.sqlite is missing (older Codex installs).
        """
        db_path = self._find_state_db()
        if db_path is not None:
            yielded_any = False
            try:
                for inv in self._query_skill_sqlite(db_path, scope):
                    yielded_any = True
                    yield inv
                return
            except sqlite3.Error as exc:
                logger.warning(
                    "Codex skill query failed (%s), falling back to jsonl: %s",
                    db_path,
                    exc,
                )
                if yielded_any:
                    return

        yield from self._jsonl_skill_fallback(scope)

    def _query_skill_sqlite(
        self, db_path: Path, scope: Path | None
    ) -> Iterator[SkillInvocation]:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            # The (archived, cwd, created_at_ms) index helps when scope is
            # provided. With no scope, a sequential scan over a few hundred
            # rows is still sub-millisecond.
            if scope is None:
                rows = conn.execute(
                    """SELECT id, rollout_path, cwd, first_user_message,
                              created_at_ms
                       FROM threads
                       WHERE first_user_message LIKE '[$%'"""
                ).fetchall()
            else:
                target = normalize_cwd(scope)
                rows = conn.execute(
                    """SELECT id, rollout_path, cwd, first_user_message,
                              created_at_ms
                       FROM threads
                       WHERE cwd = ?
                         AND first_user_message LIKE '[$%'""",
                    (str(target),),
                ).fetchall()
        finally:
            conn.close()

        for row in rows:
            first_msg = row["first_user_message"]
            if not isinstance(first_msg, str):
                continue
            match = CODEX_SKILL_RE.match(first_msg)
            if match is None:
                continue
            raw = match.group(1)
            skill = normalize_skill_name(raw)
            if not skill:
                continue

            cwd_raw = row["cwd"]
            cwd_path = Path(cwd_raw) if isinstance(cwd_raw, str) else Path("")
            ts = _ms_to_dt(row["created_at_ms"])
            rollout = row["rollout_path"]
            source = Path(rollout) if isinstance(rollout, str) and rollout else db_path

            yield SkillInvocation(
                skill_name=skill,
                provider=self.name,
                cwd=cwd_path,
                ts=ts,
                source_path=source,
                is_gstack=is_gstack_name(raw),
            )

    def _jsonl_skill_fallback(
        self, scope: Path | None
    ) -> Iterator[SkillInvocation]:
        """Walk rollout-*.jsonl files and pull skill markers from each.

        D3 decision: older Codex installs without state_5.sqlite must
        still surface in `aifd ai skill list`. Reuses _parse_rollout_file
        path style — open once per file, read first session_meta line for
        cwd, then scan event_msg::user_message for the first message.
        """
        seen_ids: set[str] = set()
        for rollout in self._all_rollout_files():
            inv = self._extract_skill_from_rollout(rollout, scope)
            if inv is None:
                continue
            if rollout.stem in seen_ids:
                continue
            seen_ids.add(rollout.stem)
            yield inv

    def _extract_skill_from_rollout(
        self, path: Path, scope: Path | None
    ) -> SkillInvocation | None:
        try:
            f = path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Codex file %s: %s", path, exc)
            return None

        meta_line = ""
        first_user_message: str | None = None
        try:
            with f:
                for line_no, raw in enumerate(f, start=1):
                    if not raw.strip():
                        continue
                    if line_no == 1:
                        meta_line = raw
                        continue
                    if first_user_message is None:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        payload = (
                            event.get("payload") if isinstance(event, dict) else None
                        )
                        if (
                            isinstance(event, dict)
                            and event.get("type") == "event_msg"
                            and isinstance(payload, dict)
                            and payload.get("type") == "user_message"
                        ):
                            msg = payload.get("message")
                            if isinstance(msg, str) and msg.strip():
                                first_user_message = msg
                                # We only need the FIRST user_message,
                                # short-circuit further scanning.
                                break
        except OSError as exc:
            logger.warning("IO error reading %s: %s", path, exc)
            return None

        if not first_user_message:
            return None

        match = CODEX_SKILL_RE.match(first_user_message)
        if match is None:
            return None
        raw = match.group(1)
        skill = normalize_skill_name(raw)
        if not skill:
            return None

        # Need the meta line for cwd + timestamp.
        try:
            meta = json.loads(meta_line)
        except (json.JSONDecodeError, ValueError):
            return None
        payload = meta.get("payload") if isinstance(meta, dict) else None
        if not isinstance(payload, dict):
            return None
        cwd_raw = payload.get("cwd")
        if not isinstance(cwd_raw, str) or not cwd_raw:
            return None
        cwd_path = Path(cwd_raw)

        if scope is not None and not cwd_equal(normalize_cwd(cwd_path), normalize_cwd(scope)):
            return None

        ts_str = payload.get("timestamp") or meta.get("timestamp")
        ts = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None

        return SkillInvocation(
            skill_name=skill,
            provider=self.name,
            cwd=cwd_path,
            ts=ts,
            source_path=path,
            is_gstack=is_gstack_name(raw),
        )


def _pick_title(
    title: object, preview: object, first_user_message: object
) -> str | None:
    """SQLite-first title selection.

    `title` is the AI-generated summary; `preview` is a short snippet;
    `first_user_message` is the raw first input. Prefer in that order,
    skipping empty / system-noise values.
    """
    for candidate in (title, preview, first_user_message):
        if isinstance(candidate, str):
            normalized = normalize_title(candidate)
            if normalized:
                return normalized
    return None


def _ms_to_dt(ms: object) -> datetime | None:
    """Codex stores created_at_ms as milliseconds since epoch."""
    if not isinstance(ms, int) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


