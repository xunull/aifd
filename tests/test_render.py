"""Tests for the output renderer."""

from __future__ import annotations

import datetime as _dt
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aifd.models import Session
from aifd.render import _relative_time, render_sessions


def _make(
    provider: str,
    sid: str,
    started_at: datetime | None = None,
    *,
    title: str | None = None,
) -> Session:
    return Session(
        provider=provider,
        session_id=sid,
        cwd=Path("/some/cwd"),
        started_at=started_at,
        event_count=42,
        source_path=Path(f"/store/{sid}.jsonl"),
        title=title,
    )


def test_empty_rows_prints_friendly_message(capsys: pytest.CaptureFixture[str]) -> None:
    render_sessions([], cwd=Path("/here"), as_json=False)
    captured = capsys.readouterr()
    assert "No AI sessions found" in captured.out
    assert "/here" in captured.out


def test_json_output_is_valid_json_array(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_make("claude", "abc-123", datetime(2026, 6, 1, tzinfo=UTC))]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert isinstance(parsed, list)
    assert parsed[0]["provider"] == "claude"
    assert parsed[0]["session_id"] == "abc-123"
    assert parsed[0]["cwd"] == "/some/cwd"
    assert parsed[0]["started_at"].startswith("2026-06-01")
    assert parsed[0]["event_count"] == 42


def test_json_handles_none_started_at(capsys: pytest.CaptureFixture[str]) -> None:
    rows = [_make("claude", "x", None)]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["started_at"] is None
    assert parsed[0]["title"] is None


def test_json_includes_full_title(capsys: pytest.CaptureFixture[str]) -> None:
    long_title = "x" * 200  # longer than table truncation
    rows = [_make("claude", "x", title=long_title)]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["title"] == long_title  # untruncated in JSON


def test_skill_stats_table_restores_gstack_prefix(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """is_gstack=True must render `gstack-<name>` in the table."""
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=10,
            count_codex=5,
            total=15,
            unique_cwd_count=3,
            last_used=None,
            is_gstack=True,
        ),
        SkillStats(
            skill_name="model",
            count_claude=8,
            count_codex=0,
            total=8,
            unique_cwd_count=2,
            last_used=None,
            is_gstack=False,
        ),
    ]
    render_skill_stats(stats, scope_label="globally", as_json=False)
    out = capsys.readouterr().out
    assert "gstack-office-hours" in out
    # `model` (no gstack-) stays bare
    assert "gstack-model" not in out


def test_skill_stats_json_includes_is_gstack(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=10,
            count_codex=5,
            total=15,
            unique_cwd_count=3,
            last_used=None,
            is_gstack=True,
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["is_gstack"] is True
    # JSON keeps the normalized skill_name — programs filter by that
    assert parsed[0]["skill_name"] == "office-hours"


def test_installed_skills_empty_friendly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.render import render_installed_skills

    render_installed_skills([], provider_label="claude", as_json=False)
    out = capsys.readouterr().out
    assert "No installed skills found" in out
    assert "claude" in out


def test_installed_skills_json_includes_all_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import InstalledSkill
    from aifd.render import render_installed_skills

    skills = [
        InstalledSkill(
            name="alpha",
            description="d",
            provider="claude",
            source="plugin",
            source_path=Path("/p/SKILL.md"),
            version="1.0",
            plugin="my-plugin",
            is_symlink=True,
        )
    ]
    render_installed_skills(skills, provider_label="claude", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["name"] == "alpha"
    assert parsed[0]["source"] == "plugin"
    assert parsed[0]["plugin"] == "my-plugin"
    assert parsed[0]["version"] == "1.0"
    assert parsed[0]["is_symlink"] is True


def test_installed_skills_table_renders_without_crash(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import InstalledSkill
    from aifd.render import render_installed_skills

    skills = [
        InstalledSkill(
            name="x",
            description="d" * 200,  # long, must be truncated
            provider="claude",
            source="user",
            source_path=Path("/p/SKILL.md"),
        )
    ]
    render_installed_skills(skills, provider_label="claude", as_json=False)
    out = capsys.readouterr().out
    assert "x" in out
    assert "user" in out


def test_json_handles_chinese_title(capsys: pytest.CaptureFixture[str]) -> None:
    """ensure_ascii=False so Chinese titles survive jq pipes."""
    rows = [_make("codex", "x", title="实现一个 CLI 工具")]
    render_sessions(rows, cwd=Path("/here"), as_json=True)
    out = capsys.readouterr().out
    assert "实现" in out
    parsed = json.loads(out)
    assert parsed[0]["title"] == "实现一个 CLI 工具"


def test_relative_time_minutes() -> None:
    now = datetime.now(UTC)
    five_min_ago = now - _dt.timedelta(minutes=5)
    assert _relative_time(five_min_ago) == "5m ago"


def test_relative_time_days() -> None:
    now = datetime.now(UTC)
    three_days_ago = now - _dt.timedelta(days=3)
    assert _relative_time(three_days_ago) == "3d ago"


def test_relative_time_handles_naive_datetime() -> None:
    naive = datetime.now(UTC).replace(tzinfo=None) - _dt.timedelta(minutes=2)
    # Should not crash; assumes UTC.
    out = _relative_time(naive)
    assert "ago" in out


# ---------- render_skill_stats ----------


def test_render_skill_stats_empty_friendly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.render import render_skill_stats

    render_skill_stats([], scope_label="globally", as_json=False)
    out = capsys.readouterr().out
    assert "No skill invocations found" in out
    assert "globally" in out


def test_render_skill_stats_json(capsys: pytest.CaptureFixture[str]) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="office-hours",
            count_claude=5,
            count_codex=3,
            total=8,
            unique_cwd_count=4,
            last_used=datetime(2026, 6, 1, tzinfo=UTC),
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["skill_name"] == "office-hours"
    assert parsed[0]["total"] == 8
    assert parsed[0]["unique_cwd_count"] == 4
    assert parsed[0]["last_used"].startswith("2026-06-01")


def test_render_skill_stats_json_handles_none_last_used(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aifd.models import SkillStats
    from aifd.render import render_skill_stats

    stats = [
        SkillStats(
            skill_name="x",
            count_claude=1,
            count_codex=0,
            total=1,
            unique_cwd_count=1,
            last_used=None,
        )
    ]
    render_skill_stats(stats, scope_label="globally", as_json=True)
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["last_used"] is None
