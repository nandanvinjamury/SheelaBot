"""Logging configuration.

Two modes, selected by `SHEELA_LOG_MODE`:

- `console` (default, local dev): pretty colored output to stderr via
  structlog's ConsoleRenderer.
- `file` (VM under systemd): JSON to `{SHEELA_LOG_DIR}/sheela.log` (rotated)
  AND JSON to stderr (captured by journald).

stdlib logging is routed through structlog's ProcessorFormatter so that
discord.py's internal log records flow through the same pipeline.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog

from sheela.config import Settings


def configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.sheela_debug else getattr(
        logging, settings.sheela_log_level.upper(), logging.INFO
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if settings.sheela_log_mode == "file":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    if settings.sheela_log_mode == "file":
        settings.sheela_log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.sheela_log_dir / "sheela.log",
            maxBytes=10_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # discord.py is chatty at INFO; tame it unless we're debugging.
    if not settings.sheela_debug:
        logging.getLogger("discord").setLevel(logging.WARNING)
        logging.getLogger("discord.http").setLevel(logging.WARNING)
