"""
Per-user rate limiter for the Telegram Bot.

Adapted from ``server/agents/JIRA_agent/utils/rate_limiter.py``.
Uses a sliding-window token-bucket algorithm with async locking.
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, List

from . import config

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when a user exceeds their rate limit."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.1f}s")


class RateLimiter:
    """Sliding-window rate limiter.

    Tracks requests per key (e.g. Telegram user ID) and raises
    ``RateLimitExceeded`` when the budget is exhausted.
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, key: str = "global") -> None:
        """Check if the request is within limits. Raises ``RateLimitExceeded`` otherwise."""
        async with self._lock:
            now = time.monotonic()
            window_start = now - self.window_seconds

            self._requests[key] = [
                t for t in self._requests[key] if t > window_start
            ]

            if len(self._requests[key]) >= self.max_requests:
                oldest = self._requests[key][0]
                retry_after = oldest + self.window_seconds - now
                logger.warning(
                    "Rate limit hit for key=%s (%d/%d in %.0fs)",
                    key, len(self._requests[key]), self.max_requests, self.window_seconds,
                )
                raise RateLimitExceeded(retry_after=max(retry_after, 0.1))

            self._requests[key].append(now)

    def cleanup(self) -> int:
        """Remove expired entries. Returns number of keys removed."""
        now = time.monotonic()
        window_start = now - self.window_seconds
        expired_keys = []
        for key, timestamps in self._requests.items():
            self._requests[key] = [t for t in timestamps if t > window_start]
            if not self._requests[key]:
                expired_keys.append(key)
        for key in expired_keys:
            del self._requests[key]
        return len(expired_keys)


# Module-level instances configured from env vars.
message_limiter = RateLimiter(
    max_requests=config.RATE_LIMIT_MESSAGES,
    window_seconds=config.RATE_LIMIT_WINDOW,
)
burst_limiter = RateLimiter(
    max_requests=config.RATE_LIMIT_BURST,
    window_seconds=config.RATE_LIMIT_BURST_WINDOW,
)


async def check_rate_limit(user_id: int) -> None:
    """Check both burst and sustained limits for a user. Raises ``RateLimitExceeded``."""
    key = str(user_id)
    await burst_limiter.check(key)
    await message_limiter.check(key)


def cleanup_all() -> int:
    """Cleanup expired entries from all limiters."""
    return message_limiter.cleanup() + burst_limiter.cleanup()
