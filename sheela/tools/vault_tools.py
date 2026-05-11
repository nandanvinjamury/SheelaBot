"""LLM-callable vault tools.

These methods are exposed to Gemini via automatic function calling. The SDK
introspects type hints and docstrings to build the schema; the docstrings
are the LLM's user-manual for when to call each tool, so they're written
for the model, not for humans.

Tools return either a string (file contents) or a list of dicts (metadata).
Errors are converted to short error messages — the model can recover by
trying a different path or tool, rather than the whole conversation crashing.
"""
from __future__ import annotations

from typing import Any, Callable

import structlog

from sheela.rag.hybrid import HybridSearcher
from sheela.tools.vault_read import VaultReader
from sheela.vault.index import VaultIndexer

log = structlog.get_logger(__name__)


class VaultTools:
    def __init__(
        self,
        vault_reader: VaultReader,
        vault_indexer: VaultIndexer,
        searcher: HybridSearcher | None = None,
    ) -> None:
        self.reader = vault_reader
        self.indexer = vault_indexer
        self.searcher = searcher

    def get_callable_tools(self) -> list[Callable[..., Any]]:
        tools: list[Callable[..., Any]] = [self.vault_read, self.vault_list]
        if self.searcher is not None:
            tools.append(self.vault_search)
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

        Returns up to k matching chunks. Each chunk has:
        - path: the source file's vault-relative path
        - section: the ## header that contained this chunk (or '_intro')
        - content: the markdown text of the chunk

        Hybrid retrieval combines vector similarity (semantic) and
        keyword search (BM25-like FTS5). Reciprocal rank fusion merges
        the two rankings.
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
