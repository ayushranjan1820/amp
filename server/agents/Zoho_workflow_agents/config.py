"""Zoho platform configuration — data-center resolution and shared settings.

Zoho serves every product from region-specific domains, so a single hard-coded
``.com`` host breaks for EU / IN / AU / JP / CA / CN / SA tenants. Everything in
this package resolves its base URL through :class:`ZohoSettings`.

All values are read from the environment at call time (never cached at import)
because the marketplace injects per-user agent credentials into ``os.environ``
around each request.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List

# ---------------------------------------------------------------------------
# Data centers
# ---------------------------------------------------------------------------

# Zoho DC key -> domain suffix used by every Zoho product host.
DC_SUFFIXES: Dict[str, str] = {
    "us": "com",
    "com": "com",
    "eu": "eu",
    "in": "in",
    "au": "com.au",
    "jp": "jp",
    "ca": "ca",
    "cn": "com.cn",
    "sa": "sa",
}

DEFAULT_DC = "us"

# OAuth scopes required by the three workflow agents, grouped per product so a
# tenant can grant only what it needs.
SCOPES: Dict[str, List[str]] = {
    "mail": [
        "ZohoMail.messages.ALL",
        "ZohoMail.accounts.READ",
        "ZohoMail.folders.READ",
    ],
    "calendar": [
        "ZohoCalendar.event.ALL",
        "ZohoCalendar.calendar.READ",
    ],
    "crm": [
        "ZohoCRM.modules.ALL",
        "ZohoCRM.settings.READ",
        "ZohoCRM.users.READ",
    ],
    "projects": ["ZohoProjects.tasks.CREATE"],
    "desk": [
        "Desk.tickets.READ",
        "Desk.tickets.UPDATE",
        "Desk.contacts.READ",
        "Desk.basic.READ",
    ],
    "cliq": [
        "ZohoCliq.Webhooks.CREATE",
        "ZohoCliq.Channels.READ",
        "ZohoCliq.Chats.CREATE",
    ],
}


def all_scopes() -> str:
    """Space-separated scope string covering every product used by the agents."""
    flat: List[str] = []
    for group in SCOPES.values():
        for scope in group:
            if scope not in flat:
                flat.append(scope)
    return " ".join(flat)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def normalize_dc(value: str) -> str:
    """Map a user-supplied data-center hint to a known DC key."""
    dc = (value or "").strip().lower()
    if not dc:
        return DEFAULT_DC
    # Accept full domains ("accounts.zoho.eu"), suffixes ("com.au") and keys.
    for key, suffix in DC_SUFFIXES.items():
        if dc == key or dc == suffix or dc.endswith(f".zoho.{suffix}"):
            return "us" if key == "com" else key
    return DEFAULT_DC


@dataclass
class ZohoSettings:
    """Resolved Zoho configuration for a single request.

    Build with :meth:`from_env` so per-user credentials injected into the
    environment are honoured.
    """

    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    access_token: str = ""
    token_expires_at: int = 0
    dc: str = DEFAULT_DC
    accounts_base_url: str = ""
    org_id: str = ""

    # MCP transport. When a Zoho MCP connection URL is present, the connection
    # itself is pre-authorized ("Authorization via Connection"), so no client
    # id, secret or refresh token is needed on this side.
    mcp_url: str = ""

    # Workflow defaults
    calendar_id: str = ""
    projects_portal_id: str = ""
    projects_project_id: str = ""
    crm_owner_id: str = ""
    cliq_channel: str = ""
    cliq_webhook_url: str = ""
    desk_department_id: str = ""
    timezone: str = "Asia/Kolkata"
    meeting_duration_minutes: int = 30
    from_address: str = ""
    dry_run: bool = True

    _raw: Dict[str, str] = field(default_factory=dict, repr=False)

    # -- construction ----------------------------------------------------
    @classmethod
    def from_env(cls) -> "ZohoSettings":
        dc = normalize_dc(_env("ZOHO_DC", DEFAULT_DC))
        try:
            duration = int(_env("ZOHO_MEETING_DURATION_MINUTES", "30") or "30")
        except ValueError:
            duration = 30
        try:
            expires_at = int(float(_env("ZOHO_TOKEN_EXPIRES_AT", "0") or "0"))
        except ValueError:
            expires_at = 0

        return cls(
            client_id=_env("ZOHO_CLIENT_ID"),
            client_secret=_env("ZOHO_CLIENT_SECRET"),
            refresh_token=_env("ZOHO_REFRESH_TOKEN"),
            access_token=_env("ZOHO_ACCESS_TOKEN"),
            token_expires_at=expires_at,
            dc=dc,
            accounts_base_url=_env("ZOHO_ACCOUNTS_BASE_URL"),
            org_id=_env("ZOHO_ORG_ID"),
            mcp_url=_env("ZOHO_MCP_URL") or _env("ZOHO_MCP_SERVER_URL"),
            calendar_id=_env("ZOHO_CALENDAR_ID"),
            projects_portal_id=_env("ZOHO_PROJECTS_PORTAL_ID"),
            projects_project_id=_env("ZOHO_PROJECTS_PROJECT_ID"),
            crm_owner_id=_env("ZOHO_CRM_OWNER_ID"),
            cliq_channel=_env("ZOHO_CLIQ_CHANNEL"),
            cliq_webhook_url=_env("ZOHO_CLIQ_WEBHOOK_URL"),
            desk_department_id=_env("ZOHO_DESK_DEPARTMENT_ID"),
            timezone=_env("ZOHO_TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata",
            meeting_duration_minutes=max(5, duration),
            from_address=_env("ZOHO_FROM_ADDRESS"),
            # Writes are OFF by default: these workflows send real mail and
            # create real records. An operator opts in explicitly.
            dry_run=_env_bool("ZOHO_DRY_RUN", True) or not _env_bool("ZOHO_CONFIRM_WRITES", False),
        )

    # -- derived hosts ---------------------------------------------------
    @property
    def suffix(self) -> str:
        return DC_SUFFIXES.get(self.dc, "com")

    @property
    def accounts_url(self) -> str:
        if self.accounts_base_url:
            return self.accounts_base_url.rstrip("/")
        return f"https://accounts.zoho.{self.suffix}"

    @property
    def token_url(self) -> str:
        return f"{self.accounts_url}/oauth/v2/token"

    @property
    def authorize_url(self) -> str:
        return f"{self.accounts_url}/oauth/v2/auth"

    @property
    def mail_base(self) -> str:
        return f"https://mail.zoho.{self.suffix}/api"

    @property
    def calendar_base(self) -> str:
        return f"https://calendar.zoho.{self.suffix}/api/v1"

    @property
    def crm_base(self) -> str:
        return f"https://www.zohoapis.{self.suffix}/crm/v6"

    @property
    def projects_base(self) -> str:
        return f"https://projectsapi.zoho.{self.suffix}/restapi"

    @property
    def desk_base(self) -> str:
        return f"https://desk.zoho.{self.suffix}/api/v1"

    @property
    def cliq_base(self) -> str:
        return f"https://cliq.zoho.{self.suffix}/api/v2"

    # -- transport -------------------------------------------------------
    @property
    def backend(self) -> str:
        """``"mcp"`` when an MCP connection URL is configured, else ``"rest"``.

        Set ``ZOHO_BACKEND=rest`` to force direct REST even with an MCP URL present.
        """
        forced = _env("ZOHO_BACKEND").lower()
        if forced in ("rest", "mcp"):
            return forced
        return "mcp" if self.mcp_url else "rest"

    @property
    def uses_mcp(self) -> bool:
        return self.backend == "mcp"

    # -- validation ------------------------------------------------------
    def missing_credentials(self) -> List[str]:
        """Credential keys needed before any live Zoho call can be made.

        In MCP mode the connection holds the authorization for every Zoho
        service, so the only requirement on this side is the connection URL.
        """
        if self.backend == "mcp":
            return [] if self.mcp_url else ["ZOHO_MCP_URL"]

        missing: List[str] = []
        if not self.client_id:
            missing.append("ZOHO_CLIENT_ID")
        if not self.client_secret:
            missing.append("ZOHO_CLIENT_SECRET")
        if not self.refresh_token and not self.access_token:
            missing.append("ZOHO_REFRESH_TOKEN")
        return missing

    def is_configured(self) -> bool:
        return not self.missing_credentials()


def get_settings() -> ZohoSettings:
    """Read Zoho settings from the current environment."""
    return ZohoSettings.from_env()


__all__ = [
    "DC_SUFFIXES",
    "DEFAULT_DC",
    "SCOPES",
    "ZohoSettings",
    "all_scopes",
    "get_settings",
    "normalize_dc",
]
