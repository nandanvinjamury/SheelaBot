"""Gemini embedding wrapper.

Uses `gemini-embedding-001` — the current GA embedding model in the
google-genai SDK (the older `text-embedding-004` was retired from the
v1beta endpoint). The model returns 3072-dim vectors by default; we
request `output_dimensionality=768` to match the FLOAT[768] schema in
RAGStore. Backoff with jitter on 429.
"""
from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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
    MODEL = "gemini-embedding-001"
    DIM = 768

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value()
        )
        self._config = genai_types.EmbedContentConfig(
            output_dimensionality=self.DIM,
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
                    config=self._config,
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
