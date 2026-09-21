"""Agent catalog loader — single source of truth from agents_catalog.json."""

import json
import logging
import os
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path + aliases
# ---------------------------------------------------------------------------

_CATALOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "agents_catalog.json",
)

# Map old orchestrator IDs → canonical catalog IDs
_AGENT_ID_ALIASES: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_catalog() -> Dict[str, Any]:
    """Load and parse agents_catalog.json once."""
    try:
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error("agents_catalog.json not found at %s", _CATALOG_PATH)
        return {"agents": []}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse agents_catalog.json: %s", e)
        return {"agents": []}


def _build_from_catalog() -> Tuple[
    Dict[str, Dict[str, str]],
    Dict[str, Tuple[str, str, str, bool]],
    Dict[str, List[str]],
]:
    """Build AGENT_REGISTRY, _AGENT_DISPATCH, and AGENT_PROGRESS_PHASES from the catalog.

    Returns:
        (registry, dispatch, progress_phases)
    """
    catalog = _load_catalog()
    agents = catalog.get("agents", [])

    registry: Dict[str, Dict[str, str]] = {}
    dispatch: Dict[str, Tuple[str, str, str, bool]] = {}
    progress: Dict[str, List[str]] = {}

    for agent in agents:
        agent_id = agent.get("id", "")
        if not agent_id:
            continue

        # --- Registry ---
        name = agent.get("name", agent_id)
        usage = agent.get("usage", {})
        api_endpoint = usage.get("api_endpoint", "")
        endpoint = api_endpoint.split(" ", 1)[-1] if api_endpoint else ""
        registry[agent_id] = {"name": name, "endpoint": endpoint}

        # --- Dispatch ---
        disp = agent.get("dispatch")
        invocation = agent.get("invocation", {})
        if disp:
            getter_key = disp.get("getter_key", agent_id)
            method_name = invocation.get("method", "process_query")
            call_style = disp.get("call_style", "q")
            async_native = disp.get("async_native", False)
            dispatch[agent_id] = (getter_key, method_name, call_style, async_native)

        # --- Progress phases ---
        phases = agent.get("progress_phases")
        if phases and isinstance(phases, list):
            progress[agent_id] = phases

    # Inject aliases so old IDs still resolve
    for alias, canonical in _AGENT_ID_ALIASES.items():
        if canonical in registry and alias not in registry:
            registry[alias] = registry[canonical]
        if canonical in dispatch and alias not in dispatch:
            dispatch[alias] = dispatch[canonical]
        if canonical in progress and alias not in progress:
            progress[alias] = progress[canonical]

    return registry, dispatch, progress


# ---------------------------------------------------------------------------
# Module-level singletons (populated on first import)
# ---------------------------------------------------------------------------

AGENT_REGISTRY, _AGENT_DISPATCH, AGENT_PROGRESS_PHASES = _build_from_catalog()

DEFAULT_PROGRESS_PHASES = ["Processing...", "Working...", "Almost done..."]


def reload_agent_catalog():
    """Re-read agents_catalog.json and refresh the module-level registries.

    Useful after adding/removing agents at runtime without restarting the server.
    """
    global AGENT_REGISTRY, _AGENT_DISPATCH, AGENT_PROGRESS_PHASES
    AGENT_REGISTRY, _AGENT_DISPATCH, AGENT_PROGRESS_PHASES = _build_from_catalog()
    logger.info("Agent catalog reloaded: %d agents", len(AGENT_REGISTRY))
