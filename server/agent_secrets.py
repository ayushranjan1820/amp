"""Secrets crypto for the Agent Builder.

Encrypts secret credentials in `agent_definitions.default_config` at rest, so
the database never holds plaintext API keys / tokens / passwords. Tools at
runtime see the decrypted plaintext via _inject_env(); the API surface returns
a redacted form (REDACTED_SENTINEL with a 4-char tail) so the browser never
receives a usable secret after the user types it.

Key derivation:
- AGENT_BUILDER_SECRET_KEY env var (recommended in production)
- Falls back to deriving from JWT_SECRET + CORE_SYSTEM_MONGO_DB so existing
  deployments keep working without explicit configuration
- The derived Fernet key is deterministic for a given env, so encrypted blobs
  remain readable across restarts
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

_log = logging.getLogger("agent_secrets")

ENC_PREFIX = "enc::v1::"          # marks a Fernet-encrypted value
REDACTED_SENTINEL = "__REDACTED__"  # what the API returns instead of plaintext
MASK_KEEP_TAIL = 4                # how many trailing chars to expose for hint UX

# Explicit allowlist of keys we always treat as secret (case-sensitive).
_ALWAYS_SECRET = {
    "OLLAMA_API_KEY",
    "PWC_GENAI_API_KEY",
    "PWC_GENAI_BEARER_TOKEN",
    "ELEVENLABS_API_KEY",
    "JIRA_API_TOKEN",
    "GITHUB_TOKEN",
    "SLACK_WEBHOOK_URL",
    "DATABASE_URL",
    "DATABASE_CONNECTION_STRING",
    "MONGODB_URI",
    "CORE_SYSTEM_MONGO_DB",
    "SMTP_PASSWORD",
    "ON_PREM_CLOUD_ACCESS_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "COHERE_API_KEY",
    "PERPLEXITY_API_KEY",
}

# Keys that look like creds but aren't, so the heuristic doesn't false-positive.
_NEVER_SECRET = {
    "LLM_PROVIDER",
    "PWC_GENAI_ENDPOINT_URL",
    "OLLAMA_HOST",
    "OLLAMA_CLOUD_URL",
    "LOCAL_LLM_URL",
    "LOCAL_LLM_N_GPU_LAYERS",
    "SMTP_HOST",
    "SMTP_USER",
    "JIRA_URL",
    "JIRA_EMAIL",
}

_SECRET_PATTERNS = re.compile(
    r"(_API_KEY$|_TOKEN$|_SECRET$|_PASSWORD$|_PASSWD$|_PWD$|_CREDENTIAL$|_PRIVATE_KEY$)",
    re.IGNORECASE,
)


def is_secret_key(key: str) -> bool:
    """True if `key` should be treated as a secret in default_config."""
    if not key:
        return False
    if key in _NEVER_SECRET:
        return False
    if key in _ALWAYS_SECRET:
        return True
    return bool(_SECRET_PATTERNS.search(key))


# ---------------------------------------------------------------------------
# Fernet key derivation
# ---------------------------------------------------------------------------

_fernet: Optional[Fernet] = None


def _derive_key() -> bytes:
    """Build a deterministic 32-byte key from env. Stable across restarts."""
    explicit = os.environ.get("AGENT_BUILDER_SECRET_KEY", "").strip()
    if explicit:
        # User-supplied: hash to 32 bytes so length doesn't matter
        return hashlib.sha256(explicit.encode("utf-8")).digest()

    # Fallback: derive from JWT_SECRET + the core MongoDB URI so an existing
    # deployment gets a stable key without explicit config. Add a static salt
    # so it isn't the raw JWT secret material.
    seed_parts = [
        os.environ.get("JWT_SECRET", ""),
        os.environ.get("CORE_SYSTEM_MONGO_DB", "") or os.environ.get("MONGODB_URI", ""),
        "agent-builder-secrets-v1",
    ]
    seed = "::".join(p for p in seed_parts if p)
    if not seed.strip("::"):
        # Genuinely empty environment — emit a warning but still produce a key.
        # This only applies in dev where no env vars are set.
        _log.warning(
            "agent_secrets: no AGENT_BUILDER_SECRET_KEY/JWT_SECRET/CORE_SYSTEM_MONGO_DB — "
            "encrypted blobs will not survive an env change."
        )
        seed = "agent-builder-default-development-key"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _fernet_instance() -> Fernet:
    global _fernet
    if _fernet is None:
        key = base64.urlsafe_b64encode(_derive_key())
        _fernet = Fernet(key)
    return _fernet


def reset_fernet_for_tests():
    """Test helper — re-derives the Fernet from current env."""
    global _fernet
    _fernet = None


# ---------------------------------------------------------------------------
# Encrypt / decrypt single values
# ---------------------------------------------------------------------------

def encrypt_value(plaintext: str) -> str:
    """Encrypt a string. Idempotent: already-encrypted values pass through."""
    if not isinstance(plaintext, str) or plaintext == "":
        return plaintext
    if plaintext.startswith(ENC_PREFIX):
        return plaintext  # already encrypted
    if plaintext == REDACTED_SENTINEL:
        # Caller sent back the redaction sentinel — treat as "no change"; the
        # registry layer should detect this and skip the field, but encrypting
        # it would corrupt the value, so refuse here too.
        return plaintext
    token = _fernet_instance().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_value(value: str) -> str:
    """Decrypt a string; pass through if not encrypted."""
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    try:
        token = value[len(ENC_PREFIX):]
        return _fernet_instance().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        _log.error(
            "agent_secrets: failed to decrypt a secret. The encryption key has "
            "likely changed — re-enter the credential in the UI."
        )
        return ""
    except Exception as e:
        _log.error("agent_secrets: unexpected decrypt error: %s", e)
        return ""


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


# ---------------------------------------------------------------------------
# default_config helpers
# ---------------------------------------------------------------------------

def encrypt_default_config(
    config: Optional[Dict[str, Any]],
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a copy of `config` with secret values encrypted.

    - Plaintext secrets → encrypted blob
    - REDACTED_SENTINEL → keep the existing encrypted value (caller didn't change it)
    - Empty string → drop the key (user cleared it)
    - Already-encrypted value → pass through
    - Non-secret keys → pass through unchanged
    """
    if not config:
        return {}
    existing = existing or {}
    out: Dict[str, Any] = {}
    for k, v in config.items():
        if not isinstance(v, str):
            out[k] = v
            continue
        if v == "":
            # User cleared the field — drop entirely (don't store empty secrets)
            continue
        if v == REDACTED_SENTINEL:
            # Frontend echoed back a redacted value — preserve what's already in DB
            existing_v = existing.get(k)
            if existing_v:
                out[k] = existing_v
            continue
        if is_secret_key(k):
            out[k] = encrypt_value(v)
        else:
            out[k] = v
    return out


