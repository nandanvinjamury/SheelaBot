"""System-prompt assembly from the vault's Agent/ files.

PersonaLoader concatenates PERSONA.md + RULES.md + MY_SHEELA.md, caches the
result in memory, and re-checks file mtimes every CACHE_TTL_SECONDS. Vault
reads go through VaultReader so the lazy git-pull machinery applies — vault
edits pushed from the user's phone or laptop are picked up automatically
the next time the persona refresh window expires.
"""
from __future__ import annotations

import asyncio
import time
from typing import ClassVar

from sheela.tools.vault_read import VaultReader


class PersonaLoader:
    PERSONA_FILES: ClassVar[tuple[str, ...]] = (
        "Agent/PERSONA.md",
        "Agent/RULES.md",
        "Agent/MY_SHEELA.md",
    )
    SECTION_SEPARATOR: ClassVar[str] = "\n\n---\n\n"
    CACHE_TTL_SECONDS: ClassVar[float] = 300.0

    def __init__(self, vault_reader: VaultReader) -> None:
        self.reader = vault_reader
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
            full = self.reader.vault_path / rel_path
            current = await asyncio.to_thread(lambda p=full: p.stat().st_mtime)
            if self._cached_mtimes.get(rel_path) != current:
                return True
        return False

    async def _reload(self) -> None:
        contents = await self.reader.read_many(list(self.PERSONA_FILES))
        sections: list[str] = []
        new_mtimes: dict[str, float] = {}
        for rel_path in self.PERSONA_FILES:
            if rel_path not in contents:
                raise FileNotFoundError(
                    f"required persona file missing: {rel_path}"
                )
            sections.append(contents[rel_path])
            full = self.reader.vault_path / rel_path
            new_mtimes[rel_path] = await asyncio.to_thread(
                lambda p=full: p.stat().st_mtime
            )
        self._cache = self.SECTION_SEPARATOR.join(sections)
        self._cached_mtimes = new_mtimes
        self._next_check_at = time.monotonic() + self.CACHE_TTL_SECONDS
