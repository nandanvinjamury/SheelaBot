"""Model routing within the Gemini provider.

Picks a model name based on the task type and an optional context-token
estimate, plus the rate-limit fallback chain.
"""
from __future__ import annotations

from dataclasses import dataclass

from sheela.llm.base import TaskType


FLASH = "gemini-2.5-flash"
FLASH_LITE = "gemini-2.5-flash-lite"
PRO = "gemini-2.5-pro"


@dataclass(frozen=True)
class ModelRouter:
    flash: str = FLASH
    flash_lite: str = FLASH_LITE
    pro: str = PRO

    def route(self, task_type: TaskType, context_tokens: int = 0) -> str:
        if task_type in ("summarize", "classify", "extract"):
            return self.flash_lite
        if task_type == "complex_reasoning" or context_tokens > 100_000:
            return self.pro
        return self.flash

    def fallbacks_for(self, model: str) -> list[str]:
        """Rate-limit fallback chain for `model`. Empty list = no fallback."""
        if model == self.flash:
            return [self.pro]
        if model == self.flash_lite:
            return [self.flash]
        return []
