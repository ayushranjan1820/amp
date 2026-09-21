"""Workflow 2 - high-priority support ticket triage.

Trigger: a high-priority ticket arrives in Zoho Desk.

Sequence:
1. Get the ticket - by id, by "latest high priority", or pasted into the prompt.
2. Add a private escalation note to the Zoho Desk ticket.
3. Create a Zoho Projects follow-up task.
4. Send the customer an acknowledgement reply through Zoho Desk.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List

from .base_workflow import (
    WorkflowContext,
    ZohoWorkflowAgent,
    ZohoWorkflowError,
    extract_emails,
)
from .services.desk_service import ESCALATION_PRIORITIES
from .services.mail_service import to_plain_text

_log = logging.getLogger("zoho_support_ticket")

_SUMMARY_PROMPT = """You triage one support ticket for an engineering channel.

Return ONLY a JSON object, no markdown:
{{
  "severity_summary": "one sentence a responder can read at a glance",
  "customer_impact": "what the customer cannot do right now",
  "suggested_owner_action": "the single next action for the assignee",
  "acknowledgement_message": "2-3 sentence reply to the customer, plain and specific, no placeholders",
  "sla_hours": 4
}}

Write in plain professional English. Never invent facts that are not in the ticket.

TICKET
------
Number: {number}
Subject: {subject}
Priority: {priority}
Status: {status}
Customer: {contact_name} <{contact_email}>
Account: {account}
Created: {created}

