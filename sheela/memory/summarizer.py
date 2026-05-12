"""ConversationSummarizer — turns archived messages + prior summary into a
single-paragraph rolling summary, in Sheela's first-person voice.

The actual LLM call goes through `LLMProvider.summarize`, which uses
Flash-Lite under the hood. The summarizer here is concerned with formatting
the input and providing the POV instruction.
"""
from __future__ import annotations

from typing import Any, Protocol


POV_INSTRUCTION = (
    "You are Sheela, recalling earlier conversation in this channel from your "
    "own first-person point of view. Produce ONE PARAGRAPH preserving facts "
    "the user shared, decisions made, emotional context, and patterns worth "
    "remembering. Write in your normal voice — dry, observational, brief. No "
    "bullet points. No preamble. No \"user said\" / \"I said\" framing — just "
    "convey what's relevant for picking the conversation back up."
)


class SummarizingLLM(Protocol):
    async def summarize(self, text: str, max_tokens: int) -> str: ...


class ConversationSummarizer:
    DEFAULT_MAX_TOKENS = 400

    def __init__(
        self, llm: SummarizingLLM, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    async def summarize(
        self,
        messages: list[dict[str, Any]],
        previous_summary: str | None,
    ) -> str:
        text = self._format(messages, previous_summary)
        return (await self.llm.summarize(text, max_tokens=self.max_tokens)).strip()

    @staticmethod
    def _format(
        messages: list[dict[str, Any]], previous_summary: str | None
    ) -> str:
        sections: list[str] = [POV_INSTRUCTION]
        if previous_summary:
            sections.append(
                "PREVIOUS SUMMARY OF EARLIER CONVERSATION:\n"
                + previous_summary.strip()
            )
        sections.append("NEW MESSAGES TO FOLD IN:")
        for m in messages:
            who = "Sheela" if m["role"] == "assistant" else "User"
            sections.append(f"{who}: {m['content']}")
        sections.append("Produce the updated summary paragraph below:")
        return "\n\n".join(sections)
