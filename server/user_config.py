"""Utility to apply user-provided configuration as environment variable overrides."""
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from request_config import scoped_request_config

# PwC GenAI credentials must come only from merged agent config (catalog defaults + client),
# never from server/.env. These names are stripped after any dotenv load and are not restored
# from the process environment after a scoped request.
PWC_GENAI_CONFIG_KEYS = ("PWC_GENAI_API_KEY", "PWC_GENAI_BEARER_TOKEN")


def _llm_env_key_agent_config_only(key: str) -> bool:
    """True when this env name must not fall back to process/.env under isolate_catalog_environment."""
    if key in ("LLM_PROVIDER", "USE_LOCAL_LLM", "OLLAMA_HOST", "DEFAULT_LLM_PROVIDER"):
        return True
    if key.startswith("PWC_GENAI_") or key.startswith("GEMINI_"):
        return True
    if key.startswith("OLLAMA_CLOUD_"):
        return True
    if key.startswith("LOCAL_LLM_"):
        return True
    return False

# Langfuse tracing / host credentials — never override from per-request ``user_config``
# when using the non-catalog env merge path, so MCP/UI headers cannot disable tracing
# or repoint the server process to another project. Agents that take Langfuse API
# keys from the catalog still receive them via ``isolate_catalog_environment``.
_SERVER_OBSERVABILITY_ENV_KEYS = frozenset(
    {
        "LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_BASE_URL",
    }
)


def scrub_pwc_genai_credentials_from_environ() -> None:
    """Remove PwC GenAI credential env vars (e.g. after load_dotenv)."""
    for k in PWC_GENAI_CONFIG_KEYS:
        os.environ.pop(k, None)


def load_dotenv_then_scrub_pwc(*args, **kwargs) -> bool:
    """Load ``.env`` then strip PwC GenAI keys so they cannot be sourced from disk."""
    from dotenv import load_dotenv

    result = load_dotenv(*args, **kwargs)
    scrub_pwc_genai_credentials_from_environ()
    return result


def _load_catalog() -> dict:
    """Load the live agents catalog from MongoDB (``agents_catalog_db``).

    ``agents_catalog.json`` is only a one-time seed for that collection (see
    its module docstring) — reading the file directly here meant admin-saved
    ``default_config`` (e.g. an agent's own PWC GenAI key, set through the
    Agent Marketplace UI) was silently invisible to every catalog-driven
    credential lookup below, since the UI saves to MongoDB, not this file.
    """
    from agents_catalog_db import get_catalog

    try:
        return get_catalog(required=False)
    except Exception:
        return {}


def with_server_config_status(agent: Dict[str, Any]) -> Dict[str, Any]:
    if agent.get("id") not in {
        "zoho_email_meeting_agent", "zoho_support_ticket_agent", "zoho_new_customer_agent",
    }:
        return agent
    configuration = agent.get("configuration") or {}
    settings = configuration.get("required_settings", []) + configuration.get("optional_settings", [])
    keys = sorted({
        setting["key"] for setting in settings
        if setting.get("key", "").startswith("ZOHO_")
        and os.environ.get(setting["key"], "").strip()
    })
    return {**agent, "server_configured_keys": keys}


def get_default_config_for_agent(agent_name: str) -> Dict[str, str]:
    """Look up default_config for an agent by its display name in the catalog."""
    catalog = _load_catalog()
    for agent in catalog.get("agents", []):
        if agent.get("name") == agent_name:
            return agent.get("default_config") or {}
    return {}


def get_catalog_env_keys_for_agent(agent_display_name: str) -> List[str]:
    """Env var names for one agent: catalog configuration + default_config keys (deduped, stable order)."""
    catalog = _load_catalog()
    seen: Dict[str, None] = {}
    ordered: List[str] = []

    def _add(k: str) -> None:
        if k and isinstance(k, str) and k not in seen:
            seen[k] = None
            ordered.append(k)

    for agent in catalog.get("agents", []):
        if agent.get("name") != agent_display_name:
            continue
        cfg = agent.get("configuration") or {}
        for s in cfg.get("required_settings") or []:
            _add(s.get("key") or "")
        for s in cfg.get("optional_settings") or []:
            _add(s.get("key") or "")
        for ev in cfg.get("environment_variables") or []:
            _add(ev.get("name") or "")
        for k in (agent.get("default_config") or {}):
            _add(k)
        break
    else:
        # No catalog row for this display name (e.g. Global Chat router SSE path).
        if agent_display_name == "Global Chat":
            for k in PWC_GENAI_CONFIG_KEYS:
                _add(k)
            for k in (
                "LLM_PROVIDER",
                "USE_LOCAL_LLM",
                "ON_PREM_CLOUD_ACCESS_TOKEN",
                "OLLAMA_CLOUD_BEARER_TOKEN",
                "ON_PREM_CLOUD_MODEL",
                "OLLAMA_CLOUD_URL",
            ):
                _add(k)
    return ordered


