"""`aifd ai question` group and `aifd ai question list` command.

v0.3 feature — retro of AskUserQuestion decisions across AI tools.
v0.3.1 addition: --html output mode (CEO plan D2=A) so long-form Q + options
+ ELI10 / Stakes / Recommendation render cleanly in a browser, escaping
all user-derived text per D3=A.

Data flow:

    user runs `aifd ai question list [--cwd] [--html | --json]`
                    │
                    ▼
              list_cmd()  ── click parses flags (mutex --html/--json)
                    │
                    ▼
          run_provider_query(extractor=p.list_question_answers, ...)
                    │
                    ▼
          ┌─────────┴─────────┐
       ClaudeProvider     CodexProvider (no-op default)
       .list_question_answers
                    │
                    ▼
              list[QuestionAnswer]  (sorted by ts desc)
                    │
                    ▼
       ┌──────────┬──┴───┬─────────────────┐
       ▼          ▼      ▼                 ▼
    rich Table   JSON   HTML (stdout)    HTML (file + maybe webbrowser.open)
    + footer
"""

from __future__ import annotations

import sys
import tempfile
import webbrowser
from pathlib import Path

import click

from aifd.cli._runner import run_provider_query
from aifd.models import QuestionAnswer
from aifd.providers.base import Provider
from aifd.providers.registry import PROVIDERS
from aifd.render import render_question_answers, render_question_answers_html


@click.group()
def question() -> None:
    """Operations on AskUserQuestion calls (list, ...).

    Future: search by text, stats subcommand.
    """


@question.command(name="list")
@click.option(
    "--cwd",
    "cwd_scope",
    is_flag=True,
    help="Only show questions asked while in the current directory. Default is global.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output JSON instead of a rich table (pipe-friendly).",
)
@click.option(
    "--html",
    "as_html",
    is_flag=True,
    help="Print a self-contained HTML page to stdout (pipe-friendly, escaped, "
    "Notion-style reader). Mutually exclusive with --json. For one-shot "
    "browser viewing prefer --open.",
)
@click.option(
    "--open",
    "open_in_browser",
    is_flag=True,
    help="Render HTML to a temp file and open it in your default browser. "
    "Zero extra flags needed; mutually exclusive with --json.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Persist HTML to this path instead of a temp file. Implies --html. "
    "Combine with --open to also launch the browser.",
)
@click.option(
    "--provider",
    "providers",
    multiple=True,
    type=click.Choice([p.name for p in PROVIDERS], case_sensitive=False),
    help="Only include questions from the given provider. Repeatable.",
)
@click.option(
    "--limit",
    type=int,
    default=50,
    show_default=True,
    help="Show at most N most recent questions. Use --all to disable.",
)
@click.option(
    "--all",
    "all_rows",
    is_flag=True,
    help="Show every question (overrides --limit). Use with caution; --json "
    "and --html pipes downstream usually want this.",
)
@click.option(
    "-v",
    "--verbose",
    count=True,
    help="Increase log verbosity. -v=INFO, -vv=DEBUG. Logs go to stderr.",
)
def list_cmd(
    cwd_scope: bool,
    as_json: bool,
    as_html: bool,
    output_path: Path | None,
    open_in_browser: bool,
    providers: tuple[str, ...],
    limit: int,
    all_rows: bool,
    verbose: int,
) -> None:
    """List AskUserQuestion calls with the user's recorded answer.

    By default scans every project globally. Use --cwd to narrow to the
    current directory (mirrors `aifd ai session list` cwd scoping). JSON
    output includes the full per-question record including options,
    notes, tool_use_id, and source_path. HTML output renders a clean
    reader-mode page (escaped, Notion-style) so long-form Q text + options
    are fully visible in a browser.
    """
    # HTML mode triggers when --html, --open, or --output is present.
    # --open is the zero-friction path (writes a temp file + launches
    # browser), --html is the pipe-friendly path (HTML to stdout),
    # --output is the persistence modifier (write to a specific file).
    # All three are mutually exclusive with --json (different rendering
    # targets, not orthogonal flags).
    html_mode = as_html or open_in_browser or output_path is not None

    if html_mode and as_json:
        raise click.UsageError(
            "--json is mutually exclusive with --html/--open/--output"
        )

    scope_cwd = Path.cwd() if cwd_scope else None
    scope_label = str(Path.cwd()) if cwd_scope else "global"

    def extractor(provider: Provider, scope: Path | None) -> list[QuestionAnswer]:
        return list(provider.list_question_answers(scope))

    def render_fn(rows: list[QuestionAnswer], json_mode: bool) -> None:
        if not all_rows and limit > 0:
            rows = rows[:limit]

        if html_mode:
            _render_html(rows, scope_label, output_path, open_in_browser, as_html)
            return

        render_question_answers(rows, scope_label, as_json=json_mode)

    run_provider_query(
        providers_pool=PROVIDERS,
        extractor=extractor,
        providers_filter=providers,
        scope_cwd=scope_cwd,
        # Newest first; questions without timestamps sink to the bottom.
        sort_key=lambda qa: (qa.ts is None, qa.ts),
        render_fn=render_fn,
        as_json=as_json,
        verbose=verbose,
    )


def _render_html(
    rows: list[QuestionAnswer],
    scope_label: str,
    output_path: Path | None,
    open_in_browser: bool,
    explicit_html_flag: bool,
) -> None:
    """Render rows as HTML, routed by which flag the caller passed.

    Routing table:
        --open                         -> tempfile + open browser
        --html                         -> stdout (pipe-friendly)
        --output PATH                  -> persist to PATH (no browser)
        --open --output PATH           -> persist to PATH + open browser
        --html --output PATH           -> persist to PATH (no browser)
        --html --open                  -> tempfile + open browser
                                          (--html silent in this combo)

    D4=A: file-write failures surface as a one-line error on stderr + exit 1
    instead of an opaque Python traceback.
    """
    # Pure-stdout path: --html alone, no browser, no persistence.
    if explicit_html_flag and not open_in_browser and output_path is None:
        page = render_question_answers_html(rows, scope_label)
        assert page is not None  # path=None returns str
        sys.stdout.write(page)
        return

    # Resolve the destination. If --output is set, persist there; otherwise
    # write to a temp file the user can keep, share, or ignore.
    if output_path is not None:
        target = output_path
        is_temp = False
    else:
        # delete=False so the file survives this process (webbrowser.open
        # is async; reading the file might happen after Python exits).
        fd = tempfile.NamedTemporaryFile(
            prefix="aifd-questions-",
            suffix=".html",
            delete=False,
        )
        target = Path(fd.name)
        fd.close()
        is_temp = True

    try:
        render_question_answers_html(rows, scope_label, output_path=target)
    except OSError as exc:
        click.echo(f"Error: cannot write to {target}: {exc}", err=True)
        sys.exit(1)

    if open_in_browser:
        url = target.resolve().as_uri()
        # webbrowser.open silently no-ops on headless / WSL / SSH.
        # We still surface the path so the user can curl or scp it.
        webbrowser.open(url)
        click.echo(f"Opened {target}", err=True)
    else:
        # User asked for persistence via --output without --open. Tell them
        # where the file landed so they can `open` it themselves.
        if not is_temp:
            click.echo(f"Wrote {target}", err=True)
