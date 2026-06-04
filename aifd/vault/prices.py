"""Canonical model price table for `aifd vault cost`.

Prices are PER 1 MILLION tokens, in USD.

Sources (verified subset):
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  (fetched 2026-06-04 — every Claude entry below traces to that page)
- OpenAI:    https://openai.com/api/pricing
  (NOT fetched — Cloudflare blocked WebFetch on 2026-06-04. OpenAI rows
   below are best-effort estimates from public docs / training data; treat
   them as approximate. PRs welcome with verified numbers.)

Schema per row (all in USD / 1M tokens):
    input        fresh input
    output       completion tokens
    cache_write  5-minute prompt cache write (Anthropic: 1.25x base input;
                 1-hour writes are 2x base input — not modeled here, treat
                 5m as the default. OpenAI: ~= input rate)
    cache_read   cache hit / refresh (Anthropic: 0.1x base input;
                 OpenAI: similar ratio)
    reasoning    hidden reasoning tokens (OpenAI o-family / gpt-5;
                 billed at output rate. Always 0 for Claude.)

Anthropic note: starting with Opus 4.5, Opus pricing dropped from
$15/$75 to $5/$25. Earlier versions (Opus 4, Opus 4.1) retain the old
rate. The new tokenizer in Opus 4.7+ may use ~35% more tokens for
identical text; aifd counts actual reported tokens so this is already
accounted for automatically.
"""
# ruff: noqa: E501
# The price table uses aligned columns past 100 chars on purpose.
# Readability of the stacked input/output/cache_write/cache_read/reasoning
# columns beats the 100-char default.

from __future__ import annotations

LAST_UPDATED = "2026-06-04"
ANTHROPIC_VERIFIED_ON = "2026-06-04"
OPENAI_VERIFIED_ON: str | None = None  # set when WebFetch becomes viable


# fmt: off
_PRICE_TABLE: dict[str, dict[str, float]] = {
    # --- Anthropic Claude family (verified 2026-06-04 from platform.claude.com) ---
    # Opus 4.5+: NEW lower pricing tier ($5/$25)
    "claude-opus-4-8":       {"input":  5.00, "output": 25.00, "cache_write":  6.25, "cache_read": 0.50, "reasoning": 0.0},
    "claude-opus-4-7":       {"input":  5.00, "output": 25.00, "cache_write":  6.25, "cache_read": 0.50, "reasoning": 0.0},
    "claude-opus-4-6":       {"input":  5.00, "output": 25.00, "cache_write":  6.25, "cache_read": 0.50, "reasoning": 0.0},
    "claude-opus-4-5":       {"input":  5.00, "output": 25.00, "cache_write":  6.25, "cache_read": 0.50, "reasoning": 0.0},
    # Opus 4.1: legacy higher pricing tier ($15/$75)
    "claude-opus-4-1":       {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50, "reasoning": 0.0},
    # Opus 4: deprecated but still in jsonl history; old pricing
    "claude-opus-4":         {"input": 15.00, "output": 75.00, "cache_write": 18.75, "cache_read": 1.50, "reasoning": 0.0},
    # Sonnet 4.x: stable $3/$15 across versions
    "claude-sonnet-4-6":     {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30, "reasoning": 0.0},
    "claude-sonnet-4-5":     {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30, "reasoning": 0.0},
    "claude-sonnet-4":       {"input":  3.00, "output": 15.00, "cache_write":  3.75, "cache_read": 0.30, "reasoning": 0.0},
    # Haiku 4.x: stable $1/$5
    "claude-haiku-4-5":      {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10, "reasoning": 0.0},
    "claude-haiku-4":        {"input":  1.00, "output":  5.00, "cache_write":  1.25, "cache_read": 0.10, "reasoning": 0.0},
    # Haiku 3.5: retired except on Bedrock / Vertex; older pricing
    "claude-3-5-haiku":      {"input":  0.80, "output":  4.00, "cache_write":  1.00, "cache_read": 0.08, "reasoning": 0.0},

    # --- OpenAI Codex / GPT family (UNVERIFIED — estimates only) ---
    # WebFetch on https://openai.com/api/pricing returns 403 (Cloudflare).
    # Numbers below are public-knowledge estimates; verify before relying
    # on the absolute USD numbers. Token ratios (cached = 10x cheaper than
    # input, reasoning ~= output) are stable public policy.
    "gpt-5-codex":           {"input":  2.00, "output": 10.00, "cache_write":  2.00, "cache_read": 0.20, "reasoning": 10.00},
    "gpt-5":                 {"input":  2.50, "output": 10.00, "cache_write":  2.50, "cache_read": 0.25, "reasoning": 10.00},
    "gpt-5.5":               {"input":  2.50, "output": 10.00, "cache_write":  2.50, "cache_read": 0.25, "reasoning": 10.00},
    "gpt-5-mini":            {"input":  0.25, "output":  2.00, "cache_write":  0.25, "cache_read": 0.025, "reasoning": 2.00},
    "codex-auto-review":     {"input":  2.00, "output": 10.00, "cache_write":  2.00, "cache_read": 0.20, "reasoning": 10.00},
    "gpt-4o":                {"input":  2.50, "output": 10.00, "cache_write":  2.50, "cache_read": 1.25, "reasoning": 0.0},
    "gpt-4o-mini":           {"input":  0.15, "output":  0.60, "cache_write":  0.15, "cache_read": 0.075, "reasoning": 0.0},
    "o1":                    {"input": 15.00, "output": 60.00, "cache_write": 15.00, "cache_read": 7.50, "reasoning": 60.00},
    "o1-mini":               {"input":  1.10, "output":  4.40, "cache_write":  1.10, "cache_read": 0.55, "reasoning": 4.40},
    "o3":                    {"input":  2.00, "output":  8.00, "cache_write":  2.00, "cache_read": 0.50, "reasoning": 8.00},
    "o3-mini":               {"input":  1.10, "output":  4.40, "cache_write":  1.10, "cache_read": 0.55, "reasoning": 4.40},
}
# fmt: on


# Which model ids carry verified prices. Used by the CLI to mark each
# row with a "verified" / "estimate" badge so users see at a glance which
# numbers to trust without reading prices.py source.
VERIFIED_MODELS: frozenset[str] = frozenset(
    k for k in _PRICE_TABLE if k.startswith("claude-")
)


def lookup_price(model: str | None) -> dict[str, float] | None:
    """Return the price row for a model id, or None if unknown.

    Tries exact match first, then strips trailing date / minor-version
    suffixes (e.g. `-20251101`, `-preview`) and re-matches. Returning
    None signals "unknown model, skip cost calc but still surface
    tokens" to callers.
    """
    if not model:
        return None
    if model in _PRICE_TABLE:
        return _PRICE_TABLE[model]
    parts = model.split("-")
    while len(parts) > 1:
        parts.pop()
        candidate = "-".join(parts)
        if candidate in _PRICE_TABLE:
            return _PRICE_TABLE[candidate]
    return None


def is_verified(model: str | None) -> bool:
    """Whether a model's price was verified against the vendor page."""
    if not model:
        return False
    if model in VERIFIED_MODELS:
        return True
    parts = model.split("-")
    while len(parts) > 1:
        parts.pop()
        candidate = "-".join(parts)
        if candidate in VERIFIED_MODELS:
            return True
    return False


def known_models() -> list[str]:
    """Return sorted list of all priced model ids (for --help diagnostics)."""
    return sorted(_PRICE_TABLE.keys())
