"""Gemini provider — primary backend.

Implements LLMProvider via the google-genai SDK. Step 3 added streaming;
Step 4 adds automatic function calling: pass Python callables in `tools`
and the SDK orchestrates the tool-call loop. Backoff with jitter on 429 at
request init; mid-stream errors propagate so the caller's partial output
is preserved. Per-model rate-limit fallback (Flash → Pro) only applies
when nothing has been yielded yet.
"""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any, AsyncIterator, Callable

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
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            continue
        role = "model" if m.role == "assistant" else "user"
        out.append({"role": role, "parts": [{"text": m.content}]})
    return out


def _usage_dict(meta: Any, model_name: str, latency_ms: int) -> dict[str, Any]:
    return {
        "model": model_name,
        "input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
        "output_tokens": getattr(meta, "candidates_token_count", 0) or 0,
        "cached_tokens": getattr(meta, "cached_content_token_count", 0) or 0,
        "latency_ms": latency_ms,
    }


def _extract_text(response: Any) -> str:
    try:
        return response.text or ""
    except (ValueError, AttributeError) as e:
        log.warning("response text unavailable", error=str(e))
        return ""


def _build_config(
    system_prompt: str, tools: list[Callable[..., Any]] | None
) -> genai_types.GenerateContentConfig:
    kwargs: dict[str, Any] = {"system_instruction": system_prompt}
    if tools:
        kwargs["tools"] = list(tools)
    return genai_types.GenerateContentConfig(**kwargs)


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
        tools: list[Callable[..., Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ResponseChunk]:
        primary = self.router.route("respond", context_tokens=0)
        chain = [primary, *self.router.fallbacks_for(primary)]

        contents = _to_gemini_contents(messages)
        config = _build_config(system_prompt, tools)

        last_exc: Exception | None = None
        yielded_anything = False

        for model_name in chain:
            try:
                if stream:
                    async for chunk in self._stream_with_backoff(
                        model_name, contents, config
                    ):
                        yielded_anything = True
                        yield chunk
                else:
                    start = time.monotonic()
                    response = await self._call_with_backoff(
                        model_name, contents, config
                    )
                    latency_ms = int((time.monotonic() - start) * 1000)
                    yielded_anything = True
                    yield ResponseChunk(
                        text=_extract_text(response),
                        finish_reason="stop",
                        usage=_usage_dict(
                            getattr(response, "usage_metadata", None),
                            model_name,
                            latency_ms,
                        ),
                    )
                return
            except genai_errors.ClientError as e:
                if not _is_rate_limit(e):
                    raise
                last_exc = e
                if yielded_anything:
                    raise
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

    async def _stream_with_backoff(
        self,
        model_name: str,
        contents: list[dict[str, Any]],
        config: genai_types.GenerateContentConfig,
    ) -> AsyncIterator[ResponseChunk]:
        stream = None
        last_exc: Exception | None = None
        start = time.monotonic()
        for attempt in range(MAX_BACKOFF_ATTEMPTS):
            try:
                stream = await self._client.aio.models.generate_content_stream(
                    model=model_name,
                    contents=contents,  # type: ignore[arg-type]
                    config=config,
                )
                break
            except genai_errors.ClientError as e:
                if not _is_rate_limit(e):
                    raise
                last_exc = e
                if attempt == MAX_BACKOFF_ATTEMPTS - 1:
                    raise
                base = BACKOFF_BASE_SECONDS * (2 ** attempt)
                delay = base + random.uniform(0, BACKOFF_JITTER_FRACTION * base)
                log.info(
                    "backoff before stream retry",
                    model=model_name,
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)
        if stream is None:
            assert last_exc is not None
            raise last_exc

        last_usage_meta: Any = None
        async for sdk_chunk in stream:
            text = sdk_chunk.text or ""
            meta = getattr(sdk_chunk, "usage_metadata", None)
            if meta is not None:
                last_usage_meta = meta
            if text:
                yield ResponseChunk(text=text)

        if last_usage_meta is not None:
            latency_ms = int((time.monotonic() - start) * 1000)
            yield ResponseChunk(
                text="",
                finish_reason="stop",
                usage=_usage_dict(last_usage_meta, model_name, latency_ms),
            )

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
        """One-shot summarization via Flash-Lite (the cheaper, higher-RPD
        model in the router). The caller embeds any task-specific instructions
        into `text`; we only enforce shape (one paragraph, no preamble)."""
        model_name = self.router.flash_lite
        config = genai_types.GenerateContentConfig(
            system_instruction=(
                "You are a concise summarization tool. Output exactly ONE "
                "paragraph. No preamble, no bullets, no headers."
            ),
            max_output_tokens=max_tokens,
        )
        response = await self._call_with_backoff(
            model_name,
            [{"role": "user", "parts": [{"text": text}]}],
            config,
        )
        return _extract_text(response).strip()


_: type[LLMProvider] = GeminiProvider  # type: ignore[assignment]
