"""Configuration loaded from environment variables via pydantic-settings."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


LLMProviderName = Literal["gemini", "anthropic", "ollama_local"]
LogMode = Literal["console", "file"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: LLMProviderName = "gemini"
    gemini_api_key: SecretStr
    anthropic_api_key: SecretStr | None = None

    discord_bot_token: SecretStr
    discord_guild_id: int

    vault_repo_path: Path = Path("/home/sheela/vault")

    sheela_data_dir: Path = Path("/home/sheela/data")
    sheela_log_dir: Path = Path("/home/sheela/logs")
    sheela_db_path: Path = Path("/home/sheela/data/sheela.db")
    sheela_tz: str = "America/New_York"

    sheela_log_mode: LogMode = "console"
    sheela_log_level: str = "INFO"
    sheela_debug: bool = False
