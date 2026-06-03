"""Tests for the Provider Protocol default behavior."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from aifd.models import Session, SkillInvocation
from aifd.providers.base import Provider


class _MinimalProvider(Provider):
    """A custom provider that explicitly inherits Provider but only
    implements `list_sessions`. Tests D2 decision: the Protocol's
    default body for `list_skill_invocations` returns [] so providers
    without skill semantics don't crash.
    """

    name = "minimal"

    def list_sessions(self, cwd: Path) -> Iterable[Session]:
        return ()


def test_inherited_default_returns_empty(tmp_path: Path) -> None:
    """A subclass that doesn't override list_skill_invocations inherits
    the Protocol's default body returning ()."""
    p = _MinimalProvider()
    result = list(p.list_skill_invocations(scope=tmp_path))
    assert result == []


def test_inherited_default_with_no_scope() -> None:
    p = _MinimalProvider()
    result = list(p.list_skill_invocations())
    assert result == []


def test_inherited_default_is_typed_iterable() -> None:
    """Sanity check the type — empty but properly typed."""
    p = _MinimalProvider()
    result: list[SkillInvocation] = list(p.list_skill_invocations())
    assert result == []


def test_inherited_list_installed_skills_returns_empty() -> None:
    """Protocol default for list_installed_skills returns ()."""
    from aifd.models import InstalledSkill

    p = _MinimalProvider()
    result: list[InstalledSkill] = list(p.list_installed_skills())
    assert result == []
