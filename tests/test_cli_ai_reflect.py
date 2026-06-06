"""Tests for `aifd ai reflect` CLI (T7)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import litellm
import pytest
from click.testing import CliRunner

from aifd.cli import cli
from aifd.insights.activity import ActivityReport


def _empty_report() -> ActivityReport:
    return ActivityReport(
        period_start=datetime(2026, 6, 1, tzinfo=UTC),
        period_end=datetime(2026, 6, 7, tzinfo=UTC),
        session_count=0, cost_usd=0.0, total_tokens=0,
        by_provider=[], top_skills=[], top_topics=[],
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Isolate HOME and strip every LLM-related env var so no real config or
    inherited credentials reach the test under any provider."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in (
        "AIFD_LLM_API_KEY",
        "AIFD_LLM_API_BASE",
        "AIFD_LLM_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ZHIPUAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "ARK_API_KEY",
        "GROQ_API_KEY",
        "TOGETHER_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


# ---------- --help ----------


def test_reflect_help_advertises_flags(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["ai", "reflect", "--help"])
    assert result.exit_code == 0
    assert "--week" in result.output
    assert "--month" in result.output
    assert "--since" in result.output
    assert "--lang" in result.output
    assert "--json" in result.output
    assert "--api-base" in result.output
    assert "--model" in result.output


# ---------- fallback when no API key ----------


def test_reflect_no_api_key_fallback(
    runner: CliRunner, isolated: Path,
) -> None:
    with patch(
        "aifd.insights.reflection.summarize_activity",
        return_value=_empty_report(),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week"])
    assert result.exit_code == 0
    assert "[fallback]" in result.stderr or "[fallback]" in result.output
    # Falls through to render — must NOT crash
    assert "AI coach unavailable" in result.output


def test_reflect_no_api_key_json_fallback(
    runner: CliRunner, isolated: Path,
) -> None:
    with patch(
        "aifd.insights.reflection.summarize_activity",
        return_value=_empty_report(),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["prompt_version"] == "v1"
    assert "_fallback_reason" in parsed


# ---------- successful LLM call ----------


def test_reflect_calls_llm_when_key_set(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-test")
    fake_llm_output = {
        "prompt_version": "v1",
        "essay": "Test essay content.",
        "wins": ["a", "b", "c"],
        "anti_pattern": "test anti",
        "concrete_action": "do x next week",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call",
            return_value=fake_llm_output,
        ) as mock_call,
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week", "--lang", "en"])
    assert result.exit_code == 0
    assert mock_call.called
    assert "Test essay content" in result.output


def test_reflect_passes_api_base_override(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-test")
    fake = {
        "prompt_version": "v1", "essay": "x",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call", return_value=fake,
        ) as mock_call,
    ):
        runner.invoke(cli, [
            "ai", "reflect", "--week",
            "--api-base", "http://127.0.0.1:11434/v1",
            "--model", "ollama/qwen2.5",
        ])
    kwargs = mock_call.call_args.kwargs
    assert kwargs["api_base"] == "http://127.0.0.1:11434/v1"
    assert kwargs["model"] == "ollama/qwen2.5"


def test_reflect_passes_provider_model_string(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--model accepts LiteLLM's 'provider/model' format unchanged."""
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-test")
    fake = {
        "prompt_version": "v1", "essay": "x",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call", return_value=fake,
        ) as mock_call,
    ):
        runner.invoke(cli, [
            "ai", "reflect", "--week", "--model", "zhipu/glm-4-plus",
        ])
    assert mock_call.call_args.kwargs["model"] == "zhipu/glm-4-plus"


# ---------- LLM error fallback ----------


def test_reflect_auth_failure_falls_back(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-bad")
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call",
            side_effect=litellm.AuthenticationError(
                message="401 unauthorized",
                llm_provider="deepseek",
                model="deepseek-chat",
            ),
        ),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week"])
    assert result.exit_code == 0
    assert "fallback" in result.stderr.lower() or "fallback" in result.output.lower()


def test_reflect_transient_falls_back(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-ok")
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call",
            side_effect=litellm.APIConnectionError(
                message="network down",
                llm_provider="deepseek",
                model="deepseek-chat",
            ),
        ),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week"])
    assert result.exit_code == 0
    assert "AI coach unavailable" in result.output


def test_reflect_bad_request_falls_back_with_model_hint(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad model name → fallback hint mentions the model the user passed."""
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-ok")
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch(
            "aifd.cli.ai.reflect.llm_call",
            side_effect=litellm.BadRequestError(
                message="model not found",
                model="bogus",
                llm_provider="deepseek",
            ),
        ),
    ):
        result = runner.invoke(
            cli, ["ai", "reflect", "--week", "--model", "deepseek/bogus"],
        )
    assert result.exit_code == 0
    # Fallback reason surfaces the model name from --model flag
    assert "deepseek/bogus" in result.output or "deepseek/bogus" in result.stderr


# ---------- verbose timing breakdown (D8) ----------


def test_reflect_verbose_shows_timing(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {
        "prompt_version": "v1", "essay": "x",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch("aifd.cli.ai.reflect.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week", "-v"])
    assert result.exit_code == 0
    # Verbose adds timing line — vendor-neutral 'llm=' key after the swap
    assert "llm=" in result.output
    assert "local=" in result.output


# ---------- custom window ----------


def test_reflect_custom_since_until(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {
        "prompt_version": "v1", "essay": "x",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch("aifd.cli.ai.reflect.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, [
            "ai", "reflect", "--since", "2026-06-01", "--until", "2026-06-07",
        ])
    assert result.exit_code == 0


# ---------- --lang override ----------


def test_reflect_lang_zh_default(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {
        "prompt_version": "v1", "essay": "测试反思",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch("aifd.cli.ai.reflect.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week"])
    assert result.exit_code == 0
    # zh shows up in essay rendering
    assert "测试反思" in result.output


def test_reflect_lang_en_override(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {
        "prompt_version": "v1", "essay": "test english essay",
        "wins": [], "anti_pattern": "x", "concrete_action": "x",
    }
    with (
        patch(
            "aifd.insights.reflection.summarize_activity",
            return_value=_empty_report(),
        ),
        patch("aifd.cli.ai.reflect.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "reflect", "--week", "--lang", "en"])
    assert result.exit_code == 0
    assert "Try next period" in result.output
