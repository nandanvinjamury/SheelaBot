from pathlib import Path

import pytest

from sheela.tools.vault_read import VaultReader
from sheela.tools.vault_tools import VaultTools
from sheela.vault.index import VaultIndexer


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    people = tmp_path / "People" / "Family"
    people.mkdir(parents=True)
    (people / "Parent.md").write_text(
        "---\nname: Parent\nrelationship: family\n---\n# Parent\nbody", encoding="utf-8"
    )
    recipes = tmp_path / "Recipes" / "Dinner"
    recipes.mkdir(parents=True)
    (recipes / "Pasta.md").write_text(
        "---\nname: Pasta\nrating: 9\n---\n# Pasta\nrecipe", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def tools(vault: Path, tmp_path: Path) -> VaultTools:
    reader = VaultReader(vault)
    indexer = VaultIndexer(reader, tmp_path / "vault_index.json")
    return VaultTools(reader, indexer)


async def test_vault_read_returns_content(tools: VaultTools):
    content = await tools.vault_read("People/Family/Parent.md")
    assert "Parent" in content
    assert "relationship" in content


async def test_vault_read_missing_returns_error_message(tools: VaultTools):
    result = await tools.vault_read("nonexistent.md")
    assert "not found" in result.lower()
    assert "nonexistent.md" in result


async def test_vault_list_returns_all_notes(tools: VaultTools):
    notes = await tools.vault_list()
    paths = {n["path"] for n in notes}
    assert "People/Family/Parent.md" in paths
    assert "Recipes/Dinner/Pasta.md" in paths


async def test_vault_list_filters_by_type(tools: VaultTools):
    people = await tools.vault_list(type="person")
    assert all(n["type"] == "person" for n in people)
    assert any(n["path"] == "People/Family/Parent.md" for n in people)
    assert all("Recipes" not in n["path"] for n in people)


async def test_vault_list_unknown_type_returns_empty(tools: VaultTools):
    notes = await tools.vault_list(type="nope")
    assert notes == []


def test_get_callable_tools(tools: VaultTools):
    callables = tools.get_callable_tools()
    # tools fixture has no searcher and no writer → only read + list
    assert len(callables) == 2
    names = {c.__name__ for c in callables}
    assert names == {"vault_read", "vault_list"}


def test_get_callable_tools_includes_writer_tools(vault, tmp_path):
    from unittest.mock import AsyncMock
    from sheela.tools.drafts import DraftScheduler
    from sheela.tools.safety import SafetyChecker
    from sheela.tools.vault_read import VaultReader
    from sheela.tools.vault_write import VaultWriter
    from sheela.vault.index import VaultIndexer

    reader = VaultReader(vault)
    indexer = VaultIndexer(reader, tmp_path / "idx.json")
    safety = SafetyChecker(vault_path=vault, tz="America/New_York")
    scheduler = DraftScheduler(tmp_path / "drafts", debounce_seconds=999)
    writer = VaultWriter(
        vault_path=vault,
        scheduler=scheduler,
        safety=safety,
        git_client=AsyncMock(),
    )
    tools_with_writer = VaultTools(reader, indexer, writer=writer)
    names = {c.__name__ for c in tools_with_writer.get_callable_tools()}
    assert names == {
        "vault_read",
        "vault_list",
        "vault_write",
        "vault_cancel_draft",
        "vault_list_drafts",
    }


async def test_vault_search_returns_helpful_error_when_uninitialized(
    tools: VaultTools,
):
    # tools fixture builds VaultTools without a searcher
    results = await tools.vault_search("anything")
    assert len(results) == 1
    assert "error" in results[0]
    assert "not initialized" in results[0]["error"].lower()


async def test_vault_write_without_writer_returns_denied(tools: VaultTools):
    msg = await tools.vault_write("Inbox.md", "x", "append")
    assert "denied" in msg.lower()


def test_get_callable_tools_includes_search_when_configured(
    vault, tmp_path
):
    from sheela.rag.embeddings import GeminiEmbedder
    from sheela.rag.hybrid import HybridSearcher
    from sheela.rag.store import RAGStore
    from sheela.tools.vault_read import VaultReader
    from sheela.vault.index import VaultIndexer

    # Just construct the wiring; don't connect or call
    reader = VaultReader(vault)
    indexer = VaultIndexer(reader, tmp_path / "idx.json")

    class _FakeEmbedder:
        async def embed_one(self, text):
            return [0.0] * 768

    store = RAGStore(tmp_path / "rag.db")
    searcher = HybridSearcher(store, _FakeEmbedder())  # type: ignore[arg-type]
    tools_with_search = VaultTools(reader, indexer, searcher=searcher)
    names = {c.__name__ for c in tools_with_search.get_callable_tools()}
    assert names == {"vault_read", "vault_list", "vault_search"}
