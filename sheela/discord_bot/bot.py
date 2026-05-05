"""Discord client. Step 1: replies 'pong' to 'ping'."""
from __future__ import annotations

import logging

import discord

from sheela.config import Settings

log = logging.getLogger(__name__)


def respond_to(content: str) -> str | None:
    """Pure function: given message content, return reply text or None to ignore.

    Step 1 only. Step 2 replaces this with a Claude call.
    """
    match content.strip().lower():
        case "ping":
            return "pong"
        case _:
            return None


class SheelaClient(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings

    async def on_ready(self) -> None:
        user_id = self.user.id if self.user else None
        log.info("Connected as %s (id=%s)", self.user, user_id)
        guild = self.get_guild(self.settings.discord_guild_id)
        if guild is None:
            log.warning(
                "Configured guild %s not in connected guilds",
                self.settings.discord_guild_id,
            )
        else:
            log.info("Watching guild '%s'", guild.name)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is None:
            return  # No DMs — RULES.md hard rule.
        if message.guild.id != self.settings.discord_guild_id:
            return

        reply = respond_to(message.content)
        if reply is None:
            return

        log.info("Replying in #%s: %r -> %r", message.channel, message.content, reply)
        await message.channel.send(reply)


def create_bot(settings: Settings) -> SheelaClient:
    return SheelaClient(settings)
