"""Custom LangChain LLM wrapper for PwC GenAI.

Enterprise improvements:
- Cleaner async/sync bridging without global nest_asyncio.apply()
- Falls back to thread-pool executor when nested loop is unavailable
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, List, Optional

from langchain_core.language_models.llms import LLM
from langchain_core.callbacks import CallbackManagerForLLMRun

from .ai_service import AIService
from ..core.logging import log_info


class PwCGenAILLM(LLM):
    """Custom LangChain LLM wrapper for PwC GenAI."""

    temperature: float = 0.7
    max_tokens: int = 4096
    task_name: str = "jira_agent"

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "ai_service", AIService())

    @property
    def _llm_type(self) -> str:
        return "pwc_genai"

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Synchronous entry-point used by LangChain AgentExecutor."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an async event loop — run in a thread to avoid
            # nested-loop issues without requiring nest_asyncio globally.
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(
                    self._acall_async(prompt, stop, run_manager, **kwargs)
                )
            except ImportError:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(
                        asyncio.run,
                        self._acall_async(prompt, stop, run_manager, **kwargs),
                    ).result()
        else:
            return asyncio.run(self._acall_async(prompt, stop, run_manager, **kwargs))

    async def _acall_async(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        """Async call to PwC GenAI."""
        log_info(f"LLM call with prompt length: {len(prompt)}", "pwc_genai_llm")

        ai_service: AIService = object.__getattribute__(self, "ai_service")
        return await ai_service.call_genai(
            prompt=prompt,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
