"""Tests for ReflectionDataSource (D3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aifd.insights.reflection_source import (
    GstackDataSource,
    NullSource,
    QuestionLogEntry,
    SkillEvent,
    default_source,
)


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


# ---------- NullSource ----------


def test_null_source_yields_nothing() -> None:
    s = NullSource()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 12, 31, tzinfo=UTC)
    assert list(s.question_log(start, end)) == []
    assert list(s.skill_events(start, end)) == []
    assert s.is_available() is False


# ---------- QuestionLogEntry / SkillEvent value object ----------


def test_question_log_entry_user_matched_when_equal() -> None:
    e = QuestionLogEntry(
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        skill="office-hours", question_id="qid1",
        user_choice="A", recommended="A",
    )
    assert e.user_matched_recommendation is True


def test_question_log_entry_user_did_not_match() -> None:
    e = QuestionLogEntry(
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        skill="office-hours", question_id="qid1",
        user_choice="B", recommended="A",
    )
    assert e.user_matched_recommendation is False


def test_question_log_entry_unknown_when_either_none() -> None:
    e = QuestionLogEntry(
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        skill="office-hours", question_id="qid1",
        user_choice=None, recommended="A",
    )
    assert e.user_matched_recommendation is None


# ---------- GstackDataSource: slug discovery + path resolution ----------


@pytest.fixture
def gstack_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    home = tmp_path / "gstack-home"
    home.mkdir()
    return home


def test_gstack_source_unavailable_when_no_dir(gstack_home: Path) -> None:
    src = GstackDataSource(_gstack_home=gstack_home)
    assert src.is_available() is False


def test_gstack_source_resolves_owner_name_from_git_remote(
    tmp_path: Path, gstack_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slug should resolve via `git remote get-url origin` → owner-repo."""
    project = tmp_path / "aifd"
    project.mkdir()
    # Simulate a git remote
    project_dir = gstack_home / "projects" / "xunull-aifd"
    project_dir.mkdir(parents=True)

    real_run = __import__("subprocess").run

    def fake_run(args: list[str], **kwargs: object) -> object:
        if args[:3] == ["git", "remote", "get-url"]:
            r = type("R", (), {})()
            r.returncode = 0
            r.stdout = "https://github.com/xunull/aifd.git"
            return r
        # bash gstack-slug → not found
        if args[:1] == ["bash"]:
            r = type("R", (), {})()
            r.returncode = 1
            r.stdout = ""
            return r
        return real_run(args, **kwargs)

    monkeypatch.setattr(
        "aifd.insights.reflection_source.subprocess.run", fake_run,
    )

    src = GstackDataSource(
        project_root=project, _gstack_home=gstack_home,
    )
    assert src.is_available() is True


