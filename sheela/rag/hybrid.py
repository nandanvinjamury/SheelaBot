"""Hybrid retrieval via reciprocal rank fusion (RRF).

Runs vector and keyword search in parallel, then merges the two ranked
lists with RRF: each item's score is the sum of `1 / (k_const + rank + 1)`
across rankings. Simplest hybrid scheme that consistently outperforms
either method alone.
"""
from __future__ import annotations

import asyncio
from typing import Any, Hashable, Iterable

import structlog

from sheela.rag.embeddings import GeminiEmbedder
from sheela.rag.store import RAGStore

log = structlog.get_logger(__name__)

RRF_K = 60


def reciprocal_rank_fusion(
    rankings: Iterable[list[Hashable]], *, k: int = RRF_K
) -> list[tuple[Hashable, float]]:
    scores: dict[Hashable, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class HybridSearcher:
    def __init__(self, store: RAGStore, embedder: GeminiEmbedder) -> None:
        self.store = store
        self.embedder = embedder

    async def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        # Vector search needs the query embedding first; keyword can run
        # alongside the embedding call.
        embed_task = asyncio.create_task(self.embedder.embed_one(query))
        keyword_task = asyncio.create_task(
            self.store.keyword_search(query, k=k * 2)
        )
        query_emb = await embed_task
        keyword_hits = await keyword_task
        vector_hits = await self.store.vector_search(query_emb, k=k * 2)

        vector_ids = [cid for cid, _ in vector_hits]
        keyword_ids = [cid for cid, _ in keyword_hits]
        fused = reciprocal_rank_fusion([vector_ids, keyword_ids])
        top_ids = [int(cid) for cid, _ in fused[:k]]

        return await self.store.get_chunks(top_ids)
