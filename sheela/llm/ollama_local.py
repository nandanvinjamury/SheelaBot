"""Local Ollama provider — future option for fully-local inference."""
from __future__ import annotations

from typing import AsyncIterator

from sheela.llm.base import Message, ResponseChunk, Tool


class OllamaLocalProvider:
    async def respond(
        self,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]:
        raise NotImplementedError("OllamaLocalProvider — future, not implemented yet")
        yield  # noqa — unreachable; required to make this an async generator

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("OllamaLocalProvider — future, not implemented yet")

    async def summarize(self, text: str, max_tokens: int) -> str:
        raise NotImplementedError("OllamaLocalProvider — future, not implemented yet")
