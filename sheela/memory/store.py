"""SQLite layer for conversation memory.

Two tables, both per-channel:
  - conversations: one row per message (user or assistant). `archived=1`
    when folded into a summary.
  - summaries: one row per channel — the rolling summary covering everything
    archived so far.

A separate aiosqlite connection is used (not the RAGStore's). They live in the
same file but stay isolated; this also means MemoryStore doesn't need the
sqlite-vec extension loaded.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

log = structlog.get_logger(__name__)


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS conversations (
        turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user','assistant')),
        content TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        tokens_in INTEGER NOT NULL DEFAULT 0,
        tokens_out INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_conv_channel_active "
    "ON conversations(channel_id, archived, turn_id);",
    """
    CREATE TABLE IF NOT EXISTS summaries (
        channel_id TEXT PRIMARY KEY,
        summary TEXT NOT NULL,
        covers_through_turn_id INTEGER NOT NULL,
        turn_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        for stmt in SCHEMA:
            await self._conn.execute(stmt)
        await self._conn.commit()
        log.info("memory store connected", path=str(self.db_path))

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "must call connect() first"
        return self._conn

    async def add_message(
        self,
        channel_id: str,
        role: str,
        content: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> int:
        async with self._lock:
            cursor = await self.conn.execute(
                "INSERT INTO conversations "
                "(channel_id, role, content, timestamp, tokens_in, tokens_out) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [channel_id, role, content, _now_iso(), tokens_in, tokens_out],
            )
            turn_id = cursor.lastrowid
            await cursor.close()
            await self.conn.commit()
            assert turn_id is not None
            return turn_id

    async def add_exchange(
        self,
        channel_id: str,
        user_content: str,
        assistant_content: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> tuple[int, int]:
        """Atomic insert of a user+assistant pair. Token usage is attached to
        the assistant row (per-call cost; the user row stays at 0/0)."""
        async with self._lock:
            now = _now_iso()
            cur1 = await self.conn.execute(
                "INSERT INTO conversations "
                "(channel_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                [channel_id, "user", user_content, now],
            )
            user_id = cur1.lastrowid
            await cur1.close()
            cur2 = await self.conn.execute(
                "INSERT INTO conversations "
                "(channel_id, role, content, timestamp, tokens_in, tokens_out) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    channel_id,
                    "assistant",
                    assistant_content,
                    now,
                    tokens_in,
                    tokens_out,
                ],
            )
            assistant_id = cur2.lastrowid
            await cur2.close()
            await self.conn.commit()
            assert user_id is not None and assistant_id is not None
            return user_id, assistant_id

    async def get_active_messages(self, channel_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        async with self.conn.execute(
            "SELECT turn_id, role, content, timestamp "
            "FROM conversations WHERE channel_id = ? AND archived = 0 "
            "ORDER BY turn_id",
            [channel_id],
        ) as cursor:
            async for row in cursor:
                rows.append(
                    {
                        "turn_id": row[0],
                        "role": row[1],
                        "content": row[2],
                        "timestamp": row[3],
                    }
                )
        return rows

    async def get_recent_messages(
        self, channel_id: str, n_rows: int
    ) -> list[dict[str, Any]]:
        """Up to `n_rows` most recent active messages, in chronological order."""
        rows: list[dict[str, Any]] = []
        async with self.conn.execute(
            "SELECT turn_id, role, content, timestamp "
            "FROM conversations WHERE channel_id = ? AND archived = 0 "
            "ORDER BY turn_id DESC LIMIT ?",
            [channel_id, n_rows],
        ) as cursor:
            async for row in cursor:
                rows.append(
                    {
                        "turn_id": row[0],
                        "role": row[1],
                        "content": row[2],
                        "timestamp": row[3],
                    }
                )
        return list(reversed(rows))

    async def count_active(self, channel_id: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM conversations "
            "WHERE channel_id = ? AND archived = 0",
            [channel_id],
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def list_active_channels(self) -> list[str]:
        rows: list[str] = []
        async with self.conn.execute(
            "SELECT DISTINCT channel_id FROM conversations WHERE archived = 0"
        ) as cursor:
            async for row in cursor:
                rows.append(row[0])
        return rows

    async def archive_messages(self, turn_ids: list[int]) -> None:
        if not turn_ids:
            return
        placeholders = ",".join("?" * len(turn_ids))
        async with self._lock:
            await self.conn.execute(
                f"UPDATE conversations SET archived = 1 "
                f"WHERE turn_id IN ({placeholders})",
                turn_ids,
            )
            await self.conn.commit()

    async def get_summary(self, channel_id: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            "SELECT summary, covers_through_turn_id, turn_count, created_at "
            "FROM summaries WHERE channel_id = ?",
            [channel_id],
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "summary": row[0],
                "covers_through_turn_id": row[1],
                "turn_count": row[2],
                "created_at": row[3],
            }

    async def upsert_summary(
        self,
        channel_id: str,
        summary: str,
        covers_through_turn_id: int,
        turn_count: int,
    ) -> None:
        async with self._lock:
            await self.conn.execute(
                "INSERT INTO summaries "
                "(channel_id, summary, covers_through_turn_id, turn_count, created_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(channel_id) DO UPDATE SET "
                "  summary = excluded.summary, "
                "  covers_through_turn_id = excluded.covers_through_turn_id, "
                "  turn_count = excluded.turn_count, "
                "  created_at = excluded.created_at",
                [
                    channel_id,
                    summary,
                    covers_through_turn_id,
                    turn_count,
                    _now_iso(),
                ],
            )
            await self.conn.commit()