{description}
"""


class ZohoSupportTicketAgent(ZohoWorkflowAgent):
    """Desk ticket in, private note + Projects task + customer acknowledgement out."""

    agent_name = "Zoho Support Ticket Agent"
    required_products = ["Zoho Desk", "Zoho Projects"]
    workflow_steps = [
        "Read the high-priority ticket",
        "Summarize severity and impact",
        "Add the private Desk escalation note",
        "Create the Projects follow-up task",
        "Send the customer acknowledgement",
    ]

    # ------------------------------------------------------------------ #
    async def run_workflow(
        self,
        query: str,
        ctx: WorkflowContext,
        step: Callable[..., None],
        session_id: str,
    ) -> Dict[str, Any]:
        ticket = await self._resolve_ticket(query, ctx, step)
        step(
            f"Ticket #{ticket['ticket_number'] or ticket['ticket_id'] or 'n/a'} "
            f"({ticket['priority'] or 'no priority'}) - {ticket['subject'] or '(no subject)'}",
            step_type="tool_result",
            tool_name="zoho_desk",
        )

        if ticket["priority"] and ticket["priority"] not in ESCALATION_PRIORITIES:
            step(
                f"Priority is {ticket['priority']}, not {' or '.join(ESCALATION_PRIORITIES)}. "
                "Escalation actions are skipped.",
                step_type="thinking",
            )
            return {
                "success": True,
                "response": (
                    f"### Zoho Support Ticket Agent\n\n"
                    f"Ticket #{ticket['ticket_number'] or ticket['ticket_id']} is priority "
                    f"**{ticket['priority']}**, below the escalation threshold "
                    f"({' / '.join(ESCALATION_PRIORITIES)}). No Desk note, Projects task or customer "
                    f"reply was created.\n\n"
                    f"Only High or Urgent tickets are escalated."
                ),
                "actions": [],
                "data": {"ticket": ticket},
            }

        if not ctx.settings.dry_run and not ticket["ticket_id"]:
            raise ZohoWorkflowError(
                "A Desk ticket ID is required for live escalation and acknowledgement. "
                "Create the ticket in Desk, then submit its ID. No records were created."
            )

        if not ctx.settings.dry_run and not ticket["contact_email"]:
            raise ZohoWorkflowError("The Desk ticket needs a customer email for acknowledgement. No records were created.")

        if not ctx.settings.dry_run and not ctx.settings.from_address:
            raise ZohoWorkflowError("Configure ZOHO_FROM_ADDRESS with an authorized Desk reply address. No records were created.")

        triage = await self._summarize(ticket, step)
        actions: List[Dict[str, Any]] = []

        alert_text = self._escalation_text(ticket, triage)
        destination = f"Desk ticket #{ticket['ticket_number'] or ticket['ticket_id']}"
        note_action = await self.guarded_write(
            ctx,
            label="Add private Desk escalation note",
            description=f"add a {ticket['priority'] or 'high'}-priority internal note to {destination}",
            details={
                "Destination": destination,
                "Headline": triage.get("severity_summary", "")[:140],
            },
            call=lambda: ctx.desk.add_comment(
                ticket_id=ticket["ticket_id"],
                content=_as_html(alert_text),
                is_public=False,
            ),
            step=step,
        )
        actions.append(note_action)

        sla_hours = _int_or(triage.get("sla_hours"), 4)
        due = datetime.now() + timedelta(hours=sla_hours)
        task_subject = (
            f"[{ticket['priority'] or 'High'}] Ticket #{ticket['ticket_number'] or ticket['ticket_id']}: "
            f"{ticket['subject'] or 'support escalation'}"
        )[:240]
        task_action = await self.guarded_write(
            ctx,
            label="Create Projects follow-up task",
            description=f"create Projects task '{task_subject}' due {due.strftime('%Y-%m-%d')}",
            details={
                "Subject": task_subject,
                "Due date": due.strftime("%Y-%m-%d"),
                "SLA": f"{sla_hours}h",
                "Customer": ticket["contact_email"],
            },
            call=lambda: ctx.projects.create_task(
                subject=task_subject,
                due_date=due,
                priority="High",
                description=(
                    f"Escalated from Zoho Desk ticket #{ticket['ticket_number'] or ticket['ticket_id']}.\n"
                    f"Customer: {ticket['contact_name']} <{ticket['contact_email']}>\n"
                    f"Impact: {triage.get('customer_impact') or 'not assessed'}\n"
                    f"Next action: {triage.get('suggested_owner_action') or 'triage the ticket'}\n"
                    f"Ticket URL: {ticket.get('web_url') or 'n/a'}"
                ),
            ),
            step=step,
        )
        actions.append(task_action)

        # 3. Customer acknowledgement
        ack = triage.get("acknowledgement_message") or self._default_ack(ticket, sla_hours)
        if not ticket["ticket_id"]:
            step(
                "The ticket was supplied as text rather than read from Desk, so there is no ticket id "
                "to reply on. The acknowledgement is drafted but not sent.",
                step_type="thinking",
            )
            actions.append(
                {
                    "label": "Send customer acknowledgement",
                    "description": "send an acknowledgement reply on the Desk ticket",
                    "details": {"Draft": ack[:400]},
                    "executed": False,
                    "skipped_reason": "no_ticket_id",
                }
            )
        elif not ticket["contact_email"]:
            step(
                "No customer email address is on the ticket, so the acknowledgement cannot be addressed.",
                step_type="thinking",
            )
            actions.append(
                {
                    "label": "Send customer acknowledgement",
                    "description": "send an acknowledgement reply on the Desk ticket",
                    "details": {"Draft": ack[:400]},
                    "executed": False,
                    "skipped_reason": "no_contact_email",
                }
            )
        else:
            reply_action = await self.guarded_write(
                ctx,
                label="Send customer acknowledgement",
                description=(
                    f"reply on Desk ticket #{ticket['ticket_number'] or ticket['ticket_id']} "
                    f"to {ticket['contact_email']}"
                ),
                details={"To": ticket["contact_email"], "Body": ack[:400]},
                call=lambda: ctx.desk.send_reply(
                    ticket_id=ticket["ticket_id"],
                    content=_as_html(ack),
                    to_address=ticket["contact_email"],
                    from_address=ctx.settings.from_address,
                ),
                step=step,
            )
            actions.append(reply_action)

        return {
            "success": all(action.get("executed") or action.get("skipped_reason") == "dry_run" for action in actions),
            "actions": actions,
            "workflow": "support_ticket_escalation",
            "data": {"ticket": ticket, "triage": triage},
        }

    # ------------------------------------------------------------------ #
    # Inputs
    # ------------------------------------------------------------------ #
    async def _resolve_ticket(
        self, query: str, ctx: WorkflowContext, step: Callable[..., None]
    ) -> Dict[str, Any]:
        ticket_id = _find_ticket_id(query)
        if ticket_id:
            step(f"Reading Zoho Desk ticket {ticket_id}", step_type="tool_call", tool_name="zoho_desk")
            return await ctx.desk.get_ticket(ticket_id)

        if _wants_desk_read(query):
            step(
                "Looking for the newest open High/Urgent ticket in Zoho Desk",
                step_type="tool_call",
                tool_name="zoho_desk",
            )
            ticket = await ctx.desk.get_latest_high_priority_ticket()
            if not ticket:
                raise ZohoWorkflowError(
                    "No open High or Urgent ticket was found in Zoho Desk. Give a ticket id, or paste "
                    "the ticket details into the prompt."
                )
            return ticket

        body = to_plain_text(query)
        if len(body.strip()) < 15:
            raise ZohoWorkflowError(
                "Give the agent a ticket to triage: a ticket id, 'triage the latest high priority "
                "ticket', or the ticket details pasted into the prompt."
            )
        step("Using the ticket details supplied in the prompt", step_type="thinking")
        return _ticket_from_text(body)

    async def _summarize(self, ticket: Dict[str, Any], step: Callable[..., None]) -> Dict[str, Any]:
        step("Summarizing severity and drafting the customer reply", step_type="tool_call",
             tool_name="ticket_triage")
        prompt = _SUMMARY_PROMPT.format(
            number=ticket.get("ticket_number", ""),
            subject=ticket.get("subject", ""),
            priority=ticket.get("priority", ""),
            status=ticket.get("status", ""),
            contact_name=ticket.get("contact_name", ""),
            contact_email=ticket.get("contact_email", ""),
            account=ticket.get("account_name", ""),
            created=ticket.get("created_time", ""),
            description=(ticket.get("description") or "")[:6000],
        )
        fallback = {
            "severity_summary": f"{ticket.get('priority') or 'High'} priority: {ticket.get('subject') or 'support issue'}",
            "customer_impact": (ticket.get("description") or "")[:200],
            "suggested_owner_action": "Review the ticket and contact the customer.",
            "acknowledgement_message": self._default_ack(ticket, 4),
            "sla_hours": 4,
        }
        triage = await self.extract_json(prompt, fallback=fallback, step=step)
        step(
            f"Triage: {triage.get('severity_summary', '')[:180]}",
            step_type="tool_result",
            tool_name="ticket_triage",
        )
        return triage

    async def _find_crm_contact(
        self, ticket: Dict[str, Any], ctx: WorkflowContext, step: Callable[..., None]
    ) -> str:
        email = ticket.get("contact_email") or ""
        if not email:
            return ""
        try:
            matches = await ctx.crm.search_contacts(email=email, limit=1)
        except Exception as exc:
            step(f"CRM contact lookup skipped: {exc}", step_type="tool_result", tool_name="zoho_crm")
            return ""
        if matches:
            contact_id = str(matches[0].get("id") or "")
            step(f"Matched CRM contact {contact_id} for {email}", step_type="tool_result", tool_name="zoho_crm")
            return contact_id
        step(f"No CRM contact found for {email}", step_type="tool_result", tool_name="zoho_crm")
        return ""

    # ------------------------------------------------------------------ #
    def _escalation_text(self, ticket: Dict[str, Any], triage: Dict[str, Any]) -> str:
        lines = [
            f"*{ticket.get('priority') or 'High'} priority ticket* "
            f"#{ticket.get('ticket_number') or ticket.get('ticket_id') or 'n/a'}",
            f"*Subject:* {ticket.get('subject') or '(no subject)'}",
            f"*Customer:* {ticket.get('contact_name') or 'unknown'}"
            + (f" <{ticket['contact_email']}>" if ticket.get("contact_email") else ""),
        ]
        if ticket.get("account_name"):
            lines.append(f"*Account:* {ticket['account_name']}")
        if triage.get("severity_summary"):
            lines.append(f"*Summary:* {triage['severity_summary']}")
        if triage.get("customer_impact"):
            lines.append(f"*Impact:* {triage['customer_impact']}")
        if triage.get("suggested_owner_action"):
            lines.append(f"*Next action:* {triage['suggested_owner_action']}")
        if ticket.get("web_url"):
            lines.append(f"*Ticket:* {ticket['web_url']}")
        return "\n".join(lines)

    def _default_ack(self, ticket: Dict[str, Any], sla_hours: int) -> str:
        name = ticket.get("contact_name") or "there"
        number = ticket.get("ticket_number") or ticket.get("ticket_id") or "your ticket"
        return (
            f"Hi {name}, thanks for reporting this. Ticket {number} has been raised at "
            f"{(ticket.get('priority') or 'high').lower()} priority and is with our support team now. "
            f"You will hear from an engineer within {sla_hours} hours with an update."
        )


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _find_ticket_id(query: str) -> str:
    """Pull a Desk ticket id out of the request.

    Desk's REST API addresses tickets by their long internal id, so two digits
    is the floor. A ticket *number* passed here simply 404s with a message
    naming the URL, which is clearer than silently triaging the wrong ticket.
    """
    match = re.search(r"ticket\s*(?:id|number|#)?\s*[:=#]?\s*(\d{2,})", query or "", re.I)
    if match:
        return match.group(1)
    match = re.search(r"#(\d{2,})", query or "")
    return match.group(1) if match else ""


def _wants_desk_read(query: str) -> bool:
    lowered = (query or "").lower()
    triggers = (
        "latest",
        "newest",
        "most recent",
        "high priority ticket",
        "urgent ticket",
        "open ticket",
        "new ticket",
        "check desk",
        "from desk",
    )
    return any(t in lowered for t in triggers)


def _ticket_from_text(body: str) -> Dict[str, Any]:
    """Build a ticket record out of pasted text, for demos without Desk access."""
    def field(*names: str) -> str:
        for name in names:
            match = re.search(rf"^\s*{name}\s*[:\-]\s*(.+)$", body, re.I | re.M)
            if match:
                return match.group(1).strip()
        return ""

    priority = field("priority") or _infer_priority(body)
    emails = extract_emails(body)
    return {
        "ticket_id": field("ticket id", "ticket_id", "id"),
        "ticket_number": field("ticket number", "ticket", "number", "#"),
        "subject": field("subject", "title") or next((l.strip() for l in body.splitlines() if l.strip()), "")[:120],
        "description": body,
        "priority": priority,
        "status": field("status") or "Open",
        "category": field("category"),
        "created_time": field("created", "created time") or datetime.now().isoformat(timespec="seconds"),
        "due_date": "",
        "web_url": "",
        "department_id": "",
        "contact_name": field("customer", "contact", "contact name", "from"),
        "contact_email": field("email", "customer email", "contact email") or (emails[0] if emails else ""),
        "contact_id": "",
        "account_name": field("account", "company"),
        "assignee": field("assignee", "owner"),
        "source": "prompt",
    }


def _infer_priority(body: str) -> str:
    lowered = body.lower()
    if any(w in lowered for w in ("urgent", "outage", "down", "critical", "p1", "sev1")):
        return "Urgent"
    if any(w in lowered for w in ("high priority", "asap", "blocked", "blocker")):
        return "High"
    return ""


def _as_html(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text or "") if p.strip()]
    if not paragraphs:
        return "<p></p>"
    return "".join(f"<p>{p.replace(chr(10), '<br>')}</p>" for p in paragraphs)


def _int_or(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


zoho_support_ticket_agent = ZohoSupportTicketAgent()

__all__ = ["ZohoSupportTicketAgent", "zoho_support_ticket_agent"]
