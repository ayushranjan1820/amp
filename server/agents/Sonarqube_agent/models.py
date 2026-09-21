from typing import Dict, Optional, List, Any
from pydantic import BaseModel


class SonarqubeRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    github_token: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class SonarqubeResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    timestamp: str
    repo_url: Optional[str] = None
    requires_token: bool = False
