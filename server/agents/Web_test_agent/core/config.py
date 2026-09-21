"""Configuration management for Web Test Agent using Pydantic Settings.

Reads credentials and tuning knobs from environment variables (injected
per-request by ``user_config.apply_user_config``).  No ``@lru_cache`` so that
multi-tenant credential injection works correctly.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Web Test Agent settings sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- PwC GenAI ----------------------------------------------------- #
    pwc_genai_endpoint_url: str = ""
    pwc_genai_api_key: str = ""
    pwc_genai_bearer_token: str = ""

    # ---- LLM model (overridable per-request) --------------------------- #
    llm_model_name: str = ""
    llm_provider: str = "pwc_genai"

    # ---- Ollama Cloud -------------------------------------------------- #
    ollama_cloud_api_token: str = ""
    ollama_cloud_model: str = "gemma3:27b-cloud"

    # ---- Agent-specific tuning ----------------------------------------- #
    web_test_default_temperature: float = 0.3
    web_test_max_tokens: int = 8192
    web_test_timeout: int = 180
    web_test_max_features: int = 50
    web_test_max_history_turns: int = 6

    # ---- Server -------------------------------------------------------- #
    port: int = 5000
    node_env: str = "development"


def get_settings() -> Settings:
    """Create a fresh Settings instance from current environment.

    Reads ``os.environ`` every time so per-request credential injection
    works correctly.
    """
    return Settings()
