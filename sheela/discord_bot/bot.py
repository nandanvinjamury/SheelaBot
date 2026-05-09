"""Discord client. Step 1: replies 'pong' to 'ping'."""
from __future__ import annotations

import discord
import structlog

from sheela.config import Settings

log = structlog.get_logger(__name__)


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
        log.info("connected", user=str(self.user), user_id=user_id)
        guild = self.get_guild(self.settings.discord_guild_id)
        if guild is None:
            log.warning(
                "configured guild not in connected guilds",
                guild_id=self.settings.discord_guild_id,
            )
        else:
            log.info("watching guild", guild=guild.name, guild_id=guild.id)

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

        log.info(
            "replying",
            channel=str(message.channel),
            received=message.content,
            sent=reply,
        )
        await message.channel.send(reply)


def create_bot(settings: Settings) -> SheelaClient:
    return SheelaClient(settings)
