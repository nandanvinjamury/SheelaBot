"""Smoke test for the LLM provider abstraction.

Step 1 only verifies the contract: every concrete provider satisfies the
Protocol structurally and the stub methods raise NotImplementedError.
Real behavior arrives in Step 2 (Gemini) and beyond.
"""
import pytest

from sheela.llm.anthropic import AnthropicProvider
from sheela.llm.base import LLMProvider, Message, ResponseChunk, Tool
from sheela.llm.gemini import GeminiProvider
from sheela.llm.ollama_local import OllamaLocalProvider


PROVIDERS = [GeminiProvider, AnthropicProvider, OllamaLocalProvider]


@pytest.mark.parametrize("provider_cls", PROVIDERS)
def test_provider_satisfies_protocol(provider_cls):
    provider = provider_cls()
    assert isinstance(provider, LLMProvider)


@pytest.mark.parametrize("provider_cls", PROVIDERS)
async def test_respond_raises_not_implemented(provider_cls):
    provider = provider_cls()
    with pytest.raises(NotImplementedError):
        await provider.respond("system", [Message(role="user", content="hi")])


@pytest.mark.parametrize("provider_cls", PROVIDERS)
async def test_embed_raises_not_implemented(provider_cls):
    provider = provider_cls()
    with pytest.raises(NotImplementedError):
        await provider.embed("text")


@pytest.mark.parametrize("provider_cls", PROVIDERS)
async def test_summarize_raises_not_implemented(provider_cls):
    provider = provider_cls()
    with pytest.raises(NotImplementedError):
        await provider.summarize("text", max_tokens=100)


def test_dataclasses_are_frozen():
    msg = Message(role="user", content="hi")
    chunk = ResponseChunk(text="hi")
    tool = Tool(name="t", description="d", parameters={})
    for obj in (msg, chunk, tool):
        with pytest.raises(Exception):
            obj.content = "mutated"  # type: ignore[misc]
