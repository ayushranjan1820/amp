"""Request/response models for the Zoho workflow agent endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ZohoWorkflowRequest(BaseModel):
    """Shared request body for all three Zoho workflow endpoints."""

    query: str
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class ZohoWorkflowResponse(BaseModel):
    success: bool
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    dry_run: bool = True
    workflow: str = ""
    session_id: Optional[str] = None
    timestamp: Optional[str] = None


__all__ = ["ZohoWorkflowRequest", "ZohoWorkflowResponse"]
