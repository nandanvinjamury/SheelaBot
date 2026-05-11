"""SQLite-backed combined store: chunks + embeddings + FTS5 + metadata.

Three virtual/concrete tables co-located in the existing sheela.db:
- rag_chunks      : chunk_id, file_path, chunk_index, section_title, content
- rag_embeddings  : sqlite-vec vec0 virtual table (chunk_id PK, 768-dim float)
- rag_fts         : FTS5 virtual table (chunk_id, file_path, section_title, content)
- rag_metadata    : key/value (last_indexed_sha, last_indexed_at)

Per-file upserts are atomic under an asyncio.Lock to keep the three tables
in sync. sqlite-vec is loaded as a SQLite extension at connect time.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
import sqlite_vec
import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ChunkWithEmbedding:
    section_title: str
    content: str
    embedding: list[float]


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS rag_chunks (
        chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        section_title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        UNIQUE(file_path, chunk_index)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_path ON rag_chunks(file_path);",
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS rag_embeddings USING vec0(
        chunk_id INTEGER PRIMARY KEY,
        embedding FLOAT[768]
    );
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
        chunk_id UNINDEXED,
        file_path UNINDEXED,
        section_title,
        content,
        tokenize='porter unicode61'
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS rag_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]

# FTS5 query characters that need escaping (we strip them and OR the bare terms)
_FTS_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _sanitize_fts_query(query: str) -> str:
    tokens = _FTS_TOKEN_RE.findall(query.lower())
    return " OR ".join(tokens) if tokens else ""


class RAGStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.enable_load_extension(True)
        await self._conn.load_extension(sqlite_vec.loadable_path())
        await self._conn.enable_load_extension(False)
        for stmt in SCHEMA:
            await self._conn.execute(stmt)
        await self._conn.commit()
        log.info("rag store connected", path=str(self.db_path))

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "must call connect() first"
        return self._conn

    async def upsert_file(
        self, file_path: str, chunks: list[ChunkWithEmbedding]
    ) -> None:
        async with self._lock:
            await self._delete_chunks_locked(file_path)
            for i, chunk in enumerate(chunks):
                cursor = await self.conn.execute(
                    "INSERT INTO rag_chunks "
                    "(file_path, chunk_index, section_title, content) "
                    "VALUES (?, ?, ?, ?)",
                    [file_path, i, chunk.section_title, chunk.content],
                )
                chunk_id = cursor.lastrowid
                await cursor.close()
                await self.conn.execute(
                    "INSERT INTO rag_embeddings (chunk_id, embedding) VALUES (?, ?)",
                    [chunk_id, sqlite_vec.serialize_float32(chunk.embedding)],
                )
                await self.conn.execute(
                    "INSERT INTO rag_fts "
                    "(chunk_id, file_path, section_title, content) "
                    "VALUES (?, ?, ?, ?)",
                    [chunk_id, file_path, chunk.section_title, chunk.content],
                )
            await self.conn.commit()

    async def delete_file(self, file_path: str) -> None:
        async with self._lock:
            await self._delete_chunks_locked(file_path)
            await self.conn.commit()

    async def _delete_chunks_locked(self, file_path: str) -> None:
        ids: list[int] = []
        async with self.conn.execute(
            "SELECT chunk_id FROM rag_chunks WHERE file_path = ?", [file_path]
        ) as cursor:
            async for row in cursor:
                ids.append(row[0])
        for cid in ids:
            await self.conn.execute("DELETE FROM rag_chunks WHERE chunk_id = ?", [cid])
            await self.conn.execute(
                "DELETE FROM rag_embeddings WHERE chunk_id = ?", [cid]
            )
            await self.conn.execute("DELETE FROM rag_fts WHERE chunk_id = ?", [cid])

    async def vector_search(
        self, query_embedding: list[float], k: int = 10
    ) -> list[tuple[int, float]]:
        query_bytes = sqlite_vec.serialize_float32(query_embedding)
        rows: list[tuple[int, float]] = []
        async with self.conn.execute(
            "SELECT chunk_id, distance FROM rag_embeddings "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            [query_bytes, k],
        ) as cursor:
            async for row in cursor:
                rows.append((row[0], row[1]))
        return rows

    async def keyword_search(
        self, query: str, k: int = 10
    ) -> list[tuple[int, float]]:
        safe = _sanitize_fts_query(query)
        if not safe:
            return []
        rows: list[tuple[int, float]] = []
        async with self.conn.execute(
            "SELECT chunk_id, rank FROM rag_fts WHERE rag_fts MATCH ? "
            "ORDER BY rank LIMIT ?",
            [safe, k],
        ) as cursor:
            async for row in cursor:
                rows.append((row[0], row[1]))
        return rows

    async def get_chunks(self, chunk_ids: list[int]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        by_id: dict[int, dict[str, Any]] = {}
        async with self.conn.execute(
            f"SELECT chunk_id, file_path, chunk_index, section_title, content "
            f"FROM rag_chunks WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ) as cursor:
            async for row in cursor:
                by_id[row[0]] = {
                    "chunk_id": row[0],
                    "file_path": row[1],
                    "chunk_index": row[2],
                    "section_title": row[3],
                    "content": row[4],
                }
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    async def count_chunks(self) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM rag_chunks"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_meta(self, key: str) -> str | None:
        async with self.conn.execute(
            "SELECT value FROM rag_metadata WHERE key = ?", [key]
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def set_meta(self, key: str, value: str) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO rag_metadata (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [key, value],
            )
            await self.conn.commit()
