"""AI service for Web Test Agent — delegates to shared BaseAIService.

Reads credentials from the Settings object (which pulls from environment
variables injected per-request by ``user_config.apply_user_config``).
"""
import os
from pathlib import Path
from typing import Optional

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService
from .core.config import Settings, get_settings


class AIService(BaseAIService):
    """Web Test Agent AI service backed by agent config settings."""

    def __init__(self, settings: Optional[Settings] = None):
        cfg = settings or get_settings()
        super().__init__(
            default_temperature=cfg.web_test_default_temperature,
            default_max_tokens=cfg.web_test_max_tokens,
            timeout=cfg.web_test_timeout,
        )


ai_service = AIService()
