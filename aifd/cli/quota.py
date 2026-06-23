"""`aifd quota` - AI subscription usage windows.

E3: a click group defaulting to MiniMax. `aifd quota` (no subcommand) shows
the MiniMax Coding Plan 5h rolling-window remaining quota. Future providers
(Claude / Cursor) add as `aifd quota <provider>` subcommands - additive, no
breaking rename.

Data source (spike 2026-06-23): GET coding_plan/remains with Bearer auth.
Best-effort: MiniMax's usage endpoint is undocumented; if the response shape
changes we fail with a clear "update aifd" message, never a stack trace.

SECURITY (E2 / outside-voice #2): the MiniMax key is a Bearer credential. It is
built into the Authorization header at the call site only and MUST NEVER reach
a log, error, or traceback - aifd's own `vault scan` flags `Bearer <key>` as a
secret. Every _QuotaError message is key-free; no except path interpolates the
key or the raw request object.

Response shape (spike-confirmed):

    { "model_remains": [ {model_name: "general"|"video",
                          current_interval_remaining_percent, remains_time(ms),
                          current_interval_total_count, current_interval_usage_count,
                          start_time, end_time, ...} ],
      "base_resp": {status_code: 0, status_msg: "success"} }

The coding plan is the `general` row. `total/usage_count` are often 0
(unreliable), so percent + the server-provided `remains_time` countdown are
the dependable signals.
"""

from __future__ import annotations

import json

import click
import httpx

from aifd.config import load as load_config

_USAGE_URL = "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains"
_REFERER = "https://platform.minimaxi.com/"
_TIMEOUT = 10.0
_CODING_MODEL = "general"  # coding-plan window is the 'general' model row


class _QuotaError(click.ClickException):
    """User-facing quota error. Message is SAFE - never carries the API key."""


@click.group(name="quota", invoke_without_command=True)
@click.pass_context
def quota(ctx: click.Context) -> None:
    """Show AI subscription usage (defaults to MiniMax Coding Plan)."""
    if ctx.invoked_subcommand is None:
        _run_minimax()


@quota.command(name="minimax")
def _minimax_cmd() -> None:
    """MiniMax Coding Plan - 5h rolling-window remaining quota."""
    _run_minimax()


def _run_minimax() -> None:
    cfg = load_config()
    key = cfg.minimax.api_key
    if not key:
        raise _QuotaError(
            "No MiniMax key. Set MINIMAX_API_KEY env var, or add a `minimax:` "
            "section with `api_key:` to ~/.aifd/config.yaml."
        )
    data = _fetch_remains(key)
    row = _select_model(data, _CODING_MODEL)
    click.echo(_render(row))


def _fetch_remains(key: str) -> dict[str, object]:
    """GET coding_plan/remains. Raise _QuotaError (key-free msg) on any failure.

    The key lives only in the Authorization header built here. No except path
    below interpolates the exception object or the request, so the key can
    never reach the screen or a log (E2 / outside-voice #2).
    """
    try:
        resp = httpx.get(
            _USAGE_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "referer": _REFERER,
                "Accept": "application/json",
            },
            timeout=_TIMEOUT,
        )
    except httpx.TimeoutException:
        # `from None` cuts the exception chain so the original httpx error
        # (which can carry the request + Bearer key) never surfaces (E2).
        raise _QuotaError(
            "MiniMax usage query timed out. Check your network."
        ) from None
    except httpx.HTTPError:
        # Deliberately drop the exception detail: it could echo the request and
        # leak the Bearer key. `from None` keeps the key off-screen and logs.
        raise _QuotaError("MiniMax usage query failed (network error).") from None

    if resp.status_code == 401:
        raise _QuotaError(
            "MiniMax key invalid or expired. Re-check MINIMAX_API_KEY."
        )
    if resp.status_code != 200:
        raise _QuotaError(
            f"MiniMax usage query returned HTTP {resp.status_code}."
        )

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        raise _QuotaError(
            "MiniMax returned non-JSON. Their API may have changed; update aifd."
        ) from None

    # Defensive parse (outside-voice #2): validate the shape we depend on.
    if not isinstance(data, dict):
        raise _QuotaError(
            "MiniMax response was not an object. Their API may have changed; "
            "update aifd."
        )
    base = data.get("base_resp")
    if not isinstance(base, dict) or base.get("status_code") != 0:
        raise _QuotaError(
            "MiniMax usage query unsuccessful. Their API may have changed; "
            "update aifd."
        )
    return data


def _select_model(data: dict[str, object], model_name: str) -> dict[str, object]:
    """Pick the row by explicit model_name, never by index (outside-voice #4).

    model_remains[] order is not guaranteed; selecting [0] could silently
    return the 'video' window instead of coding.
    """
    rows = data.get("model_remains")
    if not isinstance(rows, list) or not rows:
        # A valid key with no active plan returns success-shaped empty (#1).
        raise _QuotaError("No active MiniMax Coding Plan found for this key.")
    for row in rows:
        if isinstance(row, dict) and row.get("model_name") == model_name:
            return row
    raise _QuotaError(
        f"MiniMax response has no '{model_name}' window. Their API may have "
        "changed; update aifd."
    )


def _render(row: dict[str, object]) -> str:
    """Format one model window. Prefer count if reliable, else percent.

    Spike found current_interval_total_count often returns 0 (unreliable), so
    percent is the dependable signal; count is used only when it's > 0.
    """
    reset = _format_countdown(row.get("remains_time"))
    total = _safe_int(row.get("current_interval_total_count"))
    used = _safe_int(row.get("current_interval_usage_count"))
    pct = row.get("current_interval_remaining_percent")
    if total > 0:
        head = f"剩 {max(total - used, 0)}/{total}"
    elif isinstance(pct, (int, float)) and not isinstance(pct, bool):
        head = f"剩 {pct}%"
    else:
        head = "额度未知"
    return f"MiniMax 5h: {head}，{reset}"


def _format_countdown(remains_ms: object) -> str:
    """Server-provided ms countdown to a human reset string.

    Uses the server's remaining-ms, never the local clock (outside-voice #4),
    so clock skew cannot corrupt the countdown.
    """
    if not isinstance(remains_ms, (int, float)) or isinstance(remains_ms, bool):
        return "重置时间未知"
    if remains_ms <= 0:
        return "重置时间未知"
    secs = int(remains_ms / 1000)
    h, rem = divmod(secs, 3600)
    m = rem // 60
    return f"{h}h{m}m 后重置" if h > 0 else f"{m}m 后重置"


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0
