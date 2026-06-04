"""Provider Protocol.

D4 decision: use typing.Protocol + @runtime_checkable rather than ABC.
Contributors must adhere to the structural interface; mypy strict catches
missing methods at type-check time, isinstance() catches at runtime when
needed.

Adapter relationship (per design doc):

    ┌────────────────────────────────────────┐
    │ Protocol Provider                       │
    │ ─────────────────────────────────────  │
    │  name: str                              │
    │  __init__(root: Path | None = None)    │
    │  list_sessions(cwd: Path) -> Iter[S]   │
    └────────────────────────────────────────┘
             △               △
             │               │
       ClaudeProvider   CodexProvider   [v0.2: CursorProvider]
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from aifd.models import InstalledSkill, QuestionAnswer, Session, SkillInvocation


@runtime_checkable
class Provider(Protocol):
    """Structural interface every AI-tool adapter must satisfy.

    Implementations are expected to:
    - Set `name` as a short id ("claude", "codex", ...).
    - Accept an optional `root` Path in their constructor (D9), defaulting
      to the platform-native storage location when None. This makes them
      testable without monkey-patching.
    - Yield Session objects from `list_sessions(cwd)`. Per D7, single-file
      parse errors must be silently skipped (logged at warning/debug), not
      raised — one bad file must not break the listing.
    - Optionally override `list_skill_invocations(scope)` to expose skill
      stats. The default returns `[]` so third-party providers without
      skill semantics (e.g. a hypothetical Cursor provider in v0.3) keep
      working without explicit support.
    """

    name: str

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        """Enumerate sessions whose recorded cwd equals the given cwd."""
        ...

    def list_skill_invocations(
        self, scope: Path | None = None
    ) -> Iterable[SkillInvocation]:
        """Enumerate skill (slash-command) invocations.

        scope is None for a global scan; a Path narrows the result to
        invocations whose recorded cwd equals that path. The default
        implementation returns an empty iterable — providers without
        skill semantics inherit no-op behavior.
        """
        return ()

    def list_installed_skills(self) -> Iterable[InstalledSkill]:
        """Enumerate skills the user has installed for this tool.

        Distinct from `list_skill_invocations` — this scans the provider's
        on-disk skills directory(ies) and returns one InstalledSkill per
        SKILL.md found. Default returns empty so providers without a skills
        directory concept inherit no-op behavior.
        """
        return ()

    def list_question_answers(
        self, scope: Path | None = None
    ) -> Iterable[QuestionAnswer]:
        """Enumerate AskUserQuestion calls and the user's recorded answers.

        scope=None: global scan. scope=Path: narrow to a single cwd using
        the same two-phase matching pattern as list_sessions.

        Default returns empty so providers without structured
        AskUserQuestion semantics (Codex, hypothetical Cursor) inherit
        no-op behavior. Only Claude Code currently emits AUQ as a
        structured tool_use; Codex equivalents would need a separate
        opt-in heuristic provider (see v0.3 TODOS.md).
        """
        return ()
