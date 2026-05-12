"""VaultWriter — orchestrates safety, draft queueing, and git commit/push.

Public surface (called from LLM-facing tools):
  - `request_write(path, content, operation, channel, confirmed)` —
    enforces safety, queues a draft, returns a status message.

Internal flush path (called by DraftScheduler when the debounce elapses):
  - applies each draft to its target file (append / overwrite)
  - `git add` each touched file, one `git commit`, one `git push`
  - retry push on non-fast-forward via `git pull --rebase`
  - calls `on_post_flush` to invalidate caches and trigger RAG rebuild
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

import structlog

from sheela.tools.drafts import Draft, DraftScheduler
from sheela.tools.git import GitClient, GitError
from sheela.tools.safety import SafetyChecker

log = structlog.get_logger(__name__)

PUSH_MAX_RETRIES = 3
PUSH_REJECTED_FRAGMENTS = (
    "non-fast-forward",
    "rejected",
    "fetch first",
    "would be overwritten",
)


class VaultWriter:
    def __init__(
        self,
        vault_path: Path,
        scheduler: DraftScheduler,
        safety: SafetyChecker,
        git_client: GitClient,
        on_post_flush: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.vault_path = vault_path
        self.scheduler = scheduler
        self.safety = safety
        self.git = git_client
        self.on_post_flush = on_post_flush

    async def request_write(
        self,
        path: str,
        content: str,
        operation: str = "append",
        channel: str | None = None,
        confirmed: bool = False,
    ) -> tuple[bool, str]:
        decision = self.safety.check(path, operation, channel, confirmed)
        if not decision.allowed:
            prefix = "needs confirmation" if decision.needs_confirmation else "denied"
            return False, f"{prefix}: {decision.reason}"
        draft = await self.scheduler.queue(path, operation, content, channel)
        return True, (
            f"draft queued: {draft.draft_id} -> {path} "
            f"(flushes in {self.scheduler.debounce_seconds:.0f}s)"
        )

    async def cancel(self, draft_id: str) -> tuple[bool, str]:
        ok = await self.scheduler.cancel(draft_id)
        if ok:
            return True, f"cancelled: {draft_id}"
        return False, f"draft not found: {draft_id}"

    def list_pending(self) -> list[Draft]:
        return self.scheduler.list_drafts()

    async def shutdown(self) -> None:
        await self.scheduler.shutdown()

    async def flush_callback(self, drafts: list[Draft]) -> None:
        touched: set[str] = set()
        for draft in drafts:
            try:
                await self._apply_draft(draft)
                touched.add(draft.target_path)
            except Exception as e:
                log.exception(
                    "draft apply failed",
                    draft_id=draft.draft_id,
                    target=draft.target_path,
                    error=str(e),
                )

        if not touched:
            return

        message = self._commit_message(drafts)
        try:
            await self._commit_and_push(sorted(touched), message)
            log.info(
                "vault flush committed",
                files=len(touched),
                drafts=len(drafts),
                message=message,
            )
        except GitError as e:
            log.exception(
                "commit/push failed; drafts retained for retry", error=str(e)
            )
            raise

        if self.on_post_flush is not None:
            try:
                await self.on_post_flush()
            except Exception:
                log.exception("post-flush hook failed")

    async def _apply_draft(self, draft: Draft) -> None:
        target = self.vault_path / draft.target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if draft.operation == "append":
            existing = ""
            if target.exists():
                existing = await asyncio.to_thread(
                    target.read_text, encoding="utf-8"
                )
            if existing:
                new = existing.rstrip("\n") + "\n" + draft.content.rstrip("\n") + "\n"
            else:
                new = draft.content.rstrip("\n") + "\n"
            await asyncio.to_thread(target.write_text, new, encoding="utf-8")
        elif draft.operation == "overwrite":
            await asyncio.to_thread(
                target.write_text, draft.content, encoding="utf-8"
            )
        else:
            raise ValueError(f"unknown operation: {draft.operation}")

    def _commit_message(self, drafts: list[Draft]) -> str:
        if len(drafts) == 1:
            d = drafts[0]
            short = d.target_path.split("/")[-1]
            return f"Sheela: {d.operation} {short}"
        return f"Sheela: {len(drafts)} updates"

    async def _commit_and_push(self, files: list[str], message: str) -> None:
        for f in files:
            await self.git.add(f)
        await self.git.commit(message)
        for attempt in range(PUSH_MAX_RETRIES):
            try:
                await self.git.push()
                return
            except GitError as e:
                err = str(e).lower()
                if not any(frag in err for frag in PUSH_REJECTED_FRAGMENTS):
                    raise
                if attempt == PUSH_MAX_RETRIES - 1:
                    raise
                log.warning(
                    "push rejected; pulling --rebase and retrying",
                    attempt=attempt + 1,
                    error=str(e),
                )
                try:
                    await self.git.pull(rebase=True)
                except GitError as pe:
                    log.warning("pull --rebase failed", error=str(pe))
                    raise
        raise GitError(f"push failed after {PUSH_MAX_RETRIES} attempts")
