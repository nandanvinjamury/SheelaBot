from pathlib import Path

import pytest

from sheela.persona import PersonaLoader


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    agent = tmp_path / "Agent"
    agent.mkdir()
    (agent / "PERSONA.md").write_text("PERSONA content", encoding="utf-8")
    (agent / "RULES.md").write_text("RULES content", encoding="utf-8")
    (agent / "MY_SHEELA.md").write_text("MY_SHEELA content", encoding="utf-8")
    return tmp_path


async def test_loads_all_three_files(vault: Path):
    loader = PersonaLoader(vault)
    prompt = await loader.get_system_prompt()
    assert "PERSONA content" in prompt
    assert "RULES content" in prompt
    assert "MY_SHEELA content" in prompt
    assert prompt.count("---") >= 2  # separator between sections


async def test_caches_within_ttl(vault: Path):
    loader = PersonaLoader(vault)
    prompt1 = await loader.get_system_prompt()
    (vault / "Agent" / "PERSONA.md").write_text("CHANGED", encoding="utf-8")
    prompt2 = await loader.get_system_prompt()
    assert prompt1 == prompt2  # cached, change not visible yet


async def test_reloads_after_ttl_when_mtime_changed(vault: Path):
    loader = PersonaLoader(vault)
    await loader.get_system_prompt()
    persona_file = vault / "Agent" / "PERSONA.md"
    # Bump mtime forward to ensure detection regardless of FS resolution
    import os, time
    new_time = time.time() + 10
    os.utime(persona_file, (new_time, new_time))
    persona_file.write_text("CHANGED", encoding="utf-8")
    os.utime(persona_file, (new_time, new_time))
    loader._next_check_at = 0.0
    prompt = await loader.get_system_prompt()
    assert "CHANGED" in prompt


async def test_no_reload_after_ttl_if_mtimes_unchanged(vault: Path):
    loader = PersonaLoader(vault)
    prompt1 = await loader.get_system_prompt()
    loader._next_check_at = 0.0
    prompt2 = await loader.get_system_prompt()
    assert prompt1 == prompt2


async def test_missing_file_raises(tmp_path: Path):
    loader = PersonaLoader(tmp_path)
    with pytest.raises(FileNotFoundError):
        await loader.get_system_prompt()
