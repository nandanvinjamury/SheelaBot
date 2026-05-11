"""Async wrappers around `git` subprocess calls.

We use the binary rather than a Python git library to stay close to what
the user would run manually and to avoid an extra dependency. All callers
must tolerate `GitError` — vault freshness checks degrade gracefully if
git is unavailable.
"""
from __future__ import annotations

import asyncio
from pathlib import Path


class GitError(Exception):
    """A git subprocess returned non-zero."""


class GitClient:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    async def _run(self, *args: str, check: bool = True) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.repo_path),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        if check and proc.returncode != 0:
            raise GitError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{stderr_bytes.decode(errors='replace').strip()}"
            )
        return stdout_bytes.decode(errors="replace").strip()

    async def is_git_repo(self) -> bool:
        try:
            out = await self._run("rev-parse", "--is-inside-work-tree")
            return out == "true"
        except (GitError, FileNotFoundError):
            return False

    async def rev_parse_head(self) -> str:
        return await self._run("rev-parse", "HEAD")

    async def ls_remote_head(self, remote: str = "origin") -> str:
        """Returns the remote's HEAD sha (cheap network call)."""
        out = await self._run("ls-remote", remote, "HEAD")
        if not out:
            raise GitError(f"ls-remote {remote} HEAD returned empty")
        return out.split()[0]

    async def pull(self, remote: str = "origin", branch: str = "main") -> None:
        await self._run("pull", "--ff-only", remote, branch)
