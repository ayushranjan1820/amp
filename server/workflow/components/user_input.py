"""User-input management — futures for interactive workflow steps."""

import asyncio
import logging
from typing import Dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_pending_inputs: Dict[str, asyncio.Future] = {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def wait_for_user_input(execution_id: str, step_num: int, timeout: int = 300) -> str:
    """Block until the user submits input for a waiting step, or timeout."""
    key = f"{execution_id}:{step_num}"
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    _pending_inputs[key] = future
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for user input on %s", key)
        return ""
    finally:
        _pending_inputs.pop(key, None)


def submit_user_input(execution_id: str, step_num: int, user_input: str) -> bool:
    """Resolve a pending user-input future so the waiting step can resume."""
    key = f"{execution_id}:{step_num}"
    future = _pending_inputs.get(key)
    if future and not future.done():
        future.set_result(user_input)
        return True
    return False
