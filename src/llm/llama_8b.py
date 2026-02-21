import os

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .base import BaseLLMClient, LLMError
from .. import config


class NebiusLlama8BClient(BaseLLMClient):
    def __init__(self) -> None:
        api_key = os.environ.get(config.NEBIUS_API_KEY_ENV)
        if not api_key:
            raise ValueError(f"Missing required env var: {config.NEBIUS_API_KEY_ENV}")
        self._client = AsyncOpenAI(
            base_url=config.NEBIUS_API_BASE,
            api_key=api_key,
        )

    async def complete(self, messages: list[ChatCompletionMessageParam]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=config.PLANNER_MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as exc:
            raise LLMError(f"Nebius API error: {exc}") from exc
        content = response.choices[0].message.content
        if content is None:
            raise LLMError("Nebius API returned empty content")
        return content

    async def close(self) -> None:
        await self._client.close()
