import os
import tiktoken
from typing import Optional, Tuple

MODEL_CONTEXT_LIMITS = {
    # Used when ``LLM_PROVIDER=ollama_cloud`` (model id varies; shared safe window).
    "ollama_cloud": {
        "context_window": 131_072,
        "max_output_tokens": 8_192,
    },
    "": {
        "context_window": 32_768,
        "max_output_tokens": 8_192,
    },
    "vertex_ai.gemini-1.5-flash": {
        "context_window": 32_768,
        "max_output_tokens": 8_192,
    },
    "vertex_ai.gemini-1.5-pro": {
        "context_window": 32_768,
        "max_output_tokens": 8_192,
    },
    "vertex_ai.gemini-2.5-flash-image": {
        "context_window": 32_768,
        "max_output_tokens": 4_096,
    },
    "vertex_ai.gemini-2.5-flash": {
        "context_window": 32_768,
        "max_output_tokens": 8_192,
    },
    "vertex_ai.gemini-2.5-pro": {
        "context_window": 32_768,
        "max_output_tokens": 8_192,
    },
    "gpt-4": {
        "context_window": 128_000,
        "max_output_tokens": 4_096,
    },
    "gpt-4o": {
        "context_window": 128_000,
        "max_output_tokens": 16_384,
    },
    "gpt-3.5-turbo": {
        "context_window": 16_385,
        "max_output_tokens": 4_096,
    },
}

DEFAULT_CONTEXT_WINDOW = 32_768
DEFAULT_MAX_OUTPUT = 8_192

# Models whose native tokenizer (e.g. Gemini) produces MORE tokens than tiktoken
# for the same text — especially for non-ASCII, code, and structured data. We
# trim prompts using tiktoken counts, so we must leave extra headroom to avoid
# hitting the real server-side limit. Applied as a multiplicative factor on the
# tiktoken count when deciding how aggressively to trim.
_TOKENIZER_MISMATCH_MODELS = ("gemini", "vertex_ai.", "claude", "anthropic")
_TOKENIZER_SAFETY_FACTOR = 1.35


def _tokenizer_safety_factor(model: str) -> float:
    """Return a multiplier applied to tiktoken counts for models with mismatched tokenizers."""
    m = (model or "").lower()
    if any(tag in m for tag in _TOKENIZER_MISMATCH_MODELS):
        return _TOKENIZER_SAFETY_FACTOR
    return 1.0

_encoder: Optional[tiktoken.Encoding] = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        try:
            _encoder = tiktoken.encoding_for_model("gpt-4o")
        except Exception:
            _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    if not text:
        return 0
    encoder = _get_encoder()
    return len(encoder.encode(text))


def get_model_limits(model: str) -> Tuple[int, int]:
    limits = MODEL_CONTEXT_LIMITS.get(model, {})
    context_window = limits.get("context_window", DEFAULT_CONTEXT_WINDOW)
    max_output = limits.get("max_output_tokens", DEFAULT_MAX_OUTPUT)
    return context_window, max_output


def get_safe_max_tokens(model: str, prompt: str, requested_max_tokens: int = 8192) -> int:
    context_window, model_max_output = get_model_limits(model)
    prompt_tokens = count_tokens(prompt)

    factor = _tokenizer_safety_factor(model)
    effective_prompt_tokens = int(prompt_tokens * factor)

    safety_buffer = max(500, int(context_window * 0.03))
    available_for_output = context_window - effective_prompt_tokens - safety_buffer

    if available_for_output <= 0:
        return min(512, model_max_output)

    effective_max = min(requested_max_tokens, model_max_output, available_for_output)
    return max(256, effective_max)


def validate_and_prepare(
    model: str,
    prompt: str,
    requested_max_tokens: int = 8192,
) -> Tuple[str, int]:
    context_window, model_max_output = get_model_limits(model)
    prompt_tokens = count_tokens(prompt)

    factor = _tokenizer_safety_factor(model)
    safety_buffer = max(500, int(context_window * 0.05))

    # Compute the tiktoken budget such that (budget * factor) + output + buffer
    # stays under the real server-side context window.
    max_prompt_tokens = int((context_window - model_max_output - safety_buffer) / factor)
    if max_prompt_tokens < 256:
        max_prompt_tokens = 256

    if prompt_tokens > max_prompt_tokens:
        encoder = _get_encoder()
        encoded = encoder.encode(prompt)

        truncation_marker = "\n\n... [Content trimmed to fit model context window] ...\n\n"
        marker_tokens = count_tokens(truncation_marker)

        keep_start = int(max_prompt_tokens * 0.3)
        keep_end = max_prompt_tokens - keep_start - marker_tokens
        if keep_end < 0:
            keep_end = 0
            keep_start = max(0, max_prompt_tokens - marker_tokens)

        trimmed_tokens = encoded[:keep_start] + encoder.encode(truncation_marker) + encoded[-keep_end:]
        prompt = encoder.decode(trimmed_tokens)
        prompt_tokens = len(trimmed_tokens)
        print(
            f"[TokenManager] Prompt trimmed from {len(encoded)} to {prompt_tokens} tokens "
            f"(tokenizer_factor={factor}) to fit {model!r} context window ({context_window})"
        )

    safe_max_tokens = get_safe_max_tokens(model, prompt, requested_max_tokens)

    return prompt, safe_max_tokens


def get_active_context_tokens(prompt_reserve: int = 5000, output_reserve: int = 2048) -> int:
    """Return available tokens for content based on the active LLM provider."""
    from agents.local_llm import get_llm_provider

    provider = get_llm_provider()

    if provider == "ollama_cloud":
        context_window = MODEL_CONTEXT_LIMITS["ollama_cloud"]["context_window"]
    elif provider == "local_llm":
        context_window = int(os.getenv("LOCAL_LLM_N_CTX", "8192"))
    else:
        PREMIUM_MODEL = os.getenv("PREMIUM_MODEL", "")
        limits = MODEL_CONTEXT_LIMITS.get(PREMIUM_MODEL, {})
        context_window = limits.get("context_window", DEFAULT_CONTEXT_WINDOW)

    return context_window - output_reserve - prompt_reserve


def log_token_usage(model: str, prompt: str, max_tokens: int):
    prompt_tokens = count_tokens(prompt)
    context_window, model_max_output = get_model_limits(model)
    total = prompt_tokens + max_tokens
    utilization = (prompt_tokens / context_window) * 100
    print(
        f"[TokenManager] Model: {model} | "
        f"Prompt: {prompt_tokens} tokens | "
        f"Max output: {max_tokens} tokens | "
        f"Total: {total}/{context_window} | "
        f"Utilization: {utilization:.1f}%"
    )
