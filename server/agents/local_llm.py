"""
Local LLM client — calls a locally-hosted LLM server.

Endpoint format (configurable via LOCAL_LLM_URL env var):
  POST http://127.0.0.1:4099/api/v1/generate

Request body:
  {
    "question": "<prompt>",
    "model_name": "<from LOCAL_LLM_MODEL env>",
    "temperature": 0.6,
    "max_tokens": 256,
    "n_gpu_layers": 40,
    "n_batch": 512,
    "n_ctx": 8192,
    "stream": true
  }

When stream=true / Accept: text/event-stream the server sends SSE lines:
  data: {"response": "chunk", "done": false}
  ...
  data: {"response": "last chunk", "done": true, "finish_reason": "stop"}
  data: [DONE]
"""

import os
import json
import re
import time
import asyncio
import requests
import httpx
from typing import AsyncIterator, Callable, Iterator, Optional, Tuple

from agents.token_manager import count_tokens
from agents.llm_activity_stream import (
    build_llm_call_step,
    build_llm_response_step,
    emit_llm_activity,
)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_MAX_CONTINUATIONS = 3

_CONTINUATION_PROMPT_TEMPLATE = (
    "{original_prompt}\n\n"
    "---\n"
    "NOTE: Your previous response to the above prompt was cut off due to length limits. "
    "Here is what you already generated:\n\n"
    "{partial}\n\n"
    "---\n"
    "Continue generating ONLY the remaining part from where you left off. "
    "Do NOT repeat any content already generated above. Do NOT add any preamble. "
    "Just continue the response seamlessly."
)


def _get_local_llm_config() -> dict:
    """Read local-LLM settings from environment."""
    return {
        "url": os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:4099/api/v1/generate"),
        "model_name": os.getenv("LOCAL_LLM_MODEL", ""),
        "temperature": float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.6")),
        "max_tokens": int(os.getenv("LOCAL_LLM_MAX_TOKENS", "8192")),
        "n_gpu_layers": int(os.getenv("LOCAL_LLM_N_GPU_LAYERS", "40")),
        "n_batch": int(os.getenv("LOCAL_LLM_N_BATCH", "512")),
        "n_ctx": int(os.getenv("LOCAL_LLM_N_CTX", "8192")),
    }


def get_llm_provider() -> str:
    """Return ``pwc_genai``, ``local_llm``, or ``ollama_cloud``.

    Priority:
    1. ``LLM_PROVIDER`` from merged agent config / env (normalized).
    2. Legacy ``USE_LOCAL_LLM=true`` from older UI.
    """
    raw = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if raw in ("pwc_genai", "pwc", "genai"):
        return "pwc_genai"
    if raw in ("local_llm", "local"):
        return "local_llm"
    if raw in ("ollama_cloud", "ollama", "ollama-cloud"):
        return "ollama_cloud"
    if raw:
        return "pwc_genai"
    if os.getenv("USE_LOCAL_LLM", "false").strip().lower() in ("true", "1", "yes"):
        return "local_llm"
    return "pwc_genai"


def is_local_llm() -> bool:
    """True when the in-process local server (127.0.0.1:4099 style) is selected."""
    return get_llm_provider() == "local_llm"


def uses_pwc_genai_credentials() -> bool:
    """True when PwC GenAI API key / bearer / endpoint are required for this request."""
    return get_llm_provider() == "pwc_genai"


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------

def _build_local_request(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> dict:
    cfg = _get_local_llm_config()
    return {
        "question": prompt,
        "model_name": cfg["model_name"],
        "temperature": temperature if temperature is not None else cfg["temperature"],
        "max_tokens": max_tokens if max_tokens is not None else cfg["max_tokens"],
        "n_gpu_layers": cfg["n_gpu_layers"],
        "n_batch": cfg["n_batch"],
        "n_ctx": cfg["n_ctx"],
        "stream": True,
    }


# Use text/event-stream so the server activates its SSE pipeline
_LOCAL_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}


