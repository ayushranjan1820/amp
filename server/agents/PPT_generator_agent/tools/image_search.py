import httpx
import asyncio
import os
import time
import hashlib
import random
import base64
from pathlib import Path
from typing import List, Optional

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "generated_files", "ppt_images")
STOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stock_images")

DEFAULT_IMAGE_CONCURRENCY = int(os.getenv("PPT_IMAGE_CONCURRENCY", "4"))
IMAGE_CACHE_TTL_HOURS = int(os.getenv("PPT_IMAGE_CACHE_TTL_HOURS", "168"))

STOCK_CATEGORIES = {
    "technology": ["technology", "tech", "software", "computer", "digital", "AI", "artificial intelligence",
                   "machine learning", "data", "cloud", "cyber", "internet", "app", "code", "programming",
                   "automation", "robot", "innovation", "startup"],
    "business": ["business", "corporate", "company", "strategy", "management", "leadership", "market",
                 "growth", "revenue", "profit", "enterprise", "meeting", "office", "team", "collaboration",
                 "startup", "entrepreneur", "pitch", "deck"],
    "science": ["science", "research", "experiment", "laboratory", "chemistry", "physics", "biology",
                "discovery", "analysis", "scientific", "study"],
    "education": ["education", "learning", "training", "school", "university", "student", "course",
                  "teaching", "knowledge", "academic", "workshop", "skill"],
    "healthcare": ["health", "healthcare", "medical", "medicine", "hospital", "patient", "doctor",
                   "wellness", "pharmaceutical", "clinical", "therapy", "diagnosis"],
    "nature": ["nature", "environment", "climate", "sustainability", "green", "energy", "solar",
               "renewable", "earth", "ecosystem", "conservation", "planet"],
    "finance": ["finance", "banking", "investment", "stock", "trading", "money", "economy", "economic",
                "budget", "tax", "accounting", "financial", "crypto", "blockchain"],
    "creative": ["creative", "design", "art", "brand", "marketing", "advertising", "media",
                 "content", "visual", "graphic", "photography", "video"],
}


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _can_generate_ai_images() -> bool:
    """True when the active provider supports remote image generation.

    Ollama Cloud models (e.g. gemma3:27b-cloud) are text-only — skip the HTTP
    call entirely instead of burning a 90s timeout per slide. PwC GenAI /
    Gemini API keys unlock the image endpoint.
    """
    try:
        from agents.local_llm import get_llm_provider
        prov = get_llm_provider()
    except Exception:
        prov = ""

    if prov == "ollama_cloud":
        return False
    if prov == "local_llm":
        return False

    api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    return bool(api_key)


