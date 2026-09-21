"""Configuration management using Pydantic Settings.

Enterprise improvements:
- Removed @lru_cache — settings are now created fresh each call so that
  per-request credential injection via os.environ works correctly for
  multi-tenant deployments.
- Added OAuth / PAT fields for flexible auth schemes.
- Added Redis URL for session persistence.
- Added configurable LLM model name.
- Added RBAC / audit toggle.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings sourced from environment variables.

    The API layer injects per-request credentials into ``os.environ`` before
    constructing a ``Settings`` instance so that each request can target a
    different JIRA tenant if required.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- PWC GenAI --------------------------------------------------- #
    pwc_genai_endpoint_url: str = ""
    pwc_genai_api_key: str = ""
    pwc_genai_bearer_token: str = ""

    # ---- LLM model (overridable per-request) ------------------------- #
    llm_model_name: str = ""

    # ---- JIRA — Basic Auth ------------------------------------------- #
    jira_email: str = ""
    jira_api_token: str = ""
    jira_instance_url: str = ""
    jira_project_key: str = ""

    # ---- JIRA — OAuth 2.0 (optional) -------------------------------- #
    jira_oauth_access_token: str = ""

    # ---- JIRA — Personal Access Token (optional) --------------------- #
    jira_pat: str = ""

    # ---- Session store ----------------------------------------------- #
    redis_url: Optional[str] = None

    # ---- RBAC / audit ------------------------------------------------ #
    rbac_enabled: bool = False

    # ---- BRD Mode ---------------------------------------------------- #
    brd_mode: bool = False

    # ---- Server ------------------------------------------------------ #
    port: int = 5000
    node_env: str = "development"


def get_settings() -> Settings:
    """Create a fresh Settings instance from current environment.

    Unlike the previous ``@lru_cache`` version, this reads os.environ every
    time so per-request credential injection works correctly.  The object is
    cheap to construct (Pydantic v2 does no I/O when env_file=None).
    """
    return Settings()
