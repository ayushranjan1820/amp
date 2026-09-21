import asyncio
import os
import time
import requests
import httpx
from typing import Callable, Optional, Tuple
from requests.exceptions import ChunkedEncodingError, ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from agents.token_manager import validate_and_prepare, log_token_usage, count_tokens
from agents.local_llm import (
    get_llm_provider,
    resolved_ollama_cloud_model,
    sync_local_llm_call,
    async_local_llm_call,
    sync_local_llm_call_httpx,
    sync_ollama_cloud_call,
    async_ollama_cloud_call,
    sync_ollama_cloud_call_httpx,
)
from agents.llm_activity_stream import (
    build_llm_call_step,
    build_llm_response_step,
    emit_llm_activity,
    emit_llm_activity_sync,
)

# Re-export Langfuse context helpers so that dispatch.py and api.py can import
# them from this module without being aware of langfuse_tracer directly.
try:
    from langfuse_tracer import (  # noqa: F401
        set_current_agent,
        set_current_user,
        set_current_session,
        trace_llm_call as _lf_trace,
    )
    _LANGFUSE_AVAILABLE = True
except ImportError:
    _LANGFUSE_AVAILABLE = False
    import logging

    _llm_cont_log = logging.getLogger("agents.llm_continuation")
    _llm_cont_log.warning(
        "langfuse_tracer import failed — LLM calls will not be sent to Langfuse "
        "(fix import path or install deps)."
    )

    def set_current_agent(name: str) -> None:  # type: ignore[misc]
        pass

    def set_current_user(user_id: str) -> None:  # type: ignore[misc]
        pass

    def set_current_session(session_id: str) -> None:  # type: ignore[misc]
        pass

    def _lf_trace(**_kwargs) -> None:  # type: ignore[misc]
        pass

# Transient transport errors (e.g. RemoteDisconnected, LB idle timeout) — not retried by status-code logic alone.
_RETRIABLE_REQUESTS_ERRORS = (
    RequestsConnectionError,
    RequestsTimeout,
    ChunkedEncodingError,
)

_RETRIABLE_HTTPX_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)