def get_agent_display_name_by_id(agent_id: str) -> Optional[str]:
    """Resolve catalog display ``name`` (e.g. ``JIRA Agent``) from ``agent`` id (e.g. ``jira_agent``)."""
    catalog = _load_catalog()
    for agent in catalog.get("agents", []):
        if agent.get("id") == agent_id:
            return agent.get("name")
    return None


def get_catalog_agent_by_display_name(agent_display_name: str) -> Optional[Dict[str, Any]]:
    """Return the catalog agent object (``agents_catalog.json`` row) for a display ``name``."""
    catalog = _load_catalog()
    for agent in catalog.get("agents", []):
        if agent.get("name") == agent_display_name:
            return agent
    return None


def merge_configs_for_agent_id(
    agent_id: str,
    user_config: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Like ``merge_configs`` but keyed by catalog ``agent_id`` instead of display name."""
    display = get_agent_display_name_by_id(agent_id)
    if not display:
        return {}
    return merge_configs(display, user_config)


def merge_configs(agent_name: str, user_config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Merge admin default_config (from catalog) with user_config.

    Admin defaults apply first. When ``user_config`` is present (client sent the object),
    an empty string for a key means the user cleared that field: the key is removed and
    does not fall back to admin for that key.

    When ``user_config`` is ``None`` (field omitted), only admin defaults are returned.

    Values are never read from ``server/.env`` here for PwC GenAI keys (those are stripped
    after any dotenv load). With ``isolate_catalog_environment``, ``apply_user_config`` sets
    catalog keys from this merge when non-empty. LLM-related keys (PwC GenAI, Ollama Cloud,
    local LLM, ``LLM_PROVIDER``, etc.) do **not** fall back to the process environment when
    the merge has no value — only agent config applies. Other catalog keys may still use
    ``.env`` when the UI did not save that key.
    """
    admin = get_default_config_for_agent(agent_name)
    merged: Dict[str, str] = {}

    for k, v in admin.items():
        if v and isinstance(v, str) and v.strip():
            merged[k] = v.strip()

    if user_config is None:
        return merged

    for k, v in user_config.items():
        if not k:
            continue
        if isinstance(v, str) and v.strip():
            merged[k] = v.strip()
        else:
            merged.pop(k, None)

    return merged


def apply_auto_llm_provider_for_mcp(
    merged: Dict[str, str],
    catalog_agent: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Set ``LLM_PROVIDER`` when missing or blank so MCP / IDE headers match runnable credentials.

    Order: respect explicit ``LLM_PROVIDER``; legacy ``USE_LOCAL_LLM``; then infer from which
    credential groups are non-empty (Ollama cloud token → ``ollama_cloud``, PwC keys → ``pwc_genai``,
    local stack hints → ``local_llm``); finally catalog ``default_config.LLM_PROVIDER`` or
    ``pwc_genai``.
    """
    out = dict(merged)
    raw = (out.get("LLM_PROVIDER") or "").strip().lower()
    if raw in ("pwc_genai", "local_llm", "ollama_cloud"):
        return out

    leg = (out.get("USE_LOCAL_LLM") or "").strip().lower()
    if leg in ("true", "1", "yes"):
        out["LLM_PROVIDER"] = "local_llm"
        return out
    if leg in ("false", "0", "no"):
        out["LLM_PROVIDER"] = "pwc_genai"
        return out

    def _nz(key: str) -> str:
        return (out.get(key) or "").strip()

    ollama_cloud = bool(
        _nz("ON_PREM_CLOUD_ACCESS_TOKEN")
        or _nz("OLLAMA_CLOUD_BEARER_TOKEN")
        or _nz("OLLAMA_API_KEY")
    )
    pwc = bool(_nz("PWC_GENAI_API_KEY") or _nz("PWC_GENAI_BEARER_TOKEN"))
    local_hints = bool(
        _nz("OLLAMA_HOST")
        or _nz("LOCAL_LLM_URL")
        or _nz("LOCAL_LLM_MODEL")
        or _nz("LOCAL_LLM_BASE_URL")
    )

    if ollama_cloud:
        out["LLM_PROVIDER"] = "ollama_cloud"
    elif local_hints and not pwc:
        out["LLM_PROVIDER"] = "local_llm"
    elif pwc and not local_hints:
        out["LLM_PROVIDER"] = "pwc_genai"
    elif pwc and local_hints:
        admin = (catalog_agent or {}).get("default_config") or {}
        d = (admin.get("LLM_PROVIDER") or "").strip().lower()
        if d in ("pwc_genai", "local_llm", "ollama_cloud"):
            out["LLM_PROVIDER"] = d
        else:
            out["LLM_PROVIDER"] = "pwc_genai"
    else:
        admin = (catalog_agent or {}).get("default_config") or {}
        d = (admin.get("LLM_PROVIDER") or "").strip().lower()
        if d in ("pwc_genai", "local_llm", "ollama_cloud"):
            out["LLM_PROVIDER"] = d
        else:
            out["LLM_PROVIDER"] = "pwc_genai"
    return out


@contextmanager
def apply_user_config(
    merged_config: Optional[Dict[str, str]] = None,
    agent_cache: Optional[dict] = None,
    *,
    agent_display_name: Optional[str] = None,
    isolate_catalog_environment: bool = False,
):
    """Temporarily set env vars from merged config.

    If ``isolate_catalog_environment`` is True, only catalog-listed keys for this agent are
    touched for the duration of the request. A non-empty value in ``merged_config`` overrides
    the process environment. If there is no non-empty override, LLM-related keys (see
    ``_llm_env_key_agent_config_only``) are unset — they never fall back to ``server/.env``.
    For other catalog keys, the previous process value is restored when it was set at scope
    entry; otherwise the key is removed.

    If False, only keys present in ``merged_config`` are set; other env vars are unchanged.
    """
    merged = dict(merged_config or {})
    catalog_keys: List[str] = []
    if isolate_catalog_environment and agent_display_name:
        catalog_keys = get_catalog_env_keys_for_agent(agent_display_name)

    originals: Dict[str, Optional[str]] = {}
    use_catalog_scope = bool(catalog_keys)

    if use_catalog_scope:
        try:
            for key in catalog_keys:
                originals[key] = os.environ.get(key)
                val = merged.get(key)
                if val and isinstance(val, str) and val.strip():
                    os.environ[key] = val.strip()
                elif _llm_env_key_agent_config_only(key):
                    os.environ.pop(key, None)
                elif originals.get(key) is not None:
                    os.environ[key] = originals[key]
                else:
                    os.environ.pop(key, None)

            _clear_agent_settings_caches()
            if agent_cache:
                _refresh_cached_agent_settings(agent_cache)

            yield
        finally:
            for key in catalog_keys:
                if key in PWC_GENAI_CONFIG_KEYS:
                    os.environ.pop(key, None)
                    continue
                orig = originals.get(key)
                if orig is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = orig
            _clear_agent_settings_caches()
            if agent_cache:
                _refresh_cached_agent_settings(agent_cache)
        return

    if not merged:
        yield
        return

    try:
        for key, value in merged.items():
            if not key or not isinstance(value, str):
                continue
            if key in _SERVER_OBSERVABILITY_ENV_KEYS:
                continue
            originals[key] = os.environ.get(key)
            os.environ[key] = value

        _clear_agent_settings_caches()
        if agent_cache:
            _refresh_cached_agent_settings(agent_cache)

        yield
    finally:
        for key, orig in originals.items():
            if key in PWC_GENAI_CONFIG_KEYS:
                os.environ.pop(key, None)
            elif orig is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = orig
        _clear_agent_settings_caches()
        if agent_cache:
            _refresh_cached_agent_settings(agent_cache)


@contextmanager
def apply_user_config_concurrent(
    merged_config: Optional[Dict[str, str]] = None,
    agent_cache: Optional[dict] = None,
    *,
    agent_display_name: Optional[str] = None,
    isolate_catalog_environment: bool = False,
):
    """Concurrent-safe version of apply_user_config using contextvars.

    Instead of mutating global os.environ (which requires a per-agent-type lock),
    this stores the merged config in a ContextVar scoped to the current async task.
    Agents that use ``request_config.get_config_value()`` pick up per-request values
    while os.environ remains unmodified.

    For backwards compatibility, also sets os.environ — but under a much shorter
    critical section (just the catalog env keys) guarded by a threading lock.
    The lock is per-request, not held for the entire agent execution.
    """
    merged = dict(merged_config or {})

    # Build the full scoped config dict: merged + relevant os.environ fallbacks
    scoped: Dict[str, str] = {}
    catalog_keys: List[str] = []
    if isolate_catalog_environment and agent_display_name:
        catalog_keys = get_catalog_env_keys_for_agent(agent_display_name)

    if catalog_keys:
        for key in catalog_keys:
            val = merged.get(key)
            if val and isinstance(val, str) and val.strip():
                scoped[key] = val.strip()
            elif _llm_env_key_agent_config_only(key):
                # Explicitly absent — don't fall back to process env
                pass
            else:
                env_val = os.environ.get(key)
                if env_val is not None:
                    scoped[key] = env_val
    else:
        for key, value in merged.items():
            if key and isinstance(value, str) and value.strip():
                if key not in _SERVER_OBSERVABILITY_ENV_KEYS:
                    scoped[key] = value.strip()

    # Also apply to os.environ for legacy code that reads os.environ directly.
    # This happens under the existing apply_user_config for now.
    with apply_user_config(
        merged_config=merged_config,
        agent_cache=agent_cache,
        agent_display_name=agent_display_name,
        isolate_catalog_environment=isolate_catalog_environment,
    ):
        with scoped_request_config(scoped):
            yield


def _clear_agent_settings_caches():
    """Clear lru_cache on known agent settings factories."""
    known_modules = [
        "agents.JIRA_agent.core.config",
        "agents.Basic_agent.core.config",
        "agents.BRD_generation.core.config",
        "agents.RBI_circular_agent.core.config",
        "agents.SEBI_circular_agent.core.config",
        "agents.BPMN_generator_agent.core.config",
        "agents.Market_research_agent.core.config",
        "agents.Company_research_agent.core.config",
        "agents.Email_agent.core.config",
        "agents.Meeting_prep_agent.core.config",
        "agents.Web_search_agent.core.config",
        "agents.Web_test_agent.core.config",
        "agents.Claude_code_agent.core.config",
        "agents.Shannon_security_agent.core.config",
    ]
    import sys
    for mod_name in known_modules:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "get_settings"):
            fn = getattr(mod, "get_settings")
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()


def _refresh_cached_agent_settings(agent_cache: dict):
    """Walk cached agent instances and refresh any stored BaseSettings objects.
    
    After env vars are updated and lru_cache is cleared, agents that stored
    `self.settings = get_settings()` at init time still hold stale references.
    This function finds those references and updates them in-place with fresh values.
    """
    try:
        from pydantic_settings import BaseSettings
    except ImportError:
        return

    visited: set = set()

    def _refresh(obj):
        obj_id = id(obj)
        if obj_id in visited:
            return
        visited.add(obj_id)

        try:
            attrs = vars(obj)
        except TypeError:
            return

        for attr_name in list(attrs.keys()):
            try:
                attr_val = attrs[attr_name]
            except Exception:
                continue

            if isinstance(attr_val, BaseSettings):
                fresh = type(attr_val)()
                for field_name in type(attr_val).model_fields:
                    try:
                        object.__setattr__(attr_val, field_name, getattr(fresh, field_name))
                    except Exception:
                        pass
            elif hasattr(attr_val, '__dict__') and not isinstance(attr_val, (str, bytes, int, float, bool, list, dict, tuple, set, type)):
                _refresh(attr_val)

    for agent_inst in agent_cache.values():
        if hasattr(agent_inst, '__dict__'):
            _refresh(agent_inst)
        # MongoDB RAG caches MongoRAGSettings on the instance; clear so the next _cfg()
        # reads the current os.environ (matches per-request apply_user_config).
        if getattr(type(agent_inst), "__name__", "") == "MongoDBRAGAgent":
            try:
                agent_inst._settings = None  # type: ignore[attr-defined]
            except Exception:
                pass
