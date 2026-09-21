"""Process update ticket requests with validation and contextual awareness."""
import json
import re
from typing import Dict, Any, Optional, List

from ..core.logging import log_error, log_info
from ..prompts import prompt_loader
from ..utils.prompt_utils import safe_fmt
from .ticket_tools import TicketToolsContext, update_ticket_tool, get_details_tool
from ..helpers.conversation_manager import ConversationContext, ConversationState
from ..helpers import validate_update_ticket_data, generate_info_request_message
from ..helpers.llm_json_extract import (
    heuristic_jira_status_from_prompt,
    normalize_jira_update_payload,
    parse_llm_json_object,
)


_TICKET_KEY_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")


def _normalize_ticket_keys(keys: List[str]) -> List[str]:
    """Normalize, uppercase and deduplicate ticket keys preserving order."""
    normalized: List[str] = []
    seen = set()
    for key in keys:
        if not key:
            continue
        k = key.strip().upper()
        if not k or k in seen:
            continue
        seen.add(k)
        normalized.append(k)
    return normalized


async def process_update_ticket(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: Optional[TicketToolsContext] = None
) -> Dict[str, Any]:
    """Process update ticket request with validation and contextual awareness."""
    conversation_history = "\n".join([
        f"{msg['role']}: {msg['content']}"
        for msg in conversation_ctx.messages[-5:]
    ])

    prompt_ticket_keys = _normalize_ticket_keys(_TICKET_KEY_RE.findall(user_prompt))
    collected_ticket_keys_raw = conversation_ctx.collected_data.get("ticket_keys") or []
    if isinstance(collected_ticket_keys_raw, str):
        collected_ticket_keys_raw = [collected_ticket_keys_raw]

    ticket_context = ""
    ticket_key = conversation_ctx.collected_data.get('ticket_key')
    merged_ticket_keys = _normalize_ticket_keys(
        list(collected_ticket_keys_raw) + ([ticket_key] if ticket_key else []) + prompt_ticket_keys
    )

    if merged_ticket_keys:
        ticket_key = merged_ticket_keys[0]
        conversation_ctx.update_collected_data({
            "ticket_key": ticket_key,
            "ticket_keys": merged_ticket_keys,
        })

    if ticket_key:
        log_info(f"Fetching current details for ticket {ticket_key}", "direct_processor")
        try:
            ticket_details = await get_details_tool(jira_service, ticket_key)
            ticket_context = f"\n\n**CURRENT TICKET DETAILS:**\n{ticket_details}\n"
        except Exception as e:
            log_error(f"Error fetching ticket details: {e}", "direct_processor")

    extract_prompt = safe_fmt(
        prompt_loader.get_prompt("direct_processor.yml", "extract_update_details"),
        conversation_history=conversation_history,
        user_prompt=user_prompt,
        collected_data=json.dumps(conversation_ctx.collected_data),
        ticket_context=ticket_context
    )

    try:
        extracted = await ai_service.call_genai(
            prompt=extract_prompt,
            temperature=0.1,
            max_tokens=500,
            task_name="jira_ticket_extraction",
        )

        raw_obj = parse_llm_json_object(extracted)
        ai_data = normalize_jira_update_payload(raw_obj)
        conversation_ctx.update_collected_data(ai_data)

    except Exception as e:
        log_error(f"AI extraction error: {e}", "direct_processor")

    if not conversation_ctx.collected_data.get("status"):
        inferred = heuristic_jira_status_from_prompt(user_prompt)
        if inferred:
            conversation_ctx.update_collected_data({"status": inferred})

    final_ticket_keys_raw = conversation_ctx.collected_data.get("ticket_keys") or []
    if isinstance(final_ticket_keys_raw, str):
        final_ticket_keys_raw = [final_ticket_keys_raw]
    final_ticket_keys = _normalize_ticket_keys(
        list(final_ticket_keys_raw)
        + ([conversation_ctx.collected_data.get("ticket_key")] if conversation_ctx.collected_data.get("ticket_key") else [])
        + prompt_ticket_keys
    )
    if final_ticket_keys:
        conversation_ctx.update_collected_data({
            "ticket_key": final_ticket_keys[0],
            "ticket_keys": final_ticket_keys,
        })

    is_complete, missing_fields = validate_update_ticket_data(user_prompt, conversation_ctx.collected_data)

    if not is_complete:
        conversation_ctx.set_missing_fields(missing_fields)
        message = generate_info_request_message(missing_fields)

        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "update",
            "response": message,
            "missing_fields": [f.to_dict() for f in missing_fields],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    conversation_ctx.state = ConversationState.PROCESSING

    update_fields = {
        "status": conversation_ctx.collected_data.get("status"),
        "priority": conversation_ctx.collected_data.get("priority"),
        "summary": conversation_ctx.collected_data.get("summary"),
        "description": conversation_ctx.collected_data.get("description"),
        "labels": conversation_ctx.collected_data.get("labels"),
        "comment": conversation_ctx.collected_data.get("comment"),
    }
    update_fields = {
        k: v for k, v in update_fields.items()
        if v is not None and not (isinstance(v, str) and not v.strip())
    }

    keys_to_update_raw = conversation_ctx.collected_data.get("ticket_keys") or []
    if isinstance(keys_to_update_raw, str):
        keys_to_update_raw = [keys_to_update_raw]
    keys_to_update = _normalize_ticket_keys(keys_to_update_raw)
    if not keys_to_update:
        single = conversation_ctx.collected_data.get("ticket_key")
        keys_to_update = _normalize_ticket_keys([single] if single else [])

    if len(keys_to_update) <= 1:
        payload = {
            "ticket_key": keys_to_update[0],
            **update_fields,
        }
        result = await update_ticket_tool(jira_service, json.dumps(payload))
        success = "Failed" not in result and "Error" not in result
    else:
        item_results = []
        failed = False
        for key in keys_to_update:
            payload = {"ticket_key": key, **update_fields}
            item_result = await update_ticket_tool(jira_service, json.dumps(payload))
            item_results.append(item_result)
            low = item_result.lower()
            if "failed" in low or "error" in low:
                failed = True
        result = (
            f"Updated {len(keys_to_update)} ticket(s):\n"
            + "\n".join(f"- {line}" for line in item_results)
        )
        success = not failed

    conversation_ctx.state = ConversationState.COMPLETED

    return {
        "success": success,
        "state": conversation_ctx.state.value,
        "session_id": conversation_ctx.session_id,
        "prompt": user_prompt,
        "intent": "update",
        "response": result,
        "collected_data": conversation_ctx.collected_data,
        "tickets": []
    }
