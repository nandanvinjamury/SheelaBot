"""Gemini embedding wrapper.

Uses `text-embedding-004` (768-dim, free tier 1500 RPM). Calls are made
through the same `google-genai` client as the conversational LLM. Backoff
with jitter on 429.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog
from google import genai
from google.genai import errors as genai_errors

from sheela.config import Settings

log = structlog.get_logger(__name__)

MAX_BACKOFF_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_JITTER_FRACTION = 0.5
RATE_LIMIT_STATUS = 429
PARALLEL_LIMIT = 8


def _is_rate_limit(exc: BaseException) -> bool:
    return (
        isinstance(exc, genai_errors.ClientError)
        and getattr(exc, "code", None) == RATE_LIMIT_STATUS
    )


class GeminiEmbedder:
    MODEL = "text-embedding-004"
    DIM = 768

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )

    async def embed_one(self, text: str) -> list[float]:
        result = await self._call_with_backoff(text)
        return list(result.embeddings[0].values)

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        sem = asyncio.Semaphore(PARALLEL_LIMIT)

        async def _one(t: str) -> list[float]:
            async with sem:
                return await self.embed_one(t)

        return await asyncio.gather(*[_one(t) for t in texts])

    async def _call_with_backoff(self, text: str) -> Any:
        last_exc: Exception | None = None
        for attempt in range(MAX_BACKOFF_ATTEMPTS):
            try:
                return await self._client.aio.models.embed_content(
                    model=self.MODEL,
                    contents=text,
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
                    "embed backoff",
                    attempt=attempt + 1,
                    delay_seconds=round(delay, 2),
                )
                await asyncio.sleep(delay)
        assert last_exc is not None
        raise last_exc
