"""AI service for Browser Agent — delegates text-only calls to shared BaseAIService.

Vision / multimodal requests (screenshot_png) are handled locally via the
/chat/completions endpoint with image_url content parts.
"""
import base64
import io
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService
from agents.local_llm import get_llm_provider, sync_local_llm_call, sync_ollama_cloud_call

logger = logging.getLogger(__name__)

_MAX_IMAGE_B64_BYTES = 1_500_000  # ~1.5 MB base64 ≈ ~1.1 MB raw
_TAG = "[BrowserVision]"


def _compress_screenshot(png_bytes: bytes) -> tuple[str, str]:
    """Return (base64_str, mime_type) — compressing to JPEG if the PNG is too large."""
    b64_png = base64.standard_b64encode(png_bytes).decode("ascii")
    if len(b64_png) <= _MAX_IMAGE_B64_BYTES:
        print(
            f"{_TAG} Image: using original PNG | raw={len(png_bytes):,} bytes | base64={len(b64_png):,} bytes"
        )
        return b64_png, "image/png"

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        buf = io.BytesIO()
        for quality in (70, 50, 35):
            buf.seek(0)
            buf.truncate()
            img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
            b64_jpg = base64.standard_b64encode(buf.getvalue()).decode("ascii")
            if len(b64_jpg) <= _MAX_IMAGE_B64_BYTES:
                print(
                    f"{_TAG} Image: compressed PNG->JPEG q={quality} | "
                    f"raw_png={len(png_bytes):,} bytes | base64_jpg={len(b64_jpg):,} bytes"
                )
                return b64_jpg, "image/jpeg"
        print(
            f"{_TAG} WARNING: JPEG q=35 still large (base64={len(b64_jpg):,} bytes); sending anyway"
        )
        return b64_jpg, "image/jpeg"
    except ImportError:
        print(
            f"{_TAG} WARNING: PNG is large (base64={len(b64_png):,} bytes) but Pillow not installed; sending as-is"
        )
        return b64_png, "image/png"


def _parse_genai_json_content(result: dict) -> str:
    """Extract assistant text from PwC / OpenAI-style completion JSON."""
    if "choices" in result and len(result["choices"]) > 0:
        choice = result["choices"][0]
        if "message" in choice and "content" in choice["message"]:
            c = choice["message"]["content"]
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append(p.get("text", ""))
                    elif isinstance(p, str):
                        parts.append(p)
                return "".join(parts)
        if "text" in choice:
            return str(choice["text"])
    if "text" in result:
        return str(result["text"])
    if "content" in result:
        return str(result["content"])
    return ""


