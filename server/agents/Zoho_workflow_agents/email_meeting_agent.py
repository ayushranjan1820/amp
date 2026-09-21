"""Workflow 1 - email to meeting.

Trigger: an inbound email that asks for a meeting.

Sequence:
1. Get the email - either pasted into the prompt, or read from Zoho Mail.
2. Extract the meeting intent (who, when, what) with the LLM.
3. Create the Zoho Calendar event.
4. Send a confirmation email back to the requester through Zoho Mail.
5. Create a Zoho Projects task for the meeting owner.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List

from .base_workflow import (
    WorkflowContext,
    ZohoWorkflowAgent,
    ZohoWorkflowError,
    extract_emails,
    next_business_hour,
    parse_datetime_hint,
)
from .services.mail_service import to_plain_text

_log = logging.getLogger("zoho_email_meeting")

_EXTRACT_PROMPT = """You read one inbound email and decide whether the sender is asking for a meeting.

Return ONLY a JSON object, no markdown and no commentary:
{{
  "is_meeting_request": true,
  "requester_name": "sender's display name or empty string",
  "requester_email": "sender's email address",
  "additional_attendees": ["other@example.com"],
  "title": "short meeting title",
  "purpose": "one sentence on why they want to meet",
  "proposed_datetime": "ISO 8601 like 2026-09-18T15:00:00, or empty if none stated",
  "duration_minutes": 30,
  "location": "meeting location, video link, or empty string",
  "follow_up_task": "one line describing the preparation the owner should do"
}}

Rules:
- Set is_meeting_request to false if the email is not asking to meet.
- Use an empty string for anything the email does not state. Never invent a date.
- proposed_datetime must be an absolute timestamp. Resolve relative wording
  ("next Tuesday at 3", "tomorrow morning") against the current time given below.

Current time: {now}
Default meeting duration: {duration} minutes

EMAIL
-----
From: {sender}
Subject: {subject}
Received: {received}

