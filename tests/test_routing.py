from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from sheela.discord_bot.routing import ChannelRouter
from sheela.tools.vault_read import VaultReader

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


@pytest.fixture
def reader(vault: Path) -> VaultReader:
    return VaultReader(vault)


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


async def test_known_channel_returns_context(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    ctx = await router.get_channel_context("general")
    assert ctx is not None
    assert "general" in ctx
    assert "General channel" in ctx
    assert "inbox stuff" in ctx
    assert "today's note" in ctx


async def test_unknown_channel_returns_none(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    assert await router.get_channel_context("nonexistent") is None


async def test_strips_leading_hash(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    assert await router.get_channel_context("#general") is not None


async def test_tone_hint_appears_when_set(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    ctx = await router.get_channel_context("money")
    assert ctx is not None
    assert "Tone hint" in ctx
    assert "Educational only" in ctx


async def test_writable_section_appears(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    ctx = await router.get_channel_context("general")
    assert ctx is not None
    assert "Writable without asking" in ctx
    assert "Inbox.md" in ctx


async def test_writable_section_absent_when_empty(
    reader: VaultReader, tmp_path: Path
):
    import yaml as _yaml
    cfg_path = tmp_path / "r.yaml"
    cfg_path.write_text(
        _yaml.safe_dump(
            {
                "channels": {
                    "noop": {
                        "description": "x",
                        "vault_paths_to_load": [],
                        "vault_paths_writable_without_confirm": [],
                        "tone_hint": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    router = ChannelRouter(cfg_path, reader, TZ)
    ctx = await router.get_channel_context("noop")
    assert ctx is not None
    assert "Writable without asking" not in ctx


async def test_tone_hint_section_absent_when_null(
    reader: VaultReader, routing_yaml: Path
):
    router = ChannelRouter(routing_yaml, reader, TZ)
    ctx = await router.get_channel_context("general")
    assert ctx is not None
    assert "Tone hint" not in ctx


async def test_missing_vault_files_skipped(reader: VaultReader, tmp_path: Path):
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
    router = ChannelRouter(yaml_path, reader, TZ)
    ctx = await router.get_channel_context("test")
    assert ctx is not None
    assert "inbox stuff" in ctx
    assert "nonexistent" not in ctx


def test_writable_paths_resolved(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    paths = router.get_writable_paths("general")
    today = datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")
    assert "Inbox.md" in paths
    assert f"Daily/{today}.md" in paths


def test_writable_paths_unknown_channel_empty(reader: VaultReader, routing_yaml: Path):
    router = ChannelRouter(routing_yaml, reader, TZ)
    assert router.get_writable_paths("unknown") == []


def test_repo_example_yaml_parses(tmp_path: Path):
    repo_root = Path(__file__).parent.parent
    example = repo_root / "deploy" / "routing.yaml.example"
    assert example.exists()
    router = ChannelRouter(example, VaultReader(repo_root), TZ)
    assert "general" in router.config.channels
    assert "side-project" in router.config.channels
