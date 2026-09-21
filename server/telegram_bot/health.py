"""
Bot metrics and health reporting for the Telegram Bot.

Provides simple thread-safe counters and a ``health_report()`` callable
that the main API can query via ``/api/health``.
"""

import threading
import time
from collections import deque
from typing import Dict, Optional


class BotMetrics:
    """Thread-safe metrics collector for the Telegram bot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.start_time: float = time.time()
        self.messages_processed: int = 0
        self.commands_processed: int = 0
        self.errors: int = 0
        self.last_message_time: Optional[float] = None
        self._response_times: deque = deque(maxlen=100)

    def record_message(self, response_time_ms: float = 0.0) -> None:
        with self._lock:
            self.messages_processed += 1
            self.last_message_time = time.time()
            if response_time_ms > 0:
                self._response_times.append(response_time_ms)

    def record_command(self) -> None:
        with self._lock:
            self.commands_processed += 1
            self.last_message_time = time.time()

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def health_report(self) -> Dict:
        with self._lock:
            now = time.time()
            uptime = now - self.start_time
            total = self.messages_processed + self.commands_processed

            # Avg response time
            avg_response = 0.0
            if self._response_times:
                avg_response = sum(self._response_times) / len(self._response_times)

            # Last message age
            last_age: Optional[float] = None
            if self.last_message_time:
                last_age = now - self.last_message_time

            # Status determination
            status = "healthy"
            if total > 0 and self.errors / max(total, 1) > 0.10:
                status = "degraded"
            if uptime > 600 and (last_age is None or last_age > 600):
                # Up > 10 min but no message in 10 min — could be idle or down.
                # Don't mark as degraded if the bot simply has no traffic.
                pass

            return {
                "status": status,
                "uptime_seconds": round(uptime, 1),
                "messages_processed": self.messages_processed,
                "commands_processed": self.commands_processed,
                "total_requests": total,
                "errors": self.errors,
                "error_rate_pct": round(self.errors / max(total, 1) * 100, 2) if total else 0.0,
                "avg_response_time_ms": round(avg_response, 1),
                "last_message_age_seconds": round(last_age, 1) if last_age is not None else None,
            }


# Module-level singleton
metrics = BotMetrics()


def get_bot_health() -> Dict:
    """Callable from ``api.py`` to include in ``/api/health``."""
    return metrics.health_report()
