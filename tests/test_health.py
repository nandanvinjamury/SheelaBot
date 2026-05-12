import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sheela.health import HealthState, start_health_server


class _FakeSettings:
    def __init__(self, db_path: Path):
        self.sheela_db_path = db_path


class _FakeReader:
    last_check_iso = "2026-05-12T16:42:00+00:00"


class _FakeMemoryStore:
    async def list_active_channels(self):
        return ["#general", "#health"]


class _FakeScheduler:
    def __init__(self, drafts_dir: Path):
        self.drafts_dir = drafts_dir


@pytest.fixture
def state(tmp_path: Path):
    db = tmp_path / "sheela.db"
    db.write_bytes(b"x" * 1024)
    drafts_dir = tmp_path / "drafts"
    drafts_dir.mkdir()
    (drafts_dir / "one.json").write_text("{}")
    return HealthState(
        settings=_FakeSettings(db),  # type: ignore[arg-type]
        vault_reader=_FakeReader(),  # type: ignore[arg-type]
        memory_store=_FakeMemoryStore(),  # type: ignore[arg-type]
        draft_scheduler=_FakeScheduler(drafts_dir),  # type: ignore[arg-type]
    )


async def test_snapshot_basic_shape(state: HealthState):
    snap = await state.snapshot()
    assert snap["status"] == "ok"
    assert snap["uptime_seconds"] >= 0
    assert snap["last_message_at"] is None
    assert snap["db_size_bytes"] == 1024
    assert snap["vault_last_pull_check"] == "2026-05-12T16:42:00+00:00"
    assert snap["memory_channels_active"] == 2
    assert snap["drafts_pending"] == 1


async def test_mark_message_updates_timestamp(state: HealthState):
    assert state.last_message_at is None
    state.mark_message()
    snap = await state.snapshot()
    assert snap["last_message_at"] is not None


async def test_snapshot_handles_missing_db(state: HealthState):
    state.settings.sheela_db_path.unlink()
    snap = await state.snapshot()
    assert snap["db_size_bytes"] == 0


async def test_snapshot_handles_memory_failure(state: HealthState):
    state.memory_store.list_active_channels = AsyncMock(side_effect=RuntimeError)
    snap = await state.snapshot()
    assert snap["memory_channels_active"] == -1


async def test_http_server_returns_json(state: HealthState, unused_tcp_port):
    server = await start_health_server("127.0.0.1", unused_tcp_port, state)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read()
        writer.close()
        await writer.wait_closed()
        text = data.decode()
        assert "HTTP/1.1 200 OK" in text
        assert "application/json" in text
        body = text.split("\r\n\r\n", 1)[1]
        payload = json.loads(body)
        assert payload["status"] == "ok"
    finally:
        server.close()
        await server.wait_closed()


async def test_http_server_404_for_other_paths(state: HealthState, unused_tcp_port):
    server = await start_health_server("127.0.0.1", unused_tcp_port, state)
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        writer.write(b"GET /nope HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()
        data = await reader.read()
        writer.close()
        await writer.wait_closed()
        assert b"404 Not Found" in data
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def unused_tcp_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
