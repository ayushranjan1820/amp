"""Typed service wrappers around the Zoho product APIs used by the workflows."""

from .calendar_service import ZohoCalendarService, to_zoho_datetime
from .cliq_service import ZohoCliqService
from .crm_service import ZohoCRMService
from .desk_service import ESCALATION_PRIORITIES, ZohoDeskService
from .mail_service import ZohoMailService, looks_like_html, strip_html, to_plain_text

__all__ = [
    "ESCALATION_PRIORITIES",
    "ZohoCRMService",
    "ZohoCalendarService",
    "ZohoCliqService",
    "ZohoDeskService",
    "ZohoMailService",
    "looks_like_html",
    "strip_html",
    "to_plain_text",
    "to_zoho_datetime",
]
