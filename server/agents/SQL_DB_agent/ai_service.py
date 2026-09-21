"""AI service for SQL DB Agent — provider-agnostic, follows agent / env config.

No hardcoded provider or model. The underlying dispatch honours ``LLM_PROVIDER``
(``pwc_genai`` / ``ollama_cloud`` / ``local_llm``) via ``BaseAIService`` →
``llm_continuation``. The ``default_model`` sent in the request body is only
consumed on the PwC GenAI path; the Ollama and local-LLM paths read their own
model ids from ``ON_PREM_CLOUD_MODEL`` / ``LOCAL_LLM_MODEL``.
"""
import os
from pathlib import Path
from typing import Tuple

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService
from agents.local_llm import get_llm_provider, resolved_ollama_cloud_model


def _resolved_default_model() -> str:
    """Pick a sensible default model per the active provider.

    Precedence:
      1. ``SQL_DB_AGENT_MODEL`` — explicit override from agent Config.
      2. Provider-specific env var (``ON_PREM_CLOUD_MODEL`` / ``LOCAL_LLM_MODEL`` / ``PWC_GENAI_MODEL``).
      3. Empty string — let the backend pick its own default.
    """
    explicit = (os.getenv("SQL_DB_AGENT_MODEL") or "").strip()
    if explicit:
        return explicit
    prov = get_llm_provider()
    if prov == "ollama_cloud":
        return resolved_ollama_cloud_model()
    if prov == "local_llm":
        return (os.getenv("LOCAL_LLM_MODEL") or "").strip()
    # pwc_genai — model from env; empty string means backend picks default
    return (os.getenv("PWC_GENAI_MODEL") or "").strip()


class SqlDbAIService(BaseAIService):
    def __init__(self):
        super().__init__(
            default_model=_resolved_default_model(),
            default_temperature=0.1,
            default_max_tokens=8192,
            timeout=180,
            agent_name="SQL DB Agent",
        )
        prov = get_llm_provider()
        print(f"SQL DB Agent AI service — provider={prov}, model={self.default_model}")

    def provider_meta(self) -> Tuple[str, str]:
        """Return (provider, model) — re-resolved each call so hot-reload works."""
        return get_llm_provider(), _resolved_default_model()

    def refresh_model(self) -> None:
        """Re-read model from env; useful after the Config tab writes new values."""
        self.default_model = _resolved_default_model()


ai_service = SqlDbAIService()
