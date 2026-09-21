"""AI service for GenAI interactions.

Enterprise improvements:
- Model name sourced from Settings (configurable per-tenant, not hardcoded)
- No module-level singleton — instantiate per-request or inject
"""
from __future__ import annotations

from typing import Optional

from ..core.config import Settings, get_settings
from ..core.logging import log_info, log_error, log_debug
from agents.llm_continuation import async_call_with_continuation
from agents.local_llm import get_llm_provider, uses_pwc_genai_credentials


class AIService:
    """Service for AI / GenAI operations.

    Accepts optional ``Settings`` for multi-tenant model overrides.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings: Settings = settings or get_settings()

    async def call_genai(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> str:
        """Call the configured LLM with auto-continuation.

        Model name comes from ``Settings.llm_model_name`` (default:
        ````), so enterprise users can
        override it per-request without a code change.
        """
        try:
            from langfuse_tracer import set_current_agent
            set_current_agent("JIRA Agent")
        except Exception:
            pass

        if (
            not all([
                self.settings.pwc_genai_api_key,
                self.settings.pwc_genai_bearer_token,
                self.settings.pwc_genai_endpoint_url,
            ])
            and uses_pwc_genai_credentials()
        ):
            raise ValueError(
                "PwC GenAI credentials not configured. Please provide "
                "PWC_GENAI_API_KEY, PWC_GENAI_BEARER_TOKEN, and PWC_GENAI_ENDPOINT_URL."
            )

        prov = get_llm_provider()
        _prov_label = {
            "pwc_genai": "PwC GenAI",
            "local_llm": "local LLM",
            "ollama_cloud": "Ollama Cloud",
        }.get(prov, prov)

        # Model from settings — configurable per tenant
        model_name = self.settings.llm_model_name

        request_body = {
            "model": model_name,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 1,
            "presence_penalty": 0,
            "stream": False,
            "stream_options": None,
            "seed": 25,
            "stop": None,
        }

        headers = {
            "accept": "application/json",
            "API-Key": self.settings.pwc_genai_api_key,
            "Authorization": f"Bearer {self.settings.pwc_genai_bearer_token}",
            "Content-Type": "application/json",
        }

        log_info(f"Calling {_prov_label} (prompt length: {len(prompt)} chars)", "ai")
        log_debug(f"AI parameters: temp={temperature}, max_tokens={max_tokens}, model={model_name}", "ai")

        result = await async_call_with_continuation(
            endpoint_url=self.settings.pwc_genai_endpoint_url,
            headers=headers,
            request_body=request_body,
            original_prompt=prompt,
            timeout=120.0,
        )

        log_info(f"{_prov_label} response received successfully", "ai")
        return result

    def build_prompt(self, system_message: str, user_message: str) -> str:
        """Build a formatted prompt."""
        return f"System: {system_message}\n\nUser: {user_message}"
