import pytest

from sheela.discord_bot.streaming import (
    EMPTY_FALLBACK,
    PLACEHOLDER,
    split_for_discord,
    stream_to_discord,
)
from sheela.llm.base import ResponseChunk


class FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.history: list[str] = [content]

    async def edit(self, content: str) -> None:
        self.content = content
        self.history.append(content)


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[FakeMessage] = []

    async def send(self, content: str) -> FakeMessage:
        msg = FakeMessage(content)
        self.sent.append(msg)
        return msg


async def chunks_from(*texts, usage=None):
    for t in texts:
        yield ResponseChunk(text=t)
    if usage is not None:
        yield ResponseChunk(text="", finish_reason="stop", usage=usage)


def test_split_under_limit():
    assert split_for_discord("hello") == ["hello"]


def test_split_empty():
    assert split_for_discord("") == []


def test_split_word_boundary():
    text = "a" * 1000 + " " + "b" * 1000 + " " + "c" * 1000
    pages = split_for_discord(text, max_chars=1990)
    assert all(len(p) <= 1990 for p in pages)
    assert "".join(p.replace(" ", "") for p in pages) == text.replace(" ", "")


async def test_streams_chunks_and_returns_text():
    channel = FakeChannel()
    text, usage = await stream_to_discord(
        channel,
        chunks_from("Hello ", "world", usage={"model": "x", "input_tokens": 5}),
        edit_interval_s=0.0,
    )
    assert text == "Hello world"
    assert usage == {"model": "x", "input_tokens": 5}
    assert len(channel.sent) == 1
    assert channel.sent[0].content == "Hello world"  # final, no cursor


async def test_placeholder_sent_immediately():
    channel = FakeChannel()
    await stream_to_discord(channel, chunks_from("hi"), edit_interval_s=0.0)
    assert channel.sent[0].history[0] == PLACEHOLDER


async def test_cursor_appears_during_stream_and_disappears_at_end():
    channel = FakeChannel()
    await stream_to_discord(
        channel,
        chunks_from("partial"),
        edit_interval_s=0.0,
        cursor="X",
    )
    msg = channel.sent[0]
    # Mid-stream history contains cursor; final does not.
    assert any("X" in c for c in msg.history[:-1])
    assert msg.history[-1] == "partial"
    assert "X" not in msg.history[-1]


async def test_overflow_creates_additional_messages():
    channel = FakeChannel()
    text = "a" * 1500 + " " + "b" * 1500
    text_full, _ = await stream_to_discord(
        channel,
        chunks_from(text),
        edit_interval_s=0.0,
        max_chars=1990,
    )
    assert text_full == text
    assert len(channel.sent) >= 2


async def test_empty_response_falls_back():
    channel = FakeChannel()
    text, usage = await stream_to_discord(
        channel, chunks_from(usage=None), edit_interval_s=0.0
    )
    assert text == ""
    assert usage is None
    assert channel.sent[0].content == EMPTY_FALLBACK


async def test_exception_during_stream_finalizes_and_reraises():
    async def failing_iter():
        yield ResponseChunk(text="partial")
        raise RuntimeError("boom")

    channel = FakeChannel()
    with pytest.raises(RuntimeError):
        await stream_to_discord(channel, failing_iter(), edit_interval_s=0.0)
    msg = channel.sent[0]
    assert msg.content == "partial"  # cursor removed on cleanup


async def test_throttles_edits_with_long_interval():
    channel = FakeChannel()
    # With a long interval, only the first chunk triggers a mid-stream flush
    # (last_edit_at starts at 0; monotonic() returns large), then the rest
    # are throttled until the final flush at the end.
    await stream_to_discord(
        channel,
        chunks_from("a", "b", "c", "d", "e"),
        edit_interval_s=999.0,
    )
    msg = channel.sent[0]
    # We expect: placeholder, one mid-stream edit (with cursor), one final edit.
    # That's at most 3 entries in history.
    assert len(msg.history) <= 3
    assert msg.history[-1] == "abcde"
