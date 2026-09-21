"""Input/output guardrails for the MongoDB Atlas KB Agent.

Checks:
  - Input: empty query, length cap, null bytes, prompt injection patterns
  - Output: length cap, PII detection (SSN, credit card, email, phone)
  - Sanitise: strip control characters before processing
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# Prompt injection / jailbreak patterns
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKED = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?your\s+instructions",
    r"you\s+are\s+now\s+(a|an)\s+(?!assistant|helpful)",
    r"new\s+instructions?\s*:",
    r"system\s*prompt\s*:",
    r"<\s*/?system\s*>",
    r"(?:fetch|curl|wget)\s+https?://",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
    r"subprocess\.",
]

_PII_PATTERNS = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),
    (r"\b\d{16}\b", "Credit Card"),
    (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "Credit Card"),
    (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "Email"),
    (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "Phone"),
]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    is_valid: bool
    message: str = ""
    blocked_reason: Optional[str] = None
    pii_detected: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_input(query: str, settings: MongoRAGSettings) -> ValidationResult:
    if not settings.guardrails_enabled:
        return ValidationResult(is_valid=True)

    if not query or not query.strip():
        return ValidationResult(is_valid=False, message="Query cannot be empty.", blocked_reason="empty_query")

    if len(query) > settings.max_query_length:
        return ValidationResult(
            is_valid=False,
            message=f"Query exceeds maximum length of {settings.max_query_length} characters.",
            blocked_reason="query_too_long",
        )

    if "\x00" in query:
        return ValidationResult(is_valid=False, message="Query contains invalid characters.", blocked_reason="null_bytes")

    patterns = _DEFAULT_BLOCKED + (settings.blocked_input_patterns or [])
    lower = query.lower()
    for pat in patterns:
        try:
            if re.search(pat, lower, re.IGNORECASE):
                return ValidationResult(
                    is_valid=False,
                    message="Query contains blocked content.",
                    blocked_reason="blocked_pattern",
                )
        except re.error:
            continue

    return ValidationResult(is_valid=True)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(response: str, settings: MongoRAGSettings) -> ValidationResult:
    if not settings.guardrails_enabled:
        return ValidationResult(is_valid=True)

    if len(response) > settings.max_response_length:
        return ValidationResult(is_valid=False, message="Response exceeds maximum length.", blocked_reason="response_too_long")

    pii_found: List[str] = []
    if settings.pii_detection_enabled:
        for pattern, pii_type in _PII_PATTERNS:
            if re.search(pattern, response):
                pii_found.append(pii_type)

    return ValidationResult(is_valid=True, pii_detected=pii_found)


# ---------------------------------------------------------------------------
# Sanitise
# ---------------------------------------------------------------------------

def sanitize_query(query: str) -> str:
    """Strip control characters except newline and tab."""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', query).strip()
