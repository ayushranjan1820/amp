"""Simple in-memory rate limiter for JIRA agent endpoints."""
import time
import asyncio
from collections import defaultdict
from typing import Optional

from ..core.logging import log_warning


class RateLimitExceeded(Exception):
    """Raised when a rate limit is exceeded."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.1f}s")


class RateLimiter:
    """Token-bucket rate limiter.

    Tracks requests per key (e.g. session_id or IP) using a sliding window.

    Args:
        max_requests: Maximum number of requests allowed in the window
        window_seconds: Time window in seconds
    """

    def __init__(self, max_requests: int = 30, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, key: str = "global") -> None:
        """Check if the request is allowed under the rate limit.

        Args:
            key: Identifier for the rate limit bucket (e.g. session_id, IP)

        Raises:
            RateLimitExceeded: If the rate limit has been exceeded
        """
        async with self._lock:
            now = time.monotonic()
            window_start = now - self.window_seconds

            # Prune old entries
            self._requests[key] = [
                t for t in self._requests[key] if t > window_start
            ]

            if len(self._requests[key]) >= self.max_requests:
                oldest = self._requests[key][0]
                retry_after = oldest + self.window_seconds - now
                log_warning(
                    f"Rate limit exceeded for key={key} "
                    f"({len(self._requests[key])}/{self.max_requests} in {self.window_seconds}s)",
                    "rate_limiter",
                )
                raise RateLimitExceeded(retry_after=max(retry_after, 0.1))

            self._requests[key].append(now)

    def cleanup(self) -> int:
        """Remove expired entries. Returns number of keys cleaned up."""
        now = time.monotonic()
        window_start = now - self.window_seconds
        cleaned = 0
        expired_keys = []
        for key, timestamps in self._requests.items():
            self._requests[key] = [t for t in timestamps if t > window_start]
            if not self._requests[key]:
                expired_keys.append(key)
                cleaned += 1
        for key in expired_keys:
            del self._requests[key]
        return cleaned


# Global rate limiters
agent_rate_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
agent_burst_limiter = RateLimiter(max_requests=5, window_seconds=5.0)
