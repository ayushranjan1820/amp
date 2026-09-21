"""Shared Playwright browser with one BrowserContext per session_id (LRU capped).

Provides both sync and async APIs.  The async API uses playwright.async_api
natively — no thread-pool wrapping needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Pool branch: ("launch", headless_bool) | ("cdp", url) | ("persistent", profile_dir)
BranchKey = Tuple[str, Union[bool, str]]


def _is_headless_env() -> bool:
    """Return True when no usable graphical display is available (e.g. Linux servers).

    Uses X11/Wayland heuristics only on Unix. Windows and macOS do not set DISPLAY;
    treating that as \"no GUI\" incorrectly forced headless mode and hid the browser.
    """
    if sys.platform == "win32" or sys.platform == "darwin":
        return False

    display = os.environ.get("DISPLAY", "")
    wayland = os.environ.get("WAYLAND_DISPLAY", "")

    if not display and not wayland:
        return True

    if display:
        try:
            display_num = display.lstrip(":").split(".")[0]
            x11_socket = f"/tmp/.X11-unix/X{display_num}"
            if not os.path.exists(x11_socket):
                return True
        except Exception:
            return True

    return False


def _system_chromium_path() -> Optional[str]:
    path = (
        os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
    )
    if not path:
        import glob
        candidates = sorted(glob.glob("/nix/store/*/bin/chromium"), reverse=True)
        if candidates:
            path = candidates[0]
    if path and os.path.isfile(path):
        logger.info("Using system Chromium at %s", path)
        return path
    logger.warning("No system Chromium found; falling back to Playwright bundled browser")
    return None

DEFAULT_MAX_SESSIONS = 16

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_VIEWPORT = {"width": 1366, "height": 768}
_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-setuid-sandbox",
    "--start-maximized",
    "--disable-blink-features=AutomationControlled",
]


def _kill_stale_chrome_for_profile(profile_dir: str) -> None:
    """Kill any Chromium/Chrome processes still locking *profile_dir*.

    This covers the case where a previous ``launch_persistent_context`` left a
    zombie browser (e.g. the Python event-loop was torn down without cleanly
    closing the CDP pipe).  Without this the next launch fails with
    ``Target page, context or browser has been closed``.
    """
    if not profile_dir:
        return
    killed = False
    kill_count = 0
    basename = os.path.basename(os.path.normpath(profile_dir))
    try:
        if sys.platform == "win32":
            # ── Method 1: Get-CimInstance with WQL -Filter (no $_ needed) ──
            # WQL LIKE handles the matching server-side, avoiding PowerShell escaping issues.
            wql_filter = (
                "(Name LIKE '%chrome%' OR Name LIKE '%edge%' OR Name LIKE '%chromium%') "
                f"AND CommandLine LIKE '%{basename}%'"
            )
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                     f'Get-CimInstance Win32_Process -Filter "{wql_filter}"'
                     " | ForEach-Object { Stop-Process -Id $($_.ProcessId) -Force -ErrorAction SilentlyContinue;"
                     " Write-Output $_.ProcessId }"],
                    capture_output=True, text=True, timeout=20,
                )
                if r.stdout.strip():
                    logger.info("kill_stale_chrome: killed PIDs %s", r.stdout.strip().replace("\n", ", "))
                    killed = True
                    kill_count += len([p for p in r.stdout.splitlines() if p.strip().isdigit()])
                else:
                    logger.debug("kill_stale_chrome: no matching Chrome processes found via Get-CimInstance")
            except Exception as e1:
                logger.debug("Get-CimInstance kill failed: %s", e1)

            # ── Method 2: targeted Playwright-marker cleanup (best-effort) ──
            if not killed:
                extra = _kill_playwright_browser_processes(profile_dir)
                if extra > 0:
                    killed = True
                    kill_count += extra
        else:
            # Unix: try /proc scanning first (works in minimal containers), fall back to ps
            norm = os.path.normcase(os.path.normpath(profile_dir))
            proc_path = Path("/proc")
            if proc_path.is_dir():
                for pid_dir in proc_path.iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        cmdline = (pid_dir / "cmdline").read_text()
                        if norm not in cmdline:
                            continue
                        if "chrom" not in cmdline.lower():
                            continue
                        pid = int(pid_dir.name)
                        os.kill(pid, 9)
                        logger.info("Killed stale Chrome pid %d for profile %s", pid, profile_dir)
                        killed = True
                        kill_count += 1
                    except (OSError, ValueError):
                        continue
            if not killed:
                try:
                    out = subprocess.check_output(
                        ["ps", "aux"], text=True, timeout=10, stderr=subprocess.DEVNULL,
                    )
                    for line in out.splitlines():
                        if norm not in line:
                            continue
                        cols = line.split()
                        if len(cols) >= 2 and cols[1].isdigit():
                            pid = int(cols[1])
                            try:
                                os.kill(pid, 9)
                                logger.info("Killed stale Chrome pid %d for profile %s", pid, profile_dir)
                                killed = True
                                kill_count += 1
                            except OSError:
                                pass
                except FileNotFoundError:
                    logger.debug("Neither /proc nor ps available for stale Chrome cleanup")
    except Exception as exc:
        logger.debug("_kill_stale_chrome_for_profile: %s", exc)

    # Remove lock files that Chromium leaves behind
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_file = Path(profile_dir) / lock_name
        try:
            if lock_file.exists():
                lock_file.unlink(missing_ok=True)
                logger.info("Removed stale %s in %s", lock_name, profile_dir)
        except OSError:
            pass

    # Give the OS time to release file handles after process kill
    if killed:
        time.sleep(2)
        logger.info("kill_stale_chrome_for_profile: killed %d process(es)", kill_count)


def _kill_playwright_browser_processes(extra_profile_dir: Optional[str] = None) -> int:
    """Kill lingering Chromium-family processes likely spawned by Playwright.

    Targets command-lines containing Playwright markers (remote-debugging-pipe,
    headless, automation flags) and optionally a profile path basename.
    """
    killed = 0
    profile_basename = ""
    if extra_profile_dir:
        profile_basename = os.path.basename(os.path.normpath(extra_profile_dir)).strip()

    try:
        if sys.platform == "win32":
            safe_basename = profile_basename.replace("'", "''")
            ps_script = (
                "$targets = @('chrome.exe','chromium.exe','msedge.exe');"
                f"$basename = '{safe_basename}';"
                "$killed = @();"
                "Get-CimInstance Win32_Process | ForEach-Object {"
                "  $name = ('' + $_.Name).ToLower();"
                "  $cmd = '' + $_.CommandLine;"
                "  if (-not $cmd) { return };"
                "  if ($targets -notcontains $name) { return };"
                "  $isPlaywright = ($cmd -match '--remote-debugging-pipe') -or ($cmd -match '--headless') -or ($cmd -match '--disable-blink-features=AutomationControlled');"
                "  $isProfile = $false;"
                "  if ($basename) { $isProfile = $cmd -like ('*' + $basename + '*') };"
                "  if ($isPlaywright -or $isProfile) {"
                "    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $killed += $_.ProcessId } catch {}"
                "  }"
                "};"
                "$killed -join ','"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=25,
            )
            if r.stdout.strip():
                pids = [p.strip() for p in r.stdout.split(",") if p.strip()]
                killed = len(pids)
                logger.info("kill_playwright_browsers: killed PIDs %s", ", ".join(pids))
        else:
            try:
                out = subprocess.check_output(
                    ["ps", "-eo", "pid=,command="],
                    text=True,
                    timeout=10,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                out = ""
            markers = ("--remote-debugging-pipe", "--headless", "--disable-blink-features=automationcontrolled")
            for line in out.splitlines():
                row = line.strip()
                if not row:
                    continue
                parts = row.split(maxsplit=1)
                if len(parts) != 2 or not parts[0].isdigit():
                    continue
                pid = int(parts[0])
                cmd = parts[1].lower()
                if "chrom" not in cmd and "edge" not in cmd:
                    continue
                matched = any(m in cmd for m in markers)
                if profile_basename and profile_basename.lower() in cmd:
                    matched = True
                if not matched:
                    continue
                try:
                    os.kill(pid, 9)
                    killed += 1
                except OSError:
                    pass
            if killed:
                logger.info("kill_playwright_browsers: killed %d process(es)", killed)
    except Exception as exc:
        logger.debug("_kill_playwright_browser_processes: %s", exc)

    if killed:
        time.sleep(1)
    return killed


# ═══════════════════════════════════════════════════════════════════
#  Sync branch (original API — kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════════

class _SyncBranch:
    def __init__(
        self,
        headless: bool,
        max_sessions: int,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ):
        self.headless = headless
        self.cdp_url = (cdp_url or "").strip() or None
        self.persistent_profile_dir = (persistent_profile_dir or "").strip() or None
        self.max_sessions = max(1, max_sessions)
        self._lock = threading.Lock()
        self._playwright = None
        self._browser = None
        self._persistent_context = None
        self._sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def _ensure_browser(self, slow_mo: int) -> None:
        if self._browser is not None or self._persistent_context is not None:
            return
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        if self.cdp_url:
            self._browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
            logger.info("BrowserPool(sync): connected over CDP (%s)", self.cdp_url)
            return
        exe = _system_chromium_path()
        headless = self.headless or _is_headless_env()
        if headless != self.headless:
            logger.info("BrowserPool(sync): no display detected — forcing headless mode")
        if self.persistent_profile_dir:
            Path(self.persistent_profile_dir).mkdir(parents=True, exist_ok=True)
            try:
                self._persistent_context = self._playwright.chromium.launch_persistent_context(
                    self.persistent_profile_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport=_VIEWPORT,
                    user_agent=UA,
                    args=_LAUNCH_ARGS,
                    **({"executable_path": exe} if exe else {}),
                )
            except Exception as first_err:
                logger.warning("launch_persistent_context failed (%s) — killing stale Chrome and retrying", first_err)
                _kill_stale_chrome_for_profile(self.persistent_profile_dir)
                # Restart playwright in case the first attempt left it in a bad state
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = sync_playwright().start()
                self._persistent_context = self._playwright.chromium.launch_persistent_context(
                    self.persistent_profile_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport=_VIEWPORT,
                    user_agent=UA,
                    args=_LAUNCH_ARGS,
                    **({"executable_path": exe} if exe else {}),
                )
            logger.info(
                "BrowserPool(sync): persistent profile at %s (headless=%s)",
                self.persistent_profile_dir,
                headless,
            )
            return
        self._browser = self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=_LAUNCH_ARGS,
            **({"executable_path": exe} if exe else {}),
        )
        logger.info("BrowserPool(sync): browser launched (headless=%s)", headless)

    def _close_entry(self, data: Dict[str, Any], close_context: bool) -> None:
        try:
            page = data.get("page")
            ctx = data.get("context")
            if self.cdp_url or self.persistent_profile_dir:
                if close_context and page:
                    page.close()
                return
            if close_context and ctx:
                ctx.close()
        except Exception as exc:
            logger.debug("context/page close: %s", exc)

    def acquire_page(self, session_id: str, slow_mo: int = 300):
        with self._lock:
            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                return self._sessions[session_id]["page"]
            while len(self._sessions) >= self.max_sessions:
                _, old = self._sessions.popitem(last=False)
                self._close_entry(old, close_context=True)
            self._ensure_browser(slow_mo)
            if self.cdp_url:
                contexts = self._browser.contexts
                context = contexts[0] if contexts else self._browser.new_context(
                    viewport=_VIEWPORT, user_agent=UA
                )
                page = context.new_page()
            elif self.persistent_profile_dir:
                context = self._persistent_context
                page = context.new_page()
            else:
                context = self._browser.new_context(
                    viewport=_VIEWPORT,
                    user_agent=UA,
                )
                page = context.new_page()
            page.set_default_timeout(30_000)
            self._sessions[session_id] = {"context": context, "page": page}
            self._sessions.move_to_end(session_id)
            return page

    def release_session(self, session_id: str, close_context: bool) -> None:
        if not close_context:
            return
        with self._lock:
            if session_id not in self._sessions:
                return
            data = self._sessions.pop(session_id)
            self._close_entry(data, close_context=True)
            if not self._sessions:
                if self._browser:
                    try:
                        self._browser.close()
                    except Exception:
                        pass
                    self._browser = None
                if self._persistent_context:
                    try:
                        self._persistent_context.close()
                    except Exception:
                        pass
                    self._persistent_context = None
                try:
                    if self._playwright:
                        self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                kind = " from CDP" if self.cdp_url else ""
                if self.persistent_profile_dir:
                    kind = " (persistent profile)"
                logger.info("BrowserPool(sync): disconnected%s (no active sessions)", kind)

    def force_close_all(self) -> None:
        """Forcefully close all sessions, browser, and playwright — kill stale Chrome if needed."""
        with self._lock:
            for sid, data in list(self._sessions.items()):
                self._close_entry(data, close_context=True)
            self._sessions.clear()
            if self._browser:
                try:
                    self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._persistent_context:
                try:
                    self._persistent_context.close()
                except Exception:
                    pass
                self._persistent_context = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            if self.persistent_profile_dir:
                _kill_stale_chrome_for_profile(self.persistent_profile_dir)
            logger.info("BrowserPool(sync): force_close_all complete")


# ═══════════════════════════════════════════════════════════════════
#  Async branch — uses playwright.async_api natively
# ═══════════════════════════════════════════════════════════════════

class _AsyncBranch:
    def __init__(
        self,
        headless: bool,
        max_sessions: int,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ):
        self.headless = headless
        self.cdp_url = (cdp_url or "").strip() or None
        self.persistent_profile_dir = (persistent_profile_dir or "").strip() or None
        self.max_sessions = max(1, max_sessions)
        self._lock = asyncio.Lock()
        self._playwright = None
        self._browser = None
        self._persistent_context = None
        self._sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def _async_teardown_all(self) -> None:
        """Invalidate cached Playwright objects (async API is bound to the event loop that created them).

        Each ``asyncio.run()`` uses a new loop; reusing pages/contexts across runs causes
        ``'NoneType' object has no attribute 'send'`` inside Playwright.
        """
        for data in list(self._sessions.values()):
            try:
                page = data.get("page")
                if page:
                    await page.close()
            except Exception as exc:
                logger.debug("async teardown page.close: %s", exc)
        self._sessions.clear()
        if self._browser:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.debug("async teardown browser.close: %s", exc)
            self._browser = None
        if self._persistent_context:
            try:
                await self._persistent_context.close()
            except Exception as exc:
                logger.debug("async teardown persistent_context.close: %s", exc)
            self._persistent_context = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.debug("async teardown playwright.stop: %s", exc)
            self._playwright = None
        # Kill any zombie Chrome processes still holding the profile dir lock
        if self.persistent_profile_dir:
            _kill_stale_chrome_for_profile(self.persistent_profile_dir)
        self._event_loop = None
        logger.info("BrowserPool(async): reset Playwright (event loop or session lifecycle)")

    async def _ensure_browser(self, slow_mo: int) -> None:
        if self._browser is not None or self._persistent_context is not None:
            return
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        if self.cdp_url:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            logger.info("BrowserPool(async): connected over CDP (%s)", self.cdp_url)
            return
        exe = _system_chromium_path()
        headless = self.headless or _is_headless_env()
        if headless != self.headless:
            logger.info("BrowserPool(async): no display detected — forcing headless mode")
        if self.persistent_profile_dir:
            Path(self.persistent_profile_dir).mkdir(parents=True, exist_ok=True)
            try:
                self._persistent_context = await self._playwright.chromium.launch_persistent_context(
                    self.persistent_profile_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport=_VIEWPORT,
                    user_agent=UA,
                    args=_LAUNCH_ARGS,
                    **({"executable_path": exe} if exe else {}),
                )
            except Exception as first_err:
                logger.warning("async launch_persistent_context failed (%s) — killing stale Chrome and retrying", first_err)
                _kill_stale_chrome_for_profile(self.persistent_profile_dir)
                # Restart playwright in case the first attempt left it in a bad state
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = await async_playwright().start()
                self._persistent_context = await self._playwright.chromium.launch_persistent_context(
                    self.persistent_profile_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                    viewport=_VIEWPORT,
                    user_agent=UA,
                    args=_LAUNCH_ARGS,
                    **({"executable_path": exe} if exe else {}),
                )
            logger.info(
                "BrowserPool(async): persistent profile at %s (headless=%s)",
                self.persistent_profile_dir,
                headless,
            )
            return
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=_LAUNCH_ARGS,
            **({"executable_path": exe} if exe else {}),
        )
        logger.info("BrowserPool(async): browser launched (headless=%s)", headless)

    async def _close_entry(self, data: Dict[str, Any], close_context: bool) -> None:
        try:
            page = data.get("page")
            ctx = data.get("context")
            if self.cdp_url or self.persistent_profile_dir:
                if close_context and page:
                    await page.close()
                return
            if close_context and ctx:
                await ctx.close()
        except Exception as exc:
            logger.debug("async context/page close: %s", exc)

    async def acquire_page(self, session_id: str, slow_mo: int = 300):
        async with self._lock:
            loop = asyncio.get_running_loop()
            if (
                self._event_loop is not None
                and self._event_loop is not loop
                and (
                    self._sessions
                    or self._browser is not None
                    or self._persistent_context is not None
                    or self._playwright is not None
                )
            ):
                await self._async_teardown_all()
            self._event_loop = loop

            if session_id in self._sessions:
                self._sessions.move_to_end(session_id)
                return self._sessions[session_id]["page"]
            while len(self._sessions) >= self.max_sessions:
                _, old = self._sessions.popitem(last=False)
                await self._close_entry(old, close_context=True)
            await self._ensure_browser(slow_mo)
            if self.cdp_url:
                contexts = self._browser.contexts
                if contexts:
                    context = contexts[0]
                    page = await context.new_page()
                else:
                    context = await self._browser.new_context(
                        viewport=_VIEWPORT, user_agent=UA
                    )
                    page = await context.new_page()
            elif self.persistent_profile_dir:
                context = self._persistent_context
                page = await context.new_page()
            else:
                context = await self._browser.new_context(
                    viewport=_VIEWPORT,
                    user_agent=UA,
                )
                page = await context.new_page()
            page.set_default_timeout(30_000)
            self._sessions[session_id] = {"context": context, "page": page}
            self._sessions.move_to_end(session_id)
            return page

    async def release_session(self, session_id: str, close_context: bool) -> None:
        if not close_context:
            return
        async with self._lock:
            if session_id not in self._sessions:
                return
            data = self._sessions.pop(session_id)
            await self._close_entry(data, close_context=True)
            if not self._sessions:
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                    self._browser = None
                if self._persistent_context:
                    try:
                        await self._persistent_context.close()
                    except Exception:
                        pass
                    self._persistent_context = None
                try:
                    if self._playwright:
                        await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                self._event_loop = None
                kind = " from CDP" if self.cdp_url else ""
                if self.persistent_profile_dir:
                    kind = " (persistent profile)"
                logger.info("BrowserPool(async): disconnected%s (no active sessions)", kind)

    async def force_close_all(self) -> None:
        """Forcefully close all sessions, browser, and playwright — kill stale Chrome if needed."""
        async with self._lock:
            await self._async_teardown_all()
            logger.info("BrowserPool(async): force_close_all complete")


# ═══════════════════════════════════════════════════════════════════
#  Public API — unified pool with sync + async support
# ═══════════════════════════════════════════════════════════════════

def browser_pool_branch_key(
    headless: bool,
    cdp_url: Optional[str],
    persistent_profile_dir: Optional[str] = None,
) -> BranchKey:
    """Isolate pool state: launch vs CDP vs persistent profile (separate per endpoint / path)."""
    u = (cdp_url or "").strip()
    if u:
        return ("cdp", u)
    p = (persistent_profile_dir or "").strip()
    if p:
        return ("persistent", os.path.normcase(os.path.normpath(p)))
    return ("launch", bool(headless))


class BrowserPool:
    """Process-wide pool: separate branch per launch mode, CDP URL, or persistent profile path."""

    # Sync branches (thread-safe)
    _global_lock = threading.Lock()
    _sync_branches: Dict[BranchKey, _SyncBranch] = {}

    # Async branches (event-loop-safe)
    _async_lock: Optional[asyncio.Lock] = None
    _async_branches: Dict[BranchKey, _AsyncBranch] = {}

    # ── Sync API ────────────────────────────────────────────────────

    @classmethod
    def acquire_page(
        cls,
        session_id: str,
        headless: bool,
        slow_mo: int = 300,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ):
        u = (cdp_url or "").strip() or None
        p = (persistent_profile_dir or "").strip() or None
        key = browser_pool_branch_key(headless, cdp_url, persistent_profile_dir)
        eff_headless = False if u else headless
        with cls._global_lock:
            if key not in cls._sync_branches:
                cls._sync_branches[key] = _SyncBranch(
                    headless=eff_headless,
                    max_sessions=max_sessions,
                    cdp_url=u,
                    persistent_profile_dir=p,
                )
        return cls._sync_branches[key].acquire_page(session_id, slow_mo=slow_mo)

    @classmethod
    def release_session(
        cls,
        session_id: str,
        headless: bool,
        close_context: bool,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ) -> None:
        key = browser_pool_branch_key(headless, cdp_url, persistent_profile_dir)
        with cls._global_lock:
            br = cls._sync_branches.get(key)
        if br:
            br.release_session(session_id, close_context=close_context)

    # ── Async API ───────────────────────────────────────────────────

    @classmethod
    async def async_acquire_page(
        cls,
        session_id: str,
        headless: bool,
        slow_mo: int = 300,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ):
        u = (cdp_url or "").strip() or None
        p = (persistent_profile_dir or "").strip() or None
        key = browser_pool_branch_key(headless, cdp_url, persistent_profile_dir)
        eff_headless = False if u else headless
        if cls._async_lock is None:
            cls._async_lock = asyncio.Lock()
        async with cls._async_lock:
            if key not in cls._async_branches:
                cls._async_branches[key] = _AsyncBranch(
                    headless=eff_headless,
                    max_sessions=max_sessions,
                    cdp_url=u,
                    persistent_profile_dir=p,
                )
        return await cls._async_branches[key].acquire_page(session_id, slow_mo=slow_mo)

    @classmethod
    async def async_release_session(
        cls,
        session_id: str,
        headless: bool,
        close_context: bool,
        cdp_url: Optional[str] = None,
        persistent_profile_dir: Optional[str] = None,
    ) -> None:
        key = browser_pool_branch_key(headless, cdp_url, persistent_profile_dir)
        if cls._async_lock is None:
            cls._async_lock = asyncio.Lock()
        async with cls._async_lock:
            br = cls._async_branches.get(key)
        if br:
            await br.release_session(session_id, close_context=close_context)

    # ── Force close all browsers ────────────────────────────────────

    @classmethod
    def force_close_all_sync(cls) -> None:
        """Forcefully close every sync branch (all sessions, browsers, playwright instances)."""
        with cls._global_lock:
            for key, br in list(cls._sync_branches.items()):
                br.force_close_all()
            cls._sync_branches.clear()

    @classmethod
    async def async_force_close_all(cls) -> None:
        """Forcefully close every async branch (all sessions, browsers, playwright instances)."""
        if cls._async_lock is None:
            cls._async_lock = asyncio.Lock()
        async with cls._async_lock:
            for key, br in list(cls._async_branches.items()):
                await br.force_close_all()
            cls._async_branches.clear()
