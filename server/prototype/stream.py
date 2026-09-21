"""SSE streaming for prototype agent responses."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi.responses import StreamingResponse

from .responses import build_agent_result


def _format_sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, 'data': data}, default=str)}\n\n"


def _chunk_text(text: str, target_size: int = 100) -> list:
    if not text:
        return []
    paragraphs = text.split("\n\n")
    chunks = []
    for i, para in enumerate(paragraphs):
        suffix = "\n\n" if i < len(paragraphs) - 1 else ""
        if len(para) <= target_size:
            chunks.append(para + suffix)
        else:
            lines = para.split("\n")
            buf, buf_len = [], 0
            for line in lines:
                buf.append(line)
                buf_len += len(line) + 1
                if buf_len >= target_size:
                    chunks.append("\n".join(buf) + "\n")
                    buf, buf_len = [], 0
            if buf:
                chunks.append("\n".join(buf) + suffix)
    return chunks or [text]


async def prototype_stream_response(
    agent_name: str,
    session_id: Optional[str] = None,
    input_text: Optional[str] = None,
):
    result = build_agent_result(agent_name, query=input_text, session_id=session_id)

    async def event_stream():
        yield _format_sse("start", {"agent": agent_name, "timestamp": datetime.now().isoformat()})
        await asyncio.sleep(0.05)

        thinking = result.pop("thinking_steps", []) or []
        for step in thinking:
            s = step if isinstance(step, dict) else {"type": "thinking", "content": str(step)}
            yield _format_sse("thinking", s)
            await asyncio.sleep(0.06)

        routed = result.get("routed_to")
        if routed:
            yield _format_sse("routing", routed)
            await asyncio.sleep(0.04)

        response_text = result.get("response", "")
        for chunk in _chunk_text(str(response_text)):
            yield _format_sse("response_chunk", {"chunk": chunk})
            await asyncio.sleep(0.04)

        result["thinking_steps"] = thinking
        yield _format_sse("done", result)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
