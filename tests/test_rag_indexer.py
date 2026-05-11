from pathlib import Path

import pytest

from sheela.rag.indexer import VaultIndexBuilder
from sheela.rag.store import RAGStore
from sheela.tools.vault_read import VaultReader


class FakeEmbedder:
    """Deterministic stand-in for GeminiEmbedder in tests."""

    DIM = 768

    async def embed_one(self, text: str) -> list[float]:
        # Use a simple hash-based vector — different text → different vector
        seed = hash(text) & 0xFFFFFFFF
        return [
            ((seed >> (i % 32)) & 1) * 1.0 for i in range(self.DIM)
        ]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_one(t) for t in texts]


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # Indexable folders with NN-prefix
    people = tmp_path / "03 People" / "Family"
    people.mkdir(parents=True)
    (people / "Parent.md").write_text(
        "---\nname: Parent\n---\n\n## Background\n\nFrom Springfield.\n\n## Recent\n\nCalled last week.",
        encoding="utf-8",
    )
    recipes = tmp_path / "06 Recipes" / "Dinner"
    recipes.mkdir(parents=True)
    (recipes / "Pasta.md").write_text(
        "---\nname: Pasta\n---\n\n# Pasta\n\n## Notes\n\nBoil 10 minutes.",
        encoding="utf-8",
    )
    # Non-indexable folder
    daily = tmp_path / "01 Daily"
    daily.mkdir(parents=True)
    (daily / "2026-05-11.md").write_text("Some daily note.", encoding="utf-8")
    # Misc top-level file
    (tmp_path / "Inbox.md").write_text("inbox", encoding="utf-8")
    return tmp_path


@pytest.fixture
async def store(tmp_path: Path):
    s = RAGStore(tmp_path / "rag.db")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def reader(vault: Path) -> VaultReader:
    return VaultReader(vault)


async def test_build_full_indexes_only_indexable_folders(reader, store):
    builder = VaultIndexBuilder(reader, store, FakeEmbedder())
    result = await builder.build()
    assert result["mode"] == "full"
    # 03 People/Family/Parent.md (3 chunks: intro? Background, Recent)
    # 06 Recipes/Dinner/Pasta.md (Notes section; intro might exist)
    # = at least 4 chunks across both files
    assert result["indexed"] == 2  # two files
    count = await store.count_chunks()
    assert count >= 4


async def test_indexable_filter_skips_daily_and_misc(reader, store):
    builder = VaultIndexBuilder(reader, store, FakeEmbedder())
    await builder.build()
    # All chunk file_paths should be in 03 People or 06 Recipes
    async with store.conn.execute(
        "SELECT DISTINCT file_path FROM rag_chunks"
    ) as cursor:
        paths = [row[0] async for row in cursor]
    for p in paths:
        assert p.startswith("03 People/") or p.startswith("06 Recipes/")
    assert all("01 Daily" not in p for p in paths)
    assert "Inbox.md" not in paths


async def test_rebuild_replaces_chunks_when_file_changes(
    reader, store, vault: Path
):
    builder = VaultIndexBuilder(reader, store, FakeEmbedder())
    await builder.build()
    initial_count = await store.count_chunks()
    # Modify Parent.md
    parent = vault / "03 People" / "Family" / "Parent.md"
    parent.write_text(
        "---\nname: Parent\n---\n## Updated\n\nnew content only", encoding="utf-8"
    )
    await builder.build(full=True)  # force rescan; no git involved
    new_count = await store.count_chunks()
    # Total chunks may differ; just make sure no orphans from old version
    async with store.conn.execute(
        "SELECT content FROM rag_chunks WHERE file_path = '03 People/Family/Parent.md'"
    ) as cursor:
        contents = [row[0] async for row in cursor]
    assert all("Springfield" not in c for c in contents)
    assert any("new content only" in c for c in contents)


async def test_sha_is_stored_after_build(reader, store):
    builder = VaultIndexBuilder(reader, store, FakeEmbedder())
    result = await builder.build()
    # tmp_path is not a git repo, so sha should be None and no SHA stored
    assert result["sha"] is None
    sha = await store.get_meta("last_indexed_sha")
    assert sha is None
    # But last_indexed_at should be set
    at = await store.get_meta("last_indexed_at")
    assert at is not None
