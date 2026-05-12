import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from sheela.tools.drafts import DraftScheduler
from sheela.tools.git import GitError
from sheela.tools.safety import SafetyChecker
from sheela.tools.vault_write import VaultWriter

TZ = "America/New_York"


def _today() -> str:
    return datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    v.mkdir()
    (v / "01 Daily").mkdir()
    return v


@pytest.fixture
def drafts_dir(tmp_path: Path) -> Path:
    return tmp_path / "drafts"


@pytest.fixture
def fake_git():
    g = AsyncMock()
    g.add = AsyncMock()
    g.commit = AsyncMock()
    g.push = AsyncMock()
    g.pull = AsyncMock()
    return g


@pytest.fixture
def writer(vault: Path, drafts_dir: Path, fake_git):
    safety = SafetyChecker(vault_path=vault, tz=TZ)
    scheduler = DraftScheduler(drafts_dir, debounce_seconds=0.05)
    w = VaultWriter(
        vault_path=vault,
        scheduler=scheduler,
        safety=safety,
        git_client=fake_git,
    )
    scheduler.on_flush = w.flush_callback
    return w


# --- safety paths in request_write ------------------------------------


async def test_denied_returns_error(writer: VaultWriter):
    ok, msg = await writer.request_write(".git/config", "x", "overwrite")
    assert not ok
    assert "off-limits" in msg or "denied" in msg


async def test_needs_confirmation_returns_error(writer: VaultWriter):
    ok, msg = await writer.request_write(
        "03 People/Family/Parent.md", "x", "overwrite"
    )
    assert not ok
    assert "needs confirmation" in msg


async def test_confirmed_succeeds_for_confirm_path(writer: VaultWriter):
    ok, msg = await writer.request_write(
        "03 People/Family/Parent.md", "x", "overwrite", confirmed=True
    )
    assert ok
    assert "draft queued" in msg


async def test_allowed_path_queues_draft(writer: VaultWriter, drafts_dir: Path):
    ok, msg = await writer.request_write(
        "Inbox.md", "captured: think about X", "append"
    )
    assert ok
    assert "draft queued" in msg
    assert len(list(drafts_dir.glob("*.json"))) == 1


# --- flush + apply ----------------------------------------------------


async def test_flush_appends_to_daily_note(
    writer: VaultWriter, vault: Path, fake_git
):
    today = _today()
    ok, _ = await writer.request_write(
        f"01 Daily/{today}.md", "ate weeknight pasta, 600 cal", "append"
    )
    assert ok
    # Wait for debounce
    await asyncio.sleep(0.2)
    target = vault / "01 Daily" / f"{today}.md"
    assert target.exists()
    assert "ate weeknight pasta" in target.read_text(encoding="utf-8")
    fake_git.add.assert_called_once()
    fake_git.commit.assert_called_once()
    fake_git.push.assert_called_once()


async def test_append_preserves_existing_content(
    writer: VaultWriter, vault: Path
):
    today = _today()
    target = vault / "01 Daily" / f"{today}.md"
    target.write_text("# Existing\n\nFirst entry\n", encoding="utf-8")
    await writer.request_write(
        f"01 Daily/{today}.md", "second entry", "append"
    )
    await asyncio.sleep(0.2)
    content = target.read_text(encoding="utf-8")
    assert "First entry" in content
    assert "second entry" in content


async def test_multiple_writes_batch_into_one_commit(
    writer: VaultWriter, vault: Path, fake_git
):
    today = _today()
    await writer.request_write(
        f"01 Daily/{today}.md", "first", "append"
    )
    await writer.request_write("Inbox.md", "second", "append")
    await asyncio.sleep(0.2)
    # One commit + one push, regardless of file count
    assert fake_git.commit.call_count == 1
    assert fake_git.push.call_count == 1
    # Two adds
    assert fake_git.add.call_count == 2


async def test_overwrite_replaces_file(
    writer: VaultWriter, vault: Path
):
    # Use an allowlisted overwrite-able path: recipes
    target = vault / "06 Recipes" / "Dinner"
    target.mkdir(parents=True)
    file = target / "Test.md"
    file.write_text("old content", encoding="utf-8")
    await writer.request_write(
        "06 Recipes/Dinner/Test.md",
        "new content",
        "overwrite",
    )
    await asyncio.sleep(0.2)
    assert file.read_text(encoding="utf-8") == "new content"


async def test_push_retries_on_non_fast_forward(
    writer: VaultWriter, vault: Path, fake_git
):
    today = _today()
    # First push attempt rejected, second succeeds
    fake_git.push.side_effect = [
        GitError("non-fast-forward: updates were rejected"),
        None,
    ]
    await writer.request_write(
        f"01 Daily/{today}.md", "entry", "append"
    )
    await asyncio.sleep(0.2)
    assert fake_git.push.call_count == 2
    fake_git.pull.assert_called_once_with(rebase=True)


async def test_push_failure_after_retries_propagates(
    writer: VaultWriter, vault: Path, fake_git, drafts_dir: Path
):
    today = _today()
    fake_git.push.side_effect = GitError("non-fast-forward: rejected")
    await writer.request_write(
        f"01 Daily/{today}.md", "entry", "append"
    )
    await asyncio.sleep(0.2)
    # Drafts retained on disk because flush raised
    assert len(list(drafts_dir.glob("*.json"))) >= 1


# --- post-flush hook --------------------------------------------------


async def test_post_flush_hook_called(vault: Path, drafts_dir: Path, fake_git):
    safety = SafetyChecker(vault_path=vault, tz=TZ)
    scheduler = DraftScheduler(drafts_dir, debounce_seconds=0.05)
    called = asyncio.Event()

    async def hook():
        called.set()

    w = VaultWriter(
        vault_path=vault,
        scheduler=scheduler,
        safety=safety,
        git_client=fake_git,
        on_post_flush=hook,
    )
    scheduler.on_flush = w.flush_callback
    await w.request_write("Inbox.md", "x", "append")
    await asyncio.wait_for(called.wait(), timeout=1.0)


# --- cancel + list ----------------------------------------------------


async def test_cancel_draft(writer: VaultWriter):
    ok, msg = await writer.request_write("Inbox.md", "x", "append")
    assert ok
    draft_id = msg.split("draft queued:")[1].split("->")[0].strip()
    ok2, msg2 = await writer.cancel(draft_id)
    assert ok2
    assert draft_id in msg2


async def test_list_pending(writer: VaultWriter):
    await writer.request_write("Inbox.md", "a", "append")
    await writer.request_write("Inbox.md", "b", "append")
    pending = writer.list_pending()
    assert len(pending) == 2