{body}
"""


class ZohoEmailMeetingAgent(ZohoWorkflowAgent):
    """Email in, calendar event + confirmation + Projects task out."""

    agent_name = "Zoho Email Meeting Agent"
    required_products = ["Zoho Mail", "Zoho Calendar", "Zoho Projects"]
    workflow_steps = [
        "Read the meeting request email",
        "Extract meeting intent",
        "Create the calendar event",
        "Send the confirmation email",
        "Create the Projects follow-up task",
    ]

    # ------------------------------------------------------------------ #
    async def run_workflow(
        self,
        query: str,
        ctx: WorkflowContext,
        step: Callable[..., None],
        session_id: str,
    ) -> Dict[str, Any]:
        email = await self._resolve_email(query, ctx, step)
        step(
            f"Working from email '{email['subject'] or '(no subject)'}' from {email['from'] or 'unknown sender'}",
            step_type="tool_result",
            tool_name="zoho_mail",
        )

        intent = await self._extract_intent(email, ctx, step)
        if not intent.get("is_meeting_request", True):
            return {
                "success": True,
                "response": (
                    "### Zoho Email Meeting Agent\n\n"
                    "This email does not read as a meeting request, so no calendar event, "
                    "confirmation email or Projects task was created.\n\n"
                    f"**Subject:** {email['subject'] or '(no subject)'}\n"
                    f"**From:** {email['from'] or 'unknown'}"
                ),
                "actions": [],
                "data": {"email": email, "intent": intent},
            }

        requester_email = intent.get("requester_email") or _sender_address(email)
        if not requester_email:
            raise ZohoWorkflowError(
                "No requester email address was found, so there is nobody to confirm the meeting with. "
                "Include the sender address in the request, or point the agent at a Zoho Mail message."
            )

        start, was_defaulted = self._resolve_start(intent, ctx)
        duration = _int_or(intent.get("duration_minutes"), ctx.settings.meeting_duration_minutes)
        end = start + timedelta(minutes=duration)
        title = intent.get("title") or f"Meeting: {email['subject'] or 'requested by ' + requester_email}"
        attendees = _unique([requester_email, *(intent.get("additional_attendees") or [])])

        if was_defaulted:
            step(
                "The email proposed no specific time, so the next weekday at 10:00 "
                f"({start.strftime('%Y-%m-%d %H:%M')}) is used as the slot.",
                step_type="thinking",
            )

        actions: List[Dict[str, Any]] = []

        # 1. Calendar event
        event_action = await self.guarded_write(
            ctx,
            label="Create Zoho Calendar event",
            description=(
                f"create a {duration}-minute event '{title}' on "
                f"{start.strftime('%Y-%m-%d %H:%M')} {ctx.settings.timezone}"
            ),
            details={
                "Title": title,
                "Start": start.strftime("%Y-%m-%d %H:%M"),
                "End": end.strftime("%Y-%m-%d %H:%M"),
                "Timezone": ctx.settings.timezone,
                "Attendees": ", ".join(attendees),
                "Location": intent.get("location") or "(not specified)",
            },
            call=lambda: ctx.calendar.create_event(
                title=title,
                start=start,
                end=end,
                description=_event_description(intent, email),
                location=intent.get("location") or "",
                attendees=attendees,
            ),
            step=step,
        )
        actions.append(event_action)

        # 2. Confirmation email
        confirmation_body = self._confirmation_body(
            intent=intent, email=email, start=start, end=end, ctx=ctx, title=title
        )
        subject = f"Confirmed: {title}"
        mail_action = await self.guarded_write(
            ctx,
            label="Send confirmation email",
            description=f"send '{subject}' to {requester_email} from the Zoho mailbox",
            details={"To": requester_email, "Subject": subject},
            call=lambda: ctx.mail.send_mail(
                to=[requester_email],
                subject=subject,
                body=confirmation_body,
                cc=[a for a in attendees if a != requester_email] or None,
            ),
            step=step,
        )
        actions.append(mail_action)

        # 3. Projects follow-up task
        task_subject = intent.get("follow_up_task") or f"Prepare for meeting with {requester_email}"
        task_action = await self.guarded_write(
            ctx,
            label="Create Projects follow-up task",
            description=f"create Projects task '{task_subject}' due {start.strftime('%Y-%m-%d')}",
            details={
                "Task": task_subject,
                "Due date": start.strftime("%Y-%m-%d"),
                "Project": "(default project)",
            },
            call=lambda: ctx.projects.create_task(
                subject=task_subject,
                due_date=start,
                description=(
                    f"Auto-created from the meeting request '{email['subject']}'.\n"
                    f"Requester: {requester_email}\n"
                    f"Purpose: {intent.get('purpose') or 'not stated'}\n"
                    f"Scheduled: {start.strftime('%Y-%m-%d %H:%M')} {ctx.settings.timezone}"
                ),
            ),
            step=step,
        )
        actions.append(task_action)

        return {
            "success": True,
            "actions": actions,
            "workflow": "email_to_meeting",
            "data": {
                "email": email,
                "intent": intent,
                "meeting": {
                    "title": title,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": ctx.settings.timezone,
                    "attendees": attendees,
                },
            },
        }

    # ------------------------------------------------------------------ #
    # Inputs
    # ------------------------------------------------------------------ #
    async def _resolve_email(
        self, query: str, ctx: WorkflowContext, step: Callable[..., None]
    ) -> Dict[str, Any]:
        """Get the email to act on: an explicit message id, a mailbox read, or the prompt itself."""
        message_id = _find_message_id(query)
        if message_id:
            step(f"Reading Zoho Mail message {message_id}", step_type="tool_call", tool_name="zoho_mail")
            return await ctx.mail.get_message(message_id)

        if _wants_mailbox_read(query):
            search = _search_term(query)
            step(
                f"Reading the latest Zoho Mail message{f' matching “{search}”' if search else ''}",
                step_type="tool_call",
                tool_name="zoho_mail",
            )
            message = await ctx.mail.get_latest_message(search=search)
            if not message:
                raise ZohoWorkflowError(
                    "No matching message was found in the Zoho mailbox. Paste the email text into the "
                    "prompt, or give a message id."
                )
            return message

        body = to_plain_text(query)
        if len(body.strip()) < 15:
            raise ZohoWorkflowError(
                "Give the agent something to work from: paste the meeting-request email, or say "
                "'process my latest email about a meeting' to read the Zoho mailbox."
            )
        senders = extract_emails(body)
        step("Using the email content supplied in the prompt", step_type="thinking")
        return {
            "message_id": "",
            "folder_id": "",
            "subject": _guess_subject(body),
            "from": senders[0] if senders else "",
            "to": "",
            "cc": "",
            "received_time": datetime.now().isoformat(timespec="seconds"),
            "summary": body[:300],
            "body": body,
            "thread_id": "",
            "source": "prompt",
        }

    async def _extract_intent(
        self, email: Dict[str, Any], ctx: WorkflowContext, step: Callable[..., None]
    ) -> Dict[str, Any]:
        step("Extracting meeting intent from the email", step_type="tool_call", tool_name="meeting_extractor")
        prompt = _EXTRACT_PROMPT.format(
            now=datetime.now().isoformat(timespec="minutes"),
            duration=ctx.settings.meeting_duration_minutes,
            sender=email.get("from", ""),
            subject=email.get("subject", ""),
            received=email.get("received_time", ""),
            body=(email.get("body") or "")[:6000],
        )
        intent = await self.extract_json(prompt, fallback=_rule_based_intent(email, ctx), step=step)
        intent.setdefault("is_meeting_request", True)
        step(
            "Intent: "
            + json.dumps(
                {
                    "title": intent.get("title", ""),
                    "proposed_datetime": intent.get("proposed_datetime", ""),
                    "requester_email": intent.get("requester_email", ""),
                },
                default=str,
            ),
            step_type="tool_result",
            tool_name="meeting_extractor",
        )
        return intent

    def _resolve_start(self, intent: Dict[str, Any], ctx: WorkflowContext) -> tuple[datetime, bool]:
        """Meeting start time, plus whether a default had to be substituted."""
        parsed = parse_datetime_hint(intent.get("proposed_datetime"))
        if parsed is None:
            return next_business_hour(), True
        # A time already in the past is almost always a misparsed relative date.
        if parsed < datetime.now():
            return next_business_hour(), True
        return parsed, False

    async def _find_crm_contact(
        self, email_address: str, ctx: WorkflowContext, step: Callable[..., None]
    ) -> str:
        """Best-effort CRM contact lookup; a miss is fine, the task still gets created."""
        try:
            matches = await ctx.crm.search_contacts(email=email_address, limit=1)
        except Exception as exc:
            step(f"CRM contact lookup skipped: {exc}", step_type="tool_result", tool_name="zoho_crm")
            return ""
        if matches:
            contact_id = str(matches[0].get("id") or "")
            step(
                f"Matched CRM contact {matches[0].get('Full_Name') or email_address} ({contact_id})",
                step_type="tool_result",
                tool_name="zoho_crm",
            )
            return contact_id
        step(f"No CRM contact found for {email_address}", step_type="tool_result", tool_name="zoho_crm")
        return ""

    # ------------------------------------------------------------------ #
    def _confirmation_body(
        self,
        *,
        intent: Dict[str, Any],
        email: Dict[str, Any],
        start: datetime,
        end: datetime,
        ctx: WorkflowContext,
        title: str,
    ) -> str:
        name = intent.get("requester_name") or "there"
        purpose = intent.get("purpose") or "the topic you raised"
        location = intent.get("location") or "Location or joining details not specified."
        return (
            f"<p>Hi {name},</p>"
            f"<p>Thanks for reaching out. The meeting is confirmed.</p>"
            f"<table cellpadding='6'>"
            f"<tr><td><b>What</b></td><td>{title}</td></tr>"
            f"<tr><td><b>When</b></td><td>{start.strftime('%A %d %B %Y, %H:%M')} - "
            f"{end.strftime('%H:%M')} ({ctx.settings.timezone})</td></tr>"
            f"<tr><td><b>Topic</b></td><td>{purpose}</td></tr>"
            f"<tr><td><b>Where</b></td><td>{location}</td></tr>"
            f"</table>"
            f"<p>If that time does not work, reply to this email and we will move it.</p>"
            f"<p>Best regards</p>"
        )


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _event_description(intent: Dict[str, Any], email: Dict[str, Any]) -> str:
    parts = [
        f"Purpose: {intent.get('purpose') or 'not stated'}",
        f"Requested by: {intent.get('requester_email') or email.get('from', '')}",
        f"Source email: {email.get('subject') or '(no subject)'}",
    ]
    return "\n".join(parts)


def _sender_address(email: Dict[str, Any]) -> str:
    candidates = extract_emails(str(email.get("from") or ""))
    if candidates:
        return candidates[0]
    return next(iter(extract_emails(email.get("body") or "")), "")


def _rule_based_intent(email: Dict[str, Any], ctx: WorkflowContext) -> Dict[str, Any]:
    """Deterministic fallback so the workflow still runs without an LLM."""
    body = email.get("body") or ""
    sender = _sender_address(email)
    return {
        "is_meeting_request": True,
        "requester_name": "",
        "requester_email": sender,
        "additional_attendees": [a for a in extract_emails(body) if a != sender][:5],
        "title": email.get("subject") or "Requested meeting",
        "purpose": (email.get("summary") or body)[:200],
        "proposed_datetime": "",
        "duration_minutes": ctx.settings.meeting_duration_minutes,
        "location": "",
        "follow_up_task": f"Prepare for meeting with {sender or 'the requester'}",
    }


def _find_message_id(query: str) -> str:
    import re

    match = re.search(r"(?:message[_\s-]?id|msg[_\s-]?id)\s*[:=]?\s*([0-9]{6,})", query or "", re.I)
    return match.group(1) if match else ""


def _wants_mailbox_read(query: str) -> bool:
    lowered = (query or "").lower()
    triggers = (
        "latest email",
        "latest meeting email",
        "last email",
        "last meeting email",
        "newest email",
        "newest meeting email",
        "my inbox",
        "check my email",
        "check my mail",
        "unread email",
        "recent email",
        "read my email",
        "from my mailbox",
    )
    return any(t in lowered for t in triggers)


def _search_term(query: str) -> str:
    import re

    match = re.search(r"about\s+(.{3,60})", query or "", re.I)
    if not match:
        return ""
    return match.group(1).strip().strip(".\"'")


def _guess_subject(body: str) -> str:
    import re

    match = re.search(r"^\s*subject\s*:\s*(.+)$", body, re.I | re.M)
    if match:
        return match.group(1).strip()
    first_line = next((l.strip() for l in body.splitlines() if l.strip()), "")
    return first_line[:120]


def _int_or(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _unique(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)
    return out


zoho_email_meeting_agent = ZohoEmailMeetingAgent()

__all__ = ["ZohoEmailMeetingAgent", "zoho_email_meeting_agent"]
