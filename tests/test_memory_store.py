from pathlib import Path

import pytest

from sheela.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path: Path):
    s = MemoryStore(tmp_path / "memory.db")
    await s.connect()
    yield s
    await s.close()


async def test_add_message_returns_turn_id(store: MemoryStore):
    tid = await store.add_message("#general", "user", "hello")
    assert tid > 0


async def test_add_exchange_inserts_two_rows(store: MemoryStore):
    uid, aid = await store.add_exchange(
        "#general", "hi", "hey", tokens_in=100, tokens_out=50
    )
    assert uid > 0
    assert aid > uid
    active = await store.get_active_messages("#general")
    assert [m["role"] for m in active] == ["user", "assistant"]
    assert active[0]["content"] == "hi"
    assert active[1]["content"] == "hey"


async def test_count_active(store: MemoryStore):
    assert await store.count_active("#general") == 0
    await store.add_exchange("#general", "u1", "a1")
    await store.add_exchange("#general", "u2", "a2")
    assert await store.count_active("#general") == 4


async def test_get_recent_messages_returns_chronological(store: MemoryStore):
    for i in range(15):
        await store.add_exchange("#general", f"u{i}", f"a{i}")
    recent = await store.get_recent_messages("#general", n_rows=6)
    assert len(recent) == 6
    # 30 rows total; last 6 are u12, a12, u13, a13, u14, a14
    assert recent[0]["content"] == "u12"
    assert recent[-1]["content"] == "a14"


async def test_per_channel_isolation(store: MemoryStore):
    await store.add_message("#general", "user", "from general")
    await store.add_message("#health", "user", "from health")
    g = await store.get_active_messages("#general")
    h = await store.get_active_messages("#health")
    assert len(g) == 1 and g[0]["content"] == "from general"
    assert len(h) == 1 and h[0]["content"] == "from health"


async def test_archive_messages_marks_archived(store: MemoryStore):
    await store.add_exchange("#general", "u1", "a1")
    await store.add_exchange("#general", "u2", "a2")
    active = await store.get_active_messages("#general")
    assert len(active) == 4
    # Archive first pair
    await store.archive_messages(
        [active[0]["turn_id"], active[1]["turn_id"]]
    )
    remaining = await store.get_active_messages("#general")
    assert [m["content"] for m in remaining] == ["u2", "a2"]
    assert await store.count_active("#general") == 2


async def test_upsert_summary_insert_and_update(store: MemoryStore):
    assert await store.get_summary("#general") is None
    await store.upsert_summary("#general", "summary v1", 10, 5)
    s = await store.get_summary("#general")
    assert s is not None
    assert s["summary"] == "summary v1"
    assert s["covers_through_turn_id"] == 10
    assert s["turn_count"] == 5
    await store.upsert_summary("#general", "summary v2", 20, 10)
    s = await store.get_summary("#general")
    assert s["summary"] == "summary v2"
    assert s["turn_count"] == 10


async def test_list_active_channels(store: MemoryStore):
    await store.add_message("#general", "user", "x")
    await store.add_message("#health", "user", "y")
    channels = await store.list_active_channels()
    assert sorted(channels) == ["#general", "#health"]


async def test_archived_messages_not_in_active_channel_list(store: MemoryStore):
    tid = await store.add_message("#general", "user", "x")
    await store.archive_messages([tid])
    channels = await store.list_active_channels()
    assert channels == []
