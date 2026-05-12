"""Lightweight loopback HTTP health endpoint.

Stdlib only — asyncio.start_server + a hand-rolled HTTP response. Returns
JSON describing the bot's process state for systemd, oncall checks, or your
own curl-based monitoring. Bound to 127.0.0.1 by default so it never
escapes the VM.

The bot creates one HealthState, mutates `last_message_at` from on_message,
and `snapshot()` returns a fresh JSON-able dict per request.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from sheela.config import Settings
    from sheela.memory.store import MemoryStore
    from sheela.tools.drafts import DraftScheduler
    from sheela.tools.vault_read import VaultReader

log = structlog.get_logger(__name__)


class HealthState:
    def __init__(
        self,
        settings: "Settings",
        vault_reader: "VaultReader",
        memory_store: "MemoryStore",
        draft_scheduler: "DraftScheduler",
    ) -> None:
        self.settings = settings
        self.vault_reader = vault_reader
        self.memory_store = memory_store
        self.draft_scheduler = draft_scheduler
        self.started_at = time.time()
        self.last_message_at: float | None = None

    def mark_message(self) -> None:
        self.last_message_at = time.time()

    async def snapshot(self) -> dict[str, Any]:
        db_path = self.settings.sheela_db_path
        db_size = db_path.stat().st_size if db_path.exists() else 0

        try:
            channels = await self.memory_store.list_active_channels()
            channels_count = len(channels)
        except Exception:
            channels_count = -1

        try:
            pending = len(list(self.draft_scheduler.drafts_dir.glob("*.json")))
        except Exception:
            pending = -1

        last_msg_iso: str | None = None
        if self.last_message_at is not None:
            last_msg_iso = datetime.fromtimestamp(
                self.last_message_at, tz=timezone.utc
            ).isoformat()

        return {
            "status": "ok",
            "uptime_seconds": int(time.time() - self.started_at),
            "last_message_at": last_msg_iso,
            "db_size_bytes": db_size,
            "vault_last_pull_check": self.vault_reader.last_check_iso,
            "memory_channels_active": channels_count,
            "drafts_pending": pending,
        }


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: HealthState,
) -> None:
    try:
        request_line = await reader.readline()
        # Drain headers
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b""):
                break

        path = "/"
        try:
            parts = request_line.decode("utf-8", errors="replace").split(" ")
            if len(parts) >= 2:
                path = parts[1]
        except Exception:
            pass

        if path in ("/", "/health"):
            try:
                payload = await state.snapshot()
                body = json.dumps(payload, indent=2).encode("utf-8")
                head = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "\r\n"
                ).encode("utf-8")
            except Exception as e:
                log.exception("health snapshot failed", error=str(e))
                body = json.dumps({"status": "error", "error": str(e)}).encode("utf-8")
                head = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json\r\n"
                    "Connection: close\r\n"
                    f"Content-Length: {len(body)}\r\n"
                    "\r\n"
                ).encode("utf-8")
        else:
            body = b"not found\n"
            head = (
                "HTTP/1.1 404 Not Found\r\n"
                "Content-Type: text/plain\r\n"
                "Connection: close\r\n"
                f"Content-Length: {len(body)}\r\n"
                "\r\n"
            ).encode("utf-8")

        writer.write(head + body)
        await writer.drain()
    except Exception as e:
        log.warning("health request handling failed", error=str(e))
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def start_health_server(
    host: str, port: int, state: HealthState
) -> asyncio.base_events.Server:
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, state), host=host, port=port
    )
    log.info("health server listening", host=host, port=port)
    return server
