"""Tests for rotation playbook library + i18n + webhook render."""

from __future__ import annotations

import pytest

from aifd.vault.playbooks import (
    PLAYBOOKS,
    known_categories,
    lookup,
    render_for_webhook,
)

# ---------- lookup ----------


def test_lookup_known_returns_playbook() -> None:
    pb = lookup("openai_key")
    assert pb["vendor_dashboard"] == "https://platform.openai.com/api-keys"
    assert "en" in pb["instruction"]
    assert "zh" in pb["instruction"]


def test_lookup_unknown_falls_back_to_generic() -> None:
    pb = lookup("nonexistent_category")
    assert pb["severity"] == "high"
    assert "en" in pb["instruction"]
    assert "zh" in pb["instruction"]
    # generic has empty dashboard
    assert pb["vendor_dashboard"] == ""


def test_lookup_never_raises_on_arbitrary_input() -> None:
    for cat in ("", "foo", "OPENAI_KEY", "openai-key", "../etc/passwd"):
        lookup(cat)  # must not raise


# ---------- i18n coverage ----------


@pytest.mark.parametrize("category", list(PLAYBOOKS.keys()))
def test_every_category_has_en_zh_instruction(category: str) -> None:
    pb = PLAYBOOKS[category]
    assert "en" in pb["instruction"]
    assert "zh" in pb["instruction"]
    assert pb["instruction"]["en"].strip()
    assert pb["instruction"]["zh"].strip()


@pytest.mark.parametrize("category", list(PLAYBOOKS.keys()))
def test_every_category_has_severity(category: str) -> None:
    pb = PLAYBOOKS[category]
    assert pb["severity"] in {"critical", "high", "medium", "low"}


# ---------- core categories present ----------


def test_required_categories_shipped() -> None:
    """v0.7 acceptance: these categories MUST ship with non-generic playbooks."""
    required = {
        "openai_key", "anthropic_key", "github_pat", "aws_access_key",
        "aws_secret", "jwt", "slack_token", "gcp_service_account",
    }
    assert required.issubset(set(PLAYBOOKS.keys()))


# ---------- render_for_webhook ----------


def test_render_for_webhook_en() -> None:
    payload = render_for_webhook("openai_key", lang="en")
    assert payload["vendor_dashboard"].startswith("https://platform.openai.com")
    assert "Revoke" in payload["instruction"]
    assert payload["severity"] == "critical"


def test_render_for_webhook_zh() -> None:
    payload = render_for_webhook("openai_key", lang="zh")
    assert "撤销" in payload["instruction"]


def test_render_for_webhook_unknown_lang_falls_back_to_en() -> None:
    payload = render_for_webhook("openai_key", lang="ja")
    # Falls back to English
    assert "Revoke" in payload["instruction"]


def test_render_for_webhook_unknown_category_returns_generic() -> None:
    payload = render_for_webhook("not_a_real_category", lang="en")
    assert payload["vendor_dashboard"] == ""
    assert payload["instruction"]  # non-empty
    assert payload["severity"] == "high"


# ---------- known_categories sorted ----------


def test_known_categories_sorted() -> None:
    cats = known_categories()
    assert cats == sorted(cats)
    assert "openai_key" in cats
