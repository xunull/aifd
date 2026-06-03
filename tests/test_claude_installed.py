"""Tests for ClaudeProvider.list_installed_skills (T4)."""

from __future__ import annotations

from pathlib import Path

from aifd.providers.claude import ClaudeProvider
from tests.conftest import write_skill_md


def test_lists_user_installed_skills(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    write_skill_md(claude_skills_root / "alpha", name="alpha", description="First")
    write_skill_md(claude_skills_root / "beta", name="beta", description="Second")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    skills = list(provider.list_installed_skills())
    by_name = {s.name: s for s in skills}
    assert {"alpha", "beta"} <= by_name.keys()
    assert by_name["alpha"].source == "user"
    assert by_name["alpha"].description == "First"
    assert by_name["alpha"].provider == "claude"


def test_dir_without_skill_md_silent_skipped(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    """Common case: ~/.claude/skills/_gstack-command/ has no SKILL.md."""
    (claude_skills_root / "no_md").mkdir()
    write_skill_md(claude_skills_root / "real", name="real", description="ok")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    names = [s.name for s in provider.list_installed_skills()]
    assert names == ["real"]


def test_lists_plugin_installed_skills(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    """plugin layout: cache/{marketplace}/{plugin}/{version}/skills/{skill}/SKILL.md"""
    skill_dir = (
        claude_plugins_root
        / "my-marketplace"
        / "my-plugin"
        / "1.0.0"
        / "skills"
        / "from-plugin"
    )
    write_skill_md(skill_dir, name="from-plugin", description="Plugin-installed")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    skills = list(provider.list_installed_skills())
    by_name = {s.name: s for s in skills}
    assert "from-plugin" in by_name
    s = by_name["from-plugin"]
    assert s.source == "plugin"
    assert s.plugin == "my-plugin"


def test_no_dedup_user_and_plugin_same_name(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    """D6: same-name skill in user + plugin produces TWO entries."""
    write_skill_md(
        claude_skills_root / "firecrawl", name="firecrawl", description="user copy"
    )
    write_skill_md(
        claude_plugins_root / "m" / "p" / "1.0" / "skills" / "firecrawl",
        name="firecrawl",
        description="plugin copy",
    )

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    firecrawls = [
        s for s in provider.list_installed_skills() if s.name == "firecrawl"
    ]
    assert len(firecrawls) == 2
    sources = {s.source for s in firecrawls}
    assert sources == {"user", "plugin"}


def test_missing_name_falls_back_to_dirname(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    write_skill_md(claude_skills_root / "dir-name-only", description="no name field")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    names = [s.name for s in provider.list_installed_skills()]
    assert "dir-name-only" in names


def test_skill_with_version(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    write_skill_md(
        claude_skills_root / "v", name="v", description="x", version="2.5.0"
    )
    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    s = next(s for s in provider.list_installed_skills() if s.name == "v")
    assert s.version == "2.5.0"


def test_missing_roots_yield_nothing(tmp_path: Path) -> None:
    provider = ClaudeProvider(
        skills_root=tmp_path / "nope", plugins_root=tmp_path / "nope2"
    )
    assert list(provider.list_installed_skills()) == []


def test_plugin_rglob_handles_deep_nesting(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    """D4: rglob + /skills/ filter. Plugin path with unexpected depth still works."""
    deep = (
        claude_plugins_root
        / "marketplace"
        / "plugin"
        / "ver"
        / "extra-nested"
        / "skills"
        / "deep-skill"
    )
    write_skill_md(deep, name="deep-skill", description="deeply nested")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    names = [s.name for s in provider.list_installed_skills()]
    assert "deep-skill" in names


def test_skill_md_outside_skills_dir_ignored(
    claude_skills_root: Path, claude_plugins_root: Path
) -> None:
    """A SKILL.md not under any /skills/ ancestor must NOT be picked up."""
    stray = claude_plugins_root / "marketplace" / "plugin" / "ver" / "templates"
    write_skill_md(stray, name="stray", description="should not appear")

    provider = ClaudeProvider(
        skills_root=claude_skills_root, plugins_root=claude_plugins_root
    )
    names = [s.name for s in provider.list_installed_skills()]
    assert "stray" not in names
