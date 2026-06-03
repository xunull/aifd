"""Provider registry.

Add a new provider here in one line — that's the contract for v0.2 Cursor
support and any community plugins (e.g. Jetbrains AI, Continue.dev).
"""

from __future__ import annotations

from aifd.providers.base import Provider
from aifd.providers.claude import ClaudeProvider
from aifd.providers.codex import CodexProvider

PROVIDERS: list[Provider] = [
    ClaudeProvider(),
    CodexProvider(),
    # v0.2: CursorProvider(),
]
