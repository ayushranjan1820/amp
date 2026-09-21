"""AI service for Document Formatter Agent — delegates to shared BaseAIService."""
import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService


class DocumentFormatterAIService(BaseAIService):
    def __init__(self):
        super().__init__(
            default_temperature=0.2,
            default_max_tokens=8192,
            timeout=120,
            transport="async",
        )

    async def call_genai(self, prompt: str, temperature: float = 0.2, max_tokens: int = 8192) -> str:
        try:
            return await self.call_genai_async(prompt, temperature, max_tokens)
        except Exception as e:
            return f"Error calling AI service: {str(e)}"


formatter_ai_service = DocumentFormatterAIService()
