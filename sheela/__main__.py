"""Entry point. Run with `python -m sheela`."""
from __future__ import annotations

import structlog

from sheela.config import Settings
from sheela.discord_bot.bot import create_bot
from sheela.discord_bot.routing import ChannelRouter
from sheela.llm import make_provider
from sheela.llm.router import ModelRouter
from sheela.llm.usage import UsageLogger
from sheela.persona import PersonaLoader
from sheela.rag.embeddings import GeminiEmbedder
from sheela.rag.hybrid import HybridSearcher
from sheela.rag.indexer import VaultIndexBuilder
from sheela.rag.store import RAGStore
from sheela.tools.vault_read import VaultReader
from sheela.tools.vault_tools import VaultTools
from sheela.utils.logging import configure_logging
from sheela.vault.index import VaultIndexer


def main() -> None:
    settings = Settings()
    configure_logging(settings)
    log = structlog.get_logger("sheela")

    vault_reader = VaultReader(settings.vault_repo_path)
    vault_indexer = VaultIndexer(vault_reader, settings.sheela_vault_index_path)

    rag_store = RAGStore(settings.sheela_db_path)
    embedder = GeminiEmbedder(settings)
    searcher = HybridSearcher(rag_store, embedder)
    rag_builder = VaultIndexBuilder(vault_reader, rag_store, embedder)

    vault_tools = VaultTools(vault_reader, vault_indexer, searcher=searcher)

    persona = PersonaLoader(vault_reader)
    channel_router = ChannelRouter(
        settings.sheela_routing_path,
        vault_reader,
        settings.sheela_tz,
    )
    model_router = ModelRouter()
    usage = UsageLogger(settings.sheela_log_dir)
    llm = make_provider(settings, router=model_router)

    log.info(
        "starting sheela bot",
        guild_id=settings.discord_guild_id,
        llm_provider=settings.llm_provider,
        log_mode=settings.sheela_log_mode,
        vault=str(settings.vault_repo_path),
        routing=str(settings.sheela_routing_path),
        vault_index=str(settings.sheela_vault_index_path),
        db=str(settings.sheela_db_path),
        rag_index_on_startup=settings.rag_index_on_startup,
        channels=sorted(channel_router.config.channels.keys()),
    )

    bot = create_bot(
        settings,
        llm=llm,
        persona=persona,
        channel_router=channel_router,
        vault_tools=vault_tools,
        rag_store=rag_store,
        rag_indexer=rag_builder,
        usage_logger=usage,
    )
    bot.run(settings.discord_bot_token.get_secret_value(), log_handler=None)


if __name__ == "__main__":
    main()
