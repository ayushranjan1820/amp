from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class GlobalChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    github_token: Optional[str] = None
    file_content: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    target_agent: Optional[str] = None
    skip_save: bool = False
    user_config: Optional[Dict[str, str]] = None


class RoutedAgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    confidence: float
    reasoning: str


class GlobalChatResponse(BaseModel):
    success: bool
    query: str
    response: str
    routed_to: RoutedAgentInfo
    thinking_steps: List[Dict[str, Any]] = []
    bpmn_xml: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: str
    task_id: Optional[str] = None
