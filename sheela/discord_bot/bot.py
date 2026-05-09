"""Discord client.

Step 3: every non-bot, non-DM message in the configured guild gets routed
to the LLM with channel-specific context appended to the system prompt,
and the response is streamed back via in-place message edits. The literal
`ping` connectivity test still bypasses the LLM.
"""
from __future__ import annotations

import discord
import structlog

from sheela.config import Settings
from sheela.discord_bot.routing import ChannelRouter
from sheela.discord_bot.streaming import stream_to_discord
from sheela.llm.base import LLMProvider, Message, RateLimitExhausted
from sheela.llm.usage import UsageLogger
from sheela.persona import PersonaLoader

log = structlog.get_logger(__name__)


def respond_to(content: str) -> str | None:
    """Local-only quick replies (no LLM call). Returns None to defer to LLM."""
    match content.strip().lower():
        case "ping":
            return "pong"
        case _:
            return None


class SheelaClient(discord.Client):
    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider,
        persona: PersonaLoader,
        channel_router: ChannelRouter,
        usage_logger: UsageLogger,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.llm = llm
        self.persona = persona
        self.channel_router = channel_router
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

    @staticmethod
    def _channel_name(channel: discord.abc.Messageable) -> str:
        name = getattr(channel, "name", None)
        return f"#{name}" if name else str(channel)

    async def _handle_llm_message(
        self, message: discord.Message, content: str
    ) -> None:
        channel_obj = message.channel
        channel_name = self._channel_name(channel_obj)

        try:
            async with channel_obj.typing():
                persona_part = await self.persona.get_system_prompt()
                channel_part = await self.channel_router.get_channel_context(
                    channel_name
                )

            system_prompt = persona_part
            if channel_part:
                system_prompt = system_prompt + "\n\n---\n\n" + channel_part

            messages = [Message(role="user", content=content)]
            response_iter = self.llm.respond(
                system_prompt, messages, stream=True
            )
            full_text, usage = await stream_to_discord(channel_obj, response_iter)
        except RateLimitExhausted:
            log.warning(
                "rate-limited; replying with fallback message",
                channel=channel_name,
            )
            await channel_obj.send("Rate-limited, try again in an hour.")
            return
        except Exception as e:
            log.exception(
                "llm call failed", channel=channel_name, error=str(e)
            )
            await channel_obj.send(
                "Something broke on my end. Logs have details."
            )
            return

        if usage is not None:
            await self.usage_logger.log(
                channel=channel_name,
                task="respond",
                **usage,
            )

        if not full_text.strip():
            log.warning("empty response from llm", channel=channel_name)


def create_bot(
    settings: Settings,
    llm: LLMProvider,
    persona: PersonaLoader,
    channel_router: ChannelRouter,
    usage_logger: UsageLogger,
) -> SheelaClient:
    return SheelaClient(
        settings,
        llm=llm,
        persona=persona,
        channel_router=channel_router,
        usage_logger=usage_logger,
    )
