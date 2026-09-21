"""Zoho workflow agents - one shared integration package, three thin agents.

Three business workflows are exposed as separate catalog agents:

* :class:`~.email_meeting_agent.ZohoEmailMeetingAgent` - meeting request email to
  calendar event, confirmation mail and CRM task.
* :class:`~.support_ticket_agent.ZohoSupportTicketAgent` - high-priority Desk
  ticket to Cliq alert, CRM task and customer acknowledgement.
* :class:`~.new_customer_agent.ZohoNewCustomerAgent` - new CRM contact to welcome
  email, intro call and Cliq sales notification.

All three share ``config`` (data-center resolution), ``zoho_auth`` (token
refresh), ``zoho_client`` (authenticated HTTP) and ``services`` (per-product API
wrappers). Writes are gated by ``ZOHO_DRY_RUN`` / ``ZOHO_CONFIRM_WRITES``.

Agent classes are imported lazily so ``import agents.Zoho_workflow_agents``
stays cheap for the API's lazy agent loader.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .config import SCOPES, ZohoSettings, all_scopes, get_settings, normalize_dc
from .zoho_auth import ZohoAuthError
from .zoho_client import ZohoAPIError, ZohoClient

if TYPE_CHECKING:  # pragma: no cover
    from .email_meeting_agent import ZohoEmailMeetingAgent
    from .new_customer_agent import ZohoNewCustomerAgent
    from .support_ticket_agent import ZohoSupportTicketAgent

_LAZY = {
    "ZohoEmailMeetingAgent": ("email_meeting_agent", "ZohoEmailMeetingAgent"),
    "zoho_email_meeting_agent": ("email_meeting_agent", "zoho_email_meeting_agent"),
    "ZohoSupportTicketAgent": ("support_ticket_agent", "ZohoSupportTicketAgent"),
    "zoho_support_ticket_agent": ("support_ticket_agent", "zoho_support_ticket_agent"),
    "ZohoNewCustomerAgent": ("new_customer_agent", "ZohoNewCustomerAgent"),
    "zoho_new_customer_agent": ("new_customer_agent", "zoho_new_customer_agent"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    module = import_module(f"{__name__}.{module_name}")
    return getattr(module, attr)


__all__ = [
    "SCOPES",
    "ZohoAPIError",
    "ZohoAuthError",
    "ZohoClient",
    "ZohoEmailMeetingAgent",
    "ZohoNewCustomerAgent",
    "ZohoSettings",
    "ZohoSupportTicketAgent",
    "all_scopes",
    "get_settings",
    "normalize_dc",
    "zoho_email_meeting_agent",
    "zoho_new_customer_agent",
    "zoho_support_ticket_agent",
]
