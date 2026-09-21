"""Centralized authentication providers for JIRA API.

Supports multiple enterprise auth schemes:
- Basic Auth (email + API token)
- OAuth 2.0 (3-legged OAuth for Jira Cloud)
- Personal Access Token (PAT) for Jira Data Center / Server

Usage:
    provider = create_auth_provider(settings)
    headers = provider.get_auth_headers()
"""
from __future__ import annotations

import abc
import base64
import time
from typing import Dict, Optional

from .logging import log_info, log_warning


class AuthProvider(abc.ABC):
    """Abstract base for JIRA authentication providers."""

    @abc.abstractmethod
    def get_auth_headers(self) -> Dict[str, str]:
        """Return authentication headers to attach to every JIRA request."""

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return True if credentials are present and usable."""

    @property
    def scheme(self) -> str:
        return self.__class__.__name__


class BasicAuthProvider(AuthProvider):
    """HTTP Basic Auth using email + API token (Jira Cloud)."""

    def __init__(self, email: str, api_token: str):
        self._email = email
        self._api_token = api_token
        self._cached_header: Optional[str] = None

    def get_auth_headers(self) -> Dict[str, str]:
        if self._cached_header is None:
            raw = f"{self._email}:{self._api_token}".encode()
            self._cached_header = f"Basic {base64.b64encode(raw).decode()}"
        return {"Authorization": self._cached_header}

    def is_configured(self) -> bool:
        return bool(self._email and self._api_token)


class OAuthProvider(AuthProvider):
    """OAuth 2.0 (3LO) bearer token for Jira Cloud.

    Accepts an access token and optional refresh callback.  When the token
    expires the provider calls ``refresh_fn`` automatically.
    """

    def __init__(
        self,
        access_token: str,
        expires_at: float = 0.0,
        refresh_fn=None,
    ):
        self._access_token = access_token
        self._expires_at = expires_at
        self._refresh_fn = refresh_fn

    def get_auth_headers(self) -> Dict[str, str]:
        if self._expires_at and time.time() >= self._expires_at - 30:
            self._rotate()
        return {"Authorization": f"Bearer {self._access_token}"}

    def _rotate(self):
        if self._refresh_fn is None:
            log_warning("OAuth token expired and no refresh_fn configured", "auth")
            return
        log_info("Refreshing OAuth access token", "auth")
        result = self._refresh_fn()
        self._access_token = result["access_token"]
        self._expires_at = result.get("expires_at", 0.0)

    def is_configured(self) -> bool:
        return bool(self._access_token)


class PATProvider(AuthProvider):
    """Personal Access Token for Jira Data Center / Server."""

    def __init__(self, token: str):
        self._token = token

    def get_auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def is_configured(self) -> bool:
        return bool(self._token)


# ------------------------------------------------------------------ #
# Factory
# ------------------------------------------------------------------ #

def create_auth_provider(settings) -> AuthProvider:
    """Create the appropriate AuthProvider from application settings.

    Selection priority:
    1. OAuth 2.0 if ``jira_oauth_access_token`` is set
    2. PAT if ``jira_pat`` is set
    3. Basic Auth (default)
    """
    oauth_token = getattr(settings, "jira_oauth_access_token", "")
    pat = getattr(settings, "jira_pat", "")

    if oauth_token:
        log_info("Using OAuth 2.0 auth provider", "auth")
        return OAuthProvider(access_token=oauth_token)

    if pat:
        log_info("Using PAT auth provider", "auth")
        return PATProvider(token=pat)

    log_info("Using Basic Auth provider", "auth")
    return BasicAuthProvider(
        email=settings.jira_email,
        api_token=settings.jira_api_token,
    )
