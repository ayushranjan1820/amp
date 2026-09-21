"""Zoho Projects tasks over the direct REST transport."""
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from ..config import ZohoSettings
from ..zoho_client import ZohoAPIError, ZohoClient


def project_destination(settings: ZohoSettings) -> Tuple[str, str]:
    portal_id = settings.projects_portal_id
    project_id = settings.projects_project_id
    if not portal_id.isascii() or not portal_id.isdigit() or not project_id.isascii() or not project_id.isdigit():
        raise ZohoAPIError("Set ZOHO_PROJECTS_PORTAL_ID and ZOHO_PROJECTS_PROJECT_ID to numeric IDs from Zoho Projects.")
    return portal_id, project_id


class ZohoProjectsService:
    def __init__(self, client: ZohoClient):
        self.client = client

    async def create_task(
        self, *, subject: str, due_date: Optional[datetime] = None,
        description: str = "", priority: str = "High",
    ) -> Dict[str, Any]:
        portal_id, project_id = project_destination(self.client.settings)
        if not subject:
            raise ZohoAPIError("A task subject is required.")
        data = {"name": subject, "description": description, "priority": priority.title()}
        if due_date:
            data["start_date"] = min(datetime.now(due_date.tzinfo).date(), due_date.date()).strftime("%m-%d-%Y")
            data["end_date"] = due_date.strftime("%m-%d-%Y")
        payload = await self.client.post(
            f"{self.client.settings.projects_base}/portal/{portal_id}/projects/{project_id}/tasks/",
            data=data,
        )
        tasks = payload.get("tasks") or []
        if not tasks or not tasks[0].get("id"):
            raise ZohoAPIError("Zoho Projects did not return a created task ID.")
        return {
            "created": True, "task_id": str(tasks[0]["id"]), "subject": subject,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else "", "priority": priority,
        }