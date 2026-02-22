"""Tests for src/llm/deepseek_v3.py and src/llm/llama_8b.py — unit tests with mocked API."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import config
from src.llm.base import LLMError
from src.llm.deepseek_v3 import NebiusDeepSeekV3Client
from src.llm.llama_8b import NebiusLlama8BClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat_response(content: str) -> MagicMock:
    """Build a fake openai ChatCompletion response object."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


MESSAGES = [{"role": "user", "content": "hello"}]


# ---------------------------------------------------------------------------
# NebiusDeepSeekV3Client
# ---------------------------------------------------------------------------

class TestDeepSeekV3Client:
    def test_raises_value_error_without_api_key(self, monkeypatch):
        monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
        with pytest.raises(ValueError, match="NEBIUS_API_KEY"):
            NebiusDeepSeekV3Client()

    async def test_complete_returns_content(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response('{"summary":"s","technologies":[],"structure":"t"}')
        client._client.chat.completions.create = AsyncMock(return_value=fake_response)

        result = await client.complete(MESSAGES)
        assert result == '{"summary":"s","technologies":[],"structure":"t"}'
        await client.close()

    async def test_complete_uses_correct_model(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["model"] == config.WORKER_MODEL
        await client.close()

    async def test_complete_uses_json_response_format(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}
        await client.close()

    async def test_complete_uses_correct_temperature(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        await client.close()

    async def test_complete_uses_correct_max_tokens(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048
        await client.close()

    async def test_complete_raises_llm_error_on_api_failure(self):
        client = NebiusDeepSeekV3Client()
        client._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("network error"))

        with pytest.raises(LLMError, match="Nebius API error"):
            await client.complete(MESSAGES)
        await client.close()

    async def test_complete_raises_llm_error_on_empty_content(self):
        client = NebiusDeepSeekV3Client()
        fake_response = _make_chat_response(None)  # type: ignore[arg-type]
        client._client.chat.completions.create = AsyncMock(return_value=fake_response)

        with pytest.raises(LLMError, match="empty content"):
            await client.complete(MESSAGES)
        await client.close()

    async def test_close_calls_underlying_close(self):
        client = NebiusDeepSeekV3Client()
        client._client.close = AsyncMock()
        await client.close()
        client._client.close.assert_called_once()


# ---------------------------------------------------------------------------
# NebiusLlama8BClient
# ---------------------------------------------------------------------------

class TestLlama8BClient:
    def test_raises_value_error_without_api_key(self, monkeypatch):
        monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
        with pytest.raises(ValueError, match="NEBIUS_API_KEY"):
            NebiusLlama8BClient()

    async def test_complete_returns_content(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response("some notes")
        client._client.chat.completions.create = AsyncMock(return_value=fake_response)

        result = await client.complete(MESSAGES)
        assert result == "some notes"
        await client.close()

    async def test_complete_uses_correct_model(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["model"] == config.PLANNER_MODEL
        await client.close()

    async def test_complete_does_not_use_json_response_format(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        # Llama client should NOT force JSON mode
        assert "response_format" not in call_kwargs

    async def test_complete_uses_correct_temperature(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["temperature"] == 0.2
        await client.close()

    async def test_complete_uses_correct_max_tokens(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response("ok")
        create_mock = AsyncMock(return_value=fake_response)
        client._client.chat.completions.create = create_mock

        await client.complete(MESSAGES)
        call_kwargs = create_mock.call_args.kwargs
        assert call_kwargs["max_tokens"] == 1024
        await client.close()

    async def test_complete_raises_llm_error_on_api_failure(self):
        client = NebiusLlama8BClient()
        client._client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

        with pytest.raises(LLMError, match="Nebius API error"):
            await client.complete(MESSAGES)
        await client.close()

    async def test_complete_raises_llm_error_on_empty_content(self):
        client = NebiusLlama8BClient()
        fake_response = _make_chat_response(None)  # type: ignore[arg-type]
        client._client.chat.completions.create = AsyncMock(return_value=fake_response)

        with pytest.raises(LLMError, match="empty content"):
            await client.complete(MESSAGES)
        await client.close()

    async def test_close_calls_underlying_close(self):
        client = NebiusLlama8BClient()
        client._client.close = AsyncMock()
        await client.close()
        client._client.close.assert_called_once()
