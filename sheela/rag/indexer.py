"""Vault RAG indexer.

Walks the vault, filters to indexable folders (People, Recipes, Career,
Learning — with Obsidian sort-prefix tolerance), chunks each note by
`##` sections, embeds the chunks, and writes them to the RAG store.

Incremental updates: stores the indexed git SHA in rag_metadata. On
subsequent runs, only files changed since that SHA are re-indexed; deleted
files are removed from the store. Falls back to a full scan when there's
no prior SHA or git is unavailable.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from sheela.rag.chunking import chunk_by_sections
from sheela.rag.embeddings import GeminiEmbedder
from sheela.rag.store import ChunkWithEmbedding, RAGStore
from sheela.tools.vault_read import VaultReader
from sheela.vault.contract import FOLDER_PREFIX_RE

log = structlog.get_logger(__name__)

INDEXABLE_FOLDERS: frozenset[str] = frozenset(
    {"People", "Recipes", "Career", "Learning"}
)


class VaultIndexBuilder:
    def __init__(
        self,
        vault_reader: VaultReader,
        store: RAGStore,
        embedder: GeminiEmbedder,
    ) -> None:
        self.reader = vault_reader
        self.store = store
        self.embedder = embedder

    async def build(self, *, full: bool = False) -> dict[str, Any]:
        await self.reader.ensure_fresh()
        current_sha = await self.reader.get_current_sha()
        last_sha = await self.store.get_meta("last_indexed_sha")

        if full or last_sha is None or current_sha is None:
            to_index = await asyncio.to_thread(self._list_indexable_files)
            to_delete: list[str] = []
            mode = "full"
        else:
            changed, deleted = await self.reader.git_diff(last_sha, current_sha)
            to_index = [f for f in changed if self._is_indexable(f)]
            to_delete = [f for f in deleted if self._is_indexable(f)]
            mode = "incremental"

        for path in to_delete:
            await self.store.delete_file(path)
            log.debug("rag deleted file", path=path)

        for path in to_index:
            try:
                await self._index_file(path)
            except Exception as e:
                log.exception("rag index file failed", path=path, error=str(e))

        if current_sha:
            await self.store.set_meta("last_indexed_sha", current_sha)
        await self.store.set_meta(
            "last_indexed_at", datetime.now(timezone.utc).isoformat()
        )

        result = {
            "mode": mode,
            "indexed": len(to_index),
            "deleted": len(to_delete),
            "sha": current_sha,
            "previous_sha": last_sha,
        }
        log.info("rag build done", **result)
        return result

    def _list_indexable_files(self) -> list[str]:
        files: list[str] = []
        for path in sorted(self.reader.vault_path.rglob("*.md")):
            rel = path.relative_to(self.reader.vault_path)
            rel_str = str(rel).replace("\\", "/")
            if self._is_indexable(rel_str):
                files.append(rel_str)
        return files

    @staticmethod
    def _is_indexable(path: str) -> bool:
        rel = path.replace("\\", "/")
        if "/" not in rel:
            return False
        first = rel.split("/", 1)[0]
        bare = FOLDER_PREFIX_RE.sub("", first)
        return bare in INDEXABLE_FOLDERS

    async def _index_file(self, relative_path: str) -> None:
        try:
            content = await self.reader.read(relative_path)
        except FileNotFoundError:
            log.debug("rag: file gone, deleting from index", path=relative_path)
            await self.store.delete_file(relative_path)
            return

        sections = chunk_by_sections(content)
        if not sections:
            await self.store.delete_file(relative_path)
            return

        texts = [s["content"] for s in sections]
        embeddings = await self.embedder.embed_many(texts)
        if len(embeddings) != len(sections):
            log.warning(
                "rag: embedding count mismatch",
                path=relative_path,
                sections=len(sections),
                embeddings=len(embeddings),
            )
            return

        chunks = [
            ChunkWithEmbedding(
                section_title=sections[i]["title"],
                content=sections[i]["content"],
                embedding=embeddings[i],
            )
            for i in range(len(sections))
        ]
        await self.store.upsert_file(relative_path, chunks)
        log.debug(
            "rag indexed file", path=relative_path, chunks=len(chunks)
        )
