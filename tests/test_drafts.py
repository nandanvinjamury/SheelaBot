import asyncio
import json
from pathlib import Path

import pytest

from sheela.tools.drafts import DraftScheduler


@pytest.fixture
def drafts_dir(tmp_path: Path) -> Path:
    d = tmp_path / "drafts"
    return d


async def test_queue_creates_json_on_disk(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=999)
    draft = await s.queue("01 Daily/x.md", "append", "hello", channel="#general")
    expected = drafts_dir / f"{draft.draft_id}.json"
    assert expected.exists()
    data = json.loads(expected.read_text(encoding="utf-8"))
    assert data["target_path"] == "01 Daily/x.md"
    assert data["operation"] == "append"
    assert data["content"] == "hello"
    assert data["channel"] == "#general"


async def test_cancel_removes_json(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=999)
    draft = await s.queue("Inbox.md", "append", "x", channel=None)
    assert await s.cancel(draft.draft_id) is True
    assert not (drafts_dir / f"{draft.draft_id}.json").exists()


async def test_cancel_missing_returns_false(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=999)
    assert await s.cancel("nonexistent") is False


async def test_list_returns_sorted_drafts(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=999)
    await s.queue("a.md", "append", "1", channel=None)
    await s.queue("b.md", "append", "2", channel=None)
    drafts = s.list_drafts()
    assert len(drafts) == 2


async def test_flush_calls_callback_and_clears_drafts(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=0.05)
    received: list = []

    async def cb(drafts):
        received.extend(drafts)

    s.on_flush = cb
    await s.queue("a.md", "append", "1", channel=None)
    await s.queue("b.md", "append", "2", channel=None)
    # Wait for debounce
    await asyncio.sleep(0.2)
    assert len(received) == 2
    assert not s.has_pending_drafts()


async def test_new_queue_resets_debounce(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=0.15)
    fired_at: list[float] = []

    async def cb(drafts):
        fired_at.append(asyncio.get_event_loop().time())

    s.on_flush = cb
    start = asyncio.get_event_loop().time()
    await s.queue("a.md", "append", "1", channel=None)
    await asyncio.sleep(0.1)  # less than debounce
    await s.queue("b.md", "append", "2", channel=None)  # resets timer
    await asyncio.sleep(0.3)
    assert len(fired_at) == 1
    # Fired at least debounce_seconds AFTER the second queue
    assert fired_at[0] - start >= 0.2


async def test_flush_callback_failure_retains_drafts(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=0.05)

    async def cb(drafts):
        raise RuntimeError("boom")

    s.on_flush = cb
    draft = await s.queue("a.md", "append", "1", channel=None)
    await asyncio.sleep(0.2)
    # Draft should still be on disk because flush raised
    assert (drafts_dir / f"{draft.draft_id}.json").exists()


async def test_shutdown_flushes_immediately(drafts_dir: Path):
    s = DraftScheduler(drafts_dir, debounce_seconds=999)
    received: list = []

    async def cb(drafts):
        received.extend(drafts)

    s.on_flush = cb
    await s.queue("a.md", "append", "1", channel=None)
    await s.shutdown()
    assert len(received) == 1
