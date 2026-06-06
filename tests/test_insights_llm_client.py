"""Tests for `aifd.insights.llm_client` (LiteLLM wrapper).

We mock `litellm.completion` at the module-import point. Unit tests are
fast and offline; the real-API smoke test lives in `test_litellm_live.py`
behind the `live_api` pytest marker.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import litellm
import pytest

from aifd.insights.llm_client import LLMResponseError, call


def _fake_response(content: Any) -> MagicMock:
    """Build a ModelResponse-shaped mock with ``choices[0].message.content``."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------- happy path ----------


def test_call_returns_parsed_json_dict() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"essay":"hello","wins":[]}')
        result = call(
            "test prompt",
            model="deepseek/deepseek-chat",
            api_key="sk-test",
        )
    assert result == {"essay": "hello", "wins": []}


def test_call_forwards_response_format_json_object() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call("p", model="deepseek/deepseek-chat", api_key="sk")
    kwargs = mock.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


def test_call_forwards_model_string_unchanged() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call("p", model="zhipu/glm-4-plus", api_key="sk")
    assert mock.call_args.kwargs["model"] == "zhipu/glm-4-plus"


def test_call_forwards_api_base_for_self_hosted() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call(
            "p",
            model="ollama/qwen2.5",
            api_key=None,
            api_base="http://127.0.0.1:11434/v1",
        )
    assert mock.call_args.kwargs["api_base"] == "http://127.0.0.1:11434/v1"


def test_call_forwards_temperature_and_max_tokens() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call("p", api_key="sk", temperature=0.7, max_tokens=200)
    kwargs = mock.call_args.kwargs
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 200


def test_call_uses_timeout_and_num_retries_defaults() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call("p", api_key="sk")
    kwargs = mock.call_args.kwargs
    assert kwargs["timeout"] == 30.0
    assert kwargs["num_retries"] == 1


def test_call_allows_api_key_none_for_autodiscover() -> None:
    """LiteLLM auto-discovers from per-provider env vars when api_key is None."""
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('{"x":1}')
        call("p", model="anthropic/claude-sonnet-4", api_key=None)
    assert mock.call_args.kwargs["api_key"] is None


# ---------- schema errors (we raise LLMResponseError) ----------


def test_call_raises_on_non_json_content() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response("not json at all")
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            call("p", api_key="sk")


def test_call_raises_on_json_list_not_object() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response('["a","b","c"]')
        with pytest.raises(LLMResponseError, match="not a JSON object"):
            call("p", api_key="sk")


def test_call_raises_on_empty_content() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.return_value = _fake_response("")
        with pytest.raises(LLMResponseError, match="empty content"):
            call("p", api_key="sk")


def test_call_raises_on_missing_choices() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        broken = MagicMock()
        broken.choices = []  # IndexError when we touch [0]
        mock.return_value = broken
        with pytest.raises(LLMResponseError, match="missing choices"):
            call("p", api_key="sk")


# ---------- pass-through of LiteLLM exceptions ----------


def test_call_propagates_authentication_error() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.side_effect = litellm.AuthenticationError(
            message="invalid api key",
            llm_provider="deepseek",
            model="deepseek-chat",
        )
        with pytest.raises(litellm.AuthenticationError):
            call("p", api_key="bad")


def test_call_propagates_rate_limit_error() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.side_effect = litellm.RateLimitError(
            message="too many requests",
            llm_provider="deepseek",
            model="deepseek-chat",
        )
        with pytest.raises(litellm.RateLimitError):
            call("p", api_key="sk")


def test_call_propagates_bad_request_error() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.side_effect = litellm.BadRequestError(
            message="model not found",
            model="bogus-model",
            llm_provider="deepseek",
        )
        with pytest.raises(litellm.BadRequestError):
            call("p", model="deepseek/bogus-model", api_key="sk")


def test_call_propagates_timeout() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.side_effect = litellm.Timeout(
            message="request timed out",
            model="deepseek-chat",
            llm_provider="deepseek",
        )
        with pytest.raises(litellm.Timeout):
            call("p", api_key="sk")


def test_call_propagates_api_connection_error() -> None:
    with patch("aifd.insights.llm_client.litellm.completion") as mock:
        mock.side_effect = litellm.APIConnectionError(
            message="connection refused",
            llm_provider="ollama",
            model="qwen2.5",
        )
        with pytest.raises(litellm.APIConnectionError):
            call("p", api_key=None, api_base="http://127.0.0.1:11434/v1")
