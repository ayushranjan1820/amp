"""In-memory chat session store for prototype mode."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class PrototypeChatStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._messages: Dict[str, List[Dict[str, Any]]] = {}
        self._seed()

    def _seed(self) -> None:
        samples = [
            ("Global routing overview", "user", "Summarize open JIRA tickets for sprint 42"),
            (
                "Global routing overview",
                "assistant",
                "I routed your request to the **JIRA Agent**. Here is a summary of sprint 42 tickets.",
            ),
            ("Company research brief", "user", "Research Acme Corp financial performance"),
            (
                "Company research brief",
                "assistant",
                "I've prepared a structured company research report with financial highlights.",
            ),
        ]
        sid = str(uuid.uuid4())
        now = _now()
        self._sessions[sid] = {
            "id": sid,
            "title": "Global routing overview",
            "created_at": now,
            "updated_at": now,
        }
        msgs: List[Dict[str, Any]] = []
        for i, (title, role, content) in enumerate(samples):
            if i == 0:
                continue
            msgs.append(
                {
                    "id": i,
                    "session_id": sid,
                    "role": role,
                    "content": content,
                    "thinking_steps": None,
                    "routed_to": {"agent_id": "jira_agent", "agent_name": "JIRA Agent"} if role == "assistant" and i == 3 else None,
                    "bpmn_xml": None,
                    "metadata": None,
                    "created_at": now,
                }
            )
        self._messages[sid] = msgs

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = sorted(
            self._sessions.values(),
            key=lambda s: s["updated_at"],
            reverse=True,
        )
        return rows[:limit]

    def create_session(self, session_id: str, title: str) -> Dict[str, Any]:
        now = _now()
        row = {"id": session_id, "title": title, "created_at": now, "updated_at": now}
        self._sessions[session_id] = row
        self._messages.setdefault(session_id, [])
        return row

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def get_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return list(self._messages.get(session_id, []))

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        thinking_steps: Optional[List] = None,
        routed_to: Optional[Dict] = None,
        bpmn_xml: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        self._messages.setdefault(session_id, [])
        msg_id = len(self._messages[session_id]) + 1
        now = _now()
        msg = {
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking_steps": thinking_steps,
            "routed_to": routed_to,
            "bpmn_xml": bpmn_xml,
            "metadata": metadata,
            "created_at": now,
        }
        self._messages[session_id].append(msg)
        if session_id in self._sessions:
            self._sessions[session_id]["updated_at"] = now
        return msg

    def update_session_title(self, session_id: str, title: str) -> Optional[Dict[str, Any]]:
        row = self._sessions.get(session_id)
        if not row:
            return None
        row["title"] = title
        row["updated_at"] = _now()
        return row

    def delete_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        self._messages.pop(session_id, None)
        return True

    @staticmethod
    def generate_title_from_query(query: str) -> str:
        q = (query or "").strip()
        if not q:
            return "New Chat"
        return q[:60] + ("…" if len(q) > 60 else "")


chat_store = PrototypeChatStore()
