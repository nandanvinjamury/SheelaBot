"""Draft storage + debounced flush.

Each queued vault write becomes a JSON file in `drafts_dir`. The directory
lives outside the vault so drafts don't pollute the git repo or appear in
Obsidian. A single asyncio task acts as the debounce timer — each new
`queue()` cancels the pending flush and starts a fresh 30-second wait.

On shutdown, `flush_now()` runs immediately so we don't lose in-flight
writes when systemd restarts the service.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import structlog

log = structlog.get_logger(__name__)

DEBOUNCE_SECONDS = 30.0


@dataclass(frozen=True)
class Draft:
    draft_id: str
    target_path: str
    operation: str
    content: str
    channel: str | None
    queued_at: str


FlushCallback = Callable[[list[Draft]], Awaitable[None]]


class DraftScheduler:
    def __init__(
        self,
        drafts_dir: Path,
        debounce_seconds: float = DEBOUNCE_SECONDS,
    ) -> None:
        self.drafts_dir = drafts_dir
        self.debounce_seconds = debounce_seconds
        self.on_flush: FlushCallback | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_lock = asyncio.Lock()
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    async def queue(
        self,
        target_path: str,
        operation: str,
        content: str,
        channel: str | None,
    ) -> Draft:
        draft = Draft(
            draft_id=str(uuid.uuid4()),
            target_path=target_path,
            operation=operation,
            content=content,
            channel=channel,
            queued_at=datetime.now(timezone.utc).isoformat(),
        )
        await asyncio.to_thread(self._save_draft, draft)
        self._schedule_flush()
        log.info(
            "draft queued",
            draft_id=draft.draft_id,
            target=draft.target_path,
            operation=draft.operation,
            channel=draft.channel,
        )
        return draft

    async def cancel(self, draft_id: str) -> bool:
        path = self.drafts_dir / f"{draft_id}.json"
        if not path.exists():
            return False
        await asyncio.to_thread(path.unlink)
        log.info("draft cancelled", draft_id=draft_id)
        return True

    def list_drafts(self) -> list[Draft]:
        drafts: list[Draft] = []
        for p in sorted(self.drafts_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                drafts.append(Draft(**data))
            except Exception as e:
                log.warning(
                    "draft load failed; ignoring", path=str(p), error=str(e)
                )
        return drafts

    def has_pending_drafts(self) -> bool:
        return any(self.drafts_dir.glob("*.json"))

    def _save_draft(self, draft: Draft) -> None:
        path = self.drafts_dir / f"{draft.draft_id}.json"
        path.write_text(
            json.dumps(asdict(draft), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _schedule_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return
        await self.flush_now()

    async def flush_now(self) -> None:
        async with self._flush_lock:
            drafts = self.list_drafts()
            if not drafts:
                return
            drafts.sort(key=lambda d: d.queued_at)
            if self.on_flush is None:
                log.warning(
                    "flush_now called but no on_flush callback set; drafts retained",
                    count=len(drafts),
                )
                return
            try:
                await self.on_flush(drafts)
            except Exception:
                log.exception(
                    "flush callback raised; drafts retained on disk",
                    count=len(drafts),
                )
                return
            for d in drafts:
                p = self.drafts_dir / f"{d.draft_id}.json"
                if p.exists():
                    p.unlink()

    async def shutdown(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        await self.flush_now()
