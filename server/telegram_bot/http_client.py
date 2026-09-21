"""
Shared httpx.AsyncClient with connection pooling and retry for the Telegram Bot.

Provides a module-level client that is lazily initialized and reused across all
requests, replacing per-request client creation.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

from . import config

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None
_lock = asyncio.Lock()

# Transient HTTP status codes that warrant a retry.
_TRANSIENT_STATUS_CODES = frozenset({429, 502, 503, 504})
_MAX_RETRIES = 3
_BASE_DELAY = 1.0
_MAX_DELAY = 15.0
_BACKOFF_FACTOR = 2.0


async def get_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient, creating it on first call."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _lock:
        if _client is not None and not _client.is_closed:
            return _client
        limits = httpx.Limits(
            max_connections=config.HTTP_MAX_CONNECTIONS,
            max_keepalive_connections=config.HTTP_MAX_KEEPALIVE,
        )
        _client = httpx.AsyncClient(limits=limits)
        logger.info(
            "HTTP client initialized (pool: max=%d, keepalive=%d)",
            config.HTTP_MAX_CONNECTIONS,
            config.HTTP_MAX_KEEPALIVE,
        )
        return _client


async def close_client() -> None:
    """Close the shared client. Call during graceful shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        logger.info("HTTP client closed")
    _client = None


async def post_with_retry(
    url: str,
    *,
    json: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> httpx.Response:
    """POST with automatic retry on transient errors."""
    client = await get_client()
    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.post(
                url, json=json, headers=headers, timeout=timeout,
            )
            if response.status_code not in _TRANSIENT_STATUS_CODES:
                return response
            if attempt == _MAX_RETRIES:
                return response
            retry_after = _get_retry_delay(attempt, response)
            logger.warning(
                "Transient HTTP %d on POST %s (attempt %d/%d), retrying in %.1fs",
                response.status_code, url, attempt, _MAX_RETRIES, retry_after,
            )
            await asyncio.sleep(retry_after)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            last_exc = exc
            if attempt == _MAX_RETRIES:
                raise
            delay = min(_BASE_DELAY * (_BACKOFF_FACTOR ** (attempt - 1)), _MAX_DELAY)
            logger.warning(
                "Transient %s on POST %s (attempt %d/%d), retrying in %.1fs",
                type(exc).__name__, url, attempt, _MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker.
    if last_exc:
        raise last_exc
    raise httpx.HTTPError("Exhausted retries")


async def get_with_retry(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> httpx.Response:
    """GET with automatic retry on transient errors."""
    client = await get_client()
    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = await client.get(url, headers=headers, timeout=timeout)
            if response.status_code not in _TRANSIENT_STATUS_CODES:
                return response
            if attempt == _MAX_RETRIES:
                return response
            retry_after = _get_retry_delay(attempt, response)
            logger.warning(
                "Transient HTTP %d on GET %s (attempt %d/%d), retrying in %.1fs",
                response.status_code, url, attempt, _MAX_RETRIES, retry_after,
            )
            await asyncio.sleep(retry_after)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                httpx.WriteTimeout, httpx.PoolTimeout) as exc:
            last_exc = exc
            if attempt == _MAX_RETRIES:
                raise
            delay = min(_BASE_DELAY * (_BACKOFF_FACTOR ** (attempt - 1)), _MAX_DELAY)
            logger.warning(
                "Transient %s on GET %s (attempt %d/%d), retrying in %.1fs",
                type(exc).__name__, url, attempt, _MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)

    if last_exc:
        raise last_exc
    raise httpx.HTTPError("Exhausted retries")


def _get_retry_delay(attempt: int, response: httpx.Response) -> float:
    """Compute retry delay from Retry-After header or exponential backoff."""
    retry_after_hdr = response.headers.get("Retry-After")
    if retry_after_hdr:
        try:
            return min(float(retry_after_hdr), _MAX_DELAY)
        except (ValueError, TypeError):
            pass
    return min(_BASE_DELAY * (_BACKOFF_FACTOR ** (attempt - 1)), _MAX_DELAY)