def _extract_sse_chunk(data: dict) -> Tuple[str, Optional[str], bool]:
    """Parse one SSE data payload.

    Returns (chunk_text, finish_reason, is_done).
    Supports both the native local-LLM shape and OpenAI-compatible shape.
    """
    finish_reason: Optional[str] = (
        data.get("finish_reason") or data.get("stop_reason")
    )
    is_done: bool = (
        bool(data.get("done", False))
        or bool(data.get("finished", False))
        or finish_reason is not None
    )

    # Native shape: {"response": "...", "done": bool}
    # Local LLM backend (route_handlers.generate_stream): {"token": "...", "finished": bool}
    for key in ("response", "text", "content", "result", "answer", "output", "token"):
        if key in data and isinstance(data[key], str):
            return data[key], finish_reason, is_done

    # OpenAI-compat streaming: {"choices": [{"delta": {"content": "..."}}]}
    choices = data.get("choices")
    if choices and len(choices) > 0:
        choice = choices[0]
        finish_reason = finish_reason or choice.get("finish_reason") or choice.get("stop_reason")
        # streaming delta
        delta = choice.get("delta", {})
        if "content" in delta:
            is_done = finish_reason is not None
            return delta["content"] or "", finish_reason, is_done
        # non-streaming text
        if "text" in choice:
            return choice["text"], finish_reason, is_done
        if "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"], finish_reason, is_done

    return "", finish_reason, is_done


def _parse_sse_line(line: str) -> Optional[dict]:
    """Parse one raw SSE line into a dict, or None if it should be skipped."""
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def _extract_local_response(data: dict) -> Tuple[str, Optional[str]]:
    """Extract (text, finish_reason) from a complete (non-streaming) JSON response."""
    finish_reason: Optional[str] = data.get("finish_reason") or data.get("stop_reason")

    for key in ("response", "text", "content", "result", "answer", "output"):
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key], finish_reason

    choices = data.get("choices")
    if choices and len(choices) > 0:
        choice = choices[0]
        finish_reason = finish_reason or choice.get("finish_reason") or choice.get("stop_reason")
        if "message" in choice and "content" in choice["message"]:
            return choice["message"]["content"], finish_reason
        if "text" in choice:
            return choice["text"], finish_reason

    return json.dumps(data), finish_reason


def _should_continue(finish_reason: Optional[str], content: str) -> bool:
    """Mirror the same heuristic used in llm_continuation.py."""
    if finish_reason and finish_reason.lower() in ("length", "max_tokens"):
        return True
    if not finish_reason and content:
        stripped = content.rstrip()
        if stripped and stripped[-1] not in '.!?;>}])\n"\'`':
            if len(content) > 2000:
                return True
    return False


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>...</think>`` reasoning blocks emitted by some models
    (e.g. qwen3.x). These blocks confuse downstream JSON parsing and
    continuation heuristics. The strip is applied once, after all
    continuations have been collected."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip()


def _build_continuation_prompt(original_prompt: str, partial: str) -> str:
    trimmed = partial
    if len(trimmed) > 6000:
        trimmed = "...[earlier content omitted]...\n\n" + trimmed[-6000:]
    return _CONTINUATION_PROMPT_TEMPLATE.format(
        original_prompt=original_prompt,
        partial=trimmed,
    )


def _log_cost(model_name: str, prompt: str, content: str):
    try:
        from agents.llm_continuation import _log_llm_cost
        _log_llm_cost(model_name, count_tokens(prompt), count_tokens(content))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# SSE stream consumers
# ---------------------------------------------------------------------------

def _consume_sse_sync(
    resp: requests.Response,
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Optional[str]]:
    """Consume an SSE stream from a requests.Response, return (full_text, finish_reason)."""
    accumulated = ""
    finish_reason: Optional[str] = None

    for raw_line in resp.iter_lines(decode_unicode=True):
        data = _parse_sse_line(raw_line)
        if data is None:
            continue
        chunk, fr, done = _extract_sse_chunk(data)
        accumulated += chunk
        if chunk and on_chunk:
            on_chunk(chunk)
        if fr:
            finish_reason = fr
        if done and not chunk:
            # Pure done marker with no content — stop
            break

    return accumulated, finish_reason


def _consume_sse_httpx_sync(resp: httpx.Response) -> Tuple[str, Optional[str]]:
    """Consume an SSE stream from a sync httpx.Response, return (full_text, finish_reason)."""
    accumulated = ""
    finish_reason: Optional[str] = None

    for raw_line in resp.iter_lines():
        data = _parse_sse_line(raw_line)
        if data is None:
            continue
        chunk, fr, done = _extract_sse_chunk(data)
        accumulated += chunk
        if fr:
            finish_reason = fr
        if done and not chunk:
            break

    return accumulated, finish_reason


