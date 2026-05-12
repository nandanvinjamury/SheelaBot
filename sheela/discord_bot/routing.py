"""Channel routing.

Loads the per-channel YAML config and produces a context block appended to
the system prompt for each Discord message. Vault files listed under
`vault_paths_to_load` are read in parallel through VaultReader (so the
lazy git-pull check happens before content is read). Missing files are
skipped silently. The `vault_paths_writable_without_confirm` allowlist is
parsed and exposed via `get_writable_paths` for Step 5 to consume.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
import yaml
from pydantic import BaseModel, Field

from sheela.tools.vault_read import VaultReader

log = structlog.get_logger(__name__)


class ChannelConfig(BaseModel):
    description: str
    vault_paths_to_load: list[str] = Field(default_factory=list)
    vault_paths_writable_without_confirm: list[str] = Field(default_factory=list)
    tone_hint: str | None = None


class RoutingConfig(BaseModel):
    channels: dict[str, ChannelConfig]


class ChannelRouter:
    SECTION_SEPARATOR = "\n\n"

    def __init__(
        self, config_path: Path, vault_reader: VaultReader, tz: str
    ) -> None:
        self.config_path = config_path
        self.reader = vault_reader
        self.tz = tz
        self.config = self._load_config(config_path)

    @staticmethod
    def _load_config(path: Path) -> RoutingConfig:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return RoutingConfig.model_validate(raw)

    @staticmethod
    def _normalize(channel_name: str) -> str:
        return channel_name.lstrip("#")

    def _today(self) -> str:
        return datetime.now(ZoneInfo(self.tz)).strftime("%Y-%m-%d")

    def _resolve_path(self, template: str) -> str:
        return template.format(date=self._today())

    def get_writable_paths(self, channel_name: str) -> list[str]:
        cfg = self.config.channels.get(self._normalize(channel_name))
        if cfg is None:
            return []
        return [
            self._resolve_path(p)
            for p in cfg.vault_paths_writable_without_confirm
        ]

    async def get_channel_context(self, channel_name: str) -> str | None:
        normalized = self._normalize(channel_name)
        cfg = self.config.channels.get(normalized)
        if cfg is None:
            log.debug("unknown channel; no context", channel=channel_name)
            return None

        sections: list[str] = [
            f"# Channel context: #{normalized}",
            cfg.description.strip(),
        ]
        if cfg.tone_hint:
            sections.append(f"## Tone hint\n\n{cfg.tone_hint.strip()}")

        if cfg.vault_paths_writable_without_confirm:
            writable = [
                self._resolve_path(p)
                for p in cfg.vault_paths_writable_without_confirm
            ]
            sections.append(
                "## Writable without asking\n\n"
                + "\n".join(f"- {p}" for p in writable)
            )

        loaded = await self._load_vault_files(cfg.vault_paths_to_load)
        for path, content in loaded:
            sections.append(f"## Vault: {path}\n\n{content.strip()}")

        return self.SECTION_SEPARATOR.join(sections)

    async def _load_vault_files(
        self, path_templates: list[str]
    ) -> list[tuple[str, str]]:
        if not path_templates:
            return []
        resolved = [self._resolve_path(p) for p in path_templates]
        contents = await self.reader.read_many(resolved)
        return [(p, contents[p]) for p in resolved if p in contents]
