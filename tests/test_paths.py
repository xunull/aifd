"""Tests for path normalization."""

from __future__ import annotations

import sys
from pathlib import Path

from aifd.paths import cwd_equal, normalize_cwd


def test_normalize_cwd_resolves_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)

    assert normalize_cwd(link) == target.resolve()


def test_normalize_cwd_strips_trailing_slash(tmp_path: Path) -> None:
    p_with = Path(str(tmp_path) + "/")
    p_without = tmp_path
    assert normalize_cwd(p_with) == normalize_cwd(p_without)


def test_normalize_cwd_returns_absolute_on_broken_path(tmp_path: Path) -> None:
    """Even an extremely weird path should not crash."""
    weird = tmp_path / "does-not-exist" / ".." / "still-no"
    # Should not raise.
    result = normalize_cwd(weird)
    assert result.is_absolute()


def test_cwd_equal_samefile(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)

    assert cwd_equal(target, link)


def test_cwd_equal_nonexistent_strings_match(tmp_path: Path) -> None:
    p = tmp_path / "ghost"
    # both refer to the same non-existent path
    assert cwd_equal(p, Path(str(p)))


def test_cwd_equal_macos_case_insensitive_when_nonexistent(tmp_path: Path) -> None:
    """On macOS, /Foo and /foo should be considered equal when neither exists."""
    a = tmp_path / "Ghost"
    b = tmp_path / "ghost"
    if sys.platform == "darwin":
        assert cwd_equal(a, b)
    else:
        assert not cwd_equal(a, b)


def test_cwd_equal_different_paths(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert not cwd_equal(a, b)
