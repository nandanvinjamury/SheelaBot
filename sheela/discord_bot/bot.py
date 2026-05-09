"""Discord client.

Step 2 wires up the LLM: every non-bot, non-DM, configured-guild message
that isn't the literal `ping` connectivity check gets sent to the LLM,
and the response is posted back. No streaming yet (Step 3); no memory
yet (Step 6).
"""
from __future__ import annotations

import discord
import structlog

from sheela.config import Settings
from sheela.llm.base import LLMProvider, Message, RateLimitExhausted
from sheela.llm.usage import UsageLogger
from sheela.persona import PersonaLoader

log = structlog.get_logger(__name__)

DISCORD_MAX_CHARS = 1990  # 2000 hard limit; leave headroom for safety


def respond_to(content: str) -> str | None:
    """Local-only quick replies (no LLM call). Returns None to defer to LLM."""
    match content.strip().lower():
        case "ping":
            return "pong"
        case _:
            return None


def split_for_discord(text: str, max_chars: int = DISCORD_MAX_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_chars:
        slice_ = remaining[:max_chars]
        split_at = slice_.rfind(" ")
        if split_at == -1:
            split_at = max_chars
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


class SheelaClient(discord.Client):
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        persona: PersonaLoader,
        usage_logger: UsageLogger,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.llm = llm
        self.persona = persona
        self.usage_logger = usage_logger

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

        content = self._strip_self_mention(message.content).strip()
        if not content:
            return

        quick = respond_to(content)
        if quick is not None:
            await message.channel.send(quick)
            return

        await self._handle_llm_message(message, content)

    def _strip_self_mention(self, content: str) -> str:
        if self.user is None:
            return content
        me_id = self.user.id
        return content.replace(f"<@{me_id}>", "").replace(f"<@!{me_id}>", "")

    async def _handle_llm_message(
        self, message: discord.Message, content: str
    ) -> None:
        channel_name = (
            f"#{message.channel.name}"
            if isinstance(message.channel, discord.TextChannel)
            else str(message.channel)
        )
        try:
            async with message.channel.typing():
                system_prompt = await self.persona.get_system_prompt()
                messages = [Message(role="user", content=content)]
                full_text = ""
                last_usage: dict[str, object] | None = None
                async for chunk in self.llm.respond(
                    system_prompt, messages, stream=False
                ):
                    full_text += chunk.text
                    if chunk.usage is not None:
                        last_usage = chunk.usage
        except RateLimitExhausted:
            log.warning(
                "rate-limited; replying with fallback message",
                channel=channel_name,
            )
            await message.channel.send("Rate-limited, try again in an hour.")
            return
        except Exception as e:
            log.exception(
                "llm call failed", channel=channel_name, error=str(e)
            )
            await message.channel.send(
                "Something broke on my end. Logs have details."
            )
            return

        if last_usage is not None:
            await self.usage_logger.log(
                channel=channel_name,
                task="respond",
                **last_usage,
            )

        if not full_text.strip():
            log.warning("empty response from llm", channel=channel_name)
            await message.channel.send(
                "I came back empty on that one — try rephrasing?"
            )
            return

        for piece in split_for_discord(full_text):
            await message.channel.send(piece)


def create_bot(
    settings: Settings,
    llm: LLMProvider,
    persona: PersonaLoader,
    usage_logger: UsageLogger,
) -> SheelaClient:
    return SheelaClient(settings, llm=llm, persona=persona, usage_logger=usage_logger)
