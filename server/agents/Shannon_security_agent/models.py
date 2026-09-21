from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ShannonSecurityRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None


class ShannonSecurityResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    timestamp: str
    session_id: Optional[str] = None
