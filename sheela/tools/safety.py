"""Vault write safety gates.

Three lists (modeled after RULES.md):
  - ALLOWLIST: paths Sheela can write to without asking
  - CONFIRM:   paths that require explicit user confirmation (LLM passes confirmed=True)
  - DENY:      paths that are hard off-limits (no override)

The check also enforces:
  - Path traversal: resolved target must stay inside the vault root.
  - Daily-note hard restriction: only today's daily note, and only append.

Channel allowlists (from routing.yaml's vault_paths_writable_without_confirm)
are unioned with the global allowlist for the current channel.

Glob matching uses `**` for recursive subdirectories (single `*` does not cross
path separators). Implementation is a tiny regex transform, not pathlib (which
doesn't support `**`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sheela.discord_bot.routing import ChannelRouter

log = structlog.get_logger(__name__)


GLOBAL_ALLOWLIST: tuple[str, ...] = (
    "Agent/MEMORY.md",
    "Inbox.md",
    "06 Recipes/**",
    "05 Exercise/**",
    "09 Hobbies/**/Match log.md",
)

GLOBAL_CONFIRM: tuple[str, ...] = (
    "03 People/**",
    "04 Money/**",
    "Agent/PERSONA.md",
    "Agent/RULES.md",
    "Agent/VAULT_CONTRACT.md",
    "Agent/MY_SHEELA.md",
)

GLOBAL_DENY: tuple[str, ...] = (
    ".git/**",
    ".obsidian/**",
)

DAILY_PREFIX = "01 Daily/"


@dataclass(frozen=True)
class WriteDecision:
    allowed: bool
    reason: str
    needs_confirmation: bool = False


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile a glob (supporting `**` for recursive) to a regex.

    `*` matches any chars except `/`.
    `**` matches any chars including `/`. A trailing `**/` is treated the same
    as `**` so `a/**/b` matches `a/x/b`, `a/x/y/b`, and `a/b`.
    """
    out: list[str] = []
    i = 0
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if i + 1 < len(glob) and glob[i + 1] == "*":
                out.append(".*")
                i += 2
                # Consume one trailing slash so a/**/b matches a/b too
                if i < len(glob) and glob[i] == "/":
                    i += 1
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".+()[]{}^$\\|":
            out.append(re.escape(c))
            i += 1
        else:
            out.append(c)
            i += 1
    return re.compile("^" + "".join(out) + "$")


def matches_glob(path: str, glob: str) -> bool:
    return _glob_to_regex(glob).match(path) is not None


def matches_any(path: str, globs: list[str] | tuple[str, ...]) -> bool:
    return any(matches_glob(path, g) for g in globs)


class SafetyChecker:
    def __init__(
        self,
        vault_path: Path,
        tz: str,
        channel_router: "ChannelRouter | None" = None,
    ) -> None:
        self.vault_path = vault_path.resolve()
        self.tz = tz
        self.channel_router = channel_router

    def check(
        self,
        relative_path: str,
        operation: str = "append",
        channel: str | None = None,
        confirmed: bool = False,
    ) -> WriteDecision:
        # 1. Path-traversal check (resolved target must live inside vault root)
        try:
            target = (self.vault_path / relative_path).resolve()
        except (ValueError, OSError) as e:
            return WriteDecision(False, f"invalid path: {e}")
        try:
            target.relative_to(self.vault_path)
        except ValueError:
            return WriteDecision(False, f"path escapes vault: {relative_path}")

        # 2. Off-limits (deny). Hard, no override.
        if matches_any(relative_path, GLOBAL_DENY):
            return WriteDecision(False, f"off-limits: {relative_path}")

        # 3. Daily-note hard restriction (RULES.md: today only, append only).
        if relative_path.startswith(DAILY_PREFIX) and relative_path.endswith(".md"):
            return self._check_daily(relative_path, operation)

        # 4. Allowlist (global + channel).
        channel_allow = self._channel_allowlist(channel)
        if matches_any(relative_path, list(GLOBAL_ALLOWLIST) + channel_allow):
            return WriteDecision(True, "allowed")

        # 5. Confirm list — confirmed=True bypasses.
        if matches_any(relative_path, GLOBAL_CONFIRM):
            if confirmed:
                return WriteDecision(True, "user-confirmed")
            return WriteDecision(
                False,
                f"requires confirmation: {relative_path} is in the confirm list",
                needs_confirmation=True,
            )

        # 6. Uncategorized — default to requiring confirmation.
        if confirmed:
            return WriteDecision(True, "user-confirmed (uncategorized)")
        return WriteDecision(
            False,
            f"requires confirmation: {relative_path} is not in any allowlist",
            needs_confirmation=True,
        )

    def _check_daily(self, path: str, operation: str) -> WriteDecision:
        today = datetime.now(ZoneInfo(self.tz)).strftime("%Y-%m-%d")
        expected = f"{DAILY_PREFIX}{today}.md"
        if path != expected:
            return WriteDecision(
                False,
                f"daily-note writes restricted to today ({expected}); got {path}",
            )
        if operation != "append":
            return WriteDecision(
                False, "daily notes are append-only; use operation='append'"
            )
        return WriteDecision(True, "allowed: today's daily, append")

    def _channel_allowlist(self, channel: str | None) -> list[str]:
        if channel is None or self.channel_router is None:
            return []
        try:
            return self.channel_router.get_writable_paths(channel)
        except Exception as e:
            log.warning("channel allowlist lookup failed", channel=channel, error=str(e))
            return []
