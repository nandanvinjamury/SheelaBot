"""Vault metadata index.

Generates a JSON file listing every note's path, title, type, frontmatter,
size, and mtime. Written to `settings.sheela_vault_index_path` (outside the
vault by default, so it doesn't pollute the git repo).

Triggers in Commit A:
- On first call to `get()` if no cached or on-disk version exists.
- Explicitly when the bot starts (background task in on_ready).

Step 5 will add: regenerate after every vault write. Step 4-RAG will add:
regenerate after lazy git pull pulls in new SHAs.

Frontmatter values are normalized through JSON so that dates and other
non-primitive YAML types become strings — this keeps the in-memory cache
byte-identical to the on-disk file.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from sheela.tools.vault_read import VaultReader
from sheela.vault.contract import extract_title, infer_type, parse_frontmatter

log = structlog.get_logger(__name__)

_EXCLUDED_DIRS: frozenset[str] = frozenset(
    {".git", ".obsidian", ".claude", "Agent"}
)


def _json_normalize(value: Any) -> Any:
    """Round-trip a value through JSON to coerce dates/etc to plain types.

    Keeps the in-memory index byte-identical to the on-disk JSON file —
    important for `result == on_disk` equality checks and for downstream
    consumers that shouldn't have to handle YAML-specific types.
    """
    return json.loads(json.dumps(value, default=str))


class VaultIndexer:
    def __init__(self, vault_reader: VaultReader, index_path: Path) -> None:
        self.reader = vault_reader
        self.vault_path = vault_reader.vault_path
        self.index_path = index_path
        self._cache: dict[str, Any] | None = None

    async def build(self) -> dict[str, Any]:
        await self.reader.ensure_fresh()
        notes = await asyncio.to_thread(self._scan_vault)
        index: dict[str, Any] = {
            "version": datetime.now(timezone.utc).isoformat(),
            "vault_path": str(self.vault_path),
            "notes": notes,
        }
        await asyncio.to_thread(self._write_index, index)
        self._cache = index
        log.info("vault index built", count=len(notes), path=str(self.index_path))
        return index

    async def get(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if self.index_path.exists():
            self._cache = await asyncio.to_thread(self._read_index)
            return self._cache
        return await self.build()

    def invalidate(self) -> None:
        """Drop the in-memory cache. Next `get()` re-reads from disk
        (or rebuilds if disk is missing)."""
        self._cache = None

    def _scan_vault(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted(self.vault_path.rglob("*.md")):
            rel = path.relative_to(self.vault_path)
            if self._should_skip(rel):
                continue
            try:
                entries.append(self._note_entry(path, rel))
            except OSError as e:
                log.warning("indexer skipped file (io)", path=str(rel), error=str(e))
        return entries

    def _should_skip(self, rel: Path) -> bool:
        for part in rel.parts:
            if part.startswith("."):
                return True
            if part in _EXCLUDED_DIRS:
                return True
        if rel.name.startswith("_"):
            return True
        return False

    def _note_entry(self, full: Path, rel: Path) -> dict[str, Any]:
        content = full.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        rel_str = str(rel).replace("\\", "/")
        stat = full.stat()
        return {
            "path": rel_str,
            "title": extract_title(body, full.stem),
            "type": infer_type(rel_str),
            "frontmatter": _json_normalize(fm or {}),
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
        }

    def _write_index(self, index: dict[str, Any]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def _read_index(self) -> dict[str, Any]:
        return json.loads(self.index_path.read_text(encoding="utf-8"))
