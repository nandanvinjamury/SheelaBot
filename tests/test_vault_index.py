import json
from pathlib import Path

import pytest

from sheela.tools.vault_read import VaultReader
from sheela.vault.contract import (
    extract_title,
    infer_type,
    parse_frontmatter,
)
from sheela.vault.index import VaultIndexer


# --- contract.py tests -----------------------------------------------------


def test_parse_frontmatter_present():
    content = "---\nname: Parent\nrelationship: family\n---\n\n# Parent\n\nBody"
    fm, body = parse_frontmatter(content)
    assert fm == {"name": "Parent", "relationship": "family"}
    assert body.startswith("# Parent")


def test_parse_frontmatter_absent():
    content = "# Just a header\n\nBody."
    fm, body = parse_frontmatter(content)
    assert fm is None
    assert body == content


def test_parse_frontmatter_malformed_yaml():
    content = "---\n[unclosed bracket\n---\nBody"
    fm, body = parse_frontmatter(content)
    assert fm is None


def test_extract_title_from_h1():
    body = "Some intro\n# The Title\n\nMore stuff"
    assert extract_title(body, "fallback") == "The Title"


def test_extract_title_fallback():
    body = "No headers in this body."
    assert extract_title(body, "fallback") == "fallback"


def test_infer_type():
    # Bare folder names
    assert infer_type("People/Family/Parent.md") == "person"
    assert infer_type("Recipes/Dinner/Weeknight pasta.md") == "recipe"
    assert infer_type("Career/Side project/Architecture.md") == "project"
    assert infer_type("Learning/LangGraph/Notes.md") == "learning"
    assert infer_type("Daily/2026-05-09.md") == "daily"
    assert infer_type("Exercise/Yoga/Hip openers.md") == "exercise"
    assert infer_type("Hobbies/Sport/Drills.md") == "hobby"
    assert infer_type("Templates/Daily.md") == "template"
    assert infer_type("Schedule/Google Calendar.md") == "schedule"
    assert infer_type("Money/Earnings.md") == "money"
    assert infer_type("Agent/PERSONA.md") == "config"
    assert infer_type("Inbox.md") == "misc"


def test_infer_type_with_obsidian_prefix():
    # Real vault uses NN-space prefixes for Obsidian sort ordering
    assert infer_type("01 Daily/2026-05-11.md") == "daily"
    assert infer_type("02 Schedule/Google Calendar.md") == "schedule"
    assert infer_type("03 People/Family/Parent.md") == "person"
    assert infer_type("04 Money/Earnings.md") == "money"
    assert infer_type("05 Exercise/Index.md") == "exercise"
    assert infer_type("06 Recipes/Dinner/Weeknight pasta.md") == "recipe"
    assert infer_type("07 Learning/Topic/Notes.md") == "learning"
    assert infer_type("08 Career/Side project/Architecture.md") == "project"
    assert infer_type("09 Hobbies/Sport/Drills.md") == "hobby"
    assert infer_type("10 Travel/Templates/International.md") == "travel"


# --- VaultIndexer tests ----------------------------------------------------


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # People/Family/Parent.md with frontmatter
    family = tmp_path / "People" / "Family"
    family.mkdir(parents=True)
    (family / "Parent.md").write_text(
        "---\nname: Parent\nrelationship: family\nlast_contacted: 2026-04-28\n---\n\n"
        "# Parent\n\nBackground stuff.",
        encoding="utf-8",
    )
    # Recipes/Dinner/Weeknight pasta.md
    dinner = tmp_path / "Recipes" / "Dinner"
    dinner.mkdir(parents=True)
    (dinner / "Weeknight pasta.md").write_text(
        "---\nname: Weeknight pasta\nrating: 9\n---\n\n# Weeknight pasta\n\nRecipe.",
        encoding="utf-8",
    )
    # Inbox.md (top level, misc)
    (tmp_path / "Inbox.md").write_text("# Inbox\n\nThings to triage.", encoding="utf-8")
    # Agent/PERSONA.md (should be skipped)
    agent = tmp_path / "Agent"
    agent.mkdir()
    (agent / "PERSONA.md").write_text("# Persona", encoding="utf-8")
    # _drafts/_pending.md (should be skipped due to underscore prefix)
    drafts = tmp_path / "_drafts"
    drafts.mkdir()
    (drafts / "_pending.md").write_text("draft", encoding="utf-8")
    return tmp_path


async def test_build_creates_index_file(vault: Path, tmp_path: Path):
    index_path = tmp_path / "vault_index.json"
    indexer = VaultIndexer(VaultReader(vault), index_path)
    result = await indexer.build()
    assert index_path.exists()
    on_disk = json.loads(index_path.read_text(encoding="utf-8"))
    assert result == on_disk


async def test_index_contains_expected_notes(vault: Path, tmp_path: Path):
    indexer = VaultIndexer(VaultReader(vault), tmp_path / "vault_index.json")
    result = await indexer.build()
    paths = {n["path"] for n in result["notes"]}
    assert "People/Family/Parent.md" in paths
    assert "Recipes/Dinner/Weeknight pasta.md" in paths
    assert "Inbox.md" in paths
    # Excluded
    assert "Agent/PERSONA.md" not in paths
    assert all("_drafts" not in p for p in paths)
    assert all(not p.startswith(".") for p in paths)


async def test_index_entry_shape(vault: Path, tmp_path: Path):
    indexer = VaultIndexer(VaultReader(vault), tmp_path / "vault_index.json")
    result = await indexer.build()
    parent = next(n for n in result["notes"] if n["path"] == "People/Family/Parent.md")
    assert parent["type"] == "person"
    assert parent["title"] == "Parent"
    assert parent["frontmatter"]["relationship"] == "family"
    assert parent["size_bytes"] > 0
    assert "modified" in parent


async def test_get_uses_cache(vault: Path, tmp_path: Path):
    indexer = VaultIndexer(VaultReader(vault), tmp_path / "vault_index.json")
    a = await indexer.get()
    b = await indexer.get()
    assert a is b  # same object reference


async def test_get_reads_existing_file_when_cache_cold(vault: Path, tmp_path: Path):
    index_path = tmp_path / "vault_index.json"
    indexer1 = VaultIndexer(VaultReader(vault), index_path)
    await indexer1.build()
    # Fresh indexer, no in-memory cache, but file exists
    indexer2 = VaultIndexer(VaultReader(vault), index_path)
    result = await indexer2.get()
    paths = {n["path"] for n in result["notes"]}
    assert "Inbox.md" in paths
