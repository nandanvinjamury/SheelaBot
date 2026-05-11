"""Anthropic provider — opt-in fallback if Gemini is unavailable.

Never enabled by default. Activated only when the user sets
ANTHROPIC_API_KEY and LLM_PROVIDER=anthropic.
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from sheela.llm.base import Message, ResponseChunk


class AnthropicProvider:
    async def respond(
        self,
        system_prompt: str,
        messages: list[Message],
        tools: list[Callable[..., Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]:
        raise NotImplementedError("AnthropicProvider — fallback, not implemented yet")
        yield  # noqa — unreachable; required to make this an async generator

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("AnthropicProvider — fallback, not implemented yet")

    async def summarize(self, text: str, max_tokens: int) -> str:
        raise NotImplementedError("AnthropicProvider — fallback, not implemented yet")
