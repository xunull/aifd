"""Tests for CodexProvider.list_installed_skills (T5)."""

from __future__ import annotations

from pathlib import Path

from aifd.providers.codex import CodexProvider
from tests.conftest import write_skill_md


def test_lists_user_installed_skills(codex_skills_root: Path) -> None:
    write_skill_md(codex_skills_root / "alpha", name="alpha", description="x")
    write_skill_md(codex_skills_root / "beta", name="beta", description="y")

    provider = CodexProvider(skills_root=codex_skills_root)
    skills = list(provider.list_installed_skills())
    by_name = {s.name: s for s in skills}
    assert {"alpha", "beta"} <= by_name.keys()
    assert by_name["alpha"].source == "user"
    assert by_name["alpha"].provider == "codex"


def test_system_subdir_marked_system_source(codex_skills_root: Path) -> None:
    """D5: .system/ skills are listed with source='system'."""
    write_skill_md(
        codex_skills_root / ".system" / "imagegen",
        name="imagegen",
        description="image generation",
    )
    write_skill_md(
        codex_skills_root / "office-hours", name="office-hours", description="OH"
    )

    provider = CodexProvider(skills_root=codex_skills_root)
    skills = list(provider.list_installed_skills())
    by_name = {s.name: s for s in skills}
    assert by_name["imagegen"].source == "system"
    assert by_name["office-hours"].source == "user"


def test_runtime_sentinel_dir_silent_skipped(codex_skills_root: Path) -> None:
    """codex-primary-runtime/ exists but has no SKILL.md — must skip."""
    (codex_skills_root / "codex-primary-runtime").mkdir()
    write_skill_md(codex_skills_root / "real", name="real", description="ok")

    provider = CodexProvider(skills_root=codex_skills_root)
    names = [s.name for s in provider.list_installed_skills()]
    assert names == ["real"]


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    provider = CodexProvider(skills_root=tmp_path / "nope")
    assert list(provider.list_installed_skills()) == []


def test_dir_without_skill_md_silent_skipped(codex_skills_root: Path) -> None:
    (codex_skills_root / "junk").mkdir()
    write_skill_md(codex_skills_root / "real", name="real", description="ok")

    provider = CodexProvider(skills_root=codex_skills_root)
    names = [s.name for s in provider.list_installed_skills()]
    assert names == ["real"]


def test_empty_system_dir_doesnt_crash(codex_skills_root: Path) -> None:
    (codex_skills_root / ".system").mkdir()
    write_skill_md(codex_skills_root / "real", name="real", description="ok")

    provider = CodexProvider(skills_root=codex_skills_root)
    names = [s.name for s in provider.list_installed_skills()]
    assert names == ["real"]


def test_missing_name_falls_back_to_dirname(codex_skills_root: Path) -> None:
    write_skill_md(codex_skills_root / "dir-name-only", description="no name field")

    provider = CodexProvider(skills_root=codex_skills_root)
    names = [s.name for s in provider.list_installed_skills()]
    assert "dir-name-only" in names
