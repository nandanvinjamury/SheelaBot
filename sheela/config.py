"""Configuration loaded from environment variables via pydantic-settings."""
from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: SecretStr
    llm_model: str = "claude-sonnet-4-5"
    llm_max_tokens: int = 4096

    discord_bot_token: SecretStr
    discord_guild_id: int

    vault_repo_path: Path = Path("/home/sheela/vault")

    sheela_data_dir: Path = Path("/home/sheela/data")
    sheela_log_dir: Path = Path("/home/sheela/logs")
    sheela_db_path: Path = Path("/home/sheela/data/sheela.db")
    sheela_tz: str = "America/New_York"

    sheela_debug: bool = False
