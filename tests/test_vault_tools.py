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
    assert len(callables) == 2
    names = {c.__name__ for c in callables}
    assert names == {"vault_read", "vault_list"}
