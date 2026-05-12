"""ConversationManager — sliding window memory + compaction.

Per-channel state:
  - Recent: the last 10 exchanges (20 rows) included verbatim in every prompt
  - Mid-term: a single rolling summary covering everything older than the recent window
  - Long-term: the vault (Sheela writes to MEMORY.md / daily notes proactively)

Compaction fires when active rows for a channel exceed
COMPACTION_TRIGGER_EXCHANGES * 2. It archives all but the most recent 20 rows
and folds them — together with the prior summary — into a new summary that
replaces the prior one.

A per-channel `asyncio.Lock` prevents overlapping compactions when messages
arrive in quick succession.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from sheela.memory.store import MemoryStore
from sheela.memory.summarizer import ConversationSummarizer

log = structlog.get_logger(__name__)

RECENT_EXCHANGES = 10
COMPACTION_TRIGGER_EXCHANGES = 30
ROWS_PER_EXCHANGE = 2  # user + assistant


class ConversationManager:
    def __init__(
        self,
        store: MemoryStore,
        summarizer: ConversationSummarizer,
        *,
        recent_exchanges: int = RECENT_EXCHANGES,
        compact_trigger_exchanges: int = COMPACTION_TRIGGER_EXCHANGES,
    ) -> None:
        self.store = store
        self.summarizer = summarizer
        self.recent_rows = recent_exchanges * ROWS_PER_EXCHANGE
        self.compact_threshold_rows = compact_trigger_exchanges * ROWS_PER_EXCHANGE
        self._compact_locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, channel_id: str) -> asyncio.Lock:
        lock = self._compact_locks.get(channel_id)
        if lock is None:
            lock = asyncio.Lock()
            self._compact_locks[channel_id] = lock
        return lock

    async def get_context(
        self, channel_id: str
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Returns (summary_text_or_None, recent_messages_chronological)."""
        summary_row = await self.store.get_summary(channel_id)
        summary = summary_row["summary"] if summary_row else None
        recent = await self.store.get_recent_messages(
            channel_id, n_rows=self.recent_rows
        )
        return summary, recent

    async def record_exchange(
        self,
        channel_id: str,
        user_content: str,
        assistant_content: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> tuple[int, int]:
        return await self.store.add_exchange(
            channel_id,
            user_content,
            assistant_content,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    async def maybe_compact(self, channel_id: str) -> dict[str, Any] | None:
        async with self._lock_for(channel_id):
            count = await self.store.count_active(channel_id)
            if count <= self.compact_threshold_rows:
                return None

            active = await self.store.get_active_messages(channel_id)
            to_archive = active[: -self.recent_rows]
            if not to_archive:
                return None

            prev = await self.store.get_summary(channel_id)
            prev_summary = prev["summary"] if prev else None
            prev_turn_count = prev["turn_count"] if prev else 0

            try:
                new_summary = await self.summarizer.summarize(
                    to_archive, prev_summary
                )
            except Exception:
                log.exception(
                    "summarization failed; skipping compaction",
                    channel_id=channel_id,
                )
                return None

            if not new_summary.strip():
                log.warning(
                    "summarizer returned empty; skipping compaction",
                    channel_id=channel_id,
                )
                return None

            last_archived_id = to_archive[-1]["turn_id"]
            new_turn_count = prev_turn_count + len(to_archive)
            await self.store.upsert_summary(
                channel_id,
                new_summary,
                last_archived_id,
                new_turn_count,
            )
            await self.store.archive_messages(
                [m["turn_id"] for m in to_archive]
            )

            log.info(
                "channel compacted",
                channel_id=channel_id,
                archived=len(to_archive),
                summary_chars=len(new_summary),
                covers_through=last_archived_id,
                total_summary_messages=new_turn_count,
            )
            return {
                "archived": len(to_archive),
                "summary_chars": len(new_summary),
                "covers_through": last_archived_id,
                "total_summary_messages": new_turn_count,
            }

    async def compact_all_channels(self) -> dict[str, dict[str, Any]]:
        """Run after startup to catch up on channels that grew past threshold
        while the bot was offline."""
        results: dict[str, dict[str, Any]] = {}
        for ch in await self.store.list_active_channels():
            r = await self.maybe_compact(ch)
            if r is not None:
                results[ch] = r
        return results
