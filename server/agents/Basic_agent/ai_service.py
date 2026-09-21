"""AI service for Basic Agent — delegates to shared BaseAIService."""
import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService


class AIService(BaseAIService):
    """Backward-compatible wrapper preserving the original interface."""

    def __init__(self):
        super().__init__(default_temperature=0.7, default_max_tokens=4096, timeout=120)


ai_service = AIService()
