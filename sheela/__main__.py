"""Entry point. Run with `python -m sheela`."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from sheela.config import Settings
from sheela.discord_bot.bot import create_bot


def setup_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.sheela_debug else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.sheela_log_dir.exists():
        log_file = settings.sheela_log_dir / "sheela.log"
        handlers.append(
            RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5)
        )

    for handler in handlers:
        handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers


def main() -> None:
    settings = Settings()
    setup_logging(settings)
    log = logging.getLogger("sheela")
    log.info("Starting Sheela bot (guild=%s)", settings.discord_guild_id)
    bot = create_bot(settings)
    bot.run(settings.discord_bot_token.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    main()
