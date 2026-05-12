"""LLM-callable vault tools.

These methods are exposed to Gemini via automatic function calling. The SDK
introspects type hints and docstrings to build the schema; the docstrings
are the LLM's user-manual for when to call each tool, so they're written
for the model, not for humans.

The "current channel" for a write is propagated through a contextvar that
the Discord bot sets before each LLM call; the safety check uses it to
consult the channel's `vault_paths_writable_without_confirm` list.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable

import structlog

from sheela.rag.hybrid import HybridSearcher
from sheela.tools.vault_read import VaultReader
from sheela.tools.vault_write import VaultWriter
from sheela.vault.index import VaultIndexer

log = structlog.get_logger(__name__)


current_channel: ContextVar[str | None] = ContextVar(
    "sheela_current_channel", default=None
)


class VaultTools:
    def __init__(
        self,
        vault_reader: VaultReader,
        vault_indexer: VaultIndexer,
        searcher: HybridSearcher | None = None,
        writer: VaultWriter | None = None,
    ) -> None:
        self.reader = vault_reader
        self.indexer = vault_indexer
        self.searcher = searcher
        self.writer = writer

    def get_callable_tools(self) -> list[Callable[..., Any]]:
        tools: list[Callable[..., Any]] = [self.vault_read, self.vault_list]
        if self.searcher is not None:
            tools.append(self.vault_search)
        if self.writer is not None:
            tools.extend(
                [self.vault_write, self.vault_cancel_draft, self.vault_list_drafts]
            )
        return tools

    async def vault_read(self, path: str) -> str:
        """Read a vault file by its relative path.

        Use this when you already know the exact path — for instance,
        after vault_list told you the path of a note. Paths are relative
        to the vault root with forward slashes. Examples:
        '03 People/Family/Parent.md', '06 Recipes/Dinner/Weeknight pasta.md',
        '08 Career/Side project/Architecture.md'.

        Returns the full markdown content of the file.
        """
        try:
            return await self.reader.read(path)
        except FileNotFoundError:
            log.info("vault_read: file not found", path=path)
            return f"File not found: {path}"
        except Exception as e:
            log.exception("vault_read failed", path=path, error=str(e))
            return f"Error reading {path}: {e}"

    async def vault_list(self, type: str | None = None) -> list[dict[str, Any]]:
        """List vault notes, optionally filtered by type.

        Returns each note's path, title, type, and frontmatter. Use this
        to discover what files exist before calling vault_read.

        Valid type values: 'person', 'recipe', 'project', 'learning',
        'daily', 'exercise', 'hobby', 'travel', 'schedule', 'money',
        'template', 'config', 'misc'. Pass no argument (or null) to
        list everything.
        """
        try:
            index = await self.indexer.get()
            notes = index.get("notes", [])
            if type is not None:
                notes = [n for n in notes if n.get("type") == type]
            return [
                {
                    "path": n["path"],
                    "title": n["title"],
                    "type": n["type"],
                    "frontmatter": n.get("frontmatter", {}),
                }
                for n in notes
            ]
        except Exception as e:
            log.exception("vault_list failed", error=str(e))
            return []

    async def vault_search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Search the vault for free-form queries using hybrid retrieval.

        Use this for "what did I say about X" or "find me notes about Y"
        type questions where you don't know the exact path. For known
        paths, use vault_read directly.

        Returns up to k matching chunks with path, section, content.
        """
        if self.searcher is None:
            return [
                {
                    "error": (
                        "Vault search is not initialized. "
                        "Set RAG_INDEX_ON_STARTUP=1 and restart, "
                        "or trigger a build manually."
                    )
                }
            ]
        try:
            results = await self.searcher.search(query, k=k)
            return [
                {
                    "path": r["file_path"],
                    "section": r["section_title"],
                    "content": r["content"],
                }
                for r in results
            ]
        except Exception as e:
            log.exception("vault_search failed", query=query, error=str(e))
            return [{"error": f"Search failed: {e}"}]

    async def vault_write(
        self,
        path: str,
        content: str,
        operation: str = "append",
        confirmed: bool = False,
    ) -> str:
        """Queue a write to a vault file. Use this to log data, append to
        notes, or create files.

        operation:
          - 'append' (default): add content to end of file, newline-separated.
            Use for daily-note entries, inbox additions, match logs, MEMORY notes.
          - 'overwrite': replace the entire file. For frontmatter updates,
            first read the file with vault_read, modify it, then call vault_write
            with operation='overwrite' and the full new content.

        Path is vault-relative with forward slashes, e.g.
        '01 Daily/2026-05-12.md', '06 Recipes/Dinner/Weeknight pasta.md'. The
        channel context's "Writable without asking" section lists paths that
        are pre-authorized for the current channel.

        confirmed: set to true ONLY after the user has explicitly agreed to
        a write that previously returned "needs confirmation". Do not set
        preemptively.

        Returns one of:
          - "draft queued: <id> -> <path>" — success; flushes in ~30s
          - "needs confirmation: ..." — ask the user, then retry with confirmed=true
          - "denied: ..." — hard rule; tell the user and move on

        Writes are batched: multiple writes within 30 seconds become a
        single git commit and a single push.
        """
        if self.writer is None:
            return "denied: vault writes are not enabled"
        channel = current_channel.get()
        _, message = await self.writer.request_write(
            path=path,
            content=content,
            operation=operation,
            channel=channel,
            confirmed=confirmed,
        )
        return message

    async def vault_cancel_draft(self, draft_id: str) -> str:
        """Cancel a pending vault write before it commits.

        Use when you queued a write and then realize it was wrong, before
        the 30-second debounce window elapses. After cancellation, the
        draft will not be written or committed.
        """
        if self.writer is None:
            return "no writer configured"
        _, message = await self.writer.cancel(draft_id)
        return message

    async def vault_list_drafts(self) -> list[dict[str, Any]]:
        """List vault writes that are queued but not yet flushed.

        Useful when deciding whether to add another write to the current
        batch, or to verify what's about to be committed. Returns each
        draft's id, target path, operation, queued_at, and content preview.
        """
        if self.writer is None:
            return []
        drafts = self.writer.list_pending()
        return [
            {
                "draft_id": d.draft_id,
                "target_path": d.target_path,
                "operation": d.operation,
                "queued_at": d.queued_at,
                "content_preview": (
                    d.content[:200] + "..." if len(d.content) > 200 else d.content
                ),
            }
            for d in drafts
        ]
