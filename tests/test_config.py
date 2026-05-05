import pytest
from pydantic import ValidationError

from sheela.config import Settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")


def test_settings_loads_from_env(env: None):
    s = Settings(_env_file=None)
    assert s.anthropic_api_key.get_secret_value() == "test-key"
    assert s.discord_bot_token.get_secret_value() == "test-token"
    assert s.discord_guild_id == 123456789


def test_settings_defaults(env: None):
    s = Settings(_env_file=None)
    assert s.llm_model == "claude-sonnet-4-5"
    assert s.llm_max_tokens == 4096
    assert s.sheela_tz == "America/New_York"
    assert s.sheela_debug is False


def test_settings_missing_required_fails(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
