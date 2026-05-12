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

    sheela_routing_path: Path = Path("/home/sheela/.config/sheela-routing.yaml")

    sheela_vault_index_path: Path = Path("/home/sheela/data/vault_index.json")

    sheela_drafts_dir: Path = Path("/home/sheela/data/drafts")

    sheela_data_dir: Path = Path("/home/sheela/data")
    sheela_log_dir: Path = Path("/home/sheela/logs")
    sheela_db_path: Path = Path("/home/sheela/data/sheela.db")
    sheela_tz: str = "America/New_York"

    sheela_log_mode: LogMode = "console"
    sheela_log_level: str = "INFO"
    sheela_debug: bool = False

    # RAG: when true, bootstrap the embedding index on startup if it's empty.
    # Subsequent restarts always do an incremental update if a prior SHA exists.
    rag_index_on_startup: bool = False

    # Health endpoint. Loopback-only; never expose externally.
    sheela_health_host: str = "127.0.0.1"
    sheela_health_port: int = 8765
