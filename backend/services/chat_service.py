import json
from pydantic import TypeAdapter
from langchain_core.messages import AIMessageChunk, ToolMessage
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
)
from errors.global_exception_handler import AgentMartException
from agents.agent_config import AgentConfig
from agents.agent_factory import AgentFactory
from tools.tool_config import ToolConfig
from utils.logger import get_logger

logger = get_logger(__name__)


async def _get_agent_instance(
    agent_id: str,
    agent_factory: AgentFactory,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
):
    available_agent = await agent_catalog_collection.get_agent_config(agent_id)
    if available_agent is None:
        raise AgentMartException("Agent not found", 404)

    tool_ids = available_agent.get("tools", [])
    available_tools = []
    for tool_id in tool_ids:
        raw_tool_config = await tool_catalog_collection.get_tool_config(tool_id)
        if raw_tool_config:
            if "_id" in raw_tool_config:
                raw_tool_config["tool_id"] = str(raw_tool_config["_id"])
            tool_obj = TypeAdapter(ToolConfig).validate_python(raw_tool_config)
            available_tools.append(tool_obj)

    agent_config = AgentConfig(
        _id=str(available_agent["_id"]),
        name=available_agent["name"],
        description=available_agent["description"],
        system_prompt=available_agent["system_prompt"],
        tools=available_tools,
        model=available_agent["model"],
        capabilities=available_agent["capabilities"],
        enabled=available_agent["enabled"],
        version=available_agent["version"],
        visibility=available_agent["visibility"],
        status=available_agent["status"],
    )

    agent = await agent_factory.create(agent_config)
    logger.info("Agent is initialized and ready for execution")
    return agent


async def chat_with_agent(
    agent_id: str,
    user_id: str,
    user_message: str,
    agent_factory: AgentFactory,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
) -> str:
    """
    Non-streaming chat execution. Returns full response string.
    """
    agent = await _get_agent_instance(
        agent_id, agent_factory, agent_catalog_collection, tool_catalog_collection
    )
    agent_response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_message}]}
    )
    logger.debug(f"The agent response is {agent_response}")
    last_msg = agent_response["messages"][-1]
    content = getattr(last_msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) > 0:
        last_part = content[-1]
        if isinstance(last_part, dict) and "text" in last_part:
            return last_part["text"]
        return str(last_part)
    return str(content)


async def chat_with_agent_stream(
    agent_id: str,
    user_id: str,
    user_message: str,
    agent_factory: AgentFactory,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
):
    """
    Streaming chat execution. Yields SSE chunks: `data: {"content": "..."}\\n\\n`
    """
    try:
        agent = await _get_agent_instance(
            agent_id, agent_factory, agent_catalog_collection, tool_catalog_collection
        )

        tool_call_buffers: dict[int, dict] = {}

        async for chunk, meta in agent.astream(
            {"messages": [{"role": "user", "content": user_message}]},
            stream_mode="messages",
        ):
            meta_dict = meta if isinstance(meta, dict) else {}
            checkpoint_ns = str(meta_dict.get("checkpoint_ns", ""))

            # 1. Tool execution result (ToolMessage)
            if isinstance(chunk, ToolMessage) or getattr(chunk, "type", "") == "tool":
                tool_name = getattr(chunk, "name", "") or "tool"
                call_id = getattr(chunk, "tool_call_id", "")
                tool_output = getattr(chunk, "content", "")
                status = getattr(chunk, "status", "success")

                is_subagent = (
                    tool_name == "task"
                    or "subagent" in tool_name.lower()
                    or "subagent" in checkpoint_ns.lower()
                )
                kind = "subagent_result" if is_subagent else "tool_result"

                payload = json.dumps(
                    {
                        "type": "trace",
                        "step": {
                            "kind": kind,
                            "id": call_id,
                            "name": tool_name,
                            "output": tool_output,
                            "status": status,
                        },
                    },
                    default=str,
                )
                yield f"data: {payload}\n\n"
                continue

            # 2. Reasoning / Thinking content (e.g. DeepSeek or thinking models)
            reasoning_delta = ""
            if hasattr(chunk, "additional_kwargs") and isinstance(chunk.additional_kwargs, dict):
                reasoning_delta = chunk.additional_kwargs.get("reasoning_content", "")
            if not reasoning_delta and hasattr(chunk, "response_metadata") and isinstance(chunk.response_metadata, dict):
                reasoning_delta = chunk.response_metadata.get("reasoning_content", "")

            if reasoning_delta:
                payload = json.dumps(
                    {
                        "type": "trace",
                        "step": {
                            "kind": "thought",
                            "text": str(reasoning_delta),
                        },
                    },
                    default=str,
                )
                yield f"data: {payload}\n\n"

            # 3. Tool call chunks (agent deciding to call a tool or subagent)
            tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
            has_tool_call_chunks = bool(tool_call_chunks)
            if tool_call_chunks:
                for tc in tool_call_chunks:
                    idx = tc.get("index", 0)
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tc.get("id") or f"call_{idx}",
                            "name": tc.get("name") or "",
                            "args": "",
                        }
                    if tc.get("id"):
                        tool_call_buffers[idx]["id"] = tc["id"]
                    if tc.get("name"):
                        tool_call_buffers[idx]["name"] = tc["name"]
                    if tc.get("args"):
                        tool_call_buffers[idx]["args"] += tc["args"]

                    buf = tool_call_buffers[idx]
                    t_name = buf["name"]
                    is_subagent = (
                        t_name == "task"
                        or "subagent" in t_name.lower()
                        or "subagent" in checkpoint_ns.lower()
                    )
                    kind = "subagent_call" if is_subagent else "tool_call"

                    payload = json.dumps(
                        {
                            "type": "trace",
                            "step": {
                                "kind": kind,
                                "id": buf["id"],
                                "name": t_name,
                                "input": buf["args"],
                                "status": "calling",
                            },
                        },
                        default=str,
                    )
                    yield f"data: {payload}\n\n"

            # 4. Text content
            content = getattr(chunk, "content", "")
            text_delta = ""
            thinking_delta = ""

            if isinstance(content, str):
                text_delta = content
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        p_type = part.get("type")
                        if p_type == "text":
                            text_delta += part.get("text", "")
                        elif p_type in ("thinking", "reasoning"):
                            thinking_delta += part.get("thinking", "") or part.get("reasoning", "")
                    elif isinstance(part, str):
                        text_delta += part

            if thinking_delta:
                payload = json.dumps(
                    {
                        "type": "trace",
                        "step": {
                            "kind": "thought",
                            "text": thinking_delta,
                        },
                    },
                    default=str,
                )
                yield f"data: {payload}\n\n"

            if text_delta:
                # If this AI chunk was accompanied by tool call chunks, treat its text as thought / pre-tool reasoning
                if has_tool_call_chunks:
                    payload = json.dumps(
                        {
                            "type": "trace",
                            "step": {
                                "kind": "thought",
                                "text": text_delta,
                            },
                        },
                        default=str,
                    )
                    yield f"data: {payload}\n\n"
                else:
                    payload = json.dumps({"type": "content", "content": text_delta})
                    yield f"data: {payload}\n\n"

        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"Error during streaming chat: {e}", exc_info=True)
        err_payload = json.dumps({"error": str(e)})
        yield f"data: {err_payload}\n\n"
        yield "data: [DONE]\n\n"
