from abc import ABC, abstractmethod

from openai.types.chat import ChatCompletionMessageParam


class LLMError(Exception):
    pass


class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(self, messages: list[ChatCompletionMessageParam]) -> str:
        ...
