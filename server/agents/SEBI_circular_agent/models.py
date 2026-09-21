from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class SEBIAgentRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class SEBINotification(BaseModel):
    title: str
    date: str
    link: str
    department: Optional[str] = None
    content: Optional[str] = None


class SEBIAgentResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str
    timestamp: str = ""
    notifications: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None
    thinking_steps: Optional[List[Dict[str, Any]]] = None
