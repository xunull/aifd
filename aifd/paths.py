"""Path normalization utilities.

Per design doc P4 + D8 decision: cwd matching must handle symlinks,
trailing slashes, macOS case-insensitive filesystems, and missing
intermediate symlink components without crashing.
"""

from __future__ import annotations

import sys
from pathlib import Path


def normalize_cwd(p: Path) -> Path:
    """Return an absolute, symlink-resolved Path.

    Falls back to `.absolute()` on OSError (e.g. broken intermediate
    symlink on Python 3.13 macOS). D8 decision: never crash on cwd
    normalization, even if the user runs aifd in a weird environment.
    """
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return p.absolute()


def cwd_equal(a: Path, b: Path) -> bool:
    """Compare two cwds for equality across platforms.

    Strategy:
    1. Prefer `samefile()` — handles symlinks and is filesystem-aware.
    2. If either side doesn't exist on disk, fall back to string compare.
       On macOS (and Windows) match case-insensitively because the
       default filesystems are case-insensitive — `os.path.normcase`
       only lowercases on Windows, so we use `str.casefold()` to also
       cover macOS APFS/HFS+. On Linux, literal compare.
    """
    try:
        return a.samefile(b)
    except (OSError, FileNotFoundError, ValueError):
        if sys.platform in ("darwin", "win32"):
            return str(a).casefold() == str(b).casefold()
        return str(a) == str(b)
