"""Vault reader with lazy git pull.

The first read in any 60-second window checks whether origin's HEAD has
moved (`git ls-remote` — cheap) and, only if it has, runs `git pull --ff-only`.
Subsequent reads within the window skip the check. An asyncio.Lock prevents
concurrent freshness checks when multiple Discord messages arrive at once.

If the vault directory isn't a git repo (e.g., test fixtures, manual
checkouts), git operations are skipped silently and reads proceed normally.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import structlog

from sheela.tools.git import GitClient, GitError

log = structlog.get_logger(__name__)


class VaultReader:
    FRESHNESS_TTL_SECONDS = 60.0

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self._git = GitClient(vault_path)
        self._lock = asyncio.Lock()
        self._last_check_at: float = 0.0
        self.last_check_iso: str | None = None

    async def ensure_fresh(self) -> None:
        """Public: perform the freshness check now if the TTL has elapsed."""
        async with self._lock:
            now = time.monotonic()
            if now - self._last_check_at < self.FRESHNESS_TTL_SECONDS:
                return
            try:
                if not await self._git.is_git_repo():
                    self._last_check_at = now
                    return
                local = await self._git.rev_parse_head()
                remote = await self._git.ls_remote_head()
                if local != remote:
                    await self._git.pull()
                    log.info(
                        "vault pulled",
                        local=local[:8],
                        remote=remote[:8],
                    )
            except GitError as e:
                log.warning("vault freshness check failed; using cached", error=str(e))
            except Exception as e:
                log.warning("vault freshness unexpected error", error=str(e))
            self._last_check_at = now
            self.last_check_iso = datetime.now(timezone.utc).isoformat()

    async def read(self, relative_path: str) -> str:
        await self.ensure_fresh()
        return await self._read_one(relative_path)

    async def read_many(self, relative_paths: list[str]) -> dict[str, str]:
        await self.ensure_fresh()
        results = await asyncio.gather(
            *[self._read_one(p) for p in relative_paths],
            return_exceptions=True,
        )
        out: dict[str, str] = {}
        for path, result in zip(relative_paths, results):
            if isinstance(result, BaseException):
                log.warning("vault read failed", path=path, error=str(result))
            else:
                out[path] = result
        return out

    async def _read_one(self, relative_path: str) -> str:
        full = self.vault_path / relative_path
        return await asyncio.to_thread(full.read_text, encoding="utf-8")

    async def get_current_sha(self) -> str | None:
        """Current HEAD of the vault repo, or None if git is unavailable."""
        try:
            if not await self._git.is_git_repo():
                return None
            return await self._git.rev_parse_head()
        except GitError:
            return None

    async def git_diff(
        self, from_sha: str, to_sha: str
    ) -> tuple[list[str], list[str]]:
        """List paths changed (M/A/R/...) and deleted (D) between two SHAs."""
        try:
            out = await self._git.diff_name_status(from_sha, to_sha)
        except GitError as e:
            log.warning("git diff failed", error=str(e))
            return [], []
        changed: list[str] = []
        deleted: list[str] = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0]
            path = parts[-1]  # rename rows have the new path last
            if status.startswith("D"):
                deleted.append(path)
            else:
                changed.append(path)
        return changed, deleted
