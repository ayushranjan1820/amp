"""Request-scoped configuration via contextvars.

Replaces global os.environ mutation with per-request config isolation.
This allows concurrent requests to the SAME agent type without serialization.

Usage in agent code:
    from request_config import get_config_value
    api_key = get_config_value("PWC_GENAI_API_KEY")  # checks request scope first, then os.environ
"""
import contextvars
import os
import threading
from contextlib import contextmanager
from typing import Dict, Optional

# Per-request config: each async task / thread gets its own dict
_request_config: contextvars.ContextVar[Optional[Dict[str, str]]] = contextvars.ContextVar(
    "request_config", default=None
)


def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a config value: request-scoped config first, then os.environ fallback.

    This is the primary function agents should use instead of os.environ[key] or os.getenv(key).
    """
    cfg = _request_config.get()
    if cfg is not None and key in cfg:
        return cfg[key]
    return os.environ.get(key, default)


def get_request_config() -> Optional[Dict[str, str]]:
    """Return the full request-scoped config dict, or None if not in a request scope."""
    return _request_config.get()


@contextmanager
def scoped_request_config(config: Dict[str, str]):
    """Context manager that sets request-scoped config for the current task/thread.

    Nests safely — inner scopes override outer scopes for the duration.
    """
    token = _request_config.set(dict(config) if config else {})
    try:
        yield
    finally:
        _request_config.reset(token)
