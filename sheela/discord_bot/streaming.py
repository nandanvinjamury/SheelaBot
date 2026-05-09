"""Stream LLM responses to Discord by editing messages in place.

Discord allows up to 5 edits/second per channel; we throttle to one edit
every 500 ms to stay well under that. A cursor character is appended during
streaming and removed on the final edit. When the accumulated text exceeds
~2000 chars (Discord's hard limit), we send additional placeholder messages
on the fly and stream into them.
"""
from __future__ import annotations

import time
from typing import Any, AsyncIterator, Protocol

import structlog

from sheela.llm.base import ResponseChunk

log = structlog.get_logger(__name__)

DISCORD_MAX_CHARS = 1990
EDIT_INTERVAL_S = 0.5
CURSOR = "▌"
PLACEHOLDER = "…"
EMPTY_FALLBACK = "I came back empty on that one — try rephrasing?"


class StreamableMessage(Protocol):
    async def edit(self, content: str) -> Any: ...


class StreamableChannel(Protocol):
    async def send(self, content: str) -> StreamableMessage: ...


def split_for_discord(text: str, max_chars: int = DISCORD_MAX_CHARS) -> list[str]:
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
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


async def stream_to_discord(
    channel: StreamableChannel,
    response_iter: AsyncIterator[ResponseChunk],
    *,
    max_chars: int = DISCORD_MAX_CHARS,
    edit_interval_s: float = EDIT_INTERVAL_S,
    cursor: str = CURSOR,
    placeholder: str = PLACEHOLDER,
) -> tuple[str, dict[str, Any] | None]:
    """Stream chunks into Discord, editing in place with a cursor visual.

    Returns (full_text, last_usage_or_None). On overflow, additional
    Discord messages are sent and streamed into. Final flush removes
    the cursor; if the response is empty, the placeholder is replaced
    with a fallback message.

    On exception, a final flush runs to remove the cursor before re-raising.
    """
    sent: list[StreamableMessage] = [await channel.send(placeholder)]
    rendered: list[str] = [placeholder]
    accumulated = ""
    last_usage: dict[str, Any] | None = None
    last_edit_at = 0.0

    async def flush(final: bool) -> None:
        pages = split_for_discord(accumulated, max_chars=max_chars)
        if not pages:
            if not final:
                return
            pages = [EMPTY_FALLBACK]
        while len(sent) < len(pages):
            sent.append(await channel.send(placeholder))
            rendered.append(placeholder)
        for i, page in enumerate(pages):
            is_last_page = i == len(pages) - 1
            target = page if (final or not is_last_page) else page + cursor
            if target != rendered[i]:
                await sent[i].edit(content=target)
                rendered[i] = target

    try:
        async for chunk in response_iter:
            accumulated += chunk.text
            if chunk.usage is not None:
                last_usage = chunk.usage
            now = time.monotonic()
            if now - last_edit_at >= edit_interval_s:
                await flush(final=False)
                last_edit_at = now
        await flush(final=True)
    except BaseException:
        try:
            await flush(final=True)
        except Exception:
            pass
        raise

    return accumulated, last_usage
