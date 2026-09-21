"""Retry decorator with exponential backoff for transient failures."""
import asyncio
import functools
from typing import Tuple, Type

from ..core.logging import log_warning, log_error


# Default transient exception types
TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

try:
    import httpx
    TRANSIENT_EXCEPTIONS = TRANSIENT_EXCEPTIONS + (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.ConnectTimeout,
    )
except ImportError:
    pass


def retry_async(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    transient_exceptions: Tuple[Type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    source: str = "retry",
):
    """Async retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        backoff_factor: Multiplier for each retry delay
        transient_exceptions: Tuple of exception types considered transient
        source: Logging source tag
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except transient_exceptions as exc:
                    last_exception = exc
                    if attempt == max_retries:
                        log_error(
                            f"All {max_retries} retries exhausted for {func.__name__}: {exc}",
                            source,
                        )
                        raise
                    delay = min(base_delay * (backoff_factor ** (attempt - 1)), max_delay)
                    log_warning(
                        f"Transient error in {func.__name__} (attempt {attempt}/{max_retries}), "
                        f"retrying in {delay:.1f}s: {exc}",
                        source,
                    )
                    await asyncio.sleep(delay)
            # Should not reach here, but just in case
            raise last_exception  # type: ignore

        return wrapper

    return decorator
