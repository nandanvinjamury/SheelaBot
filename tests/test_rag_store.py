from pathlib import Path

import pytest

from sheela.rag.store import ChunkWithEmbedding, RAGStore


def _emb(*first: float) -> list[float]:
    """Construct a 768-dim embedding with the given leading values, zeros after."""
    return list(first) + [0.0] * (768 - len(first))


@pytest.fixture
async def store(tmp_path: Path):
    s = RAGStore(tmp_path / "rag.db")
    await s.connect()
    yield s
    await s.close()


async def test_upsert_and_count(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [
            ChunkWithEmbedding("_intro", "alpha bravo charlie", _emb(1.0, 0.0)),
            ChunkWithEmbedding("Section X", "delta echo foxtrot", _emb(0.0, 1.0)),
        ],
    )
    assert await store.count_chunks() == 2


async def test_vector_search_returns_closer_chunks_first(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [
            ChunkWithEmbedding("near", "x", _emb(1.0, 0.0)),
            ChunkWithEmbedding("far", "y", _emb(0.0, 1.0)),
        ],
    )
    hits = await store.vector_search(_emb(1.0, 0.0), k=2)
    assert len(hits) == 2
    # First hit should be the "near" chunk (lower distance)
    chunks = await store.get_chunks([hits[0][0]])
    assert chunks[0]["section_title"] == "near"


async def test_keyword_search_finds_matching_terms(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [
            ChunkWithEmbedding("a", "lorem ipsum dolor", _emb(1.0)),
            ChunkWithEmbedding("b", "weeknight pasta recipe with tomato sauce", _emb(0.0, 1.0)),
        ],
    )
    hits = await store.keyword_search("pasta", k=5)
    assert len(hits) >= 1
    chunks = await store.get_chunks([hits[0][0]])
    assert "pasta" in chunks[0]["content"].lower()


async def test_keyword_search_ignores_special_chars(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [ChunkWithEmbedding("a", "hello world", _emb(1.0))],
    )
    # FTS-special syntax should not raise — sanitizer strips it
    hits = await store.keyword_search('"hello AND', k=5)
    assert len(hits) >= 1


async def test_upsert_replaces_existing_chunks(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [ChunkWithEmbedding("v1", "first", _emb(1.0))],
    )
    assert await store.count_chunks() == 1
    await store.upsert_file(
        "Notes/A.md",
        [
            ChunkWithEmbedding("v2a", "second a", _emb(0.5)),
            ChunkWithEmbedding("v2b", "second b", _emb(0.3)),
        ],
    )
    assert await store.count_chunks() == 2
    hits = await store.keyword_search("first", k=5)
    assert hits == []  # old chunk gone


async def test_delete_file_removes_all_chunks(store: RAGStore):
    await store.upsert_file(
        "Notes/A.md",
        [
            ChunkWithEmbedding("a", "alpha", _emb(1.0)),
            ChunkWithEmbedding("b", "bravo", _emb(0.0, 1.0)),
        ],
    )
    await store.upsert_file(
        "Notes/B.md",
        [ChunkWithEmbedding("c", "charlie", _emb(0.0, 0.0, 1.0))],
    )
    assert await store.count_chunks() == 3
    await store.delete_file("Notes/A.md")
    assert await store.count_chunks() == 1


async def test_metadata_kv(store: RAGStore):
    assert await store.get_meta("foo") is None
    await store.set_meta("foo", "bar")
    assert await store.get_meta("foo") == "bar"
    await store.set_meta("foo", "baz")
    assert await store.get_meta("foo") == "baz"