def _get_genai_config():
    api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")
    image_endpoint = os.getenv("PWC_GENAI_IMAGE_ENDPOINT_URL", "")
    if not image_endpoint:
        endpoint_url = os.getenv("PWC_GENAI_ENDPOINT_URL", "https://genai-sharedservice-americas.pwc.com/completions")
        if "/completions" in endpoint_url:
            base_url = endpoint_url.rsplit("/completions", 1)[0]
        else:
            base_url = endpoint_url.rstrip("/")
        image_endpoint = f"{base_url}/images/generations"

    headers = {
        "accept": "application/json",
        "API-Key": api_key,
        "Content-Type": "application/json",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    return api_key, image_endpoint, headers


def _get_stock_image(query: str, used_stocks: set) -> Optional[str]:
    query_lower = query.lower()

    best_match = None
    best_score = 0

    for category, keywords in STOCK_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > best_score:
            best_score = score
            best_match = category

    if best_match:
        path = os.path.join(STOCK_DIR, f"{best_match}.jpg")
        if os.path.exists(path) and path not in used_stocks:
            used_stocks.add(path)
            return path

    try:
        stock_files = os.listdir(STOCK_DIR)
    except OSError:
        return None
    available = []
    for f in stock_files:
        if f.endswith((".jpg", ".png")):
            full = os.path.join(STOCK_DIR, f)
            if full not in used_stocks:
                available.append(full)

    if not available:
        try:
            all_stocks = [os.path.join(STOCK_DIR, f) for f in os.listdir(STOCK_DIR) if f.endswith((".jpg", ".png"))]
        except OSError:
            return None
        if all_stocks:
            choice = random.choice(all_stocks)
            used_stocks.add(choice)
            return choice
        return None

    choice = random.choice(available)
    used_stocks.add(choice)
    return choice


async def generate_ai_image(query: str, slide_index: int = 0) -> Optional[str]:
    _ensure_cache_dir()

    cache_key = hashlib.md5(f"ai_gen_v2_{query}".encode()).hexdigest()
    cached_path = os.path.join(CACHE_DIR, f"{cache_key}.png")
    if os.path.exists(cached_path) and os.path.getsize(cached_path) > 1000:
        print(f"🎨 Cached AI image for slide {slide_index+1}")
        return cached_path

    api_key, image_endpoint, headers = _get_genai_config()

    if not api_key:
        return None

    prompt = (
        f"Create a high-quality, professional, photorealistic image for a presentation slide about: {query}. "
        f"The image should be clean, modern, visually compelling, and suitable for a corporate presentation. "
        f"No text, no words, no labels, no watermarks in the image."
    )

    request_body = {
        "model": os.getenv("PREMIUM_MODEL", ""),
        "prompt": prompt,
        "n": 1,
        "size": "1024x1024",
        "response_format": "b64_json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(image_endpoint, json=request_body, headers=headers)

            if response.status_code != 200:
                print(f"⚠️ AI image generation failed for slide {slide_index+1}: HTTP {response.status_code}")
                return None

            result = response.json()

            if "data" in result and isinstance(result["data"], list) and result["data"]:
                item = result["data"][0]
                b64_data = item.get("b64_json", "")
                if b64_data and isinstance(b64_data, str) and len(b64_data) > 100:
                    try:
                        image_bytes = base64.b64decode(b64_data, validate=True)
                    except Exception:
                        print(f"⚠️ Invalid base64 data for slide {slide_index+1}")
                        return None
                    is_png = image_bytes[:4] == b'\x89PNG'
                    is_jpeg = image_bytes[:2] == b'\xff\xd8'
                    is_webp = image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP'
                    if not (is_png or is_jpeg or is_webp):
                        print(f"⚠️ AI response for slide {slide_index+1} is not a valid image format")
                        return None
                    if len(image_bytes) > 1000:
                        with open(cached_path, "wb") as f:
                            f.write(image_bytes)
                        size_kb = len(image_bytes) / 1024
                        print(f"🎨 AI generated image for slide {slide_index+1} ({size_kb:.0f} KB): {query[:50]}")
                        return cached_path

            print(f"⚠️ AI image response for slide {slide_index+1} had no image data")
            return None

    except Exception as e:
        print(f"⚠️ AI image generation error for slide {slide_index+1}: {e}")
        return None


async def search_images_batch(
    queries: List[str],
    slide_titles: List[str] = None,
    concurrency: int = DEFAULT_IMAGE_CONCURRENCY,
) -> List[Optional[str]]:
    """Resolve one image per slide, running AI generations in parallel.

    Falls back to the bundled stock library for any slide that couldn't be
    generated. Providers without image support (Ollama Cloud, local LLM) skip
    the remote call entirely and go straight to stock.
    """
    results: List[Optional[str]] = [None] * len(queries)
    used_stocks: set = set()

    if _can_generate_ai_images():
        print(f"🎨 Generating {len(queries)} AI images (up to {concurrency} concurrent)...")
        sem = asyncio.Semaphore(max(1, concurrency))

        async def _one(idx: int, q: str):
            async with sem:
                return idx, await generate_ai_image(q, idx)

        tasks = [asyncio.create_task(_one(i, q)) for i, q in enumerate(queries)]
        for fut in asyncio.as_completed(tasks):
            try:
                idx, res = await fut
                results[idx] = res
            except Exception as e:
                print(f"⚠️ Image task failed: {e}")
    else:
        print(f"ℹ️ AI image generation unavailable for active provider — using curated stock library")

    for i in range(len(results)):
        if results[i] is None:
            stock = _get_stock_image(queries[i], used_stocks)
            if stock:
                results[i] = stock
                print(f"📷 Using stock photo for slide {i+1}: {os.path.basename(stock)}")

    ai_count = sum(1 for r in results if r and "ppt_images" in r)
    stock_count = sum(1 for r in results if r and "stock_images" in r)
    total = sum(1 for r in results if r is not None)
    print(f"📊 Images: {total}/{len(queries)} total ({ai_count} AI-generated, {stock_count} stock fallback)")

    return results


async def search_and_download_image(query: str) -> Optional[str]:
    return await generate_ai_image(query)


def cleanup_old_cached_images(max_age_hours: int = IMAGE_CACHE_TTL_HOURS) -> int:
    """Delete AI-image cache files older than max_age_hours. Returns count removed."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    try:
        for name in os.listdir(CACHE_DIR):
            path = os.path.join(CACHE_DIR, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    if removed:
        print(f"🧹 Cleaned {removed} stale AI image cache entries (>{max_age_hours}h old)")
    return removed
