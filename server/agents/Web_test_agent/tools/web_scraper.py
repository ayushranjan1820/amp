import httpx
import ipaddress
import socket
import logging
import asyncio
import shutil
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


def _find_system_chromium() -> Optional[str]:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only HTTP and HTTPS URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: no hostname found")

    hn = hostname.lower()

    blocked_hosts = ["localhost", "0.0.0.0", "metadata.google.internal"]
    if hn in blocked_hosts:
        raise ValueError("Access to internal/private addresses is not allowed")

    blocked_prefixes = ["169.254.", "10.", "192.168."]
    if any(hn.startswith(p) for p in blocked_prefixes):
        raise ValueError("Access to internal/private addresses is not allowed")

    try:
        ip = ipaddress.ip_address(hn)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Access to internal/private addresses is not allowed")
    except ValueError:
        pass

    blocked_metadata = ["metadata.google.internal", "metadata.aws.internal"]
    if hn in blocked_metadata:
        raise ValueError("Access to cloud metadata endpoints is not allowed")

    return url


_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-timer-throttling",
    "--disable-setuid-sandbox",
    "--single-process",
]


def _launch_options() -> dict:
    opts: dict = {"headless": True, "args": _CHROMIUM_ARGS}
    sys_chromium = _find_system_chromium()
    if sys_chromium:
        opts["executable_path"] = sys_chromium
        logger.info(f"Using system Chromium: {sys_chromium}")
    return opts


async def _playwright_worker_async(url: str) -> str:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(**_launch_options())
        try:
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            return html
        finally:
            await browser.close()


