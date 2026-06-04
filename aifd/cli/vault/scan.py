"""`aifd vault scan` — find PII / secrets across provider jsonl.

Default scope: all known provider history roots (Claude + Codex). Default
min_confidence: 7 (regex hits only — entropy-only matches need explicit
opt-in via --min-confidence 4 because they're noisy).

Output is safe to paste / share / log: every snippet is redacted
(first 4 + last 4 chars only, never the full secret).
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from aifd.cli._logging import configure_logging
from aifd.render import render_scan_matches
from aifd.vault.scan import scan_paths

logger = logging.getLogger("aifd")


@click.command(name="scan")
@click.option(
    "--root",
    "extra_roots",
    multiple=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
    help="Additional path to scan (file or directory). Default scans "
    "~/.claude/projects and ~/.codex/sessions. Repeatable.",
)
@click.option(
    "--min-confidence",
    type=click.IntRange(1, 10),
    default=7,
    show_default=True,
    help="Suppress findings below this confidence. 7 keeps regex hits "
    "(API keys, JWTs, emails). Lower to 4 to include entropy-only matches "
    "(often noisy: hashes, UUIDs, embeddings).",
)
@click.option(
    "--no-default-roots",
    is_flag=True,
    help="Skip ~/.claude and ~/.codex; only scan paths from --root.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="JSON output (pipe-friendly). Redacted snippets only — never the "
    "full secret value.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def scan(
    extra_roots: tuple[Path, ...],
    min_confidence: int,
    no_default_roots: bool,
    as_json: bool,
    verbose: int,
) -> None:
    """Scan provider jsonl for PII / API keys / secrets.

    By default scans ~/.claude/projects and ~/.codex/sessions. Add
    --root /path to scan extra locations, or --no-default-roots to scan
    only your --root paths.

    Output snippets are redacted (head + tail only). Safe to share.
    """
    configure_logging(verbose)

    roots: list[Path] = []
    if not no_default_roots:
        roots.append(Path.home() / ".claude" / "projects")
        roots.append(Path.home() / ".codex" / "sessions")
        roots.append(Path.home() / ".codex" / "archived_sessions")
    roots.extend(extra_roots)

    if not roots:
        raise click.UsageError(
            "No roots to scan. Drop --no-default-roots or supply --root PATH."
        )

    logger.info("Scanning %d root(s) for PII / secrets", len(roots))
    # Propagate min_confidence into the scanner so the entropy layer
    # (confidence 4-6 only) is skipped whenever the caller wouldn't
    # display its results. This is the main perf optimization — default
    # `aifd vault scan` (min_confidence=7) goes from ~50s to ~3s on
    # 800MB of jsonl by skipping shannon_entropy entirely.
    matches = list(scan_paths(roots, min_confidence=min_confidence))

    render_scan_matches(matches, as_json=as_json, min_confidence=min_confidence)
