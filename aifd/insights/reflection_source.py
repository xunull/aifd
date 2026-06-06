"""Data source abstraction for `aifd ai reflect` (D3 from /plan-eng-review).

The compliance/review/plan-then-ship dimensions read data that aifd does NOT
write directly — gstack does. Two consequences:

1. User without gstack → data unavailable → reflection should still run
   with those dimensions returning None (prompt shows "(no question log)").
2. gstack slug vs aifd slug mismatch is a known v0.7 trap. The default
   impl tries multiple candidate paths (bare basename, owner-name, etc.)
   to be lenient.

Future: v0.9+ might write its own question-log; another impl will plug in
here without touching reflection.py.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("aifd.insights.reflection_source")


@dataclass(frozen=True)
class QuestionLogEntry:
    """One AskUserQuestion event from gstack's question-log.jsonl."""

    timestamp: datetime
    skill: str
    question_id: str
    user_choice: str | None
    recommended: str | None

    @property
    def user_matched_recommendation(self) -> bool | None:
        """True if user picked the recommended option, False if not, None
        if either side is unknown."""
        if self.user_choice is None or self.recommended is None:
            return None
        return self.user_choice == self.recommended


@dataclass(frozen=True)
class SkillEvent:
    """One skill invocation from gstack timeline.jsonl (or aifd-native log
    when v0.9+ adds one)."""

    timestamp: datetime
    skill: str
    event: str  # "started" | "completed"
    outcome: str | None = None


class ReflectionDataSource(Protocol):
    """Read-only access to the reflective-data substrate.

    Each method either yields data or returns an empty iterable. Methods
    NEVER raise; missing data → empty iterable + (optional) one-time
    warning.
    """

    def question_log(
        self, start: datetime, end: datetime,
    ) -> Iterator[QuestionLogEntry]: ...

    def skill_events(
        self, start: datetime, end: datetime,
    ) -> Iterator[SkillEvent]: ...

    def is_available(self) -> bool:
        """Whether the source has any data at all. Used by prompt rendering
        to decide whether to include 'N/A' placeholders."""
        ...


class NullSource:
    """Source that returns nothing. Used when no real source is available.

    Lets reflection.py keep computing the dimensions it CAN handle (cost,
    timing, project focus) while showing N/A for compliance / plan-then-ship.
    """

    def question_log(
        self, start: datetime, end: datetime,
    ) -> Iterator[QuestionLogEntry]:
        return iter(())

    def skill_events(
        self, start: datetime, end: datetime,
    ) -> Iterator[SkillEvent]:
        return iter(())

    def is_available(self) -> bool:
        return False