def _playwright_worker_sync(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        try:
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
            html = page.content()
            return html
        finally:
            browser.close()


def _is_inside_event_loop() -> bool:
    """Check if we're currently inside an asyncio event loop."""
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


async def _fetch_with_playwright_async(url: str) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — falling back to basic HTTP request")
        return None

    try:
        html = await _playwright_worker_async(url)
        return html
    except Exception as e:
        logger.warning(f"Playwright rendering failed: {e} — falling back to basic HTTP request")
        return None


def _fetch_with_playwright_sync(url: str) -> Optional[str]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — falling back to basic HTTP request")
        return None

    try:
        html = _playwright_worker_sync(url)
        return html
    except Exception as e:
        logger.warning(f"Playwright rendering failed: {e} — falling back to basic HTTP request")
        return None


def _fetch_with_httpx(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    timeout_seconds = 60

    response = httpx.get(url, headers=headers, timeout=timeout_seconds, follow_redirects=True, verify=False)
    response.raise_for_status()

    if len(response.content) > 10 * 1024 * 1024:
        raise ValueError("Page too large (>10MB)")

    return response.text


def _is_spa_shell(soup: BeautifulSoup) -> bool:
    body = soup.find("body")
    if not body:
        return False

    body_text = body.get_text(strip=True)
    if len(body_text) < 50:
        return True

    root_div = body.find("div", id="root") or body.find("div", id="app") or body.find("div", id="__next")
    if root_div:
        children = [c for c in body.children if hasattr(c, 'name') and c.name]
        scripts = body.find_all("script")
        non_script_children = [c for c in children if c.name != "script"]
        if len(non_script_children) <= 2 and len(scripts) >= 1:
            return True

    forms = body.find_all("form")
    buttons = body.find_all("button")
    inputs = body.find_all(["input", "select", "textarea"])
    headings = body.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    if len(forms) == 0 and len(buttons) == 0 and len(inputs) == 0 and len(headings) == 0:
        return True

    return False


def _parse_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "path"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"})
    if meta_tag and meta_tag.get("content"):
        meta_desc = meta_tag["content"]

    nav_items = _extract_navigation(soup)
    forms = _extract_forms(soup)
    buttons = _extract_buttons(soup)
    links = _extract_links(soup)
    inputs = _extract_inputs(soup)
    headings = _extract_headings(soup)
    images = _extract_images(soup)
    tables = _extract_tables(soup)
    modals_dropdowns = _extract_interactive_elements(soup)
    text_sections = _extract_text_sections(soup)

    return {
        "title": title,
        "meta_description": meta_desc,
        "navigation": nav_items,
        "forms": forms,
        "buttons": buttons,
        "links": links[:50],
        "inputs": inputs,
        "headings": headings,
        "images": images[:30],
        "tables": tables,
        "interactive_elements": modals_dropdowns,
        "text_sections": text_sections[:20],
        "page_stats": {
            "total_links": len(links),
            "total_buttons": len(buttons),
            "total_forms": len(forms),
            "total_inputs": len(inputs),
            "total_images": len(images),
            "total_headings": len(headings),
        }
    }, soup


def scrape_webpage(url: str) -> Dict[str, Any]:
    """
    Scrape a webpage with automatic SPA detection and rendering.
    
    Automatically detects if running inside asyncio loop and uses appropriate Playwright API.
    
    Process:
    1. Fetch HTML with basic HTTP request
    2. Detect if it's an SPA shell (empty or minimal content)
    3. If SPA detected, use Playwright to render JavaScript (async or sync depending on context)
    4. Parse and extract content
    """
    # Check if we're inside an event loop
    inside_loop = _is_inside_event_loop()
    
    if inside_loop:
        # We're inside an async context - need to run async version
        # Since scrape_webpage itself is synchronous, we need to run the async version
        # using asyncio.get_event_loop().run_until_complete() or similar
        #But we can't do that from within a running loop! So we use a workaround:
        # Run the scraping in a separate thread that has its own event loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            # This runs in a new thread,outside the current event loop
            future = pool.submit(_scrape_webpage_with_async_playwright, url)
            return future.result()
    else:
        # We're in sync context - use sync implementation directly
        return _scrape_webpage_sync(url)


def _scrape_webpage_with_async_playwright(url: str) -> Dict[str, Any]:
    """
    Wrapper to run async scraping in a new event loop.
    Used when called from within an existing async context.
    """
    # This runs in a separate thread, so we can create a new event loop
    return asyncio.run(_scrape_webpage_async(url))


def _scrape_webpage_sync(url: str) -> Dict[str, Any]:
    try:
        url = _validate_url(url)
        
        logger.info(f"Scraping {url} (sync mode)")

        html = None
        playwright_used = False

        pw_html = _fetch_with_playwright_sync(url)
        if pw_html:
            html = pw_html
            playwright_used = True
            logger.info(f"Browser rendering successful for {url}")

        if not html:
            html = _fetch_with_httpx(url)
            check_soup = BeautifulSoup(html, "html.parser")

            if _is_spa_shell(check_soup) and not playwright_used:
                logger.info(f"SPA detected for {url} but Playwright unavailable, using basic HTML")

        result, soup = _parse_html(html)
        result["success"] = True
        result["url"] = url
        result["rendered_with_browser"] = playwright_used
        
        logger.info(f"Scraped {url}: {result['page_stats']['total_forms']} forms, {result['page_stats']['total_buttons']} buttons")
        
        return result

    except ValueError as e:
        logger.error(f"Validation error for {url}: {e}")
        return {"success": False, "url": url, "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error for {url}: {e.response.status_code}")
        return {"success": False, "url": url, "error": f"HTTP {e.response.status_code}: Page returned an error"}
    except httpx.TimeoutException:
        logger.error(f"Timeout for {url}")
        return {"success": False, "url": url, "error": "Request timed out — the page took too long to respond"}
    except Exception as e:
        import traceback
        error_details = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Scraping error for {url}: {error_details}\n{traceback.format_exc()}")
        return {"success": False, "url": url, "error": f"Failed to fetch the webpage: {error_details}"}


async def _scrape_webpage_async(url: str) -> Dict[str, Any]:
    try:
        url = _validate_url(url)
        
        logger.info(f"Scraping {url} (async mode)")

        html = None
        playwright_used = False

        pw_html = await _fetch_with_playwright_async(url)
        if pw_html:
            html = pw_html
            playwright_used = True
            logger.info(f"Browser rendering successful for {url}")

        if not html:
            html = _fetch_with_httpx(url)
            check_soup = BeautifulSoup(html, "html.parser")

            if _is_spa_shell(check_soup) and not playwright_used:
                logger.info(f"SPA detected for {url} but Playwright unavailable, using basic HTML")

        result, soup = _parse_html(html)
        result["success"] = True
        result["url"] = url
        result["rendered_with_browser"] = playwright_used
        
        logger.info(f"Scraped {url}: {result['page_stats']['total_forms']} forms, {result['page_stats']['total_buttons']} buttons")
        
        return result

    except ValueError as e:
        logger.error(f"Validation error for {url}: {e}")
        return {"success": False, "url": url, "error": str(e)}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error for {url}: {e.response.status_code}")
        return {"success": False, "url": url, "error": f"HTTP {e.response.status_code}: Page returned an error"}
    except httpx.TimeoutException:
        logger.error(f"Timeout for {url}")
        return {"success": False, "url": url, "error": "Request timed out — the page took too long to respond"}
    except Exception as e:
        import traceback
        error_details = f"{type(e).__name__}: {str(e)}"
        logger.error(f"Scraping error for {url}: {error_details}\n{traceback.format_exc()}")
        return {"success": False, "url": url, "error": f"Failed to fetch the webpage: {error_details}"}


def _extract_navigation(soup: BeautifulSoup) -> List[Dict]:
    navs = []
    for nav in soup.find_all("nav"):
        nav_links = []
        for a in nav.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if text:
                nav_links.append({"text": text, "href": href})
        if nav_links:
            label = nav.get("aria-label", "")
            navs.append({"label": label, "items": nav_links[:20]})
    return navs


def _extract_forms(soup: BeautifulSoup) -> List[Dict]:
    forms = []
    for form in soup.find_all("form"):
        fields = []
        for inp in form.find_all(["input", "select", "textarea"]):
            field = {
                "tag": inp.name,
                "type": inp.get("type", "text"),
                "name": inp.get("name", ""),
                "id": inp.get("id", ""),
                "placeholder": inp.get("placeholder", ""),
                "required": inp.has_attr("required"),
                "aria_label": inp.get("aria-label", ""),
            }
            if inp.name == "select":
                options = [opt.get_text(strip=True) for opt in inp.find_all("option")]
                field["options"] = options[:10]
            fields.append(field)

        labels = []
        for label in form.find_all("label"):
            label_text = label.get_text(strip=True)
            label_for = label.get("for", "")
            if label_text:
                labels.append({"text": label_text, "for": label_for})

        submit_btn = form.find("button", type="submit") or form.find("input", type="submit")
        if not submit_btn:
            submit_btn = form.find("button")
        submit_text = ""
        if submit_btn:
            submit_text = submit_btn.get_text(strip=True) or submit_btn.get("value", "Submit")

        forms.append({
            "action": form.get("action", ""),
            "method": form.get("method", "GET"),
            "id": form.get("id", ""),
            "fields": fields,
            "labels": labels,
            "submit_button": submit_text,
        })
    return forms


def _extract_buttons(soup: BeautifulSoup) -> List[Dict]:
    buttons = []
    for btn in soup.find_all("button"):
        text = btn.get_text(strip=True)
        if text:
            buttons.append({
                "text": text,
                "type": btn.get("type", ""),
                "id": btn.get("id", ""),
                "class": " ".join(btn.get("class", [])),
                "disabled": btn.has_attr("disabled"),
                "aria_label": btn.get("aria-label", ""),
            })
    for a in soup.find_all("a", role="button"):
        text = a.get_text(strip=True)
        if text:
            buttons.append({
                "text": text,
                "type": "link-button",
                "href": a.get("href", ""),
                "id": a.get("id", ""),
            })
    return buttons


def _extract_links(soup: BeautifulSoup) -> List[Dict]:
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if text and href and not href.startswith("#"):
            links.append({"text": text, "href": href})
    return links


def _extract_inputs(soup: BeautifulSoup) -> List[Dict]:
    inputs = []
    for inp in soup.find_all(["input", "select", "textarea"]):
        if inp.find_parent("form"):
            continue
        entry = {
            "tag": inp.name,
            "type": inp.get("type", "text"),
            "name": inp.get("name", ""),
            "id": inp.get("id", ""),
            "placeholder": inp.get("placeholder", ""),
            "required": inp.has_attr("required"),
            "aria_label": inp.get("aria-label", ""),
        }
        label = None
        inp_id = inp.get("id")
        if inp_id:
            label = soup.find("label", attrs={"for": inp_id})
        if not label:
            label = inp.find_parent("label")
        if label:
            entry["label"] = label.get_text(strip=True)
        inputs.append(entry)
    return inputs


def _extract_headings(soup: BeautifulSoup) -> List[Dict]:
    headings = []
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = h.get_text(strip=True)
        if text:
            headings.append({"level": h.name, "text": text})
    return headings


def _extract_images(soup: BeautifulSoup) -> List[Dict]:
    images = []
    for img in soup.find_all("img"):
        src = img.get("src", "")
        alt = img.get("alt", "")
        if src:
            images.append({"src": src, "alt": alt})
    return images


def _extract_tables(soup: BeautifulSoup) -> List[Dict]:
    tables = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        row_count = len(table.find_all("tr"))
        tables.append({
            "id": table.get("id", ""),
            "headers": headers,
            "row_count": row_count,
        })
    return tables


def _extract_interactive_elements(soup: BeautifulSoup) -> List[Dict]:
    elements = []
    for el in soup.find_all(attrs={"role": True}):
        role = el.get("role", "")
        if role in ["dialog", "modal", "menu", "menubar", "tablist", "tab", "tabpanel",
                     "tooltip", "alert", "alertdialog", "progressbar", "slider",
                     "combobox", "listbox", "tree", "switch", "checkbox", "radio"]:
            text = el.get_text(strip=True)[:100]
            elements.append({
                "role": role,
                "id": el.get("id", ""),
                "aria_label": el.get("aria-label", ""),
                "text_preview": text,
            })
    for el in soup.find_all(attrs={"data-toggle": True}):
        elements.append({
            "role": "toggle-element",
            "data_toggle": el.get("data-toggle", ""),
            "id": el.get("id", ""),
            "text_preview": el.get_text(strip=True)[:100],
        })
    return elements


def _extract_text_sections(soup: BeautifulSoup) -> List[Dict]:
    sections = []
    for section in soup.find_all(["section", "article", "main", "aside"]):
        heading = section.find(["h1", "h2", "h3", "h4"])
        heading_text = heading.get_text(strip=True) if heading else ""
        content = section.get_text(strip=True)[:300]
        if content:
            sections.append({
                "tag": section.name,
                "id": section.get("id", ""),
                "heading": heading_text,
                "content_preview": content,
            })
    return sections
