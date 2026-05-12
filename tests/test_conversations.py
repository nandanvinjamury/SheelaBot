from pathlib import Path

import pytest

from sheela.memory.conversations import ConversationManager
from sheela.memory.store import MemoryStore
from sheela.memory.summarizer import ConversationSummarizer


class FakeLLM:
    def __init__(self):
        self.calls: list[str] = []

    async def summarize(self, text: str, max_tokens: int) -> str:
        self.calls.append(text)
        return "rolled-up summary"


@pytest.fixture
async def manager(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    await store.connect()
    summarizer = ConversationSummarizer(FakeLLM())
    yield ConversationManager(store, summarizer)
    await store.close()


async def test_empty_channel_returns_no_summary_or_recent(manager):
    summary, recent = await manager.get_context("#general")
    assert summary is None
    assert recent == []


async def test_record_exchange_visible_in_context(manager):
    await manager.record_exchange(
        "#general", "user msg", "assistant msg", tokens_in=10, tokens_out=5
    )
    summary, recent = await manager.get_context("#general")
    assert summary is None
    assert len(recent) == 2
    assert recent[0]["role"] == "user"
    assert recent[1]["role"] == "assistant"


async def test_below_threshold_no_compaction(manager):
    for i in range(20):
        await manager.record_exchange("#general", f"u{i}", f"a{i}")
    result = await manager.maybe_compact("#general")
    assert result is None
    assert await manager.store.count_active("#general") == 40


async def test_above_threshold_compacts(manager):
    # 31 exchanges = 62 rows; > 60 threshold
    for i in range(31):
        await manager.record_exchange("#general", f"u{i}", f"a{i}")
    result = await manager.maybe_compact("#general")
    assert result is not None
    assert result["archived"] == 42  # 31*2 - 20 (recent window) = 42
    # After compaction: only the recent 10 exchanges (20 rows) remain active
    assert await manager.store.count_active("#general") == 20
    # Summary is now present
    summary, recent = await manager.get_context("#general")
    assert summary == "rolled-up summary"
    assert len(recent) == 20


async def test_second_compaction_includes_previous_summary(manager):
    # First compaction
    for i in range(31):
        await manager.record_exchange("#general", f"u{i}", f"a{i}")
    await manager.maybe_compact("#general")
    # Reach the threshold again
    for i in range(21):
        await manager.record_exchange("#general", f"u{31+i}", f"a{31+i}")
    result = await manager.maybe_compact("#general")
    assert result is not None
    # The summarizer should have seen the previous summary in the prompt text
    fake_llm: FakeLLM = manager.summarizer.llm  # type: ignore[assignment]
    assert any("PREVIOUS SUMMARY" in call for call in fake_llm.calls[-1:])


async def test_per_channel_isolation(manager):
    for i in range(31):
        await manager.record_exchange("#general", f"g{i}", f"r{i}")
    await manager.maybe_compact("#general")
    # #health should not have been touched
    summary, recent = await manager.get_context("#health")
    assert summary is None
    assert recent == []


async def test_compact_all_channels(manager):
    for i in range(31):
        await manager.record_exchange("#general", f"u{i}", f"a{i}")
    for i in range(31):
        await manager.record_exchange("#health", f"u{i}", f"a{i}")
    results = await manager.compact_all_channels()
    assert set(results.keys()) == {"#general", "#health"}


async def test_recent_window_size_matches_config(tmp_path: Path):
    store = MemoryStore(tmp_path / "m.db")
    await store.connect()
    try:
        manager = ConversationManager(
            store,
            ConversationSummarizer(FakeLLM()),
            recent_exchanges=3,
            compact_trigger_exchanges=5,
        )
        for i in range(10):
            await manager.record_exchange("#x", f"u{i}", f"a{i}")
        # 10 exchanges = 20 rows; threshold = 10 rows
        assert await manager.store.count_active("#x") == 20
        result = await manager.maybe_compact("#x")
        assert result is not None
        # 10 exchanges - 3 recent = 7 archived = 14 rows
        assert result["archived"] == 14
        # 6 rows remain
        assert await manager.store.count_active("#x") == 6
    finally:
        await store.close()