async def _consume_sse_httpx_async(resp: httpx.Response) -> Tuple[str, Optional[str]]:
    """Consume an SSE stream from an async httpx.Response, return (full_text, finish_reason)."""
    accumulated = ""
    finish_reason: Optional[str] = None

    async for raw_line in resp.aiter_lines():
        data = _parse_sse_line(raw_line)
        if data is None:
            continue
        chunk, fr, done = _extract_sse_chunk(data)
        accumulated += chunk
        if fr:
            finish_reason = fr
        if done and not chunk:
            break

    return accumulated, finish_reason


# ---------------------------------------------------------------------------
# Sync call (requests) — SSE streaming + continuation
# ---------------------------------------------------------------------------

def sync_local_llm_call(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: int = 180,
    on_stream_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    """Synchronous call to local LLM via SSE stream, with auto-continuation."""
    cfg = _get_local_llm_config()
    body = _build_local_request(prompt, temperature, max_tokens)

    print(f"[LocalLLM] SSE POST {cfg['url']} | model={cfg['model_name']} | prompt={len(prompt)} chars")

    try:
        resp = requests.post(
            cfg["url"], json=body, headers=_LOCAL_HEADERS,
            timeout=timeout, stream=True,
        )
    except requests.RequestException as e:
        raise ValueError(
            f"Local LLM server unreachable at {cfg['url']}. "
            f"Make sure the server is running. Error: {e}"
        )

    if resp.status_code != 200:
        raise ValueError(f"Local LLM Error: {resp.status_code} - {resp.text}")

    content, finish_reason = _consume_sse_sync(resp, on_chunk=on_stream_chunk)
    if not content:
        raise ValueError("Empty response from local LLM")

    accumulated = content
    continuation_count = 0

    while _should_continue(finish_reason, accumulated) and continuation_count < _MAX_CONTINUATIONS:
        continuation_count += 1
        print(
            f"[LocalLLM] Response truncated (finish_reason={finish_reason}), "
            f"auto-continuing ({continuation_count}/{_MAX_CONTINUATIONS})..."
        )
        cont_body = dict(body)
        cont_body["question"] = _build_continuation_prompt(prompt, accumulated)

        try:
            cont_resp = requests.post(
                cfg["url"], json=cont_body, headers=_LOCAL_HEADERS,
                timeout=timeout, stream=True,
            )
        except requests.RequestException:
            break

        if cont_resp.status_code != 200:
            print(f"[LocalLLM] Continuation call failed: {cont_resp.status_code}")
            break

        cont_content, finish_reason = _consume_sse_sync(cont_resp, on_chunk=on_stream_chunk)
        if not cont_content:
            break
        accumulated += cont_content

    if continuation_count:
        print(f"[LocalLLM] Completed with {continuation_count} continuation(s). Total: {len(accumulated)} chars")
    else:
        print(f"[LocalLLM] Response received | {len(accumulated)} chars")

    _log_cost(cfg["model_name"], prompt, accumulated)
    return accumulated


# ---------------------------------------------------------------------------
# Async call (httpx) — SSE streaming + continuation
# ---------------------------------------------------------------------------

async def async_local_llm_call(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 180.0,
) -> str:
    """Asynchronous call to local LLM via SSE stream, with auto-continuation."""
    cfg = _get_local_llm_config()
    body = _build_local_request(prompt, temperature, max_tokens)

    print(f"[LocalLLM] SSE POST {cfg['url']} | model={cfg['model_name']} | prompt={len(prompt)} chars")

    await emit_llm_activity(
        build_llm_call_step(
            provider="local_llm",
            model=cfg["model_name"],
            prompt=prompt,
        )
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", cfg["url"], json=body, headers=_LOCAL_HEADERS) as resp:
                if resp.status_code != 200:
                    body_text = await resp.aread()
                    raise ValueError(f"Local LLM Error: {resp.status_code} - {body_text.decode()}")
                content, finish_reason = await _consume_sse_httpx_async(resp)
        except httpx.HTTPError as e:
            raise ValueError(
                f"Local LLM server unreachable at {cfg['url']}. "
                f"Make sure the server is running. Error: {e}"
            )

        if not content:
            raise ValueError("Empty response from local LLM")

        accumulated = content
        continuation_count = 0

        while _should_continue(finish_reason, accumulated) and continuation_count < _MAX_CONTINUATIONS:
            continuation_count += 1
            print(
                f"[LocalLLM] Response truncated (finish_reason={finish_reason}), "
                f"auto-continuing ({continuation_count}/{_MAX_CONTINUATIONS})..."
            )
            cont_body = dict(body)
            cont_body["question"] = _build_continuation_prompt(prompt, accumulated)

            await emit_llm_activity(
                build_llm_call_step(
                    provider="local_llm",
                    model=cfg["model_name"],
                    prompt=cont_body["question"],
                    phase_note=f"continuation {continuation_count}/{_MAX_CONTINUATIONS}",
                )
            )
            try:
                async with client.stream("POST", cfg["url"], json=cont_body, headers=_LOCAL_HEADERS) as cont_resp:
                    if cont_resp.status_code != 200:
                        print(f"[LocalLLM] Continuation call failed: {cont_resp.status_code}")
                        break
                    cont_content, finish_reason = await _consume_sse_httpx_async(cont_resp)
            except httpx.HTTPError:
                break

            if not cont_content:
                break
            accumulated += cont_content

    if continuation_count:
        print(f"[LocalLLM] Completed with {continuation_count} continuation(s). Total: {len(accumulated)} chars")
    else:
        print(f"[LocalLLM] Response received | {len(accumulated)} chars")

    _log_cost(cfg["model_name"], prompt, accumulated)
    await emit_llm_activity(
        build_llm_response_step(
            provider="local_llm",
            model=cfg["model_name"],
            text=accumulated,
        )
    )
    return accumulated


# ---------------------------------------------------------------------------
# Sync call (httpx) — SSE streaming + continuation  (BPMN, Market Research, Email agents)
# ---------------------------------------------------------------------------

def sync_local_llm_call_httpx(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 180.0,
) -> str:
    """Synchronous httpx call to local LLM via SSE stream, with auto-continuation."""
    cfg = _get_local_llm_config()
    body = _build_local_request(prompt, temperature, max_tokens)

    print(f"[LocalLLM] SSE POST {cfg['url']} | model={cfg['model_name']} | prompt={len(prompt)} chars")

    with httpx.Client(timeout=timeout) as client:
        try:
            with client.stream("POST", cfg["url"], json=body, headers=_LOCAL_HEADERS) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise ValueError(f"Local LLM Error: {resp.status_code} - {resp.text}")
                content, finish_reason = _consume_sse_httpx_sync(resp)
        except httpx.HTTPError as e:
            raise ValueError(
                f"Local LLM server unreachable at {cfg['url']}. "
                f"Make sure the server is running. Error: {e}"
            )

        if not content:
            raise ValueError("Empty response from local LLM")

        accumulated = content
        continuation_count = 0

        while _should_continue(finish_reason, accumulated) and continuation_count < _MAX_CONTINUATIONS:
            continuation_count += 1
            print(
                f"[LocalLLM] Response truncated (finish_reason={finish_reason}), "
                f"auto-continuing ({continuation_count}/{_MAX_CONTINUATIONS})..."
            )
            cont_body = dict(body)
            cont_body["question"] = _build_continuation_prompt(prompt, accumulated)

            try:
                with client.stream("POST", cfg["url"], json=cont_body, headers=_LOCAL_HEADERS) as cont_resp:
                    if cont_resp.status_code != 200:
                        print(f"[LocalLLM] Continuation call failed: {cont_resp.status_code}")
                        break
                    cont_content, finish_reason = _consume_sse_httpx_sync(cont_resp)
            except httpx.HTTPError:
                break

            if not cont_content:
                break
            accumulated += cont_content

    if continuation_count:
        print(f"[LocalLLM] Completed with {continuation_count} continuation(s). Total: {len(accumulated)} chars")
    else:
        print(f"[LocalLLM] Response received | {len(accumulated)} chars")

    _log_cost(cfg["model_name"], prompt, accumulated)
    return accumulated


# ---------------------------------------------------------------------------
# Ollama Cloud (https://ollama.com/api/chat) — NDJSON streaming
# ---------------------------------------------------------------------------


def normalize_ollama_cloud_api_token(raw: Optional[str]) -> str:
    """Normalize Ollama Cloud API keys from UI / JSON / copy-paste (401s are often hidden chars)."""
    t = (raw or "").strip()
    if not t:
        return ""
    t = t.lstrip("\ufeff")
    t = t.strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    t = t.replace("\r", "").replace("\n", "").strip()
    if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
        t = t[1:-1].strip()
    return t


def _resolve_raw_ollama_cloud_credential() -> str:
    """First non-empty API key for https://ollama.com/api (before normalization).

    Prefer ``OLLAMA_CLOUD_*`` first: those are what the agent **Config** tab sends via
    ``user_config`` / ``apply_user_config`` (per-request env). Fall back to
    ``OLLAMA_API_KEY`` from ``server/.env`` when the UI did not set a cloud token.
    """
    for env_name in ("ON_PREM_CLOUD_ACCESS_TOKEN", "OLLAMA_CLOUD_BEARER_TOKEN", "OLLAMA_API_KEY"):
        v = (os.getenv(env_name) or "").strip()
        if v:
            return v
    return ""


def ollama_cloud_credential_env_source() -> str:
    """Which env name ``_resolve_raw_ollama_cloud_credential`` used, or ``none`` (for logs only)."""
    for env_name in ("ON_PREM_CLOUD_ACCESS_TOKEN", "OLLAMA_CLOUD_BEARER_TOKEN", "OLLAMA_API_KEY"):
        if (os.getenv(env_name) or "").strip():
            return env_name
    return "none"


def ollama_cloud_credential_source_log() -> str:
    """Log-friendly provenance: env var name + where it usually comes from."""
    src = ollama_cloud_credential_env_source()
    if src == "ON_PREM_CLOUD_ACCESS_TOKEN":
        return f"{src} (agent Config → user_config)"
    if src == "OLLAMA_CLOUD_BEARER_TOKEN":
        return f"{src} (agent Config → user_config)"
    if src == "OLLAMA_API_KEY":
        return f"{src} (server .env fallback)"
    return f"{src}"


def resolved_ollama_cloud_model() -> str:
    """Model id sent to Ollama Cloud (``ON_PREM_CLOUD_MODEL``).

    Langfuse and other tracing must use this — not ``OLLAMA_MODEL``, which is unrelated
    and often set to a local tag (e.g. ``llama2``) in developer ``.env`` files.
    """
    return (os.getenv("ON_PREM_CLOUD_MODEL") or "").strip()


def _get_ollama_cloud_config() -> dict:
    return {
        "url": (os.getenv("OLLAMA_CLOUD_URL") or "https://ollama.com/api/chat").strip(),
        "token": normalize_ollama_cloud_api_token(_resolve_raw_ollama_cloud_credential()),
        "model": resolved_ollama_cloud_model(),
    }


def is_llm_provider_configured() -> bool:
    """True when the active ``LLM_PROVIDER`` has the credentials that backend needs."""
    prov = get_llm_provider()
    if prov == "pwc_genai":
        return bool((os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip())
    if prov == "local_llm":
        return True
    if prov == "ollama_cloud":
        return bool(_get_ollama_cloud_config()["token"])
    return False


def describe_missing_llm_credentials() -> str:
    """User-facing hint when :func:`is_llm_provider_configured` is False."""
    prov = get_llm_provider()
    if prov == "ollama_cloud":
        return (
            "Ollama Cloud is selected (`LLM_PROVIDER=ollama_cloud`) but no API key was found. "
            "Set `OLLAMA_API_KEY` (see https://docs.ollama.com/api/authentication) and/or "
            "`ON_PREM_CLOUD_ACCESS_TOKEN` in the agent **Config** tab, then Save."
        )
    if prov == "local_llm":
        return (
            "Local LLM is selected; ensure `LOCAL_LLM_URL` is reachable and the local inference server is running."
        )
    return "PwC GenAI is selected; set `PWC_GENAI_API_KEY` or `GEMINI_API_KEY`."


def _consume_ollama_ndjson_lines(
    line_iter: Iterator[str],
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Optional[str]]:
    accumulated = ""
    thinking_accumulated = ""
    finish_reason: Optional[str] = None
    raw_lines_debug: list = []
    for raw in line_iter:
        line = raw.strip() if isinstance(raw, str) else str(raw).strip()
        if not line:
            continue
        raw_lines_debug.append(line[:200])
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = data.get("message") or {}
        piece = msg.get("content") or ""
        thinking_piece = msg.get("thinking") or ""
        if piece:
            accumulated += piece
            if on_chunk:
                on_chunk(piece)
        if thinking_piece:
            thinking_accumulated += thinking_piece
        if data.get("done"):
            finish_reason = data.get("done_reason") or data.get("finish_reason")
    if not accumulated and thinking_accumulated:
        print(
            f"[OllamaCloud] WARNING: response content is empty but thinking has "
            f"{len(thinking_accumulated)} chars — model used all tokens for <think> blocks. "
            f"First 500 chars of thinking: {thinking_accumulated[:500]}"
        )
        print(f"[OllamaCloud] Last raw lines (up to 5): {raw_lines_debug[-5:]}")
    return accumulated, finish_reason


async def _consume_ollama_ndjson_lines_async(
    line_iter: AsyncIterator[str],
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Optional[str]]:
    accumulated = ""
    thinking_accumulated = ""
    finish_reason: Optional[str] = None
    raw_lines_debug: list = []
    async for raw in line_iter:
        line = raw.strip() if isinstance(raw, str) else str(raw).strip()
        if not line:
            continue
        raw_lines_debug.append(line[:200])
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = data.get("message") or {}
        piece = msg.get("content") or ""
        thinking_piece = msg.get("thinking") or ""
        if piece:
            accumulated += piece
            if on_chunk:
                on_chunk(piece)
        if thinking_piece:
            thinking_accumulated += thinking_piece
        if data.get("done"):
            finish_reason = data.get("done_reason") or data.get("finish_reason")
    if not accumulated and thinking_accumulated:
        print(
            f"[OllamaCloud] WARNING: response content is empty but thinking has "
            f"{len(thinking_accumulated)} chars — model used all tokens for <think> blocks. "
            f"First 500 chars of thinking: {thinking_accumulated[:500]}"
        )
        print(f"[OllamaCloud] Last raw lines (up to 5): {raw_lines_debug[-5:]}")
    elif not accumulated and not thinking_accumulated:
        print(f"[OllamaCloud] WARNING: both content and thinking are empty. Lines seen: {len(raw_lines_debug)}. Last 3: {raw_lines_debug[-3:]}")
    return accumulated, finish_reason


def _ollama_chat_body(
    user_content: str,
    temperature: Optional[float] = None,
    num_predict: Optional[int] = None,
    think: Optional[bool] = None,
) -> dict:
    cfg = _get_ollama_cloud_config()
    messages = []
    if think is False:
        # Prompt-level disable: qwen3.x and similar models respect /no_think in
        # a system message even when the API-level options.think field is ignored
        # by the hosted endpoint (Ollama Cloud does not honour options.think).
        messages.append({"role": "system", "content": "/no_think"})
    messages.append({"role": "user", "content": user_content})
    body: dict = {
        "model": cfg["model"],
        "messages": messages,
        "stream": True,
    }
    options: dict = {}
    if temperature is not None:
        options["temperature"] = temperature
    if num_predict is not None:
        options["num_predict"] = num_predict
    if think is not None:
        options["think"] = think
    if options:
        body["options"] = options
    return body


def _ollama_headers() -> dict:
    cfg = _get_ollama_cloud_config()
    return {
        "Authorization": f"Bearer {cfg['token']}",
        "Content-Type": "application/json",
        "Accept": "application/x-ndjson, application/json",
    }


def _ollama_cloud_max_http_retries() -> int:
    try:
        n = int(os.getenv("OLLAMA_CLOUD_HTTP_RETRIES", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def _ollama_cloud_retryable_status(status_code: int) -> bool:
    return status_code in (408, 429, 500, 502, 503, 504)


def _sync_ollama_post_stream_with_retries(
    url: str,
    headers: dict,
    body: dict,
    timeout: int,
    *,
    label: str = "POST",
) -> requests.Response:
    """POST with streaming; retries transient server / transport failures."""
    max_retries = _ollama_cloud_max_http_retries()
    last: Optional[requests.Response] = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url, json=body, headers=headers, timeout=timeout, stream=True,
            )
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = min(2**attempt * 2, 45)
                print(
                    f"[OllamaCloud] {label} transport error ({e!s}); "
                    f"retry in {wait}s ({attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            raise ValueError(f"Ollama Cloud unreachable at {url}. Error: {e}") from e
        last = resp
        if resp.status_code == 200:
            return resp
        try:
            _ = resp.text
        except Exception:
            pass
        if not _ollama_cloud_retryable_status(resp.status_code) or attempt >= max_retries - 1:
            return resp
        try:
            resp.close()
        except Exception:
            pass
        wait = min(2**attempt * 2, 45)
        print(
            f"[OllamaCloud] {label} HTTP {resp.status_code}; retry in {wait}s "
            f"({attempt + 1}/{max_retries})"
        )
        time.sleep(wait)
    assert last is not None
    return last


def _ollama_cloud_http_error_message(status_code: int, body_snippet: str) -> str:
    """Build a ValueError message; adds setup hints for auth failures."""
    raw = (body_snippet or "").strip()
    if len(raw) > 400:
        raw = raw[:400] + "…"
    msg = f"Ollama Cloud error: {status_code} - {raw}" if raw else f"Ollama Cloud error: {status_code}"
    if status_code == 401:
        src = ollama_cloud_credential_env_source()
        msg += (
            " — Ollama rejected the bearer token. This request used env var "
            f"**`{src}`** (precedence: **`ON_PREM_CLOUD_ACCESS_TOKEN` / `OLLAMA_CLOUD_BEARER_TOKEN`** from agent Config → "
            "then **`OLLAMA_API_KEY`** in `server/.env` as fallback). "
            "Create a new key at https://ollama.com/settings/keys . "
            "If you use the Config tab, set **ON_PREM_CLOUD_ACCESS_TOKEN** there and Save. "
            "If you still see 401, clear the Config field and use **`OLLAMA_API_KEY`** in `.env` only, or fix the key "
            "that matches the log `credential_source`. Or switch **LLM_PROVIDER** to **PwC GenAI** or **Local LLM**."
        )
    if status_code in (500, 502, 503, 504):
        msg += (
            " — Often a **transient Ollama Cloud outage** or an **upstream model error**; the client retries a few "
            "times automatically (set **`OLLAMA_CLOUD_HTTP_RETRIES`** to increase). "
            "If it persists: confirm **`ON_PREM_CLOUD_MODEL`** exists for your account, try another model, shorten "
            "very large prompts (e.g. SQL DB Agent schema text), or check https://status.ollama.com ."
        )
    return msg


def sync_ollama_cloud_call(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: int = 180,
    on_stream_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    """Synchronous Ollama Cloud chat with NDJSON streaming and auto-continuation."""
    cfg = _get_ollama_cloud_config()
    if not cfg["token"]:
        raise ValueError(
            "Ollama Cloud requires `OLLAMA_API_KEY` (see Ollama docs) or `ON_PREM_CLOUD_ACCESS_TOKEN` in configuration."
        )

    url = cfg["url"]
    headers = _ollama_headers()
    # Disable thinking mode: prevents thinking models (e.g. qwen3.x) from
    # burning the entire num_predict budget on <think> blocks, leaving no
    # tokens for the actual response content.
    body = _ollama_chat_body(prompt, temperature=temperature, num_predict=max_tokens, think=False)

    print(
        f"[OllamaCloud] POST {url} | model={cfg['model']} | prompt={len(prompt)} chars | "
        f"credential_source={ollama_cloud_credential_source_log()}"
    )

    resp = _sync_ollama_post_stream_with_retries(
        url, headers, body, timeout, label="chat",
    )

    if resp.status_code != 200:
        raise ValueError(_ollama_cloud_http_error_message(resp.status_code, resp.text))

    content, finish_reason = _consume_ollama_ndjson_lines(
        resp.iter_lines(decode_unicode=True),
        on_chunk=on_stream_chunk,
    )
    if not content:
        raise ValueError("Empty response from Ollama Cloud")

    accumulated = content
    continuation_count = 0

    while _should_continue(finish_reason, accumulated) and continuation_count < _MAX_CONTINUATIONS:
        continuation_count += 1
        print(
            f"[OllamaCloud] Truncated (finish_reason={finish_reason}), "
            f"continuing ({continuation_count}/{_MAX_CONTINUATIONS})..."
        )
        cont_body = _ollama_chat_body(_build_continuation_prompt(prompt, accumulated), temperature=temperature, num_predict=max_tokens, think=False)
        cont_resp = _sync_ollama_post_stream_with_retries(
            url, headers, cont_body, timeout, label="continuation",
        )
        if cont_resp.status_code != 200:
            print(
                f"[OllamaCloud] Continuation failed: "
                f"{_ollama_cloud_http_error_message(cont_resp.status_code, cont_resp.text)}"
            )
            break
        cont_content, finish_reason = _consume_ollama_ndjson_lines(
            cont_resp.iter_lines(decode_unicode=True),
            on_chunk=on_stream_chunk,
        )
        if not cont_content:
            break
        accumulated += cont_content

    _log_cost(cfg["model"], prompt, accumulated)
    return _strip_think_blocks(accumulated)


async def _async_ollama_stream_chat_with_retries(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    body: dict,
    timeout: float,
    *,
    label: str,
    on_chunk: Optional[Callable[[str], None]] = None,
) -> Tuple[str, Optional[str]]:
    max_retries = _ollama_cloud_max_http_retries()
    last_transport: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with client.stream(
                "POST", url, json=body, headers=headers, timeout=timeout,
            ) as resp:
                if resp.status_code != 200:
                    body_text = await resp.aread()
                    snippet = body_text.decode(errors="replace")
                    if _ollama_cloud_retryable_status(resp.status_code) and attempt < max_retries - 1:
                        wait = min(2**attempt * 2, 45)
                        print(
                            f"[OllamaCloud] async {label} HTTP {resp.status_code}; "
                            f"retry in {wait}s ({attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    raise ValueError(
                        _ollama_cloud_http_error_message(resp.status_code, snippet)
                    )
                content, finish_reason = await _consume_ollama_ndjson_lines_async(
                    resp.aiter_lines(),
                    on_chunk=on_chunk,
                )
                return content, finish_reason
        except ValueError:
            raise
        except httpx.HTTPError as e:
            last_transport = e
            if attempt < max_retries - 1:
                wait = min(2**attempt * 2, 45)
                print(
                    f"[OllamaCloud] async {label} transport ({e!s}); "
                    f"retry in {wait}s ({attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                continue
            raise ValueError(f"Ollama Cloud unreachable at {url}. Error: {e}") from e
    if last_transport:
        raise ValueError(f"Ollama Cloud unreachable at {url}. Error: {last_transport}") from last_transport
    raise ValueError("Ollama Cloud: retries exhausted")


async def async_ollama_cloud_call(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 180.0,
) -> str:
    cfg = _get_ollama_cloud_config()
    if not cfg["token"]:
        raise ValueError(
            "Ollama Cloud requires `OLLAMA_API_KEY` (see Ollama docs) or `ON_PREM_CLOUD_ACCESS_TOKEN` in configuration."
        )
    url = cfg["url"]
    headers = _ollama_headers()
    body = _ollama_chat_body(prompt, temperature=temperature, num_predict=max_tokens, think=False)

    print(
        f"[OllamaCloud] async POST {url} | model={cfg['model']} | prompt={len(prompt)} chars | "
        f"credential_source={ollama_cloud_credential_source_log()}"
    )

    await emit_llm_activity(
        build_llm_call_step(
            provider="ollama_cloud",
            model=cfg["model"],
            prompt=prompt,
        )
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        content, finish_reason = await _async_ollama_stream_chat_with_retries(
            client, url, headers, body, timeout, label="chat", on_chunk=None,
        )

        if not content:
            raise ValueError("Empty response from Ollama Cloud")

        accumulated = content
        continuation_count = 0

        while _should_continue(finish_reason, accumulated) and continuation_count < _MAX_CONTINUATIONS:
            continuation_count += 1
            cont_body = _ollama_chat_body(_build_continuation_prompt(prompt, accumulated), temperature=temperature, num_predict=max_tokens, think=False)
            await emit_llm_activity(
                build_llm_call_step(
                    provider="ollama_cloud",
                    model=cfg["model"],
                    prompt=_build_continuation_prompt(prompt, accumulated),
                    phase_note=f"continuation {continuation_count}/{_MAX_CONTINUATIONS}",
                )
            )
            try:
                cont_content, finish_reason = await _async_ollama_stream_chat_with_retries(
                    client, url, headers, cont_body, timeout,
                    label="continuation", on_chunk=None,
                )
            except ValueError:
                break
            if not cont_content:
                break
            accumulated += cont_content

        _log_cost(cfg["model"], prompt, accumulated)
        await emit_llm_activity(
            build_llm_response_step(
                provider="ollama_cloud",
                model=cfg["model"],
                text=accumulated,
            )
        )
        return _strip_think_blocks(accumulated)


def sync_ollama_cloud_call_httpx(
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 180.0,
) -> str:
    """Same as ``sync_ollama_cloud_call`` (requests + retries); kept for API compatibility."""
    return sync_ollama_cloud_call(
        prompt, temperature, max_tokens, int(timeout), on_stream_chunk=None,
    )
