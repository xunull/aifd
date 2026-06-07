"""Central user-config for aifd (v0.8).

`~/.aifd/config.yaml` — user-edited YAML, semantically distinct from
`~/.aifd/watch-state.json` (machine-written) and `~/.aifd/webhooks.yaml`
(user-written but webhooks-scoped). The format choice (YAML) mirrors
webhooks.yaml (D5 from /plan-eng-review): both are user-authored config,
both benefit from comments.

Read precedence (D2 from /plan-eng-review):
    env var > config.yaml > built-in default

Write: atomic tmp+rename (mirror watch_state pattern); chmod 0600 on
first write; warn-only when existing perms are world-readable.

Schema (v0.9.0):

    llm:
      provider: deepseek/deepseek-chat  # LiteLLM "provider/model" form
      api_key: sk-...                   # optional; LiteLLM also reads per-
                                        # provider env vars (DEEPSEEK_API_KEY,
                                        # ZHIPUAI_API_KEY, DASHSCOPE_API_KEY,
                                        # ANTHROPIC_API_KEY, OPENAI_API_KEY...)
      api_base: https://api.deepseek.com/v1   # optional override; needed for
                                              # ollama / Azure / self-hosted vLLM
    reflect:
      default_lang: zh
      include_questions: false
    habits:
      default_days: 90
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("aifd.config")

CONFIG_PATH = Path.home() / ".aifd" / "config.yaml"

# Sentinel so callers can detect "no path given" vs "explicit None" without
# changing the public API signature.
_UNSET: Path = Path()


def _default_config_path() -> Path:
    """Evaluate config path at call time so HOME monkeypatching in tests works."""
    return Path.home() / ".aifd" / "config.yaml"

# Aifd-shaped env vars override config.yaml. We deliberately do NOT shadow
# provider-specific vars (DEEPSEEK_API_KEY, ZHIPUAI_API_KEY, …): LiteLLM
# already auto-discovers those when api_key is None, and shadowing here
# would break users who switch providers via env without touching config.
_AIFD_ENV_API_KEY = "AIFD_LLM_API_KEY"
_AIFD_ENV_API_BASE = "AIFD_LLM_API_BASE"
_AIFD_ENV_MODEL = "AIFD_LLM_MODEL"

# Backwards-compat: v0.8 pre-release users may already have DEEPSEEK_API_KEY
# set; honor it when AIFD_LLM_API_KEY isn't present, so the upgrade is silent.
_LEGACY_ENV_API_KEY = "DEEPSEEK_API_KEY"


@dataclass(frozen=True)
class LLMConfig:
    """LLM endpoint config — works with any LiteLLM-supported provider."""

    model: str = "deepseek/deepseek-chat"
    api_key: str | None = None
    api_base: str | None = None


@dataclass(frozen=True)
class ReflectConfig:
    default_lang: str = "zh"
    include_questions: bool = False


@dataclass(frozen=True)
class HabitsConfig:
    """Config for `aifd ai habits` long-term behaviour analysis."""

    default_days: int = 90


@dataclass(frozen=True)
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    reflect: ReflectConfig = field(default_factory=ReflectConfig)
    habits: HabitsConfig = field(default_factory=HabitsConfig)


def load(path: Path = _UNSET) -> Config:
    if path is _UNSET:
        path = _default_config_path()
    """Read config from disk, apply env overrides, return Config.

    Missing file → defaults. Malformed YAML → warn + defaults (no crash).
    World-readable perms → warn but proceed.
    """
    data: dict[str, Any] = {}
    if path.exists():
        _warn_if_perms_too_open(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                data = raw
            else:
                logger.warning(
                    "%s must be a YAML mapping; got %s",
                    path, type(raw).__name__,
                )
        except yaml.YAMLError as exc:
            logger.warning("Cannot parse %s: %s — using defaults", path, exc)

    llm_data = data.get("llm") or {}
    reflect_data = data.get("reflect") or {}
    habits_data = data.get("habits") or {}
    if not isinstance(llm_data, dict):
        llm_data = {}
    if not isinstance(reflect_data, dict):
        reflect_data = {}
    if not isinstance(habits_data, dict):
        habits_data = {}

    api_key = (
        os.environ.get(_AIFD_ENV_API_KEY)
        or os.environ.get(_LEGACY_ENV_API_KEY)
        or llm_data.get("api_key")
    )
    api_base = (
        os.environ.get(_AIFD_ENV_API_BASE)
        or llm_data.get("api_base")
    )
    model = (
        os.environ.get(_AIFD_ENV_MODEL)
        or llm_data.get("model")
        or "deepseek/deepseek-chat"
    )

    raw_days = habits_data.get("default_days", 90)
    try:
        default_days = int(raw_days)
        if default_days < 1:
            default_days = 90
    except (TypeError, ValueError):
        default_days = 90

    return Config(
        llm=LLMConfig(
            api_key=api_key,
            model=model,
            api_base=api_base,
        ),
        reflect=ReflectConfig(
            default_lang=str(reflect_data.get("default_lang", "zh")),
            include_questions=bool(reflect_data.get("include_questions", False)),
        ),
        habits=HabitsConfig(
            default_days=default_days,
        ),
    )


def write_template(path: Path = _UNSET) -> None:
    if path is _UNSET:
        path = _default_config_path()
    """First-run helper: create ~/.aifd/config.yaml with commented template.

    Idempotent: skips if file already exists (don't clobber user edits).
    Chmods to 0600 immediately.
    """
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    template = (
        "# aifd config (v0.8). User-edited YAML.\n"
        "# Precedence: AIFD_LLM_* env vars > this file > built-in default.\n"
        "# LiteLLM also reads per-provider env vars (DEEPSEEK_API_KEY,\n"
        "# ZHIPUAI_API_KEY, DASHSCOPE_API_KEY, ARK_API_KEY, ANTHROPIC_API_KEY,\n"
        "# OPENAI_API_KEY, …) when api_key below is empty.\n"
        "\n"
        "llm:\n"
        "  # LiteLLM model string — 'provider/model'. Examples:\n"
        "  #   deepseek/deepseek-chat    (default)\n"
        "  #   openai/gpt-4o\n"
        "  #   anthropic/claude-sonnet-4\n"
        "  #   zhipu/glm-4-plus           (智谱)\n"
        "  #   dashscope/qwen-plus        (阿里通义)\n"
        "  #   ark/<endpoint_id>          (火山引擎方舟)\n"
        "  #   ollama/qwen2.5             (local ollama)\n"
        "  model: deepseek/deepseek-chat\n"
        "  # API key for the provider above. Leave empty to let LiteLLM read\n"
        "  # the provider's idiomatic env var.\n"
        "  api_key: \n"
        "  # Override endpoint for ollama / Azure / self-hosted vLLM /\n"
        "  # corporate gateways. Leave empty for hosted providers.\n"
        "  api_base: \n"
        "\n"
        "reflect:\n"
        "  # en | zh — output language for `aifd ai reflect`\n"
        "  default_lang: zh\n"
        "  # When true, --include-questions becomes default;\n"
        "  # sends question summaries to LLM (still NOT raw text).\n"
        "  include_questions: false\n"
        "\n"
        "habits:\n"
        "  # Default analysis window for `aifd ai habits` (days).\n"
        "  # Override per-run with --since Nd (e.g. --since 60d).\n"
        "  default_days: 90\n"
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(template, encoding="utf-8")
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError as exc:
        logger.warning("Cannot chmod %s to 0600: %s", path, exc)


def save(cfg: Config, path: Path = _UNSET) -> None:
    if path is _UNSET:
        path = _default_config_path()
    """Atomic write of a full Config back to disk. 0600 perms enforced.

    Used by future `aifd config set` subcommand (deferred to v0.8.1).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "llm": {
            "model": cfg.llm.model,
            "api_key": cfg.llm.api_key,
            "api_base": cfg.llm.api_base,
        },
        "reflect": {
            "default_lang": cfg.reflect.default_lang,
            "include_questions": cfg.reflect.include_questions,
        },
        "habits": {
            "default_days": cfg.habits.default_days,
        },
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError as exc:
        logger.warning("Cannot chmod %s to 0600: %s", path, exc)


def _warn_if_perms_too_open(path: Path) -> None:
    """Warn if other users can read the config file (API key risk).

    Best-effort: NFS / SMB mounts may not enforce POSIX perms, so we warn
    rather than fail. The warning is the safety net.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
        logger.warning(
            "%s permissions are world-readable (mode=%o). "
            "Run `chmod 600 %s` to protect your API key.",
            path, stat.S_IMODE(mode), path,
        )
