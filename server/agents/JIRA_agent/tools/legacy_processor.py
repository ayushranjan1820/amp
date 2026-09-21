"""Legacy single-turn processing without conversation context."""
import json
from typing import Dict, Any, Optional, List

from ..core.logging import log_error
from ..prompts import prompt_loader
from ..utils import ActionType
from ..utils.prompt_utils import safe_fmt
from ..helpers.codebase_context import build_required_sections_fallback
from .ticket_tools import (
    TicketToolsContext,
    search_tickets_tool,
    create_ticket_tool,
    update_ticket_tool,
    get_details_tool,
    get_details_multi_tool,
)
from .helpers import (
    format_tickets_for_agent,
    format_tickets_verbatim,
    is_description_fetch_request,
)
from ..helpers.llm_json_extract import (
    heuristic_jira_status_from_prompt,
    normalize_jira_update_payload,
    parse_llm_json_object,
)


def _normalize_ticket_keys(keys: List[str]) -> List[str]:
    """Normalize and deduplicate ticket keys while preserving order."""
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


async def process_without_conversation(
    user_prompt: str,
    intent: Dict[str, Any],
    jira_service,
    ai_service,
    context: TicketToolsContext,
    context_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Legacy single-turn processing without conversation context."""
    action = intent.get('action', ActionType.UNKNOWN)
    ticket_key = intent.get('ticket_key')
    ticket_keys = _normalize_ticket_keys(intent.get('ticket_keys') or ([ticket_key] if ticket_key else []))
    ticket_key = ticket_keys[0] if ticket_keys else None
    original_prompt = intent.get("original_prompt") or user_prompt
    detect_prompt_lower = (original_prompt or "").lower()
    description_only_requested = (
        "description field text only" in detect_prompt_lower
        or "description text only" in detect_prompt_lower
        or "description only" in detect_prompt_lower
    )

    try:
        if action == ActionType.SEARCH or action == ActionType.UNKNOWN:
            result = await search_tickets_tool(jira_service, context, user_prompt, ai_service)

            if context.last_search_results:
                if is_description_fetch_request(original_prompt):
                    response = format_tickets_verbatim(context.last_search_results)
                else:
                    tickets_summary = format_tickets_for_agent(context.last_search_results)
                    analysis_prompt = safe_fmt(
                        prompt_loader.get_prompt("direct_processor.yml", "search_analysis"),
                        user_prompt=user_prompt,
                        tickets_summary=tickets_summary
                    )

                    response = await ai_service.call_genai(
                        prompt=analysis_prompt,
                        temperature=0.3,
                        max_tokens=2000,
                        task_name="jira_response_format"
                    )
            else:
                response = result

            return {
                "success": True,
                "prompt": user_prompt,
                "intent": action.value,
                "response": response,
                "tickets": context.last_search_results
            }

        elif action == ActionType.CREATE:
            extract_prompt = safe_fmt(
                prompt_loader.get_prompt("direct_processor.yml", "extract_simple_ticket_data"),
                user_prompt=user_prompt
            )

            extracted = await ai_service.call_genai(
                prompt=extract_prompt,
                temperature=0.1,
                max_tokens=500,
                task_name="jira_ticket_extraction"
            )

            try:
                ticket_data = parse_llm_json_object(extracted)

                codebase_context = ""
                if context_data:
                    codebase_context = str(context_data.get("codebase_context") or "")

                if codebase_context:
                    ticket_data["codebase_context"] = codebase_context
                    ticket_data["description"] = build_required_sections_fallback(
                        summary=ticket_data.get("summary", user_prompt),
                        issue_type=ticket_data.get("issue_type", "Story"),
                        codebase_context=codebase_context,
                        existing_description=ticket_data.get("description", ""),
                    )

                result = await create_ticket_tool(jira_service, json.dumps(ticket_data))

                return {
                    "success": "Failed" not in result,
                    "prompt": user_prompt,
                    "intent": action.value,
                    "response": result,
                    "tickets": []
                }
            except (json.JSONDecodeError, ValueError):
                return {
                    "success": False,
                    "prompt": user_prompt,
                    "intent": action.value,
                    "response": "Could not extract ticket details. Please provide a clearer description.",
                    "tickets": []
                }

        elif action == ActionType.UPDATE and ticket_keys:
            extract_prompt = safe_fmt(
                prompt_loader.get_prompt("direct_processor.yml", "extract_simple_update_details"),
                ticket_key=ticket_key,
                user_prompt=user_prompt
            )

            extracted = await ai_service.call_genai(
                prompt=extract_prompt,
                temperature=0.1,
                max_tokens=500,
                task_name="jira_ticket_extraction"
            )

            update_data: Dict[str, Any] = {}
            try:
                update_data = normalize_jira_update_payload(parse_llm_json_object(extracted))
            except (json.JSONDecodeError, ValueError) as e:
                log_error(f"Update JSON extract failed: {e}", "legacy_processor")

            update_data["ticket_key"] = ticket_key
            if not update_data.get("status"):
                inferred = heuristic_jira_status_from_prompt(user_prompt)
                if inferred:
                    update_data["status"] = inferred

            if not any(
                update_data.get(k)
                for k in ("status", "priority", "summary", "description", "labels", "comment")
            ):
                return {
                    "success": False,
                    "prompt": user_prompt,
                    "intent": action.value,
                    "response": "Could not extract update details. Please be more specific.",
                    "tickets": [],
                }

            update_fields = {
                "status": update_data.get("status"),
                "priority": update_data.get("priority"),
                "summary": update_data.get("summary"),
                "description": update_data.get("description"),
                "labels": update_data.get("labels"),
                "comment": update_data.get("comment"),
            }
            update_fields = {
                k: v for k, v in update_fields.items()
                if v is not None and not (isinstance(v, str) and not v.strip())
            }

            if len(ticket_keys) <= 1:
                payload = {"ticket_key": ticket_key, **update_fields}
                result = await update_ticket_tool(jira_service, json.dumps(payload))
                success = "Failed" not in result and "Error" not in result
            else:
                item_results = []
                failed = False
                for key in ticket_keys:
                    payload = {"ticket_key": key, **update_fields}
                    item_result = await update_ticket_tool(jira_service, json.dumps(payload))
                    item_results.append(item_result)
                    low = item_result.lower()
                    if "failed" in low or "error" in low:
                        failed = True
                result = (
                    f"Updated {len(ticket_keys)} ticket(s):\n"
                    + "\n".join(f"- {line}" for line in item_results)
                )
                success = not failed

            return {
                "success": success,
                "prompt": user_prompt,
                "intent": action.value,
                "response": result,
                "tickets": [],
            }

        elif action == ActionType.GET_DETAILS and ticket_keys:
            if description_only_requested:
                parts = []
                for key in ticket_keys:
                    issue = await jira_service.get_issue(key)
                    norm_key = key.strip().upper()
                    if issue is None:
                        parts.append(f"Ticket {norm_key} not found")
                    else:
                        desc = (issue.get("description") or "").strip()
                        parts.append(f"**{norm_key}**:\n{desc or '(Description is empty)'}")
                result = "\n\n---\n\n".join(parts)
            elif len(ticket_keys) == 1:
                result = await get_details_tool(jira_service, ticket_keys[0])
            else:
                result = await get_details_multi_tool(jira_service, ticket_keys)
            return {
                "success": True,
                "prompt": user_prompt,
                "intent": action.value,
                "response": result,
                "tickets": []
            }

        elif action in (ActionType.SUBTASK, ActionType.LINK, ActionType.ANALYTICS,
                         ActionType.ISSUE_REPORT, ActionType.SEARCH_AND_UPDATE):
            result = await search_tickets_tool(jira_service, context, user_prompt, ai_service)
            if context.last_search_results:
                tickets_summary = format_tickets_for_agent(context.last_search_results)
                analysis_prompt = safe_fmt(
                    prompt_loader.get_prompt("direct_processor.yml", "search_analysis"),
                    user_prompt=user_prompt,
                    tickets_summary=tickets_summary
                )
                response = await ai_service.call_genai(
                    prompt=analysis_prompt, temperature=0.3, max_tokens=2000,
                    task_name="jira_response_format"
                )
            else:
                response = result
            return {
                "success": True,
                "prompt": user_prompt,
                "intent": action.value,
                "response": response,
                "tickets": context.last_search_results
            }

        else:
            result = await search_tickets_tool(jira_service, context, user_prompt, ai_service)
            return {
                "success": True,
                "prompt": user_prompt,
                "intent": "search",
                "response": result,
                "tickets": context.last_search_results
            }

    except Exception as e:
        log_error(f"Direct processing error: {e}", "jira_agent", e)
        return {
            "success": False,
            "prompt": user_prompt,
            "intent": action.value,
            "response": "Something went wrong while processing your request. Please try again or rephrase your query.",
            "tickets": []
        }