@dataclass
class GstackDataSource:
    """Reads from `~/.gstack/projects/{slug}/{question-log,timeline}.jsonl`.

    Slug discovery is the v0.7 trap: aifd's basename and gstack's resolved
    slug differ (xunull-aifd vs aifd). Try both, take the first that exists.

    Init is cheap (no file I/O); files are scanned lazily per call.
    """

    project_root: Path | None = None  # Path of the project (cwd if None)
    _gstack_home: Path = Path.home() / ".gstack"

    def _candidate_slugs(self) -> list[str]:
        """Possible slug names for this project, in priority order."""
        candidates: list[str] = []

        # 1. Try gstack's own slug binary if available — most authoritative.
        slug_via_gstack = self._invoke_gstack_slug()
        if slug_via_gstack:
            candidates.append(slug_via_gstack)

        # 2. owner-name from git remote (e.g. xunull-aifd)
        owner_name = self._owner_name_from_git()
        if owner_name and owner_name not in candidates:
            candidates.append(owner_name)

        # 3. Plain basename (e.g. aifd)
        if self.project_root is None:
            basename = Path.cwd().name
        else:
            basename = self.project_root.name
        if basename and basename not in candidates:
            candidates.append(basename)

        return candidates

    def _invoke_gstack_slug(self) -> str | None:
        try:
            r = subprocess.run(
                ["bash", "-c", str(
                    Path.home() / ".claude" / "skills" / "gstack" / "bin"
                    / "gstack-slug"
                )],
                capture_output=True, text=True, timeout=2,
                cwd=str(self.project_root) if self.project_root else None,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        # Output is `SLUG=<value>`; parse defensively.
        for line in r.stdout.splitlines():
            if line.startswith("SLUG="):
                return line[5:].strip().strip('"').strip("'") or None
        return None

    def _owner_name_from_git(self) -> str | None:
        try:
            r = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=2,
                cwd=str(self.project_root) if self.project_root else None,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        url = r.stdout.strip()
        # Normalize common GitHub/GitLab remote forms:
        #   https://github.com/owner/repo.git
        #   git@github.com:owner/repo.git
        #   ssh://git@github.com/owner/repo.git
        normalized = url.removesuffix(".git")
        # Get just the owner/repo tail — last two path segments
        # Replace `:` (in ssh URLs) with `/` to normalize
        normalized = normalized.replace(":", "/")
        parts = [p for p in normalized.split("/") if p]
        if len(parts) >= 2:
            owner = parts[-2]
            repo = parts[-1]
            if owner and repo and "." not in owner:
                # Reject if owner looks like a domain (e.g. "github.com")
                # for length-1 cases (we want owner/repo, not host/repo)
                return f"{owner}-{repo}"
        return None

    def _resolve_project_dir(self) -> Path | None:
        for slug in self._candidate_slugs():
            d = self._gstack_home / "projects" / slug
            if d.is_dir():
                return d
        return None

    # ---------- Protocol methods ----------

    def question_log(
        self, start: datetime, end: datetime,
    ) -> Iterator[QuestionLogEntry]:
        project = self._resolve_project_dir()
        if project is None:
            return
        path = project / "question-log.jsonl"
        if not path.exists():
            return
        yield from _iter_question_log(path, start, end)

    def skill_events(
        self, start: datetime, end: datetime,
    ) -> Iterator[SkillEvent]:
        project = self._resolve_project_dir()
        if project is None:
            return
        path = project / "timeline.jsonl"
        if not path.exists():
            return
        yield from _iter_skill_events(path, start, end)

    def is_available(self) -> bool:
        return self._resolve_project_dir() is not None


def _iter_question_log(
    path: Path, start: datetime, end: datetime,
) -> Iterator[QuestionLogEntry]:
    """Stream-decode the JSONL. Each line is one PostToolUse capture."""
    try:
        f = path.open("r", encoding="utf-8")
    except OSError as exc:
        logger.debug("question_log open %s: %s", path, exc)
        return
    with f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.debug(
                    "%s:%d malformed JSONL: %s — skip", path, line_no, exc,
                )
                continue
            entry = _parse_question_entry(obj)
            if entry is None:
                continue
            if start <= entry.timestamp < end:
                yield entry


def _parse_question_entry(obj: object) -> QuestionLogEntry | None:
    if not isinstance(obj, dict):
        return None
    ts_str = obj.get("ts") or obj.get("timestamp") or obj.get("date")
    if not isinstance(ts_str, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    skill_val = obj.get("skill")
    qid_val = obj.get("question_id")
    skill = str(skill_val) if skill_val is not None else ""
    qid = str(qid_val) if qid_val is not None else ""
    uc = obj.get("user_choice")
    rec = obj.get("recommended")
    return QuestionLogEntry(
        timestamp=ts,
        skill=skill,
        question_id=qid,
        user_choice=str(uc) if uc is not None else None,
        recommended=str(rec) if rec is not None else None,
    )


def _iter_skill_events(
    path: Path, start: datetime, end: datetime,
) -> Iterator[SkillEvent]:
    try:
        f = path.open("r", encoding="utf-8")
    except OSError as exc:
        logger.debug("skill_events open %s: %s", path, exc)
        return
    with f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ev = _parse_skill_event(obj)
            if ev is None:
                continue
            if start <= ev.timestamp < end:
                yield ev


def _parse_skill_event(obj: object) -> SkillEvent | None:
    if not isinstance(obj, dict):
        return None
    ts_str = obj.get("ts") or obj.get("timestamp")
    if not isinstance(ts_str, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    skill = obj.get("skill")
    event = obj.get("event")
    if not isinstance(skill, str) or not isinstance(event, str):
        return None
    outcome_val = obj.get("outcome")
    return SkillEvent(
        timestamp=ts,
        skill=skill,
        event=event,
        outcome=str(outcome_val) if outcome_val is not None else None,
    )


def default_source(project_root: Path | None = None) -> ReflectionDataSource:
    """Pick the right source for the current environment.

    Tries gstack; falls back to NullSource if gstack is not present.
    Always returns SOMETHING — callers never see None.
    """
    candidate = GstackDataSource(project_root=project_root)
    if candidate.is_available():
        return candidate
    return NullSource()


# Re-exports for ergonomics
__all__ = [
    "GstackDataSource",
    "NullSource",
    "QuestionLogEntry",
    "ReflectionDataSource",
    "SkillEvent",
    "default_source",
]


# Suppress unused-Iterable import if linters disagree (used in Protocol stub)
_ = Iterable