def _log_llm_cost(model: str, prompt_tokens: int, completion_tokens: int, agent_name: str = None):
    try:
        from cost_tracker import log_cost_event
        log_cost_event(
            event_type="llm_call",
            agent_name=agent_name or "unknown",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception as e:
        print(f"[CostTracker] LLM cost logging failed: {e}")

MAX_CONTINUATIONS = 3

# Shrink factor applied to the prompt when the gateway rejects it with a
# ContextWindowExceededError. Keeps ~60% of the current (already-trimmed)
# prompt and retries once — lets us self-heal when tiktoken underestimates
# the server-side (e.g. Gemini) tokenizer count.
_CONTEXT_EXCEEDED_SHRINK = 0.6
_CONTEXT_EXCEEDED_MARKERS = (
    "ContextWindowExceededError",
    "context_window_exceeded",
    "input token count exceeds",
    "maximum number of tokens",
)


def _is_context_window_error(status_code: int, body_text: str) -> bool:
    if status_code != 400:
        return False
    lower = (body_text or "").lower()
    return any(marker.lower() in lower for marker in _CONTEXT_EXCEEDED_MARKERS)


def _shrink_prompt(prompt: str, factor: float = _CONTEXT_EXCEEDED_SHRINK) -> str:
    """Keep the tail of the prompt (most recent context) after aggressive trim."""
    from agents.token_manager import _get_encoder, count_tokens  # noqa: PLC0415

    encoder = _get_encoder()
    encoded = encoder.encode(prompt)
    target = max(256, int(len(encoded) * factor))
    if target >= len(encoded):
        return prompt
    marker = "\n\n... [Content aggressively trimmed after ContextWindowExceededError retry] ...\n\n"
    marker_tokens = encoder.encode(marker)
    tail = encoded[-(target - len(marker_tokens)):] if target > len(marker_tokens) else encoded[-target:]
    rebuilt = marker_tokens + tail
    shrunk = encoder.decode(rebuilt)
    print(
        f"[LLM Retry] Context window exceeded — shrinking prompt from "
        f"{count_tokens(prompt)} to {count_tokens(shrunk)} tiktoken tokens"
    )
    return shrunk

CONTINUATION_PROMPT_TEMPLATE = (
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


def _resolve_pwc_genai_request_model(request_body: dict) -> str:
    """Set ``request_body['model']`` from the body or ``PREMIUM_MODEL`` env.

    ``BaseAIService`` often sends ``model: ""``; continuation code used to read
    ``PREMIUM_MODEL`` for logging only and never wrote it back, so the HTTP
    payload still had an empty model and the gateway returned 400.
    """
    raw = request_body.get("model") or os.getenv("PREMIUM_MODEL", "") or ""
    model = str(raw).strip()
    if not model:
        raise ValueError(
            "No GenAI model configured: set PREMIUM_MODEL in the environment to a model "
            "your API key can use, or pass default_model when constructing BaseAIService."
        )
    request_body["model"] = model
    return model


def _extract_content_and_finish_reason(result: dict) -> Tuple[str, Optional[str]]:
    content = ""
    finish_reason = None

    if "choices" in result and len(result["choices"]) > 0:
        choice = result["choices"][0]
        finish_reason = choice.get("finish_reason") or choice.get("finishReason")
        if "message" in choice and "content" in choice["message"]:
            content = choice["message"]["content"]
        elif "text" in choice:
            content = choice["text"]
    elif "text" in result:
        content = result["text"]
    elif "content" in result:
        content = result["content"]

    return content, finish_reason


def _should_continue(finish_reason: Optional[str], content: str) -> bool:
    if finish_reason and finish_reason.lower() in ("length", "max_tokens"):
        return True
    if not finish_reason and content:
        stripped = content.rstrip()
        if stripped and stripped[-1] not in '.!?;>}])\n"\'`':
            if len(content) > 2000:
                return True
    return False


def _build_continuation_prompt(original_prompt: str, partial_response: str) -> str:
    trimmed = partial_response
    if len(trimmed) > 6000:
        trimmed = "...[earlier content omitted]...\n\n" + trimmed[-6000:]
    return CONTINUATION_PROMPT_TEMPLATE.format(
        original_prompt=original_prompt,
        partial=trimmed,
    )


def _requests_post_with_retries(
    endpoint_url: str,
    headers: dict,
    json_body: dict,
    timeout: int,
    max_retries: int = 3,
):
    """POST with retries on 5xx and transient connection/transport failures."""
    last_response = None
    for attempt in range(max_retries):
        try:
            last_response = requests.post(
                endpoint_url,
                json=json_body,
                headers=headers,
                timeout=timeout,
            )
        except _RETRIABLE_REQUESTS_ERRORS as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt * 2
                print(
                    f"[LLM Retry] Transient request error ({type(e).__name__}): {e!s}, "
                    f"retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
                continue
            raise

        if last_response.status_code < 500:
            return last_response
        if attempt < max_retries - 1:
            wait_time = 2**attempt * 2
            print(
                f"[LLM Retry] Got {last_response.status_code}, retrying in {wait_time}s "
                f"(attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(wait_time)
    return last_response


async def _httpx_post_with_retries(
    client: httpx.AsyncClient,
    endpoint_url: str,
    headers: dict,
    json_body: dict,
    max_retries: int = 3,
):
    last_response = None
    for attempt in range(max_retries):
        try:
            last_response = await client.post(
                endpoint_url,
                json=json_body,
                headers=headers,
            )
        except _RETRIABLE_HTTPX_ERRORS as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt * 2
                print(
                    f"[LLM Retry] Transient request error ({type(e).__name__}): {e!s}, "
                    f"retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})..."
                )
                await asyncio.sleep(wait_time)
                continue
            raise

        if last_response.status_code < 500:
            return last_response
        if attempt < max_retries - 1:
            wait_time = 2**attempt * 2
            print(
                f"[LLM Retry] Got {last_response.status_code}, retrying in {wait_time}s "
                f"(attempt {attempt + 1}/{max_retries})..."
            )
            await asyncio.sleep(wait_time)
    return last_response


def _httpx_sync_post_with_retries(
    client: httpx.Client,
    endpoint_url: str,
    headers: dict,
    json_body: dict,
    max_retries: int = 3,
):
    last_response = None
    for attempt in range(max_retries):
        try:
            last_response = client.post(
                endpoint_url,
                json=json_body,
                headers=headers,
            )
        except _RETRIABLE_HTTPX_ERRORS as e:
            if attempt < max_retries - 1:
                wait_time = 2**attempt * 2
                print(
                    f"[LLM Retry] Transient request error ({type(e).__name__}): {e!s}, "
                    f"retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(wait_time)
                continue
            raise

        if last_response.status_code < 500:
            return last_response
        if attempt < max_retries - 1:
            wait_time = 2**attempt * 2
            print(
                f"[LLM Retry] Got {last_response.status_code}, retrying in {wait_time}s "
                f"(attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(wait_time)
    return last_response


def _emit_simulated_stream_chunks(text: str, on_chunk: Optional[Callable[[str], None]], size: int = 96) -> None:
    """Fire on_chunk with slices of text (used when remote API is non-streaming)."""
    if not on_chunk or not text:
        return
    for i in range(0, len(text), size):
        on_chunk(text[i : i + size])


def sync_call_with_continuation(
    endpoint_url: str,
    headers: dict,
    request_body: dict,
    original_prompt: str,
    timeout: int = 180,
    max_continuations: int = MAX_CONTINUATIONS,
    on_stream_chunk: Optional[Callable[[str], None]] = None,
) -> str:
    _lf_start = time.time()
    prov = get_llm_provider()
    if prov == "local_llm":
        import os as _os
        _lf_model = _os.getenv("LOCAL_LLM_MODEL", "local_llm")
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        max_tokens = request_body.get("max_tokens")
        emit_llm_activity_sync(
            build_llm_call_step(
                provider="local_llm",
                model=_lf_model,
                prompt=prompt,
            )
        )
        result = sync_local_llm_call(
            prompt, temperature, max_tokens, timeout, on_stream_chunk=on_stream_chunk
        )
        emit_llm_activity_sync(
            build_llm_response_step(
                provider="local_llm",
                model=_lf_model,
                text=result,
            )
        )
        _lf_trace(
            model=_lf_model, prompt=original_prompt, completion=result,
            prompt_tokens=count_tokens(original_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "sync/local_llm"},
        )
        return result
    if prov == "ollama_cloud":
        _lf_model = resolved_ollama_cloud_model()
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        requested_max_tokens = request_body.get("max_tokens", 8192)
        safe_prompt, safe_max_tokens = validate_and_prepare(
            "ollama_cloud", prompt, requested_max_tokens,
        )
        log_token_usage("ollama_cloud", safe_prompt, safe_max_tokens)
        emit_llm_activity_sync(
            build_llm_call_step(
                provider="ollama_cloud",
                model=_lf_model,
                prompt=safe_prompt,
            )
        )
        result = sync_ollama_cloud_call(
            safe_prompt, temperature, safe_max_tokens, timeout, on_stream_chunk=on_stream_chunk,
        )
        emit_llm_activity_sync(
            build_llm_response_step(
                provider="ollama_cloud",
                model=_lf_model,
                text=result,
            )
        )
        _lf_trace(
            model=_lf_model, prompt=safe_prompt, completion=result,
            prompt_tokens=count_tokens(safe_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "sync/ollama_cloud"},
        )
        return result

    model = _resolve_pwc_genai_request_model(request_body)
    prompt = request_body.get("prompt", original_prompt)
    requested_max_tokens = request_body.get("max_tokens", 8192)

    safe_prompt, safe_max_tokens = validate_and_prepare(model, prompt, requested_max_tokens)
    request_body["prompt"] = safe_prompt
    request_body["max_tokens"] = safe_max_tokens
    log_token_usage(model, safe_prompt, safe_max_tokens)

    emit_llm_activity_sync(
        build_llm_call_step(
            provider="pwc_genai",
            model=str(model),
            prompt=safe_prompt,
        )
    )
    response = _requests_post_with_retries(
        endpoint_url, headers, request_body, timeout, max_retries=3
    )

    if response.status_code != 200:
        if _is_context_window_error(response.status_code, response.text):
            shrunk_prompt = _shrink_prompt(request_body.get("prompt", ""))
            request_body["prompt"] = shrunk_prompt
            response = _requests_post_with_retries(
                endpoint_url, headers, request_body, timeout, max_retries=2
            )
        if response.status_code != 200:
            raise ValueError(f"GenAI API Error: {response.status_code} - {response.text}")

    result = response.json()
    content, finish_reason = _extract_content_and_finish_reason(result)

    if not content:
        raise ValueError("Unexpected response format from GenAI API")

    accumulated = content
    continuation_count = 0

    while _should_continue(finish_reason, accumulated) and continuation_count < max_continuations:
        continuation_count += 1
        print(f"[LLM Continuation] Response truncated (finish_reason={finish_reason}), auto-continuing ({continuation_count}/{max_continuations})...")

        continuation_body = dict(request_body)
        continuation_body["prompt"] = _build_continuation_prompt(original_prompt, accumulated)

        emit_llm_activity_sync(
            build_llm_call_step(
                provider="pwc_genai",
                model=str(model),
                prompt=continuation_body["prompt"],
                phase_note=f"continuation {continuation_count}/{max_continuations}",
            )
        )
        resp = _requests_post_with_retries(
            endpoint_url, headers, continuation_body, timeout, max_retries=3
        )

        if resp.status_code != 200:
            print(f"[LLM Continuation] Continuation call failed: {resp.status_code}")
            break

        cont_result = resp.json()
        cont_content, finish_reason = _extract_content_and_finish_reason(cont_result)

        if not cont_content:
            break

        accumulated += cont_content

    if continuation_count > 0:
        print(f"[LLM Continuation] Completed with {continuation_count} continuation(s). Total length: {len(accumulated)} chars")

    completion_tokens = count_tokens(accumulated)
    prompt_tokens = count_tokens(safe_prompt)
    _log_llm_cost(model, prompt_tokens, completion_tokens)

    emit_llm_activity_sync(
        build_llm_response_step(
            provider="pwc_genai",
            model=str(model),
            text=accumulated,
        )
    )
    _emit_simulated_stream_chunks(accumulated, on_stream_chunk)

    _lf_trace(
        model=model, prompt=safe_prompt, completion=accumulated,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        latency_ms=(time.time() - _lf_start) * 1000,
        extra_metadata={"path": "sync/pwc_genai", "continuations": continuation_count},
    )

    return accumulated


async def async_call_with_continuation(
    endpoint_url: str,
    headers: dict,
    request_body: dict,
    original_prompt: str,
    timeout: float = 120.0,
    max_continuations: int = MAX_CONTINUATIONS,
) -> str:
    _lf_start = time.time()
    prov = get_llm_provider()
    if prov == "local_llm":
        import os as _os
        _lf_model = _os.getenv("LOCAL_LLM_MODEL", "local_llm")
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        max_tokens = request_body.get("max_tokens")
        result = await async_local_llm_call(prompt, temperature, max_tokens, timeout)
        _lf_trace(
            model=_lf_model, prompt=original_prompt, completion=result,
            prompt_tokens=count_tokens(original_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "async/local_llm"},
        )
        return result
    if prov == "ollama_cloud":
        _lf_model = resolved_ollama_cloud_model()
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        requested_max_tokens = request_body.get("max_tokens", 8192)
        safe_prompt, safe_max_tokens = validate_and_prepare(
            "ollama_cloud", prompt, requested_max_tokens,
        )
        log_token_usage("ollama_cloud", safe_prompt, safe_max_tokens)
        result = await async_ollama_cloud_call(
            safe_prompt, temperature, safe_max_tokens, timeout,
        )
        _lf_trace(
            model=_lf_model, prompt=safe_prompt, completion=result,
            prompt_tokens=count_tokens(safe_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "async/ollama_cloud"},
        )
        return result

    model = _resolve_pwc_genai_request_model(request_body)
    prompt = request_body.get("prompt", original_prompt)
    requested_max_tokens = request_body.get("max_tokens", 8192)

    safe_prompt, safe_max_tokens = validate_and_prepare(model, prompt, requested_max_tokens)
    request_body["prompt"] = safe_prompt
    request_body["max_tokens"] = safe_max_tokens
    log_token_usage(model, safe_prompt, safe_max_tokens)

    async with httpx.AsyncClient(timeout=timeout) as client:
        await emit_llm_activity(
            build_llm_call_step(
                provider="pwc_genai",
                model=str(model),
                prompt=safe_prompt,
            )
        )
        response = await _httpx_post_with_retries(
            client, endpoint_url, headers, request_body, max_retries=3
        )

        if response.status_code != 200:
            if _is_context_window_error(response.status_code, response.text):
                shrunk_prompt = _shrink_prompt(request_body.get("prompt", ""))
                request_body["prompt"] = shrunk_prompt
                response = await _httpx_post_with_retries(
                    client, endpoint_url, headers, request_body, max_retries=2
                )
            if response.status_code != 200:
                raise ValueError(f"GenAI API Error: {response.status_code} - {response.text}")

        result = response.json()
        content, finish_reason = _extract_content_and_finish_reason(result)

        if not content:
            raise ValueError("Unexpected response format from GenAI API")

        accumulated = content
        continuation_count = 0

        while _should_continue(finish_reason, accumulated) and continuation_count < max_continuations:
            continuation_count += 1
            print(f"[LLM Continuation] Response truncated (finish_reason={finish_reason}), auto-continuing ({continuation_count}/{max_continuations})...")

            continuation_body = dict(request_body)
            continuation_body["prompt"] = _build_continuation_prompt(original_prompt, accumulated)

            await emit_llm_activity(
                build_llm_call_step(
                    provider="pwc_genai",
                    model=str(model),
                    prompt=continuation_body["prompt"],
                    phase_note=f"continuation {continuation_count}/{max_continuations}",
                )
            )
            resp = await _httpx_post_with_retries(
                client, endpoint_url, headers, continuation_body, max_retries=3
            )

            if resp.status_code != 200:
                print(f"[LLM Continuation] Continuation call failed: {resp.status_code}")
                break

            cont_result = resp.json()
            cont_content, finish_reason = _extract_content_and_finish_reason(cont_result)

            if not cont_content:
                break

            accumulated += cont_content

        if continuation_count > 0:
            print(f"[LLM Continuation] Completed with {continuation_count} continuation(s). Total length: {len(accumulated)} chars")

        completion_tokens = count_tokens(accumulated)
        prompt_tokens_count = count_tokens(safe_prompt)
        _log_llm_cost(model, prompt_tokens_count, completion_tokens)

        await emit_llm_activity(
            build_llm_response_step(
                provider="pwc_genai",
                model=str(model),
                text=accumulated,
            )
        )

    _lf_trace(
        model=model, prompt=safe_prompt, completion=accumulated,
        prompt_tokens=prompt_tokens_count, completion_tokens=completion_tokens,
        latency_ms=(time.time() - _lf_start) * 1000,
        extra_metadata={"path": "async/pwc_genai", "continuations": continuation_count},
    )

    return accumulated


def sync_call_with_continuation_httpx(
    endpoint_url: str,
    headers: dict,
    request_body: dict,
    original_prompt: str,
    timeout: float = 120.0,
    max_continuations: int = MAX_CONTINUATIONS,
) -> str:
    _lf_start = time.time()
    prov = get_llm_provider()
    if prov == "local_llm":
        import os as _os
        _lf_model = _os.getenv("LOCAL_LLM_MODEL", "local_llm")
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        max_tokens = request_body.get("max_tokens")
        emit_llm_activity_sync(
            build_llm_call_step(
                provider="local_llm",
                model=_lf_model,
                prompt=prompt,
            )
        )
        result = sync_local_llm_call_httpx(prompt, temperature, max_tokens, timeout)
        emit_llm_activity_sync(
            build_llm_response_step(
                provider="local_llm",
                model=_lf_model,
                text=result,
            )
        )
        _lf_trace(
            model=_lf_model, prompt=original_prompt, completion=result,
            prompt_tokens=count_tokens(original_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "sync_httpx/local_llm"},
        )
        return result
    if prov == "ollama_cloud":
        _lf_model = resolved_ollama_cloud_model()
        prompt = request_body.get("prompt", original_prompt)
        temperature = request_body.get("temperature")
        requested_max_tokens = request_body.get("max_tokens", 8192)
        safe_prompt, safe_max_tokens = validate_and_prepare(
            "ollama_cloud", prompt, requested_max_tokens,
        )
        log_token_usage("ollama_cloud", safe_prompt, safe_max_tokens)
        emit_llm_activity_sync(
            build_llm_call_step(
                provider="ollama_cloud",
                model=_lf_model,
                prompt=safe_prompt,
            )
        )
        result = sync_ollama_cloud_call_httpx(
            safe_prompt, temperature, safe_max_tokens, timeout,
        )
        emit_llm_activity_sync(
            build_llm_response_step(
                provider="ollama_cloud",
                model=_lf_model,
                text=result,
            )
        )
        _lf_trace(
            model=_lf_model, prompt=safe_prompt, completion=result,
            prompt_tokens=count_tokens(safe_prompt),
            completion_tokens=count_tokens(result),
            latency_ms=(time.time() - _lf_start) * 1000,
            extra_metadata={"path": "sync_httpx/ollama_cloud"},
        )
        return result

    model = _resolve_pwc_genai_request_model(request_body)
    prompt = request_body.get("prompt", original_prompt)
    requested_max_tokens = request_body.get("max_tokens", 8192)

    safe_prompt, safe_max_tokens = validate_and_prepare(model, prompt, requested_max_tokens)
    request_body["prompt"] = safe_prompt
    request_body["max_tokens"] = safe_max_tokens
    log_token_usage(model, safe_prompt, safe_max_tokens)

    with httpx.Client(timeout=timeout) as client:
        emit_llm_activity_sync(
            build_llm_call_step(
                provider="pwc_genai",
                model=str(model),
                prompt=safe_prompt,
            )
        )
        response = _httpx_sync_post_with_retries(
            client, endpoint_url, headers, request_body, max_retries=3
        )

        if response.status_code != 200:
            if _is_context_window_error(response.status_code, response.text):
                shrunk_prompt = _shrink_prompt(request_body.get("prompt", ""))
                request_body["prompt"] = shrunk_prompt
                response = _httpx_sync_post_with_retries(
                    client, endpoint_url, headers, request_body, max_retries=2
                )
            if response.status_code != 200:
                raise ValueError(f"GenAI API Error: {response.status_code} - {response.text}")

        result = response.json()
        content, finish_reason = _extract_content_and_finish_reason(result)

        if not content:
            raise ValueError("Unexpected response format from GenAI API")

        accumulated = content
        continuation_count = 0

        while _should_continue(finish_reason, accumulated) and continuation_count < max_continuations:
            continuation_count += 1
            print(f"[LLM Continuation] Response truncated (finish_reason={finish_reason}), auto-continuing ({continuation_count}/{max_continuations})...")

            continuation_body = dict(request_body)
            continuation_body["prompt"] = _build_continuation_prompt(original_prompt, accumulated)

            emit_llm_activity_sync(
                build_llm_call_step(
                    provider="pwc_genai",
                    model=str(model),
                    prompt=continuation_body["prompt"],
                    phase_note=f"continuation {continuation_count}/{max_continuations}",
                )
            )
            resp = _httpx_sync_post_with_retries(
                client, endpoint_url, headers, continuation_body, max_retries=3
            )

            if resp.status_code != 200:
                print(f"[LLM Continuation] Continuation call failed: {resp.status_code}")
                break

            cont_result = resp.json()
            cont_content, finish_reason = _extract_content_and_finish_reason(cont_result)

            if not cont_content:
                break

            accumulated += cont_content

        if continuation_count > 0:
            print(f"[LLM Continuation] Completed with {continuation_count} continuation(s). Total length: {len(accumulated)} chars")

        completion_tokens_count = count_tokens(accumulated)
        prompt_tokens_final = count_tokens(safe_prompt)
        _log_llm_cost(model, prompt_tokens_final, completion_tokens_count)

        emit_llm_activity_sync(
            build_llm_response_step(
                provider="pwc_genai",
                model=str(model),
                text=accumulated,
            )
        )

    _lf_trace(
        model=model, prompt=safe_prompt, completion=accumulated,
        prompt_tokens=prompt_tokens_final, completion_tokens=completion_tokens_count,
        latency_ms=(time.time() - _lf_start) * 1000,
        extra_metadata={"path": "sync_httpx/pwc_genai", "continuations": continuation_count},
    )

    return accumulated
