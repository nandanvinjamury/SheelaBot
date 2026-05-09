"""LLM provider package.

Public factory `make_provider(settings, router)` returns the configured
backend per `settings.llm_provider`.
"""
from __future__ import annotations

from sheela.config import Settings
from sheela.llm.anthropic import AnthropicProvider
from sheela.llm.base import LLMProvider
from sheela.llm.gemini import GeminiProvider
from sheela.llm.ollama_local import OllamaLocalProvider
from sheela.llm.router import ModelRouter


def make_provider(settings: Settings, router: ModelRouter) -> LLMProvider:
    match settings.llm_provider:
        case "gemini":
            return GeminiProvider(settings, router=router)
        case "anthropic":
            return AnthropicProvider()
        case "ollama_local":
            return OllamaLocalProvider()


__all__ = [
    "AnthropicProvider",
    "GeminiProvider",
    "LLMProvider",
    "ModelRouter",
    "OllamaLocalProvider",
    "make_provider",
]