class AIService(BaseAIService):
    def __init__(self):
        model = os.getenv("BROWSER_AGENT_MODEL", "")
        super().__init__(
            default_model=model,
            default_temperature=0.3,
            default_max_tokens=8192,
            timeout=180,
        )

    def _chat_fields(self, temperature: float, max_tokens: int) -> dict:
        """Fields for /chat/completions — omit keys that some proxies reject."""
        return {
            "model": self.default_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": 1,
            "stream": False,
        }

    def call_genai(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        screenshot_png: Optional[bytes] = None,
    ) -> str:
        # Stamp Langfuse context here so all branches (local, ollama, vision) are covered.
        # For text-only PwC calls, super().call_genai() would stamp again — that is harmless.
        self._stamp_langfuse_context()
        prov = get_llm_provider()
        if prov == "local_llm":
            if screenshot_png:
                print(f"{_TAG} call_genai: LOCAL LLM does not support vision — stripping vision instructions, using text-only | prompt={len(prompt)} chars")
                prompt = self._strip_vision_addon(prompt)
            else:
                print(f"{_TAG} call_genai: LOCAL LLM TEXT-ONLY | prompt={len(prompt)} chars")
            return sync_local_llm_call(prompt, temperature, max_tokens, timeout=180)
        if prov == "ollama_cloud":
            if screenshot_png:
                print(f"{_TAG} call_genai: Ollama Cloud does not support vision — stripping vision instructions, using text-only | prompt={len(prompt)} chars")
                prompt = self._strip_vision_addon(prompt)
            else:
                print(f"{_TAG} call_genai: Ollama Cloud TEXT-ONLY | prompt={len(prompt)} chars")
            return sync_ollama_cloud_call(prompt, temperature, max_tokens, timeout=180)

        if not self._api_key():
            raise ValueError(
                "GenAI API key not configured. "
                "Provide PWC_GENAI_API_KEY or GEMINI_API_KEY in agent configuration (not server .env)."
            )

        if not screenshot_png:
            print(f"{_TAG} call_genai: TEXT-ONLY (no screenshot) | prompt={len(prompt)} chars")
            return super().call_genai(prompt, temperature, max_tokens)

        print(
            f"{_TAG} call_genai: WITH SCREENSHOT | prompt={len(prompt)} chars | "
            f"screenshot={len(screenshot_png):,} raw bytes"
        )
        return self._call_genai_with_vision(prompt, temperature, max_tokens, screenshot_png)

    # ── Vision helpers ────────────────────────────────────────────────

    @staticmethod
    def _strip_vision_addon(prompt: str) -> str:
        """Remove the DSL_VISION_ADDON block from a prompt for text-only fallback.

        When the vision API call fails and we fall back to text-only, the prompt
        still contains instructions like "USE THE SCREENSHOT as your PRIMARY
        signal" — confusing the LLM because no image was sent.
        """
        import re
        # Strip the well-known vision section header through to the end marker
        cleaned = re.sub(
            r"\n### Vision \(screenshot attached[^\n]*\).*?Output \*\*only\*\* the same JSON object shape as above\.\n",
            "\n",
            prompt,
            flags=re.DOTALL,
        )
        return cleaned

    @staticmethod
    def _chat_endpoint(base_url: str) -> str:
        """Derive the ``/chat/completions`` URL from the configured endpoint."""
        base_url = base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/completions"):
            return base_url.rsplit("/completions", 1)[0] + "/chat/completions"
        return base_url + "/chat/completions"

    @staticmethod
    def _split_system_user(prompt: str) -> tuple[str, str]:
        """Split a 'System: ...\\n\\nUser: ...' prompt into (system, user) parts."""
        marker = "\n\nUser: "
        if prompt.startswith("System: ") and marker in prompt:
            idx = prompt.index(marker)
            system_text = prompt[len("System: "):idx]
            user_text = prompt[idx + len(marker):]
            return system_text, user_text
        return "", prompt

    def _call_genai_with_vision(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        screenshot_png: bytes,
    ) -> str:
        """Send text + viewport screenshot via the /chat/completions endpoint.

        Falls back to text-only through the normal /completions path if the
        chat endpoint rejects the multimodal payload.
        """
        headers = self._headers()
        timeout = 180
        endpoint = self._endpoint_url()
        chat_url = self._chat_endpoint(endpoint)

        b64, mime = _compress_screenshot(screenshot_png)
        data_uri = f"data:{mime};base64,{b64}"

        system_text, user_text = self._split_system_user(prompt)

        messages = []
        if system_text:
            messages.append({"role": "system", "content": system_text})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_text if system_text else prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri, "detail": "auto"},
                },
            ],
        })

        body_chat = {
            **self._chat_fields(temperature, max_tokens),
            "messages": messages,
        }

        print(
            f"{_TAG} >>> POST {chat_url} | model={self.default_model} | "
            f"messages={len(messages)} (system={'yes' if system_text else 'no'} + user+image) | "
            f"image: {mime} base64={len(b64):,} chars | "
            f"text_prompt={len(user_text if system_text else prompt)} chars"
        )

        t0 = time.monotonic()
        try:
            r = requests.post(
                chat_url, json=body_chat, headers=headers, timeout=timeout
            )
            elapsed = time.monotonic() - t0

            if r.status_code == 200:
                result_json = r.json()
                text = _parse_genai_json_content(result_json)
                if text.strip():
                    finish_reason = "N/A"
                    if result_json.get("choices"):
                        finish_reason = result_json["choices"][0].get("finish_reason") or "N/A"
                    usage = result_json.get("usage", {})
                    usage_str = ""
                    if usage:
                        usage_str = (
                            f" | prompt_tokens={usage.get('prompt_tokens', '?')}"
                            f" completion_tokens={usage.get('completion_tokens', '?')}"
                        )
                    print(
                        f"{_TAG} <<< VISION SUCCESS | {elapsed:.1f}s | "
                        f"response={len(text)} chars | finish_reason={finish_reason}{usage_str}"
                    )
                    # Trace the vision LLM call to Langfuse (direct path, not through llm_continuation)
                    try:
                        from langfuse_tracer import trace_llm_call
                        trace_llm_call(
                            model=self.default_model,
                            prompt=prompt[:12_000],
                            completion=text[:12_000],
                            prompt_tokens=usage.get("prompt_tokens") or 0,
                            completion_tokens=usage.get("completion_tokens") or 0,
                            latency_ms=elapsed * 1000,
                            agent_name="Browser Agent",
                            extra_metadata={"path": "vision/chat_completions"},
                        )
                    except Exception:
                        pass
                    return text
                print(
                    f"{_TAG} <<< VISION EMPTY RESPONSE | HTTP 200 but no content | "
                    f"{elapsed:.1f}s | raw: {r.text[:300]}"
                )
            else:
                print(
                    f"{_TAG} <<< VISION FAILED | HTTP {r.status_code} | {elapsed:.1f}s | "
                    f"url={chat_url} | response: {(r.text or '')[:300]}"
                )
        except requests.RequestException as exc:
            elapsed = time.monotonic() - t0
            print(
                f"{_TAG} <<< VISION REQUEST ERROR | {elapsed:.1f}s | "
                f"{type(exc).__name__}: {exc}"
            )

        print(
            f"{_TAG} !!! FALLING BACK TO TEXT-ONLY (model will NOT see the screenshot) | "
            f"chat_url={chat_url} rejected multimodal"
        )
        # Strip vision-specific instructions from the prompt so the text-only
        # LLM isn't told to look at a screenshot that was never sent.
        fallback_prompt = self._strip_vision_addon(prompt)
        return super().call_genai(fallback_prompt, temperature, max_tokens)


ai_service = AIService()
