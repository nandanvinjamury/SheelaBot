from sheela.memory.summarizer import POV_INSTRUCTION, ConversationSummarizer


class FakeLLM:
    def __init__(self, response: str = "fake summary"):
        self.response = response
        self.last_text: str | None = None
        self.last_max_tokens: int | None = None

    async def summarize(self, text: str, max_tokens: int) -> str:
        self.last_text = text
        self.last_max_tokens = max_tokens
        return self.response


async def test_summarize_passes_through_llm_response():
    llm = FakeLLM(response="rolled up paragraph")
    s = ConversationSummarizer(llm)
    result = await s.summarize(
        [{"role": "user", "content": "hi"}], previous_summary=None
    )
    assert result == "rolled up paragraph"


async def test_summarize_strips_whitespace():
    llm = FakeLLM(response="  with edges  \n")
    s = ConversationSummarizer(llm)
    result = await s.summarize(
        [{"role": "user", "content": "hi"}], previous_summary=None
    )
    assert result == "with edges"


async def test_format_includes_pov_instruction():
    llm = FakeLLM()
    s = ConversationSummarizer(llm)
    await s.summarize(
        [{"role": "user", "content": "x"}], previous_summary=None
    )
    assert POV_INSTRUCTION in (llm.last_text or "")


async def test_format_includes_previous_summary():
    llm = FakeLLM()
    s = ConversationSummarizer(llm)
    await s.summarize(
        [{"role": "user", "content": "new"}],
        previous_summary="old stuff",
    )
    assert "old stuff" in (llm.last_text or "")
    assert "new" in (llm.last_text or "")


async def test_format_labels_roles():
    llm = FakeLLM()
    s = ConversationSummarizer(llm)
    await s.summarize(
        [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
        ],
        previous_summary=None,
    )
    text = llm.last_text or ""
    assert "User: Q1" in text
    assert "Sheela: A1" in text


async def test_max_tokens_passed_through():
    llm = FakeLLM()
    s = ConversationSummarizer(llm, max_tokens=123)
    await s.summarize([{"role": "user", "content": "x"}], previous_summary=None)
    assert llm.last_max_tokens == 123
