"""Tests for `aifd ai habits` CLI (T5)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import litellm
import pytest
from click.testing import CliRunner

from aifd.cli import cli

LOCAL_TZ = datetime.now().astimezone().tzinfo


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def isolated(
    runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Isolate HOME + strip every LLM-related env var.

    Mirrors test_cli_ai_reflect.py to avoid leaking real DEEPSEEK_API_KEY etc.
    """
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


def _stub_collect_habits(*args, **kwargs):
    """Return an empty-ish HabitsInput so we exercise the rendering layer."""
    from aifd.insights.habits import HabitsInput
    end = datetime.now().astimezone()
    start = end.replace(year=end.year - 1)
    return HabitsInput(period_start=start, period_end=end)


# ---------- --help ----------


def test_habits_help_advertises_flags(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["ai", "habits", "--help"])
    assert result.exit_code == 0
    assert "--since" in result.output
    assert "--lang" in result.output
    assert "--json" in result.output
    assert "--api-base" in result.output
    assert "--model" in result.output


# ---------- fallback when no API key ----------


def test_habits_no_api_key_fallback(
    runner: CliRunner, isolated: Path,
) -> None:
    with patch(
        "aifd.cli.ai.habits.collect_habits_data",
        side_effect=_stub_collect_habits,
    ):
        result = runner.invoke(cli, ["ai", "habits"])
    assert result.exit_code == 0
    assert "[fallback]" in result.stderr or "[fallback]" in result.output


