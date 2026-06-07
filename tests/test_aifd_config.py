"""Tests for aifd/config.py — YAML config + env precedence + perms."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from aifd.config import (
    CONFIG_PATH,
    Config,
    HabitsConfig,
    LLMConfig,
    ReflectConfig,
    load,
    save,
    write_template,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in (
        "AIFD_LLM_API_KEY",
        "AIFD_LLM_API_BASE",
        "AIFD_LLM_MODEL",
        "DEEPSEEK_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


@pytest.fixture
def cfg_path(home: Path) -> Path:
    return home / ".aifd" / "config.yaml"


# ---------- load: missing file ----------


def test_load_missing_returns_defaults(cfg_path: Path) -> None:
    cfg = load(cfg_path)
    assert cfg.llm.api_key is None
    assert cfg.llm.model == "deepseek/deepseek-chat"
    assert cfg.llm.api_base is None
    assert cfg.reflect.default_lang == "zh"
    assert cfg.reflect.include_questions is False


# ---------- load: YAML parsing ----------


def test_load_valid_yaml(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "llm:\n"
        "  api_key: sk-test-123\n"
        "  model: zhipu/glm-4-plus\n"
        "  api_base: http://127.0.0.1:11434/v1\n"
        "reflect:\n"
        "  default_lang: en\n"
    )
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "sk-test-123"
    assert cfg.llm.model == "zhipu/glm-4-plus"
    assert cfg.llm.api_base == "http://127.0.0.1:11434/v1"
    assert cfg.reflect.default_lang == "en"


def test_load_malformed_yaml_uses_defaults(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("not :: valid {{{")
    cfg = load(cfg_path)
    assert cfg.llm.api_key is None
    assert cfg.llm.model == "deepseek/deepseek-chat"


def test_load_non_mapping_yaml_uses_defaults(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("- this\n- is\n- a list\n")
    cfg = load(cfg_path)
    assert cfg.llm.api_key is None


def test_load_partial_yaml_fills_defaults(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: sk-only-this\n")
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "sk-only-this"
    assert cfg.llm.model == "deepseek/deepseek-chat"  # default filled
    assert cfg.reflect.default_lang == "zh"  # default filled


# ---------- load: env precedence ----------


def test_aifd_env_overrides_yaml_for_api_key(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: from-yaml\n")
    monkeypatch.setenv("AIFD_LLM_API_KEY", "from-env")
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "from-env"


def test_legacy_deepseek_env_var_still_honored(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.8 pre-release users with DEEPSEEK_API_KEY set should keep working."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: from-yaml\n")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-env-key")
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "legacy-env-key"


def test_aifd_env_wins_over_legacy_deepseek_env(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_API_KEY", "aifd-env")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-env")
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "aifd-env"


def test_env_overrides_yaml_for_api_base(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(
        "llm:\n  api_base: https://yaml-host/v1\n",
    )
    monkeypatch.setenv("AIFD_LLM_API_BASE", "https://env-host/v1")
    cfg = load(cfg_path)
    assert cfg.llm.api_base == "https://env-host/v1"


def test_env_overrides_yaml_for_model(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIFD_LLM_MODEL", "anthropic/claude-sonnet-4")
    cfg = load(cfg_path)
    assert cfg.llm.model == "anthropic/claude-sonnet-4"


def test_yaml_used_when_env_unset(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: from-yaml\n")
    cfg = load(cfg_path)
    assert cfg.llm.api_key == "from-yaml"


# ---------- write_template ----------


def test_write_template_creates_file_with_0600(cfg_path: Path) -> None:
    write_template(cfg_path)
    assert cfg_path.exists()
    mode = stat.S_IMODE(cfg_path.stat().st_mode)
    assert mode == 0o600


def test_write_template_idempotent_does_not_clobber(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("# user edits\nllm:\n  api_key: sk-user\n")
    original = cfg_path.read_text()
    write_template(cfg_path)  # should be no-op
    assert cfg_path.read_text() == original


def test_write_template_includes_helpful_comments(cfg_path: Path) -> None:
    write_template(cfg_path)
    content = cfg_path.read_text()
    # Mentions multiple providers so users see the LiteLLM flexibility
    assert "deepseek" in content
    assert "zhipu" in content or "智谱" in content
    assert "ollama" in content
    assert "default_lang" in content


# ---------- save ----------


def test_save_then_load_roundtrip(cfg_path: Path) -> None:
    cfg = Config(
        llm=LLMConfig(
            api_key="sk-rt", model="dashscope/qwen-plus",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        reflect=ReflectConfig(default_lang="en", include_questions=True),
    )
    save(cfg, cfg_path)
    loaded = load(cfg_path)
    assert loaded.llm.api_key == "sk-rt"
    assert loaded.llm.model == "dashscope/qwen-plus"
    assert loaded.llm.api_base == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert loaded.reflect.default_lang == "en"
    assert loaded.reflect.include_questions is True


def test_save_atomic_no_partial(cfg_path: Path) -> None:
    """tmp + rename means an interrupted save leaves the previous file."""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: original\n")
    save(Config(), cfg_path)
    # tmp file should not exist
    assert not cfg_path.with_suffix(cfg_path.suffix + ".tmp").exists()


def test_save_chmod_0600(cfg_path: Path) -> None:
    save(Config(llm=LLMConfig(api_key="sk-x")), cfg_path)
    mode = stat.S_IMODE(cfg_path.stat().st_mode)
    assert mode == 0o600


# ---------- world-readable perm warning ----------


def test_warns_when_perms_world_readable(
    cfg_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: sk-leaky\n")
    cfg_path.chmod(0o644)  # world-readable
    with caplog.at_level("WARNING", logger="aifd.config"):
        load(cfg_path)
    assert any("world-readable" in r.message for r in caplog.records)


def test_no_warning_when_perms_correct(
    cfg_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("llm:\n  api_key: sk-safe\n")
    cfg_path.chmod(0o600)
    with caplog.at_level("WARNING", logger="aifd.config"):
        load(cfg_path)
    assert not any("world-readable" in r.message for r in caplog.records)


# ---------- default CONFIG_PATH ----------


def test_config_path_constant_under_home() -> None:
    assert CONFIG_PATH.parent.name == ".aifd"
    assert CONFIG_PATH.name == "config.yaml"


# ---------- HabitsConfig ----------


def test_load_habits_config_default(cfg_path: Path) -> None:
    cfg = load(cfg_path)
    assert cfg.habits.default_days == 90


def test_load_habits_config_from_yaml(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("habits:\n  default_days: 60\n")
    cfg = load(cfg_path)
    assert cfg.habits.default_days == 60


def test_load_habits_invalid_days_falls_back_to_default(cfg_path: Path) -> None:
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("habits:\n  default_days: not-a-number\n")
    cfg = load(cfg_path)
    assert cfg.habits.default_days == 90


def test_save_habits_roundtrip(cfg_path: Path) -> None:
    cfg = Config(habits=HabitsConfig(default_days=60))
    save(cfg, cfg_path)
    loaded = load(cfg_path)
    assert loaded.habits.default_days == 60


def test_write_template_includes_habits_section(cfg_path: Path) -> None:
    write_template(cfg_path)
    content = cfg_path.read_text()
    assert "habits:" in content
    assert "default_days" in content
