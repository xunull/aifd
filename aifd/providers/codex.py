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

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation, TokenUsage
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

    def iter_all_sessions(self) -> Iterator[Session]:
        """Yield every Session, regardless of cwd. Used by `aifd ai retro`.

        Tries SQLite first (fast, no row WHERE cwd filter). Falls back to
        a jsonl scan with `target=None`. Same dedupe semantics as the
        cwd-scoped path — `session_id` is the de-dupe key.
        """
        db_path = self._find_state_db()
        seen_ids: set[str] = set()
        if db_path is not None:
            try:
                for s in self._query_sqlite_all(db_path):
                    if s.session_id in seen_ids:
                        continue
                    seen_ids.add(s.session_id)
                    yield s
                return
            except sqlite3.Error as exc:
                logger.warning("Codex global SQLite query failed: %s", exc)
                # Fall through to jsonl scan
        for rollout in self._all_rollout_files():
            parsed = self._parse_rollout_file(rollout, target=None)
            if parsed is None or parsed.session_id in seen_ids:
                continue
            seen_ids.add(parsed.session_id)
            yield parsed

    def _query_sqlite_all(self, db_path: Path) -> Iterator[Session]:
        """Same as `_query_sqlite` but without the `WHERE cwd = ?` clause."""
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, rollout_path, cwd, title, first_user_message,
                       created_at_ms, archived, preview
                FROM threads
                ORDER BY created_at_ms DESC, id DESC
                """,
            ).fetchall()
        finally:
            conn.close()

        for row in rows:
            row_cwd_raw = row["cwd"]
            session_cwd = Path(row_cwd_raw) if isinstance(row_cwd_raw, str) else Path()
            title = _pick_title(row["title"], row["preview"], row["first_user_message"])
            started_at = _ms_to_dt(row["created_at_ms"])
            rollout = row["rollout_path"]
            source_path = (
                Path(rollout) if isinstance(rollout, str) and rollout else db_path
            )
            yield Session(
                provider=self.name,
                session_id=row["id"] if isinstance(row["id"], str) else "",
                cwd=session_cwd,
                started_at=started_at,
                event_count=0,
                source_path=source_path,
                title=title,
            )

    def _parse_rollout_file(
        self, path: Path, target: Path | None
    ) -> Session | None:
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
        if target is not None and not cwd_equal(normalize_cwd(session_cwd), target):
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

    def list_token_usage(
        self, scope: Path | None = None
    ) -> Iterable[TokenUsage]:
        """Extract per-event token usage from Codex rollout jsonl files.

        Codex records cumulative totals in
        `event_msg.payload.info.total_token_usage` (one per token_count
        event). We emit ONE TokenUsage per session per token-count event;
        the cost aggregator then sums (or takes the max if cumulative).

        Model id lives in `turn_context.payload.model`. cwd lives in
        `session_meta.payload.cwd`.

        Two layouts coexist:
          - ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl   (per-day directories)
          - ~/.codex/archived_sessions/rollout-*.jsonl     (flat)
        """
        sessions_root = self.root / "sessions"
        archived_root = self.root / "archived_sessions"

        files: list[Path] = []
        if sessions_root.is_dir():
            try:
                files.extend(p for p in sessions_root.rglob("*.jsonl"))
            except OSError as exc:
                logger.warning(
                    "Cannot walk Codex sessions %s: %s", sessions_root, exc
                )
        if archived_root.is_dir():
            try:
                files.extend(p for p in archived_root.glob("*.jsonl"))
            except OSError as exc:
                logger.warning(
                    "Cannot list Codex archived %s: %s", archived_root, exc
                )

        target = normalize_cwd(scope) if scope is not None else None

        for jsonl_path in files:
            yield from self._extract_token_usage_from_codex_file(
                jsonl_path, target
            )

    def _extract_token_usage_from_codex_file(
        self, jsonl_path: Path, target: Path | None
    ) -> Iterator[TokenUsage]:
        """Stream TokenUsage rows from one Codex rollout jsonl.

        token_count events report cumulative totals — we emit one row
        per token_count event and rely on the aggregator to dedupe per
        session (taking the max of cumulative totals per session-id).
        """
        try:
            f = jsonl_path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Codex file %s: %s", jsonl_path, exc)
            return

        session_id = jsonl_path.stem
        file_cwd: Path | None = None
        model: str | None = None
        rows: list[TokenUsage] = []

        try:
            with f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")
                    payload = event.get("payload")
                    if not isinstance(payload, dict):
                        continue

                    if etype == "session_meta" and file_cwd is None:
                        cwd_val = payload.get("cwd")
                        if isinstance(cwd_val, str) and cwd_val:
                            file_cwd = Path(cwd_val)
                        sid = payload.get("id")
                        if isinstance(sid, str) and sid:
                            session_id = sid
                    elif etype == "turn_context" and model is None:
                        m = payload.get("model")
                        if isinstance(m, str):
                            model = m
                    elif etype == "event_msg" and payload.get("type") == "token_count":
                        info = payload.get("info")
                        if not isinstance(info, dict):
                            continue
                        total = info.get("total_token_usage")
                        if not isinstance(total, dict):
                            continue
                        ts_str = event.get("timestamp")
                        ts = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None
                        # IMPORTANT: OpenAI's `input_tokens` is the TOTAL of
                        # fresh + cached. To align with our schema (and
                        # Claude's, where input_tokens excludes cache), we
                        # subtract `cached_input_tokens`. Without this, cost
                        # computation double-bills cached tokens at the full
                        # input rate.
                        total_in = _safe_int_codex(total.get("input_tokens"))
                        cached = _safe_int_codex(total.get("cached_input_tokens"))
                        fresh_input = max(total_in - cached, 0)
                        rows.append(
                            TokenUsage(
                                provider=self.name,
                                session_id=session_id,
                                cwd=file_cwd,
                                ts=ts,
                                model=model,
                                input_tokens=fresh_input,
                                output_tokens=_safe_int_codex(total.get("output_tokens")),
                                cache_creation_input_tokens=0,
                                cache_read_input_tokens=cached,
                                reasoning_output_tokens=_safe_int_codex(
                                    total.get("reasoning_output_tokens")
                                ),
                                source_path=jsonl_path,
                            )
                        )
        except OSError as exc:
            logger.warning("IO error reading %s: %s", jsonl_path, exc)
            return

        # scope filter — file's authoritative cwd must match.
        if target is not None:
            if file_cwd is None or not cwd_equal(normalize_cwd(file_cwd), target):
                return

        # CRITICAL: Codex token_count payloads are CUMULATIVE per session.
        # A session with 3 token_count events at [46936, 94371, 148163]
        # actually used 148163 tokens, not the sum. The aggregator must
        # not sum them, so we collapse to a single row per session here
        # — the last one, which holds the final cumulative totals.
        if not rows:
            return
        last = rows[-1]
        yield TokenUsage(
            provider=last.provider,
            session_id=last.session_id,
            cwd=last.cwd or file_cwd,
            ts=last.ts,
            model=last.model or model,
            input_tokens=last.input_tokens,
            output_tokens=last.output_tokens,
            cache_creation_input_tokens=last.cache_creation_input_tokens,
            cache_read_input_tokens=last.cache_read_input_tokens,
            reasoning_output_tokens=last.reasoning_output_tokens,
            source_path=last.source_path,
        )


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




def _safe_int_codex(value: object) -> int:
    """Coerce a Codex jsonl numeric field to int, defaulting to 0."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0
