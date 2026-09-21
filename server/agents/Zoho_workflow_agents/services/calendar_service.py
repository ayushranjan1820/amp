"""Zoho Calendar - list calendars and create events.

The Calendar API takes event fields as a JSON blob in an ``eventdata`` query
parameter, and its timestamps use the compact ``yyyyMMddTHHmmssZ`` form rather
than ISO 8601, so both quirks are handled here instead of in the agents.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..zoho_client import ZohoAPIError, ZohoClient

_log = logging.getLogger("zoho_calendar")


def to_zoho_datetime(value: datetime) -> str:
    """Format a datetime as Zoho Calendar's ``yyyyMMddTHHmmssZ`` string."""
    return value.strftime("%Y%m%dT%H%M%SZ")


class ZohoCalendarService:
    """Create and read Zoho Calendar events."""

    def __init__(self, client: ZohoClient):
        self.client = client
        self._calendar_uid: Optional[str] = None

    @property
    def base(self) -> str:
        return self.client.settings.calendar_base

    # -- calendars -------------------------------------------------------
    async def list_calendars(self) -> List[Dict[str, Any]]:
        payload = await self.client.get(f"{self.base}/calendars")
        return payload.get("calendars") or []

    async def get_calendar_uid(self) -> str:
        """Resolve the calendar to write to: configured id, else the default."""
        if self._calendar_uid:
            return self._calendar_uid
        configured = self.client.settings.calendar_id
        if configured:
            self._calendar_uid = configured
            return configured

        calendars = await self.list_calendars()
        if not calendars:
            raise ZohoAPIError(
                "No Zoho Calendar found for this account. Set ZOHO_CALENDAR_ID to the target calendar."
            )
        default = next((c for c in calendars if c.get("isdefault") or c.get("isDefault")), calendars[0])
        self._calendar_uid = str(default.get("uid") or default.get("calendarUid") or "")
        if not self._calendar_uid:
            raise ZohoAPIError("Zoho Calendar response contained no calendar uid.")
        return self._calendar_uid

    # -- events ----------------------------------------------------------
    async def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: Optional[datetime] = None,
        duration_minutes: Optional[int] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        timezone: str = "",
        calendar_uid: str = "",
    ) -> Dict[str, Any]:
        """Create a calendar event and return its uid plus the scheduled window."""
        if not title:
            raise ZohoAPIError("An event title is required to create a calendar event.")
        settings = self.client.settings
        minutes = duration_minutes or settings.meeting_duration_minutes
        finish = end or (start + timedelta(minutes=minutes))
        tz = timezone or settings.timezone
        uid = calendar_uid or await self.get_calendar_uid()

        event: Dict[str, Any] = {
            "title": title,
            "dateandtime": {
                "timezone": tz,
                "start": to_zoho_datetime(start),
                "end": to_zoho_datetime(finish),
            },
        }
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        invitees = [a.strip() for a in (attendees or []) if a and a.strip()]
        if invitees:
            event["attendees"] = [{"email": a, "permission": 1} for a in invitees]

        payload = await self.client.post(
            f"{self.base}/calendars/{uid}/events",
            params={"eventdata": json.dumps(event)},
        )
        events = payload.get("events") or []
        created = events[0] if events else {}
        return {
            "created": True,
            "event_uid": str(created.get("uid") or ""),
            "calendar_uid": uid,
            "title": title,
            "start": start.isoformat(),
            "end": finish.isoformat(),
            "timezone": tz,
            "attendees": invitees,
        }

    async def list_events(
        self,
        *,
        calendar_uid: str = "",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """List events in a window; defaults to the next seven days."""
        uid = calendar_uid or await self.get_calendar_uid()
        window_start = start or datetime.utcnow()
        window_end = end or (window_start + timedelta(days=7))
        params = {
            "range": json.dumps(
                {"start": to_zoho_datetime(window_start), "end": to_zoho_datetime(window_end)}
            )
        }
        payload = await self.client.get(f"{self.base}/calendars/{uid}/events", params=params)
        return payload.get("events") or []


__all__ = ["ZohoCalendarService", "to_zoho_datetime"]
