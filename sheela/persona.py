"""System-prompt assembly from the vault's Agent/ files.

PersonaLoader concatenates PERSONA.md + RULES.md + MY_SHEELA.md, caches the
result in memory, and re-checks file mtimes every CACHE_TTL_SECONDS. The
cache survives across that window unless an mtime actually changed — vault
edits within 5 minutes are picked up on the first message after the TTL
elapses.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import ClassVar


class PersonaLoader:
    PERSONA_FILES: ClassVar[tuple[str, ...]] = (
        "Agent/PERSONA.md",
        "Agent/RULES.md",
        "Agent/MY_SHEELA.md",
    )
    SECTION_SEPARATOR: ClassVar[str] = "\n\n---\n\n"
    CACHE_TTL_SECONDS: ClassVar[float] = 300.0

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self._cache: str | None = None
        self._cached_mtimes: dict[str, float] = {}
        self._next_check_at: float = 0.0

    async def get_system_prompt(self) -> str:
        now = time.monotonic()
        if self._cache is None:
            await self._reload()
        elif now >= self._next_check_at:
            if await self._mtimes_changed():
                await self._reload()
            else:
                self._next_check_at = now + self.CACHE_TTL_SECONDS
        assert self._cache is not None
        return self._cache

    async def _mtimes_changed(self) -> bool:
        for rel_path in self.PERSONA_FILES:
            full = self.vault_path / rel_path
            current = await asyncio.to_thread(lambda p=full: p.stat().st_mtime)
            if self._cached_mtimes.get(rel_path) != current:
                return True
        return False

    async def _reload(self) -> None:
        sections: list[str] = []
        new_mtimes: dict[str, float] = {}
        for rel_path in self.PERSONA_FILES:
            full = self.vault_path / rel_path
            content = await asyncio.to_thread(full.read_text, encoding="utf-8")
            mtime = await asyncio.to_thread(lambda p=full: p.stat().st_mtime)
            sections.append(content)
            new_mtimes[rel_path] = mtime
        self._cache = self.SECTION_SEPARATOR.join(sections)
        self._cached_mtimes = new_mtimes
        self._next_check_at = time.monotonic() + self.CACHE_TTL_SECONDS
