"""Smoke tests for the Session dataclass."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from aifd.models import Session


def test_session_is_frozen() -> None:
    s = Session(
        provider="claude",
        session_id="abc",
        cwd=Path("/foo"),
        started_at=datetime(2026, 6, 1),
        event_count=10,
        source_path=Path("/foo/abc.jsonl"),
    )
    with pytest.raises(AttributeError):
        s.event_count = 99  # type: ignore[misc]


def test_event_count_field_exists() -> None:
    """Per D6: field is event_count, not message_count."""
    s = Session(
        provider="codex",
        session_id="x",
        cwd=Path("/y"),
        started_at=None,
        event_count=0,
        source_path=Path("/z.jsonl"),
    )
    assert s.event_count == 0
    assert not hasattr(s, "message_count")
