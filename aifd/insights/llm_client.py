"""Minimal LiteLLM wrapper for `aifd ai reflect` (v0.8).

LiteLLM normalizes 100+ LLM providers (OpenAI / Anthropic / Gemini / DeepSeek /
Zhipu / DashScope / Volcengine Ark / Moonshot / ollama / vLLM / Azure / Bedrock)
under one OpenAI-shaped ``completion()`` call.

Why LiteLLM, not a hand-rolled urllib client:
    Users want vendor flexibility (DeepSeek today; maybe 智谱 / 通义 / 方舟 tomorrow;
    maybe self-hosted Llama next year). Each vendor has OpenAI-compat quirks
    that LiteLLM already papers over: tool_call shape, response_format flavor,
    streaming chunk format, usage-field naming, retry/exception classification.

Why not the openai-sdk:
    openai-sdk via ``base_url=`` covers ~50% of the LLM endpoints aifd users
    ask about, but the Chinese-ecosystem providers in particular (智谱 GLM /
    DashScope / Volcengine Ark) have OpenAI-compat quirks that openai-sdk
    doesn't paper over. LiteLLM does.

Model string format — ``provider/model`` (LiteLLM dispatch convention):

    deepseek/deepseek-chat        — DeepSeek
    openai/gpt-4o                 — OpenAI
    anthropic/claude-sonnet-4     — Anthropic
    zhipu/glm-4-plus              — 智谱 GLM
    dashscope/qwen-plus           — 阿里通义千问
    ark/ep-xxx                    — 火山引擎方舟 (use endpoint_id)
    ollama/qwen2.5                — local ollama
    groq/llama-3.3-70b            — Groq

Retry policy (D4 from /plan-eng-review still holds, implemented via LiteLLM):
    - AuthenticationError / BadRequestError → no retry (LiteLLM default)
    - RateLimitError / Timeout / InternalServerError → retried ``num_retries``
    - Total wall-clock budget enforced via ``timeout=30``

Exceptions the caller must handle:
    - ``litellm.AuthenticationError`` — 401 / 403, bad or revoked key
    - ``litellm.RateLimitError`` — 429, back off
    - ``litellm.BadRequestError`` — 400, payload or model name wrong
    - ``litellm.Timeout`` / ``litellm.APIConnectionError`` — transient
    - ``litellm.APIError`` — catch-all from LiteLLM
    - ``LLMResponseError`` — content is not a JSON object (we raise this)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import litellm

logger = logging.getLogger("aifd.insights.llm")

_DEFAULT_MODEL = "deepseek/deepseek-chat"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_NUM_RETRIES = 1
_DEFAULT_MAX_TOKENS = 800
_DEFAULT_TEMPERATURE = 0.3


class LLMResponseError(Exception):
    """LLM returned non-JSON content or an unexpected envelope shape.

    Distinct from LiteLLM's own exception hierarchy (auth / rate / timeout /
    bad-request) because it's a schema problem the caller should surface
    rather than retry.
    """


def call(
    prompt: str,
    *,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
    api_base: str | None = None,
    temperature: float = _DEFAULT_TEMPERATURE,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    timeout: float = _DEFAULT_TIMEOUT,
    num_retries: int = _DEFAULT_NUM_RETRIES,
) -> dict[str, Any]:
    """One chat completion → parsed JSON content dict.

    ``api_key=None`` lets LiteLLM auto-discover from the provider's idiomatic
    env var (DEEPSEEK_API_KEY / ZHIPUAI_API_KEY / DASHSCOPE_API_KEY / ARK_API_KEY
    / ANTHROPIC_API_KEY / OPENAI_API_KEY / ...).

    Returns the parsed JSON dict from the LLM's message content. Raises:

    - ``litellm.AuthenticationError`` / ``BadRequestError`` / ``RateLimitError`` /
      ``Timeout`` / ``APIConnectionError`` / ``APIError`` — passed through.
    - ``LLMResponseError`` — content is not valid JSON, or not a JSON object.

    The caller (``aifd.cli.ai.reflect``) is responsible for converting these to
    a graceful fallback render. We deliberately do NOT swallow exceptions here:
    the wrapper's single job is `prompt → dict`, and error semantics belong to
    the layer that knows the user experience.
    """
    response = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        api_key=api_key,
        api_base=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        num_retries=num_retries,
    )

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise LLMResponseError(
            f"LLM response missing choices[0].message.content: {response!r}"
        ) from exc

    if not isinstance(content, str) or not content:
        raise LLMResponseError(f"LLM returned empty content: {content!r}")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        snippet = content[:120].replace("\n", " ")
        raise LLMResponseError(
            f"LLM content not valid JSON: {exc} (snippet: {snippet!r})"
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMResponseError(
            f"LLM content not a JSON object: got {type(parsed).__name__}"
        )

    return parsed
