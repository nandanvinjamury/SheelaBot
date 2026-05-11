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

from sheela.tools.vault_read import VaultReader
from sheela.vault.index import VaultIndexer

log = structlog.get_logger(__name__)


class VaultTools:
    def __init__(self, vault_reader: VaultReader, vault_indexer: VaultIndexer) -> None:
        self.reader = vault_reader
        self.indexer = vault_indexer

    def get_callable_tools(self) -> list[Callable[..., Any]]:
        return [self.vault_read, self.vault_list]

    async def vault_read(self, path: str) -> str:
        """Read a vault file by its relative path.

        Use this when you already know the exact path — for instance,
        after vault_list told you the path of a note. Paths are relative
        to the vault root with forward slashes. Examples:
        'People/Family/Parent.md', 'Recipes/Dinner/Weeknight pasta.md',
        'Career/Side project/Architecture.md'.

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