def test_gstack_source_falls_back_to_basename(
    tmp_path: Path, gstack_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "aifd"
    project.mkdir()
    project_dir = gstack_home / "projects" / "aifd"
    project_dir.mkdir(parents=True)

    def fake_run(args: list[str], **_kw: object) -> object:
        r = type("R", (), {})()
        r.returncode = 1
        r.stdout = ""
        return r

    monkeypatch.setattr(
        "aifd.insights.reflection_source.subprocess.run", fake_run,
    )

    src = GstackDataSource(
        project_root=project, _gstack_home=gstack_home,
    )
    assert src.is_available() is True


# ---------- GstackDataSource: question_log parsing + filtering ----------


def test_gstack_source_iterates_question_log_in_window(
    tmp_path: Path, gstack_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "aifd"
    project.mkdir()
    gstack_proj = gstack_home / "projects" / "aifd"
    gstack_proj.mkdir(parents=True)
    _write_jsonl(gstack_proj / "question-log.jsonl", [
        {
            "ts": "2026-06-01T10:00:00Z", "skill": "office-hours",
            "question_id": "q1", "user_choice": "A", "recommended": "A",
        },
        {
            "ts": "2026-06-05T10:00:00Z", "skill": "plan-eng-review",
            "question_id": "q2", "user_choice": "B", "recommended": "A",
        },
        {
            "ts": "2026-06-10T10:00:00Z", "skill": "ship",
            "question_id": "q3", "user_choice": "A", "recommended": "A",
        },
    ])

    def fake_run(args: list[str], **_kw: object) -> object:
        r = type("R", (), {})()
        r.returncode = 1
        r.stdout = ""
        return r

    monkeypatch.setattr(
        "aifd.insights.reflection_source.subprocess.run", fake_run,
    )

    src = GstackDataSource(
        project_root=project, _gstack_home=gstack_home,
    )
    start = datetime(2026, 6, 4, tzinfo=UTC)
    end = datetime(2026, 6, 8, tzinfo=UTC)
    entries = list(src.question_log(start, end))
    assert len(entries) == 1
    assert entries[0].question_id == "q2"
    assert entries[0].user_matched_recommendation is False


def test_gstack_source_skips_malformed_jsonl_lines(
    tmp_path: Path, gstack_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "aifd"
    project.mkdir()
    gstack_proj = gstack_home / "projects" / "aifd"
    gstack_proj.mkdir(parents=True)
    path = gstack_proj / "question-log.jsonl"
    path.write_text(
        '{"ts":"2026-06-05T10:00:00Z","skill":"x","question_id":"q1",'
        '"user_choice":"A","recommended":"A"}\n'
        "not json at all\n"
        '{"ts":"2026-06-06T10:00:00Z","skill":"y","question_id":"q2",'
        '"user_choice":"A","recommended":"A"}\n'
    )

    def fake_run(args: list[str], **_kw: object) -> object:
        r = type("R", (), {})()
        r.returncode = 1
        r.stdout = ""
        return r

    monkeypatch.setattr(
        "aifd.insights.reflection_source.subprocess.run", fake_run,
    )

    src = GstackDataSource(
        project_root=project, _gstack_home=gstack_home,
    )
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    entries = list(src.question_log(start, end))
    assert len(entries) == 2  # malformed line skipped


# ---------- GstackDataSource: skill_events ----------


def test_gstack_source_iterates_skill_events(
    tmp_path: Path, gstack_home: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "aifd"
    project.mkdir()
    gstack_proj = gstack_home / "projects" / "aifd"
    gstack_proj.mkdir(parents=True)
    _write_jsonl(gstack_proj / "timeline.jsonl", [
        {
            "ts": "2026-06-05T10:00:00Z", "skill": "plan-eng-review",
            "event": "completed", "outcome": "clean",
        },
        {
            "ts": "2026-06-06T10:00:00Z", "skill": "ship",
            "event": "completed", "outcome": "clean",
        },
    ])

    def fake_run(args: list[str], **_kw: object) -> object:
        r = type("R", (), {})()
        r.returncode = 1
        r.stdout = ""
        return r

    monkeypatch.setattr(
        "aifd.insights.reflection_source.subprocess.run", fake_run,
    )

    src = GstackDataSource(
        project_root=project, _gstack_home=gstack_home,
    )
    start = datetime(2026, 6, 1, tzinfo=UTC)
    end = datetime(2026, 6, 30, tzinfo=UTC)
    events: list[SkillEvent] = list(src.skill_events(start, end))
    assert len(events) == 2
    assert events[0].skill == "plan-eng-review"
    assert events[0].outcome == "clean"


# ---------- default_source factory ----------


def test_default_source_falls_back_to_null_when_no_gstack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Re-point gstack home to an empty temp dir
    monkeypatch.setattr(
        "aifd.insights.reflection_source.GstackDataSource._gstack_home",
        tmp_path / "no-gstack",
    )
    src = default_source(project_root=tmp_path / "no-project")
    assert isinstance(src, NullSource)
    assert src.is_available() is False
