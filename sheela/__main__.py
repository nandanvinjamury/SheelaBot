"""Entry point. Run with `python -m sheela`."""
from __future__ import annotations

import structlog

from sheela.config import Settings
from sheela.discord_bot.bot import create_bot
from sheela.llm import make_provider
from sheela.llm.router import ModelRouter
from sheela.llm.usage import UsageLogger
from sheela.persona import PersonaLoader
from sheela.utils.logging import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings)
    log = structlog.get_logger("sheela")

    persona = PersonaLoader(settings.vault_repo_path)
    router = ModelRouter()
    usage = UsageLogger(settings.sheela_log_dir)
    llm = make_provider(settings, router=router)

    log.info(
        "starting sheela bot",
        guild_id=settings.discord_guild_id,
        llm_provider=settings.llm_provider,
        log_mode=settings.sheela_log_mode,
        vault=str(settings.vault_repo_path),
    )

    bot = create_bot(settings, llm=llm, persona=persona, usage_logger=usage)
    bot.run(settings.discord_bot_token.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    main()
