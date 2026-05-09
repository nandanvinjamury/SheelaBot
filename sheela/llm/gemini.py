"""Gemini provider — primary backend. Implementation lands in Step 2."""
from __future__ import annotations

from typing import AsyncIterator

from sheela.llm.base import Message, ResponseChunk, Tool


class GeminiProvider:
    async def respond(
        self,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]:
        raise NotImplementedError("GeminiProvider.respond — implemented in Step 2")

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("GeminiProvider.embed — implemented in Step 4 (RAG)")

    async def summarize(self, text: str, max_tokens: int) -> str:
        raise NotImplementedError(
            "GeminiProvider.summarize — implemented in Step 6 (memory)"
        )