def test_habits_no_api_key_json_fallback(
    runner: CliRunner, isolated: Path,
) -> None:
    with patch(
        "aifd.cli.ai.habits.collect_habits_data",
        side_effect=_stub_collect_habits,
    ):
        result = runner.invoke(cli, ["ai", "habits", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["prompt_version"] == "v1"
    assert "_fallback_reason" in parsed
    assert parsed["patterns"] == []


# ---------- successful LLM call ----------


def test_habits_calls_llm_when_key_set(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-test")
    fake_output = {
        "prompt_version": "v1",
        "patterns": [
            {
                "name": "周五放松崩",
                "evidence": "周五 vibe 比率是工作日 2x",
                "suggestion": "周五下午不开 review",
            },
        ],
    }
    with (
        patch(
            "aifd.cli.ai.habits.collect_habits_data",
            side_effect=_stub_collect_habits,
        ),
        patch(
            "aifd.cli.ai.habits.llm_call",
            return_value=fake_output,
        ) as mock_call,
    ):
        result = runner.invoke(cli, ["ai", "habits"])
    assert result.exit_code == 0
    assert mock_call.called
    assert "周五放松崩" in result.output


def test_habits_passes_provider_model_string(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-test")
    fake = {"prompt_version": "v1", "patterns": []}
    with (
        patch(
            "aifd.cli.ai.habits.collect_habits_data",
            side_effect=_stub_collect_habits,
        ),
        patch(
            "aifd.cli.ai.habits.llm_call", return_value=fake,
        ) as mock_call,
    ):
        runner.invoke(cli, [
            "ai", "habits",
            "--model", "zhipu/glm-4-plus",
            "--api-base", "http://127.0.0.1:11434/v1",
        ])
    kwargs = mock_call.call_args.kwargs
    assert kwargs["model"] == "zhipu/glm-4-plus"
    assert kwargs["api_base"] == "http://127.0.0.1:11434/v1"


# ---------- LLM errors fall back ----------


def test_habits_auth_failure_falls_back(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-bad")
    with (
        patch(
            "aifd.cli.ai.habits.collect_habits_data",
            side_effect=_stub_collect_habits,
        ),
        patch(
            "aifd.cli.ai.habits.llm_call",
            side_effect=litellm.AuthenticationError(
                message="401",
                llm_provider="deepseek",
                model="deepseek-chat",
            ),
        ),
    ):
        result = runner.invoke(cli, ["ai", "habits"])
    assert result.exit_code == 0
    assert "fallback" in result.stderr.lower() or "fallback" in result.output.lower()


def test_habits_bad_model_falls_back_with_model_hint(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    with (
        patch(
            "aifd.cli.ai.habits.collect_habits_data",
            side_effect=_stub_collect_habits,
        ),
        patch(
            "aifd.cli.ai.habits.llm_call",
            side_effect=litellm.BadRequestError(
                message="model not found",
                model="bogus",
                llm_provider="deepseek",
            ),
        ),
    ):
        result = runner.invoke(
            cli, ["ai", "habits", "--model", "deepseek/bogus"],
        )
    assert result.exit_code == 0
    assert "deepseek/bogus" in result.output or "deepseek/bogus" in result.stderr


# ---------- --since parsing ----------


def test_habits_since_shorthand_days(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--since 60d should narrow the window."""
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {"prompt_version": "v1", "patterns": []}
    captured: dict = {}

    def capture(start, end, **kwargs):
        captured["span_days"] = (end - start).days
        from aifd.insights.habits import HabitsInput
        return HabitsInput(period_start=start, period_end=end)

    with (
        patch("aifd.cli.ai.habits.collect_habits_data", side_effect=capture),
        patch("aifd.cli.ai.habits.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "habits", "--since", "60d"])
    assert result.exit_code == 0
    assert captured["span_days"] == 60


def test_habits_since_iso_date(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {"prompt_version": "v1", "patterns": []}
    captured: dict = {}

    def capture(start, end, **kwargs):
        captured["start_date"] = start.date().isoformat()
        from aifd.insights.habits import HabitsInput
        return HabitsInput(period_start=start, period_end=end)

    with (
        patch("aifd.cli.ai.habits.collect_habits_data", side_effect=capture),
        patch("aifd.cli.ai.habits.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "habits", "--since", "2026-01-01"])
    assert result.exit_code == 0
    assert captured["start_date"] == "2026-01-01"


def test_habits_default_window_uses_config_default_days(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No --since → uses cfg.habits.default_days (default 90)."""
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {"prompt_version": "v1", "patterns": []}
    captured: dict = {}

    def capture(start, end, **kwargs):
        captured["span_days"] = (end - start).days
        from aifd.insights.habits import HabitsInput
        return HabitsInput(period_start=start, period_end=end)

    with (
        patch("aifd.cli.ai.habits.collect_habits_data", side_effect=capture),
        patch("aifd.cli.ai.habits.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "habits"])
    assert result.exit_code == 0
    assert captured["span_days"] == 90


def test_habits_config_yaml_override_default_days(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When config.yaml sets habits.default_days, no --since uses it."""
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    cfg = isolated / ".aifd" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text("habits:\n  default_days: 30\n")

    fake = {"prompt_version": "v1", "patterns": []}
    captured: dict = {}

    def capture(start, end, **kwargs):
        captured["span_days"] = (end - start).days
        from aifd.insights.habits import HabitsInput
        return HabitsInput(period_start=start, period_end=end)

    with (
        patch("aifd.cli.ai.habits.collect_habits_data", side_effect=capture),
        patch("aifd.cli.ai.habits.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "habits"])
    assert result.exit_code == 0
    assert captured["span_days"] == 30


# ---------- --lang ----------


def test_habits_lang_en(
    runner: CliRunner, isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "sk-x")
    fake = {
        "prompt_version": "v1",
        "patterns": [
            {
                "name": "Friday-vibes",
                "evidence": "Vibe rate 2x on Fridays",
                "suggestion": "Skip reviews on Friday afternoons",
            },
        ],
    }
    with (
        patch(
            "aifd.cli.ai.habits.collect_habits_data",
            side_effect=_stub_collect_habits,
        ),
        patch("aifd.cli.ai.habits.llm_call", return_value=fake),
    ):
        result = runner.invoke(cli, ["ai", "habits", "--lang", "en"])
    assert result.exit_code == 0
    assert "Friday-vibes" in result.output
    assert "Pattern 1" in result.output