def decrypt_default_config(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return a copy with all encrypted values decrypted (for runtime use)."""
    if not config:
        return {}
    return {k: (decrypt_value(v) if isinstance(v, str) else v) for k, v in config.items()}


def redact_default_config(config: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Return (redacted_config, meta).

    - Secret values become REDACTED_SENTINEL so the browser never sees plaintext.
    - meta[key] = {"is_set": bool, "tail": last 4 chars of plaintext or ""}.
      The tail gives users a hint that the right secret is set without exposing it.
    - Non-secret keys pass through unchanged.
    """
    if not config:
        return {}, {}
    redacted: Dict[str, Any] = {}
    meta: Dict[str, Dict[str, Any]] = {}
    for k, v in config.items():
        if not isinstance(v, str):
            redacted[k] = v
            continue
        if is_secret_key(k):
            plain = decrypt_value(v) if v.startswith(ENC_PREFIX) else v
            tail = plain[-MASK_KEEP_TAIL:] if len(plain) > MASK_KEEP_TAIL else ""
            redacted[k] = REDACTED_SENTINEL if plain else ""
            meta[k] = {"is_set": bool(plain), "tail": tail, "secret": True}
        else:
            redacted[k] = v
            meta[k] = {"is_set": bool(v), "secret": False}
    return redacted, meta
