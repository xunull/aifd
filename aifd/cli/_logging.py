"""Shared logging setup for all CLI commands.

Extracted from cli/ai/session.py once cli/ai/skill.py and the per-provider
groups under cli/ai/claude/ and cli/ai/codex/ started duplicating the same
configuration. One canonical implementation; everyone calls it.
"""

from __future__ import annotations

import logging
import sys


def configure_logging(verbose: int) -> None:
    """Map -v count to log level, send `aifd.*` logger output to stderr.

    Default WARNING (silent for normal users).
        -v   -> INFO
        -vv+ -> DEBUG
    """
    if verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s [%(name)s] %(message)s"))
    aifd_logger = logging.getLogger("aifd")
    aifd_logger.handlers.clear()
    aifd_logger.addHandler(handler)
    aifd_logger.setLevel(level)
    aifd_logger.propagate = False
