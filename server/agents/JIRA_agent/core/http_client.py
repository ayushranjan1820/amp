"""Shared, long-lived HTTP client for JIRA API calls.

Enterprise improvements over per-request ``httpx.AsyncClient()``:
- Connection pooling (reuses TCP/TLS connections)
- Configurable timeouts & concurrency limits
- Automatic retry with exponential backoff for transient errors (429, 502, 503, 504)
- Circuit breaker to prevent cascading failures
- Centralised auth header injection via AuthProvider
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

import httpx

from .auth import AuthProvider
from .logging import log_info, log_warning, log_error

# ------------------------------------------------------------------ #
# Default HTTP configuration
# ------------------------------------------------------------------ #

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=30.0,
    write=10.0,
    pool=10.0,
)

DEFAULT_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
)

# Retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 30.0
RETRY_BACKOFF = 2.0
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# Circuit breaker settings
CB_FAILURE_THRESHOLD = 5       # consecutive failures to trip
CB_RECOVERY_TIMEOUT = 60.0     # seconds before half-open probe


class CircuitOpen(Exception):
    """Raised when the circuit breaker is open and requests are rejected."""


class _CircuitBreaker:
    """Minimal circuit breaker: closed -> open -> half-open -> closed."""

    def __init__(self, failure_threshold: int = CB_FAILURE_THRESHOLD, recovery_timeout: float = CB_RECOVERY_TIMEOUT):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"  # closed | open | half_open

    def record_success(self):
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = "open"
            log_warning(
                f"Circuit breaker OPEN after {self._failure_count} consecutive failures",
                "http_client",
            )

    def allow_request(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = "half_open"
                log_info("Circuit breaker HALF-OPEN — allowing probe request", "http_client")
                return True
            return False
        # half_open — allow one probe
        return True

    @property
    def state(self) -> str:
        return self._state


# ------------------------------------------------------------------ #
# Shared JIRA HTTP Client
# ------------------------------------------------------------------ #

class JiraHttpClient:
    """Enterprise-grade HTTP client for JIRA REST API.

    Wraps ``httpx.AsyncClient`` with connection pooling, retry, circuit
    breaker, and centralised auth-header injection.
    """

    def __init__(
        self,
        base_url: str,
        auth_provider: AuthProvider,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        limits: httpx.Limits = DEFAULT_LIMITS,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth_provider
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout
        self._limits = limits
        self._cb = _CircuitBreaker()

    # -- lifecycle ----------------------------------------------------- #

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                limits=self._limits,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- internal helpers ---------------------------------------------- #

    def _build_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        headers.update(self._auth.get_auth_headers())
        if extra:
            headers.update(extra)
        return headers

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute an HTTP request with retry and circuit breaker."""
        if not self._cb.allow_request():
            raise CircuitOpen(
                f"Circuit breaker is OPEN for {self._base_url}. "
                f"Requests blocked for {CB_RECOVERY_TIMEOUT}s after {CB_FAILURE_THRESHOLD} failures."
            )

        client = await self._ensure_client()
        headers = self._build_headers(extra_headers)
        last_exc: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )

                # Retry on transient HTTP status codes
                if response.status_code in RETRYABLE_STATUS_CODES:
                    retry_after = _parse_retry_after(response)
                    if attempt < MAX_RETRIES:
                        delay = retry_after or min(
                            RETRY_BASE_DELAY * (RETRY_BACKOFF ** (attempt - 1)),
                            RETRY_MAX_DELAY,
                        )
                        log_warning(
                            f"HTTP {response.status_code} on {method} {path} "
                            f"(attempt {attempt}/{MAX_RETRIES}), retrying in {delay:.1f}s",
                            "http_client",
                        )
                        await asyncio.sleep(delay)
                        continue
                    # Last attempt — fall through and return the error response
                    self._cb.record_failure()
                    return response

                self._cb.record_success()
                return response

            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout,
                    httpx.PoolTimeout, httpx.ConnectTimeout, ConnectionError,
                    TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    delay = min(
                        RETRY_BASE_DELAY * (RETRY_BACKOFF ** (attempt - 1)),
                        RETRY_MAX_DELAY,
                    )
                    log_warning(
                        f"Transient error on {method} {path} "
                        f"(attempt {attempt}/{MAX_RETRIES}): {exc}, retrying in {delay:.1f}s",
                        "http_client",
                    )
                    await asyncio.sleep(delay)
                else:
                    self._cb.record_failure()
                    log_error(
                        f"All {MAX_RETRIES} retries exhausted for {method} {path}",
                        "http_client",
                        exc,
                    )
                    raise

        # Should not be reached — final attempt either returns or raises above
        raise last_exc  # type: ignore[misc]

    # -- public convenience methods ------------------------------------ #

    async def get(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        return await self._request_with_retry("GET", path, params=params)

    async def post(self, path: str, *, json_body: Any = None) -> httpx.Response:
        return await self._request_with_retry("POST", path, json_body=json_body)

    async def put(self, path: str, *, json_body: Any = None) -> httpx.Response:
        return await self._request_with_retry("PUT", path, json_body=json_body)

    async def delete(self, path: str) -> httpx.Response:
        return await self._request_with_retry("DELETE", path)

    @property
    def circuit_state(self) -> str:
        return self._cb.state


def _parse_retry_after(response: httpx.Response) -> Optional[float]:
    """Parse the Retry-After header if present."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None
