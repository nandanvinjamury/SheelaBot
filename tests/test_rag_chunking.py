from sheela.rag.chunking import INTRO_TITLE, chunk_by_sections


def test_simple_sections():
    text = "Intro text.\n\n## Section A\n\nA content.\n\n## Section B\n\nB content."
    chunks = chunk_by_sections(text)
    titles = [c["title"] for c in chunks]
    assert INTRO_TITLE in titles
    assert "Section A" in titles
    assert "Section B" in titles
    assert len(chunks) == 3


def test_section_contents_include_their_headers():
    text = "## A\n\na body\n\n## B\n\nb body"
    chunks = chunk_by_sections(text)
    a = next(c for c in chunks if c["title"] == "A")
    assert a["content"].startswith("## A")
    assert "a body" in a["content"]


def test_frontmatter_prepended_to_first_chunk():
    text = "---\nname: Test\nrating: 9\n---\n\nIntro.\n\n## A\n\nA."
    chunks = chunk_by_sections(text)
    assert "name: Test" in chunks[0]["content"]
    assert "rating" in chunks[0]["content"]
    # Subsequent chunks unaffected
    a_chunk = next(c for c in chunks if c["title"] == "A")
    assert "name: Test" not in a_chunk["content"]


def test_no_sections_returns_single_intro():
    text = "Just a single paragraph with no markdown headers."
    chunks = chunk_by_sections(text)
    assert len(chunks) == 1
    assert chunks[0]["title"] == INTRO_TITLE
    assert "Just a single paragraph" in chunks[0]["content"]


def test_frontmatter_only_still_yields_a_chunk():
    text = "---\nname: Empty\n---\n\n"
    chunks = chunk_by_sections(text)
    assert len(chunks) == 1
    assert "name: Empty" in chunks[0]["content"]


def test_long_chunk_truncated():
    body = "## Big\n\n" + "a" * 10_000
    chunks = chunk_by_sections(body, max_chars=500)
    big = next(c for c in chunks if c["title"] == "Big")
    assert len(big["content"]) <= 500 + len("\n[... truncated]")
    assert big["content"].endswith("[... truncated]")
