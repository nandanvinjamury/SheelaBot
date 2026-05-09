"""Gemini provider — primary backend.

Implements LLMProvider via the google-genai SDK. Step 2 implements `respond`
(non-streaming under the hood, yields a single ResponseChunk with the full
text plus usage metadata). `embed` lands in Step 4 (RAG). `summarize` lands
in Step 6 (memory compaction).
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, AsyncIterator

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from sheela.config import Settings
from sheela.llm.base import (
    LLMProvider,
    Message,
    RateLimitExhausted,
    ResponseChunk,
    Tool,
)
from sheela.llm.router import ModelRouter

log = structlog.get_logger(__name__)

MAX_BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_JITTER_FRACTION = 0.5
RATE_LIMIT_STATUS = 429


def _is_rate_limit(exc: BaseException) -> bool:
    return (
        isinstance(exc, genai_errors.ClientError)
        and getattr(exc, "code", None) == RATE_LIMIT_STATUS
    )


def _to_gemini_contents(messages: list[Message]) -> list[dict[str, Any]]:
    """Translate our Message list into Gemini's content format.

    Gemini uses 'user' and 'model' roles (not 'assistant'). System prompts
    are passed through GenerateContentConfig.system_instruction, not as
    messages.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue  # handled via system_instruction
        role = "model" if m.role == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": m.content}]})
    return out


def _extract_usage(
    response: Any, model_name: str, latency_ms: int
) -> dict[str, Any]:
    meta = getattr(response, "usage_metadata", None)
    return {
        "model": model_name,
        "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        "cached_tokens": getattr(meta, "cached_content_token_count", 0) or 0,
        "latency_ms": latency_ms,
    }


def _extract_text(response: Any) -> str:
    """Get response.text but tolerate the SDK's safety-filter raise."""
    try:
        return response.text or ""
    except (ValueError, AttributeError) as e:
        log.warning("response text unavailable", error=str(e))
        return ""


class GeminiProvider:
    def __init__(self, settings: Settings, router: ModelRouter | None = None) -> None:
        self.settings = settings
        self.router = router or ModelRouter()
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )

    async def respond(
        self,
        system_prompt: str,
        messages: list[Message],
        tools: list[Tool] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]:
        """Yield response chunks. Step 2 always yields exactly one chunk
        with the full text + usage; Step 3 will honor stream=True."""
        del tools, stream  # not yet used

        primary = self.router.route("respond", context_tokens=0)
        chain = [primary, *self.router.fallbacks_for(primary)]

        contents = _to_gemini_contents(messages)
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt
        )

        last_exc: Exception | None = None
        for model_name in chain:
            try:
                start = time.monotonic()
                response = await self._call_with_backoff(
                    model_name, contents, config
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                text = _extract_text(response)
                usage = _extract_usage(response, model_name, latency_ms)
                yield ResponseChunk(text=text, finish_reason="stop", usage=usage)
                return
            except genai_errors.ClientError as e:
                if not _is_rate_limit(e):
                    raise
                last_exc = e
                idx = chain.index(model_name)
                log.warning(
                    "model rate-limited, trying fallback",
                    model=model_name,
                    fallback_remaining=chain[idx + 1 :],
                )
                continue

        raise RateLimitExhausted(
            f"all models in chain exhausted: {chain}"
        ) from last_exc

    async def _call_with_backoff(
        self,
        model_name: str,
        contents: list[dict[str, Any]],
        config: genai_types.GenerateContentConfig,
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(MAX_BACKOFF_ATTEMPTS):
            try:
                return await self._client.aio.models.generate_content(
                    model=model_name,
                    contents=contents,  # type: ignore[arg-type]
                    config=config,
                )
            except genai_errors.ClientError as e:
                if not _is_rate_limit(e):
                    raise
                last_exc = e
                if attempt == MAX_BACKOFF_ATTEMPTS - 1:
                    raise
                base = BACKOFF_BASE_SECONDS * (2 ** attempt)
                delay = base + random.uniform(0, BACKOFF_JITTER_FRACTION * base)
                log.info(
                    "backoff before retry",
                    model=model_name,
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError("GeminiProvider.embed — implemented in Step 4 (RAG)")

    async def summarize(self, text: str, max_tokens: int) -> str:
        raise NotImplementedError(
            "GeminiProvider.summarize — implemented in Step 6 (memory)"
        )


# Structural-typing self-check at import time: catches signature drift early.
_: type[LLMProvider] = GeminiProvider  # type: ignore[assignment]
