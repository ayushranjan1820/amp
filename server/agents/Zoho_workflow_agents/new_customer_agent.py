"""Workflow 3 - new customer onboarding.

Trigger: customer details are supplied in the request.

Sequence:
1. Read the customer's name, email and company from the prompt.
2. Send the welcome email through Zoho Mail.
3. Schedule an introduction call in Zoho Calendar.
4. Create an onboarding follow-up ticket in Zoho Desk.
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
    next_business_hour,
    parse_datetime_hint,
)
from .services.mail_service import to_plain_text

_log = logging.getLogger("zoho_new_customer")

_WELCOME_PROMPT = """You write onboarding content for a new customer.

Return ONLY a JSON object, no markdown:
{{
  "welcome_subject": "a specific subject line, no placeholders",
  "welcome_body_html": "<p>...</p> 3 short paragraphs: thank them, say what happens next, invite questions",
  "intro_call_title": "short calendar event title naming the customer",
  "intro_call_agenda": "3 bullet points as plain text lines for the event description",
    "sales_notification": "2 sentences for the internal Desk follow-up covering who they are and the next step"
}}

Address the customer by first name where known. Never use bracketed placeholders
and never invent products, prices or commitments.

CUSTOMER
--------
Name: {name}
Email: {email}
Company: {company}
Title: {title}
Phone: {phone}
Lead source: {source}
Description: {description}
Owner: {owner}
"""


class ZohoNewCustomerAgent(ZohoWorkflowAgent):
    """Customer details in, welcome email + intro call + Desk follow-up out."""

    agent_name = "Zoho New Customer Agent"
    required_products = ["Zoho Mail", "Zoho Calendar", "Zoho Desk"]
    workflow_steps = [
        "Read the customer details",
        "Draft the onboarding content",
        "Send the welcome email",
        "Schedule the introduction call",
        "Create the Desk onboarding follow-up ticket",
    ]

    # ------------------------------------------------------------------ #
    async def run_workflow(
        self,
        query: str,
        ctx: WorkflowContext,
        step: Callable[..., None],
        session_id: str,
    ) -> Dict[str, Any]:
        customer = await self._resolve_customer(query, ctx, step)
        if not customer.get("email"):
            raise ZohoWorkflowError(
                "The customer record has no email address, so no welcome email or calendar invite can "
                "be sent. Include the customer's name and email in the request."
            )
        step(
            f"Onboarding {customer['name'] or customer['email']}"
            + (f" at {customer['company']}" if customer.get("company") else ""),
            step_type="tool_result",
            tool_name="customer_details",
        )

        if not ctx.settings.dry_run:
            if not ctx.settings.desk_department_id:
                raise ZohoWorkflowError(
                    "Configure ZOHO_DESK_DEPARTMENT_ID before running live onboarding. "
                    "No welcome email or calendar event was created."
                )
            if ctx.settings.uses_mcp:
                await ctx.client.resolve("desk.create_ticket")
            elif not ctx.settings.org_id:
                raise ZohoWorkflowError("Configure ZOHO_ORG_ID before running live onboarding. No records were created.")

        content = await self._draft_content(customer, step)
        actions: List[Dict[str, Any]] = []

        # 1. Welcome email
        subject = content.get("welcome_subject") or f"Welcome aboard, {customer['first_name'] or 'and thank you'}"
        body = content.get("welcome_body_html") or self._default_welcome(customer)
        mail_action = await self.guarded_write(
            ctx,
            label="Send welcome email",
            description=f"send '{subject}' to {customer['email']}",
            details={"To": customer["email"], "Subject": subject},
            call=lambda: ctx.mail.send_mail(
                to=[customer["email"]], subject=subject, body=body
            ),
            step=step,
        )
        actions.append(mail_action)

        # 2. Introduction call
        start = self._resolve_call_time(query, ctx)
        duration = ctx.settings.meeting_duration_minutes
        end = start + timedelta(minutes=duration)
        event_title = content.get("intro_call_title") or (
            f"Intro call: {customer['company'] or customer['name'] or customer['email']}"
        )
        agenda = content.get("intro_call_agenda") or self._default_agenda(customer)
        event_action = await self.guarded_write(
            ctx,
            label="Schedule introduction call",
            description=(
                f"create a {duration}-minute event '{event_title}' on "
                f"{start.strftime('%Y-%m-%d %H:%M')} {ctx.settings.timezone}"
            ),
            details={
                "Title": event_title,
                "Start": start.strftime("%Y-%m-%d %H:%M"),
                "End": end.strftime("%Y-%m-%d %H:%M"),
                "Timezone": ctx.settings.timezone,
                "Attendee": customer["email"],
            },
            call=lambda: ctx.calendar.create_event(
                title=event_title,
                start=start,
                end=end,
                description=agenda,
                attendees=[customer["email"]],
            ),
            step=step,
        )
        actions.append(event_action)

        notification = self._follow_up_text(customer, content, start, ctx)
        ticket_subject = f"Onboarding follow-up: {customer['company'] or customer['name'] or customer['email']}"
        desk_action = await self.guarded_write(
            ctx,
            label="Create Desk onboarding follow-up ticket",
            description=f"create Desk ticket '{ticket_subject}' for internal onboarding follow-up",
            details={"Department": ctx.settings.desk_department_id, "Subject": ticket_subject},
            call=lambda: ctx.desk.create_ticket(
                subject=ticket_subject, description=notification, email=customer["email"],
            ),
            step=step,
        )
        actions.append(desk_action)

        return {
            "success": all(action.get("executed") or action.get("skipped_reason") == "dry_run" for action in actions),
            "actions": actions,
            "workflow": "new_customer_onboarding",
            "data": {
                "customer": customer,
                "content": content,
                "intro_call": {
                    "title": event_title,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "timezone": ctx.settings.timezone,
                },
            },
        }

    # ------------------------------------------------------------------ #
    # Inputs
    # ------------------------------------------------------------------ #
    async def _resolve_customer(
        self, query: str, ctx: WorkflowContext, step: Callable[..., None]
    ) -> Dict[str, Any]:
        emails = extract_emails(query)
        if not emails:
            raise ZohoWorkflowError(
                "The request has no email address. Include the customer's name, email and company. "
                "This workflow does not read CRM contacts."
            )
        step("Using customer details supplied in the request", step_type="thinking")
        return _customer_from_text(to_plain_text(query), fallback_email=emails[0])

    async def _draft_content(self, customer: Dict[str, Any], step: Callable[..., None]) -> Dict[str, Any]:
        step("Drafting the welcome email, call agenda and sales note", step_type="tool_call",
             tool_name="onboarding_writer")
        prompt = _WELCOME_PROMPT.format(
            name=customer.get("name", ""),
            email=customer.get("email", ""),
            company=customer.get("company", ""),
            title=customer.get("title", ""),
            phone=customer.get("phone", ""),
            source=customer.get("lead_source", ""),
            description=(customer.get("description") or "")[:2000],
            owner=customer.get("owner", ""),
        )
        fallback = {
            "welcome_subject": f"Welcome aboard, {customer.get('first_name') or 'and thank you'}",
            "welcome_body_html": self._default_welcome(customer),
            "intro_call_title": f"Intro call: {customer.get('company') or customer.get('name') or 'new customer'}",
            "intro_call_agenda": self._default_agenda(customer),
            "sales_notification": (
                f"{customer.get('name') or customer.get('email')}"
                + (f" from {customer['company']}" if customer.get("company") else "")
                + " has been added as a customer. An intro call is being scheduled."
            ),
        }
        content = await self.extract_json(prompt, fallback=fallback, step=step)
        step(
            f"Draft ready: {content.get('welcome_subject', '')[:120]}",
            step_type="tool_result",
            tool_name="onboarding_writer",
        )
        return content

    def _resolve_call_time(self, query: str, ctx: WorkflowContext) -> datetime:
        """Honour an explicit time in the request, else the next weekday at 10:00."""
        explicit = re.search(
            r"\b(\d{4}-\d{2}-\d{2})(?:T|\s+(?:at\s+)?)(\d{1,2}:\d{2})\b",
            query or "", re.I,
        )
        if explicit:
            parsed = parse_datetime_hint(f"{explicit.group(1)} {explicit.group(2)}")
            if parsed and parsed > datetime.now():
                return parsed
        match = re.search(r"\b(?:on|at|for)\s+([^.,;\n]{4,40})", query or "", re.I)
        if match:
            parsed = parse_datetime_hint(match.group(1))
            if parsed and parsed > datetime.now():
                return parsed
        return next_business_hour(days_ahead=2)

    # ------------------------------------------------------------------ #
    def _default_welcome(self, customer: Dict[str, Any]) -> str:
        name = customer.get("first_name") or "there"
        company = customer.get("company")
        return (
            f"<p>Hi {name},</p>"
            f"<p>Thank you for choosing to work with us"
            + (f", and welcome on behalf of the whole team at {company}'s account group" if company else "")
            + ".</p>"
            "<p>Next, we will set up a short introduction call to understand your goals and walk you "
            "through onboarding. A calendar invitation follows this email.</p>"
            "<p>If anything is urgent before then, reply to this email and we will pick it up.</p>"
            "<p>Best regards</p>"
        )

    def _default_agenda(self, customer: Dict[str, Any]) -> str:
        return (
            "Introductions and your goals for the next quarter\n"
            "Walkthrough of onboarding steps and timelines\n"
            "Questions, and agreeing the next checkpoint"
        )

    def _follow_up_text(
        self,
        customer: Dict[str, Any],
        content: Dict[str, Any],
        start: datetime,
        ctx: WorkflowContext,
    ) -> str:
        lines = [
            f"Onboarding follow-up: {customer.get('name') or customer.get('email')}",
        ]
        if customer.get("company"):
            lines.append(f"*Company:* {customer['company']}")
        if customer.get("title"):
            lines.append(f"*Role:* {customer['title']}")
        lines.append(f"*Email:* {customer.get('email', '')}")
        if customer.get("lead_source"):
            lines.append(f"*Source:* {customer['lead_source']}")
        if customer.get("owner"):
            lines.append(f"*Owner:* {customer['owner']}")
        lines.append(
            f"*Intro call:* {start.strftime('%A %d %B, %H:%M')} ({ctx.settings.timezone})"
        )
        if content.get("sales_notification"):
            lines.append(f"*Context:* {content['sales_notification']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #

def _normalize_contact(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a CRM Contacts record into the fields the workflow uses."""
    first = record.get("First_Name") or ""
    last = record.get("Last_Name") or ""
    full = record.get("Full_Name") or f"{first} {last}".strip()
    account = record.get("Account_Name")
    company = ""
    if isinstance(account, dict):
        company = account.get("name", "")
    elif isinstance(account, str):
        company = account
    owner = record.get("Owner")
    owner_name = owner.get("name", "") if isinstance(owner, dict) else str(owner or "")
    return {
        "contact_id": str(record.get("id") or ""),
        "name": full,
        "first_name": first or (full.split(" ")[0] if full else ""),
        "last_name": last,
        "email": record.get("Email") or "",
        "phone": record.get("Phone") or record.get("Mobile") or "",
        "company": company,
        "title": record.get("Title") or "",
        "lead_source": record.get("Lead_Source") or "",
        "description": record.get("Description") or "",
        "owner": owner_name,
        "created_time": record.get("Created_Time") or "",
        "source": "crm",
    }


