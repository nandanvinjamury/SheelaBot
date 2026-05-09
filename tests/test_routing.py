from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from sheela.discord_bot.routing import ChannelRouter

TZ = "America/New_York"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    daily = tmp_path / "Daily"
    daily.mkdir()
    today = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("today's note", encoding="utf-8")
    (tmp_path / "Inbox.md").write_text("inbox stuff", encoding="utf-8")
    (tmp_path / "Obligations.md").write_text("obligations", encoding="utf-8")
    return tmp_path


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


@pytest.fixture
def routing_yaml(tmp_path: Path) -> Path:
    return _write_yaml(
        tmp_path / "routing.yaml",
        {
            "channels": {
                "general": {
                    "description": "General channel",
                    "vault_paths_to_load": ["Inbox.md", "Daily/{date}.md"],
                    "vault_paths_writable_without_confirm": [
                        "Inbox.md",
                        "Daily/{date}.md",
                    ],
                    "tone_hint": None,
                },
                "money": {
                    "description": "Money stuff",
                    "vault_paths_to_load": [],
                    "vault_paths_writable_without_confirm": [],
                    "tone_hint": "Educational only.",
                },
            }
        },
    )


async def test_known_channel_returns_context(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    ctx = await router.get_channel_context("general")
    assert ctx is not None
    assert "general" in ctx
    assert "General channel" in ctx
    assert "inbox stuff" in ctx
    assert "today's note" in ctx


async def test_unknown_channel_returns_none(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    assert await router.get_channel_context("nonexistent") is None


async def test_strips_leading_hash(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    assert await router.get_channel_context("#general") is not None


async def test_tone_hint_appears_when_set(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    ctx = await router.get_channel_context("money")
    assert ctx is not None
    assert "Tone hint" in ctx
    assert "Educational only" in ctx


async def test_tone_hint_section_absent_when_null(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    ctx = await router.get_channel_context("general")
    assert ctx is not None
    assert "Tone hint" not in ctx


async def test_missing_vault_files_skipped(vault: Path, tmp_path: Path):
    yaml_path = _write_yaml(
        tmp_path / "r.yaml",
        {
            "channels": {
                "test": {
                    "description": "test",
                    "vault_paths_to_load": ["nonexistent.md", "Inbox.md"],
                    "vault_paths_writable_without_confirm": [],
                    "tone_hint": None,
                }
            }
        },
    )
    router = ChannelRouter(yaml_path, vault, TZ)
    ctx = await router.get_channel_context("test")
    assert ctx is not None
    assert "inbox stuff" in ctx
    assert "nonexistent" not in ctx


def test_writable_paths_resolved(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    paths = router.get_writable_paths("general")
    today = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")
    assert "Inbox.md" in paths
    assert f"Daily/{today}.md" in paths


def test_writable_paths_unknown_channel_empty(vault: Path, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, vault, TZ)
    assert router.get_writable_paths("unknown") == []


def test_repo_example_yaml_parses():
    repo_root = Path(__file__).parent.parent
    example = repo_root / "deploy" / "routing.yaml.example"
    assert example.exists()
    router = ChannelRouter(example, repo_root, TZ)  # vault path is irrelevant for parse
    assert "general" in router.config.channels
    assert "side-project" in router.config.channels
