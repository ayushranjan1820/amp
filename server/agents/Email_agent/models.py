from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class EmailAgentRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class EmailAgentResponse(BaseModel):
    success: bool
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    email_sent: bool = False
    email_id: Optional[str] = None
