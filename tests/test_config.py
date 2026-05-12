import pytest
from pydantic import ValidationError

from sheela.config import Settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")


def test_settings_loads_from_env(env: None):
    s = Settings(_env_file=None)
    assert s.gemini_api_key.get_secret_value() == "test-gemini-key"
    assert s.discord_bot_token.get_secret_value() == "test-token"
    assert s.discord_guild_id == 123456789


def test_settings_defaults(env: None):
    s = Settings(_env_file=None)
    assert s.llm_provider == "gemini"
    assert s.anthropic_api_key is None
    assert s.sheela_tz == "America/New_York"
    assert s.sheela_log_mode == "console"
    assert s.sheela_log_level == "INFO"
    assert s.sheela_debug is False
    assert str(s.sheela_routing_path).endswith("sheela-routing.yaml")
    assert str(s.sheela_vault_index_path).endswith("vault_index.json")
    assert str(s.sheela_drafts_dir).endswith("drafts")
    assert s.rag_index_on_startup is False


def test_settings_anthropic_optional(monkeypatch: pytest.MonkeyPatch, env: None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    s = Settings(_env_file=None)
    assert s.llm_provider == "anthropic"
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "anthropic-key"


def test_settings_missing_required_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