def _customer_from_text(body: str, fallback_email: str = "") -> Dict[str, Any]:
    """Build a customer record out of prompt text, for demos without CRM data."""
    def field(*names: str) -> str:
        for name in names:
            match = re.search(rf"^\s*{name}\s*[:\-]\s*(.+)$", body, re.I | re.M)
            if match:
                return match.group(1).strip()
        return ""

    emails = extract_emails(body)
    email = field("email") or fallback_email or (emails[0] if emails else "")
    name = field("name", "customer", "contact", "full name")
    if not name:
        # "onboard Priya Sharma from Acme" style phrasing
        match = re.search(r"onboard(?:ing)?\s+([A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?)", body)
        name = match.group(1).strip() if match else ""
    company = field("company", "account", "organisation", "organization")
    if not company:
        match = re.search(r"\b(?:from|at)\s+([A-Z][\w&.\- ]{2,40})", body)
        company = match.group(1).strip() if match else ""
    first = name.split(" ")[0] if name else ""
    return {
        "contact_id": "",
        "name": name,
        "first_name": first,
        "last_name": " ".join(name.split(" ")[1:]) if name and " " in name else "",
        "email": email,
        "phone": field("phone", "mobile"),
        "company": company,
        "title": field("title", "role", "designation"),
        "lead_source": field("source", "lead source"),
        "description": body[:1000],
        "owner": field("owner", "account manager"),
        "created_time": datetime.now().isoformat(timespec="seconds"),
        "source": "prompt",
    }


def _find_contact_id(query: str) -> str:
    match = re.search(r"contact\s*(?:id|#)?\s*[:=#]?\s*(\d{8,})", query or "", re.I)
    return match.group(1) if match else ""


def _wants_crm_read(query: str) -> bool:
    lowered = (query or "").lower()
    triggers = (
        "latest contact",
        "newest contact",
        "new contact",
        "most recent contact",
        "latest customer",
        "newest customer",
        "new customer in crm",
        "last customer",
        "from crm",
    )
    return any(t in lowered for t in triggers)


zoho_new_customer_agent = ZohoNewCustomerAgent()

__all__ = ["ZohoNewCustomerAgent", "zoho_new_customer_agent"]
