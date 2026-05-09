"""LLM provider abstraction.

Every backend (Gemini, Anthropic, local Ollama, ...) implements LLMProvider.
Switching providers is a config change, not a code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable


TaskType = Literal[
    "respond", "summarize", "classify", "extract", "complex_reasoning"
]


class RateLimitExhausted(Exception):
    """Raised when every model in the fallback chain has been rate-limited."""


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "system"]
    content: str


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ResponseChunk:
    """A single piece of a streamed LLM response.

    `text` is the incremental delta. `finish_reason` and `usage` are populated
    only on the terminal chunk.
    """

    text: str
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    def respond(
        self,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]: ...

    async def embed(self, text: str) -> list[float]: ...

    async def summarize(self, text: str, max_tokens: int) -> str: ...
