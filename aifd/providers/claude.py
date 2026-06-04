"""Claude Code provider.

Storage layout:
    ~/.claude/projects/{encoded-cwd}/{session-uuid}.jsonl

Encoding rule (observed): cwd's path separators '/' are replaced with '-'.
Example: /Users/foo/aifd -> -Users-foo-aifd

D2 strategy: two-phase cwd matching.
  Phase 1 (fast filter): use the directory-name encoding as a hint to
    locate candidate project directories. This is O(1) directory listing
    and rejects 99% of unrelated sessions cheaply.
  Phase 2 (authoritative): for each candidate jsonl, read the first
    event that contains a "cwd" field (typically lines 3-5; the first
    couple are session-meta without cwd). Compare against the requested
    cwd via cwd_equal(). Only sessions that match are yielded.

  The reason Phase 2 is authoritative: the encoding is lossy. A path
  containing '-' (like /Users/foo/some-project) cannot be distinguished
  from /Users/foo/some/project at the directory-name level. Claude
  itself writes the literal cwd into every event, so we use that as
  ground truth.

D7 three-tier error handling:
  - File-level IOError -> logger.warning + skip the file.
  - Single line `json.loads` failure -> logger.debug + skip that line,
    continue reading subsequent lines.
  - File ends without ever finding a cwd event, or its cwd doesn't match
    -> silent skip (no log; "doesn't match" is not an error).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation
from aifd.paths import cwd_equal, normalize_cwd
from aifd.providers._utils import (
    AUQ_TOOL_NAME_RE,
    CLAUDE_COMMAND_RE,
    is_gstack_name,
    normalize_skill_name,
    normalize_title,
    parse_iso_ts,
    parse_skill_frontmatter,
    split_recommended_suffix,
)

logger = logging.getLogger("aifd.providers.claude")


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        root: Path | None = None,
        skills_root: Path | None = None,
        plugins_root: Path | None = None,
    ) -> None:
        """Args:
            root: parent of `projects/` dir, defaults to ~/.claude/projects.
                Tests inject a fixture path; production uses the default.
            skills_root: ~/.claude/skills (user-installed skills root).
            plugins_root: ~/.claude/plugins/cache (plugin-installed skills root).
        """
        if root is None:
            root = self._default_root()
        self.root = root
        # Both default to standard Claude Code paths. Tests inject fixtures.
        self.skills_root = skills_root or (Path.home() / ".claude" / "skills")
        self.plugins_root = plugins_root or (
            Path.home() / ".claude" / "plugins" / "cache"
        )

    @staticmethod
    def _default_root() -> Path:
        """Locate the Claude Code projects directory across platforms."""
        # macOS / Linux: ~/.claude/projects/
        # Windows: ~/.claude/projects/ as well per Claude Code CLI behavior.
        # If anthropic ever changes, override via constructor in tests / setup.
        return Path.home() / ".claude" / "projects"

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        if not self.root.is_dir():
            logger.debug("Claude projects root does not exist: %s", self.root)
            return

        target = normalize_cwd(cwd)
        encoded = self._encode_cwd(target)

        # Phase 1: candidate directories. Primary hit is `encoded` itself;
        # we also scan the full directory listing because the encoding is
        # ambiguous (path containing '-' may collide with nested paths).
        candidate_dirs = list(self._candidate_dirs(encoded))
        logger.debug("Claude candidate dirs for %s: %d", target, len(candidate_dirs))

        for project_dir in candidate_dirs:
            for jsonl_path in self._jsonl_files(project_dir):
                yield from self._parse_file(jsonl_path, target)

    def _candidate_dirs(self, encoded: str) -> Iterator[Path]:
        """Phase 1: yield directories that *might* contain matching sessions."""
        primary = self.root / encoded
        if primary.is_dir():
            yield primary
        # Also scan siblings whose name shares the encoded prefix — they
        # could be nested-path encodings that look ambiguously similar.
        # In practice the prefix scan is cheap and covers '-' edge cases.
        try:
            for entry in self.root.iterdir():
                if entry.is_dir() and entry != primary and entry.name.startswith(encoded):
                    yield entry
        except OSError as exc:
            logger.warning("Cannot list Claude projects root %s: %s", self.root, exc)

    @staticmethod
    def _jsonl_files(project_dir: Path) -> Iterator[Path]:
        try:
            for entry in project_dir.iterdir():
                if entry.is_file() and entry.suffix == ".jsonl":
                    yield entry
        except OSError as exc:
            logger.warning("Cannot list Claude project dir %s: %s", project_dir, exc)

    def _parse_file(self, jsonl_path: Path, target: Path) -> Iterator[Session]:
        """Phase 2: read jsonl, find authoritative cwd, build Session if it matches.

        Also harvests title:
        - Preferred: `ai-title` event's `aiTitle` field (Claude Code auto-summary).
        - Fallback: first non-system user message text (skipping skill/system
          injections that start with '<', 'Caveat', or 'Base directory').
        """
        try:
            f = jsonl_path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Claude file %s: %s", jsonl_path, exc)
            return

        first_cwd: Path | None = None
        first_ts: datetime | None = None
        event_count = 0
        ai_title: str | None = None
        fallback_user_text: str | None = None

        try:
            with f:
                for line_no, raw in enumerate(f, start=1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    event_count += 1
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        logger.debug(
                            "Skip malformed json line %d in %s: %s",
                            line_no,
                            jsonl_path,
                            exc,
                        )
                        continue

                    if first_cwd is None:
                        raw_cwd = event.get("cwd")
                        if isinstance(raw_cwd, str) and raw_cwd:
                            first_cwd = Path(raw_cwd)
                            ts_str = event.get("timestamp")
                            first_ts = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None

                    etype = event.get("type")
                    if ai_title is None and etype == "ai-title":
                        candidate = event.get("aiTitle")
                        if isinstance(candidate, str) and candidate.strip():
                            ai_title = candidate.strip()
                    elif fallback_user_text is None and etype == "user":
                        text = _extract_user_text(event)
                        if text and not _is_system_injection(text):
                            fallback_user_text = text
        except OSError as exc:
            logger.warning("IO error reading %s: %s", jsonl_path, exc)
            return

        if first_cwd is None:
            return

        if not cwd_equal(normalize_cwd(first_cwd), target):
            return

        title = ai_title or fallback_user_text
        session_id = jsonl_path.stem
        yield Session(
            provider=self.name,
            session_id=session_id,
            cwd=first_cwd,
            started_at=first_ts,
            event_count=event_count,
            source_path=jsonl_path,
            title=normalize_title(title) if title else None,
        )

    @staticmethod
    def _encode_cwd(cwd: Path) -> str:
        """Mirror Claude Code's path encoding: '/' -> '-'.

        On POSIX, Path uses '/'. On Windows the separator differs; Claude
        Code's actual encoding on Windows is unverified (TODO T15), so we
        normalize to POSIX form first.
        """
        s = str(cwd).replace(os.sep, "/")
        return s.replace("/", "-")

    def list_installed_skills(self) -> Iterable[InstalledSkill]:
        """Enumerate skills installed on disk.

        Two sources:
          1. `~/.claude/skills/{name}/SKILL.md`     -> source="user"
          2. `~/.claude/plugins/cache/.../skills/{name}/SKILL.md` -> source="plugin"

        D2 decision: scan both, mark via `source`. D4: rglob plugin cache
        and filter by path containing `/skills/` so future Anthropic
        layout changes don't silently drop entries.
        D6: do NOT dedup; same name from two sources is two rows.
        """
        # 1. User-installed
        yield from self._scan_user_skills_root()
        # 2. Plugin-installed
        yield from self._scan_plugin_skills()

    def _scan_user_skills_root(self) -> Iterator[InstalledSkill]:
        if not self.skills_root.is_dir():
            logger.debug("Claude skills root does not exist: %s", self.skills_root)
            return
        try:
            entries = list(self.skills_root.iterdir())
        except OSError as exc:
            logger.warning("Cannot list Claude skills root %s: %s", self.skills_root, exc)
            return
        for entry in entries:
            try:
                if not entry.is_dir():
                    continue
            except OSError:
                # Dangling symlink target — skip
                continue
            skill = self._read_skill(entry, source="user")
            if skill is not None:
                yield skill

    def _scan_plugin_skills(self) -> Iterator[InstalledSkill]:
        if not self.plugins_root.is_dir():
            logger.debug(
                "Claude plugin cache does not exist: %s", self.plugins_root
            )
            return
        try:
            # rglob `SKILL.md` then filter to ones living under a /skills/
            # ancestor — the marketplace path layout puts every plugin skill
            # at `{marketplace}/{plugin}/{version}/skills/{skill}/SKILL.md`.
            candidates = list(self.plugins_root.rglob("SKILL.md"))
        except OSError as exc:
            logger.warning("Cannot walk plugin cache %s: %s", self.plugins_root, exc)
            return
        for md in candidates:
            parts = md.parts
            if "skills" not in parts:
                continue
            # Parent dir of SKILL.md is the skill dir.
            skill_dir = md.parent
            plugin_name = _claude_plugin_name_from_path(md)
            skill = self._read_skill(skill_dir, source="plugin", plugin=plugin_name)
            if skill is not None:
                yield skill

    def _read_skill(
        self,
        skill_dir: Path,
        *,
        source: str,
        plugin: str | None = None,
    ) -> InstalledSkill | None:
        """Build an InstalledSkill from a directory containing SKILL.md.

        Silent skip on:
          - SKILL.md missing
          - SKILL.md unreadable
          - frontmatter missing/malformed (name falls back to dirname)
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
            plugin=plugin,
            is_symlink=is_symlink,
        )

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        """Extract every `/skill-name` invocation from Claude jsonl logs.

        Claude Code logs user slash commands as a `<command-name>` tag
        inside the user message content. One jsonl may contain multiple
        invocations (one per `/skill` the user typed).

        scope=None scans every project dir; scope=Path narrows to one cwd
        via the two-phase pattern from list_sessions.
        """
        if not self.root.is_dir():
            logger.debug("Claude projects root does not exist: %s", self.root)
            return

        if scope is None:
            try:
                project_dirs = [p for p in self.root.iterdir() if p.is_dir()]
            except OSError as exc:
                logger.warning("Cannot list Claude projects root %s: %s", self.root, exc)
                return
        else:
            target = normalize_cwd(scope)
            encoded = self._encode_cwd(target)
            project_dirs = list(self._candidate_dirs(encoded))

        for project_dir in project_dirs:
            for jsonl_path in self._jsonl_files(project_dir):
                yield from self._extract_skills_from_file(jsonl_path, scope)

    def _extract_skills_from_file(
        self, jsonl_path: Path, scope: Path | None
    ) -> Iterator[SkillInvocation]:
        """Stream every command-name marker found in the given jsonl file.

        If `scope` is set, the file's cwd field must match scope before
        any invocation is yielded — this avoids the ambiguity issue with
        path encodings containing '-' (same Phase-2 rationale as session
        listing).
        """
        try:
            f = jsonl_path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Claude file %s: %s", jsonl_path, exc)
            return

        file_cwd: Path | None = None
        invocations: list[SkillInvocation] = []

        try:
            with f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        # Stay aligned with list_sessions: single bad line skipped
                        continue

                    if file_cwd is None:
                        cwd_val = event.get("cwd")
                        if isinstance(cwd_val, str) and cwd_val:
                            file_cwd = Path(cwd_val)

                    # Skill markers live in the user message content text.
                    if event.get("type") != "user":
                        continue
                    text = _extract_user_text(event)
                    if not text or "<command-name>" not in text:
                        continue
                    for match in CLAUDE_COMMAND_RE.finditer(text):
                        raw = match.group(1)
                        skill = normalize_skill_name(raw)
                        if not skill:
                            continue
                        ts_str = event.get("timestamp")
                        ts = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None
                        # Use the file's cwd as best-effort source for this
                        # invocation; updated below if scope filtering rejects.
                        invocations.append(
                            SkillInvocation(
                                skill_name=skill,
                                provider=self.name,
                                cwd=file_cwd or Path(""),
                                ts=ts,
                                source_path=jsonl_path,
                                is_gstack=is_gstack_name(raw),
                            )
                        )
        except OSError as exc:
            logger.warning("IO error reading %s: %s", jsonl_path, exc)
            return

        if file_cwd is None:
            return

        # scope filter: only emit when the file's authoritative cwd matches.
        if scope is not None and not cwd_equal(normalize_cwd(file_cwd), normalize_cwd(scope)):
            return

        # Patch cwd onto invocations now that we know the file's cwd.
        for inv in invocations:
            yield SkillInvocation(
                skill_name=inv.skill_name,
                provider=inv.provider,
                cwd=file_cwd,
                ts=inv.ts,
                source_path=inv.source_path,
                is_gstack=inv.is_gstack,
            )


    def list_question_answers(
        self, scope: Path | None = None
    ) -> Iterable[QuestionAnswer]:
        """Extract every AskUserQuestion call and pair with the user's answer.

        Strategy (v0.3, per CEO plan):
          1. Walk jsonl, find assistant events with a tool_use whose name
             matches AUQ_TOOL_NAME_RE.
          2. For each tool_use, iterate input.questions[] — emit one row
             per question (a single call may carry 1-4 questions).
          3. Look up the matching user tool_result via tool_use_id to set
             chosen_option + notes. Orphan AUQs (no tool_result — observed
             at ~4% in real sessions, e.g. user interrupted) still emit
             with chosen_option=None.
          4. Parse the `(recommended)` suffix from option labels to set
             recommended_option.

        scope=None scans every project dir; scope=Path narrows via the
        same two-phase pattern as list_sessions.
        """
        if not self.root.is_dir():
            logger.debug("Claude projects root does not exist: %s", self.root)
            return

        if scope is None:
            try:
                project_dirs = [p for p in self.root.iterdir() if p.is_dir()]
            except OSError as exc:
                logger.warning(
                    "Cannot list Claude projects root %s: %s", self.root, exc
                )
                return
        else:
            target = normalize_cwd(scope)
            encoded = self._encode_cwd(target)
            project_dirs = list(self._candidate_dirs(encoded))

        for project_dir in project_dirs:
            for jsonl_path in self._jsonl_files(project_dir):
                yield from self._extract_question_answers_from_file(
                    jsonl_path, scope
                )

    def _extract_question_answers_from_file(
        self, jsonl_path: Path, scope: Path | None
    ) -> Iterator[QuestionAnswer]:
        """Read one jsonl, pair AUQ tool_use with tool_result, emit per question.

        Two-pass: first pass collects asks + answers keyed by tool_use_id,
        plus the file's authoritative cwd. Then if scope filter passes,
        yield one QuestionAnswer per question (a single tool_use may have
        1-4 questions).

        File-level errors swallowed per D7 three-tier handling (warn for
        IO, debug for json, silent for no-match).
        """
        try:
            f = jsonl_path.open("r", encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping Claude file %s: %s", jsonl_path, exc)
            return

        file_cwd: Path | None = None
        session_id = jsonl_path.stem
        # tool_use_id -> (questions list, ts)
        asks: dict[str, tuple[list[dict[str, object]], datetime | None]] = {}
        # tool_use_id -> ({normalized_question -> chosen_label}, notes)
        answers: dict[str, tuple[dict[str, str], str | None]] = {}

        try:
            with f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        # Aligned with list_sessions: single bad line skipped.
                        continue

                    if file_cwd is None:
                        cwd_val = event.get("cwd")
                        if isinstance(cwd_val, str) and cwd_val:
                            file_cwd = Path(cwd_val)

                    etype = event.get("type")
                    if etype == "assistant":
                        self._collect_assistant_asks(event, asks)
                    elif etype == "user":
                        self._collect_user_answers(event, answers)
        except OSError as exc:
            logger.warning("IO error reading %s: %s", jsonl_path, exc)
            return

        if file_cwd is None:
            return

        # scope filter: only emit when the file's authoritative cwd matches.
        if scope is not None and not cwd_equal(
            normalize_cwd(file_cwd), normalize_cwd(scope)
        ):
            return

        for tool_use_id, (questions, ts) in asks.items():
            if not questions:
                # D5: silent skip + verbose-mode warning. tool_use with
                # empty questions array is a host-MCP bug signal, not
                # a legit decision row.
                logger.info(
                    "Skipped AUQ with empty questions in %s tool_use_id=%s",
                    jsonl_path,
                    tool_use_id,
                )
                continue
            chosen_map, notes = answers.get(tool_use_id, ({}, None))
            for q in questions:
                qa = self._build_question_answer(
                    q=q,
                    chosen_map=chosen_map,
                    notes=notes,
                    ts=ts,
                    cwd=file_cwd,
                    session_id=session_id,
                    jsonl_path=jsonl_path,
                    tool_use_id=tool_use_id,
                )
                if qa is not None:
                    yield qa

    @staticmethod
    def _collect_assistant_asks(
        event: dict[str, object],
        asks: dict[str, tuple[list[dict[str, object]], datetime | None]],
    ) -> None:
        """Find AUQ tool_use blocks in an assistant event."""
        msg = event.get("message")
        if not isinstance(msg, dict):
            return
        content = msg.get("content")
        if not isinstance(content, list):
            return
        ts_str = event.get("timestamp")
        ts = parse_iso_ts(ts_str) if isinstance(ts_str, str) else None
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") != "tool_use":
                continue
            name = c.get("name")
            if not isinstance(name, str) or not AUQ_TOOL_NAME_RE.match(name):
                continue
            tool_use_id = c.get("id")
            if not isinstance(tool_use_id, str):
                continue
            tool_input = c.get("input")
            if not isinstance(tool_input, dict):
                continue
            questions = tool_input.get("questions")
            if not isinstance(questions, list):
                # Schema violation; treat as empty so D5 handler kicks in.
                questions = []
            # Keep only dict questions; ignore any junk entries silently.
            clean = [q for q in questions if isinstance(q, dict)]
            asks[tool_use_id] = (clean, ts)

    @staticmethod
    def _collect_user_answers(
        event: dict[str, object],
        answers: dict[str, tuple[dict[str, str], str | None]],
    ) -> None:
        """Find tool_result blocks in a user event keyed by tool_use_id.

        The AUQ tool_result content is a string. Claude Code formats it as:
            "Your questions have been answered: \"<text>\"=\"<chosen label>\""

        We parse out the chosen label from the trailing `="<label>"` chunk;
        if that pattern doesn't match, fall back to None — the QA row still
        emits, just without a chosen_option (orphan-style).
        """
        msg = event.get("message")
        if not isinstance(msg, dict):
            return
        content = msg.get("content")
        if not isinstance(content, list):
            return
        for c in content:
            if not isinstance(c, dict) or c.get("type") != "tool_result":
                continue
            tool_use_id = c.get("tool_use_id")
            if not isinstance(tool_use_id, str):
                continue
            raw_content = c.get("content")
            # content can be a string or a list of {type: "text", text: "..."}
            text: str | None = None
            if isinstance(raw_content, str):
                text = raw_content
            elif isinstance(raw_content, list):
                for block in raw_content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if isinstance(t, str):
                            text = t
                            break
            if text is None:
                answers[tool_use_id] = ({}, None)
                continue
            chosen_map, notes = _parse_auq_answer_text(text)
            answers[tool_use_id] = (chosen_map, notes)

    @staticmethod
    def _build_question_answer(
        *,
        q: dict[str, object],
        chosen_map: dict[str, str],
        notes: str | None,
        ts: datetime | None,
        cwd: Path,
        session_id: str,
        jsonl_path: Path,
        tool_use_id: str,
    ) -> QuestionAnswer | None:
        """Project one schema-question into a QuestionAnswer.

        Looks up the chosen label by normalized question text — that's
        how the tool_result text format keys answers when a single
        tool_use carries multiple questions.

        Returns None when the question text is missing — that's structurally
        broken input we'd rather not surface.
        """
        question_text = q.get("question")
        if not isinstance(question_text, str) or not question_text.strip():
            return None
        normalized_q = normalize_title(question_text)
        chosen = chosen_map.get(normalized_q)
        raw_options = q.get("options")
        option_labels: list[str] = []
        recommended_option: str | None = None
        if isinstance(raw_options, list):
            for opt in raw_options:
                if not isinstance(opt, dict):
                    continue
                label = opt.get("label")
                if not isinstance(label, str):
                    continue
                clean, is_rec = split_recommended_suffix(label)
                option_labels.append(clean)
                if is_rec and recommended_option is None:
                    # Multiple `(recommended)` labels = ambiguous; first one wins
                    # (matches gstack hook behavior).
                    recommended_option = clean
        return QuestionAnswer(
            question=normalized_q,
            options=tuple(option_labels),
            recommended_option=recommended_option,
            chosen_option=chosen,
            notes=notes,
            ts=ts,
            cwd=cwd,
            provider="claude",
            session_id=session_id,
            source_path=jsonl_path,
            tool_use_id=tool_use_id,
        )


def _extract_user_text(event: dict[str, object]) -> str | None:
    """Pull a plain string out of a Claude user-type event's `message.content`.

    The content can be:
    - a plain string
    - a list of blocks, each {type: "text", text: "..."} etc.
    """
    msg = event.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    return text
    return None


def _claude_plugin_name_from_path(skill_md: Path) -> str | None:
    """Extract the plugin name from a plugin-cache SKILL.md path.

    Layout:
      ~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/skills/{skill}/SKILL.md

    The plugin name lives two directories above `skills/`. If the layout
    doesn't match, returns None — the skill still surfaces, just without
    the plugin name annotation.
    """
    parts = skill_md.parts
    try:
        skills_idx = parts.index("skills")
    except ValueError:
        return None
    # Need at least: .../{plugin}/{version}/skills/...
    if skills_idx < 2:
        return None
    return parts[skills_idx - 2]


# Patterns Claude/skills inject as the first user "message". These aren't
# what the user typed — they're harness scaffolding. Skip them as titles.
_SYSTEM_INJECTION_PREFIXES = (
    "<",
    "Caveat",
    "Base directory for this skill:",
    "[INFO]",
    "[system]",
)


def _is_system_injection(text: str) -> bool:
    head = text.lstrip()
    return any(head.startswith(p) for p in _SYSTEM_INJECTION_PREFIXES)


# Claude Code's tool_result text for an AUQ answer follows the shape:
#   Your questions have been answered: "<Q1>"="<A1>", "<Q2>"="<A2>", ...
#   You can now continue ...
#
# A single tool_use can carry 1-4 questions; each gets its own answer in
# the text. We harvest every `"<Q>"="<A>"` pair so multi-question AUQs
# pair each question to its own chosen_option instead of all collapsing
# to the first answer.
#
# multiSelect answers appear as a comma-joined list inside the inner
# quotes (e.g. `"Q"="A, B, C"`); we keep the literal text.

# Greedy on Q (non-quote), non-greedy across `"="`, greedy on A (non-quote).
# Both sides are quoted; the outer text never contains a literal `"` inside
# Q or A in the formats Claude Code emits, so [^"] is safe.
_AUQ_QA_PAIR_RE = re.compile(r'"([^"]+)"="([^"]+)"')
_AUQ_OTHER_NOTES_RE = re.compile(
    r"Other:\s*(?P<notes>[^\n\"]+)",
    re.IGNORECASE,
)


def _parse_auq_answer_text(
    text: str,
) -> tuple[dict[str, str], str | None]:
    """Extract per-question (chosen, notes) pairs from an AUQ tool_result.

    Returns a tuple (answers_by_question, notes):
      - answers_by_question maps the *normalized* question text to the
        chosen label. Empty dict when the expected pattern isn't found.
      - notes is the leading "Other:" annotation if present (rare; only
        on free-text Other paths). Applies to whichever question carried
        the Other selection — we don't pin it to a specific question
        because the text format doesn't say which.

    Callers look up `normalize_title(question_text)` against the dict to
    get the chosen_option for that specific question.
    """
    answers: dict[str, str] = {}
    for m in _AUQ_QA_PAIR_RE.finditer(text):
        q = " ".join(m.group(1).split())
        a = m.group(2).strip()
        answers[q] = a
    notes_match = _AUQ_OTHER_NOTES_RE.search(text)
    notes = notes_match.group("notes").strip() if notes_match else None
    return answers, notes


