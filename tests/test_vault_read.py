from pathlib import Path

import pytest

from sheela.tools.vault_read import VaultReader


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.md").write_text("bravo", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("charlie", encoding="utf-8")
    return tmp_path


async def test_read_returns_content(vault: Path):
    r = VaultReader(vault)
    assert await r.read("a.md") == "alpha"
    assert await r.read("sub/c.md") == "charlie"


async def test_read_many_parallel(vault: Path):
    r = VaultReader(vault)
    result = await r.read_many(["a.md", "b.md", "sub/c.md"])
    assert result == {"a.md": "alpha", "b.md": "bravo", "sub/c.md": "charlie"}


async def test_read_many_skips_missing_files(vault: Path):
    r = VaultReader(vault)
    result = await r.read_many(["a.md", "nope.md", "b.md"])
    assert "nope.md" not in result
    assert result["a.md"] == "alpha"
    assert result["b.md"] == "bravo"


async def test_read_missing_file_raises(vault: Path):
    r = VaultReader(vault)
    with pytest.raises(FileNotFoundError):
        await r.read("nope.md")


async def test_ensure_fresh_on_non_git_directory_is_silent(vault: Path):
    # tmp_path is not a git repo; ensure_fresh should swallow it
    r = VaultReader(vault)
    await r.ensure_fresh()
    # And subsequent read still works
    assert await r.read("a.md") == "alpha"


async def test_ttl_prevents_repeated_checks(vault: Path):
    r = VaultReader(vault)
    await r.ensure_fresh()
    first_check_at = r._last_check_at
    # Immediately again — should be a no-op (timestamp unchanged within TTL)
    await r.ensure_fresh()
    assert r._last_check_at == first_check_at
