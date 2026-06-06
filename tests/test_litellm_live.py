"""Opt-in live LLM API test (D7).

NOT run in CI. Run manually before a release:

    DEEPSEEK_API_KEY=sk-... uv run pytest tests/test_litellm_live.py -m live_api -v

Cost: ~$0.001/run. Verifies the LLM wire format / response schema hasn't
drifted from what LiteLLM expects. If this fails, mocked tests would
still pass but real users would see broken reflections.

By default this hits DeepSeek (deepseek/deepseek-chat). Override with
AIFD_LIVE_MODEL to test other providers, e.g.:

    AIFD_LIVE_MODEL=zhipu/glm-4-plus ZHIPUAI_API_KEY=... \\
        uv run pytest tests/test_litellm_live.py -m live_api -v
"""

from __future__ import annotations

import os

import pytest

from aifd.insights.llm_client import call as llm_call


@pytest.mark.live_api
def test_real_llm_call_returns_valid_json() -> None:
    """Hit a real LLM with a minimal prompt → expect valid JSON output."""
    # Default to DeepSeek; LiteLLM auto-reads DEEPSEEK_API_KEY (or whichever
    # per-provider env var matches the model). The test is skipped when the
    # matching env var is not set, to keep CI clean.
    model = os.environ.get("AIFD_LIVE_MODEL", "deepseek/deepseek-chat")
    provider = model.split("/", 1)[0]
    env_candidates = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "zhipu": "ZHIPUAI_API_KEY",
        "dashscope": "DASHSCOPE_API_KEY",
        "ark": "ARK_API_KEY",
        "groq": "GROQ_API_KEY",
        "together": "TOGETHER_API_KEY",
    }
    env_var = env_candidates.get(provider, "AIFD_LLM_API_KEY")
    api_key = os.environ.get(env_var) or os.environ.get("AIFD_LLM_API_KEY")
    if not api_key:
        pytest.skip(f"{env_var} not set; cannot run live test against {model}")

    prompt = (
        "Output a JSON object with exactly these keys: "
        '{"essay": "<one short sentence>", '
        '"wins": [], "anti_pattern": "test", "concrete_action": "test"}'
    )
    result = llm_call(prompt, model=model, api_key=api_key, max_tokens=200)

    # Wire-format assertion: result is a dict (response_format=json_object held)
    assert isinstance(result, dict)
    # The LLM may add extra keys but should at least include `essay`
    assert "essay" in result
    assert isinstance(result["essay"], str)
    assert len(result["essay"]) > 0
