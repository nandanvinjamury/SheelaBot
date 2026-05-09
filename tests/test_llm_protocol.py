"""Smoke test for the LLM provider abstraction.

Verifies that stub providers structurally satisfy the Protocol and that
their methods raise NotImplementedError. GeminiProvider is now a real
implementation and is exercised through integration; not unit-tested here.
"""
import pytest

from sheela.llm.anthropic import AnthropicProvider
from sheela.llm.base import LLMProvider, Message, ResponseChunk, Tool
from sheela.llm.ollama_local import OllamaLocalProvider


STUB_PROVIDERS = [AnthropicProvider, OllamaLocalProvider]


@pytest.mark.parametrize("provider_cls", STUB_PROVIDERS)
def test_stub_provider_satisfies_protocol(provider_cls):
    provider = provider_cls()
    assert isinstance(provider, LLMProvider)


@pytest.mark.parametrize("provider_cls", STUB_PROVIDERS)
async def test_respond_raises_not_implemented(provider_cls):
    provider = provider_cls()
    with pytest.raises(NotImplementedError):
        async for _ in provider.respond(
            "system", [Message(role="user", content="hi")]
        ):
            pass


@pytest.mark.parametrize("provider_cls", STUB_PROVIDERS)
async def test_embed_raises_not_implemented(provider_cls):
    provider = provider_cls()
    with pytest.raises(NotImplementedError):
        await provider.embed("text")


@pytest.mark.parametrize("provider_cls", STUB_PROVIDERS)
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
