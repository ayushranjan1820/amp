"""
LLM Service Module for Router Agent
Handles all LLM API interactions with auto-continuation support.
"""

import os
from pathlib import Path
from agents.llm_continuation import async_call_with_continuation
from agents.local_llm import uses_pwc_genai_credentials

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


class LLMService:
    """Service for calling LLM APIs with auto-continuation."""
    
    def __init__(self):
        self.api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")
        self.endpoint_url = os.getenv("PWC_GENAI_ENDPOINT_URL", "https://genai-sharedservice-americas.pwc.com/completions")
    
    async def call_llm(self, prompt: str, temperature: float = 0.2, max_tokens: int = 1024) -> str:
        """Call LLM with auto-continuation."""
        try:
            from langfuse_tracer import set_current_agent
            set_current_agent("Router Agent")
        except Exception:
            pass
        # Re-read credentials from env at call time so apply_user_config injection works
        # even when this service was instantiated before the per-request env was populated.
        api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or self.api_key
        bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN") or self.bearer_token
        endpoint_url = os.getenv("PWC_GENAI_ENDPOINT_URL") or self.endpoint_url
        if not api_key and uses_pwc_genai_credentials():
            raise ValueError("LLM service not configured. Set PWC_GENAI_API_KEY.")

        headers = {
            "accept": "application/json",
            "API-Key": api_key,
            "Content-Type": "application/json"
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        payload = {
            "model": os.getenv("PREMIUM_MODEL", ""),
            "prompt": prompt,
            "temperature": temperature,
            "top_p": 1,
            "max_tokens": max_tokens,
        }

        return await async_call_with_continuation(
            endpoint_url=endpoint_url,
            headers=headers,
            request_body=payload,
            original_prompt=prompt,
            timeout=60.0,
        )
