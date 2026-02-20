"""
browser/cdp.py
--------------
Ruby – Chrome DevTools Protocol (CDP) client

A lightweight async CDP client that communicates with Chromium/Chrome via
the JSON RPC WebSocket transport.  No external dependency beyond the stdlib
`websockets` package (or `aiohttp`).

Lifecycle
---------
1. Launch Chromium with `--remote-debugging-port=9222 --user-data-dir=...`
2. `CDPSession.connect("http://localhost:9222")` discovers available targets
3. Attach to a page target → use `session.send(method, params)` for any CDP command
4. `session.close()` when done

Features
--------
- Auto-discover and attach to Page targets
- Subscribe to events via `session.on_event(event_name, callback)`
- Wait for specific events via `session.wait_for(event_name, predicate)`
- Auto-reconnect on disconnect (optional)
- Vault-stored debugging port / user-data-dir so callers don't hard-code paths
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Any, Callable, Coroutine

logger = logging.getLogger("ruby.browser.cdp")

_CDPCallback = Callable[[dict], Coroutine]

# ---------------------------------------------------------------------------
# Default Chromium locations
# ---------------------------------------------------------------------------

def _find_chromium() -> str:
    """Return the first Chromium / Chrome executable found on this system."""
    candidates_win = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    candidates_nix = [
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    candidates = candidates_win if sys.platform == "win32" else candidates_nix
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "Chromium / Chrome not found. Install it or set RUBY_CHROME_PATH."
    )


# ---------------------------------------------------------------------------
# Browser process management
# ---------------------------------------------------------------------------

class ChromeProcess:
    """
    Launches a dedicated Chromium instance with remote debugging enabled.
    The instance uses a Ruby-owned user-data-dir so it is isolated from the
    user's personal browser profile.
    """

    DEFAULT_PORT = 9222

    def __init__(
        self,
        executable: str = "",
        port: int = DEFAULT_PORT,
        user_data_dir: str = "",
        headless: bool = False,
        extra_args: list[str] | None = None,
    ):
        self.executable   = executable or os.environ.get("RUBY_CHROME_PATH", "")
        self.port         = port
        self.user_data_dir = user_data_dir or os.path.join(
            tempfile.gettempdir(), "ruby_chrome_profile"
        )
        self.headless     = headless
        self.extra_args   = extra_args or []
        self._proc: subprocess.Popen | None = None

    def launch(self) -> None:
        if self._proc and self._proc.poll() is None:
            return  # already running
        exe = self.executable or _find_chromium()
        args = [
            exe,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]
        if self.headless:
            args.append("--headless=new")
        args.extend(self.extra_args)
        logger.info("[CDP] Launching Chromium: %s", " ".join(args))
        self._proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def terminate(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            logger.info("[CDP] Chromium terminated.")

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    async def wait_ready(self, timeout: float = 10.0) -> None:
        """Poll the CDP HTTP endpoint until it responds (browser has started)."""
        import httpx
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    r = await client.get(f"http://localhost:{self.port}/json/version")
                    if r.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(0.25)
        raise TimeoutError(f"Chromium did not start within {timeout}s")


# ---------------------------------------------------------------------------
# CDP Session
# ---------------------------------------------------------------------------

class CDPSession:
    """
    Async CDP session connected to a single Page target.

    Usage
    -----
        session = CDPSession()
        await session.connect("http://localhost:9222")
        await session.navigate("https://example.com")
        html = await session.get_html()
        await session.close()
    """

    def __init__(self, host: str = "localhost", port: int = 9222):
        self.host  = host
        self.port  = port
        self._ws   = None
        self._id   = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: dict[str, list[_CDPCallback]] = {}
        self._recv_task: asyncio.Task | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------------
    # Connect / disconnect
    # ------------------------------------------------------------------

    async def connect(self, target_filter: Callable[[dict], bool] | None = None) -> None:
        """Find a Page target and open a WebSocket session to it."""
        import httpx
        ws_url = None
        for _ in range(20):
            try:
                async with httpx.AsyncClient() as c:
                    resp = await c.get(f"{self.base_url}/json/list")
                    targets = resp.json()
                    for t in targets:
                        if t.get("type") == "page":
                            if target_filter is None or target_filter(t):
                                ws_url = t["webSocketDebuggerUrl"]
                                break
                if ws_url:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.25)

        if not ws_url:
            raise RuntimeError("No Page target found in Chromium CDP endpoint.")

        try:
            import websockets  # type: ignore
            self._ws = await websockets.connect(ws_url)
        except ImportError:
            # fallback: aiohttp
            import aiohttp
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(ws_url)

        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info("[CDP] Connected to %s", ws_url)

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws:
            await self._ws.close()
        if hasattr(self, "_session"):
            await self._session.close()

    # ------------------------------------------------------------------
    # Send / receive
    # ------------------------------------------------------------------

    async def send(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        msg_id = self._id
        payload = json.dumps({"id": msg_id, "method": method, "params": params or {}})
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut

        # support both websockets and aiohttp WS
        if hasattr(self._ws, "send"):
            await self._ws.send(payload)
        else:
            await self._ws.send_str(payload)

        result = await fut
        if "error" in result:
            raise RuntimeError(f"CDP error: {result['error']}")
        return result.get("result", {})

    async def _recv_loop(self) -> None:
        try:
            async for raw in self._ws:
                # raw may be str (websockets) or WSMessage (aiohttp)
                text = raw if isinstance(raw, str) else raw.data
                msg  = json.loads(text)
                if "id" in msg and msg["id"] in self._pending:
                    self._pending.pop(msg["id"]).set_result(msg)
                elif "method" in msg:
                    await self._dispatch_event(msg["method"], msg.get("params", {}))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("[CDP] recv loop exited: %s", exc)

    async def _dispatch_event(self, event: str, params: dict) -> None:
        for cb in self._listeners.get(event, []):
            try:
                await cb(params)
            except Exception as e:
                logger.warning("[CDP] event handler error (%s): %s", event, e)

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def on_event(self, event: str, callback: _CDPCallback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    async def wait_for(
        self,
        event: str,
        predicate: Callable[[dict], bool] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _handler(params: dict):
            if not fut.done():
                if predicate is None or predicate(params):
                    fut.set_result(params)

        self.on_event(event, _handler)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            if event in self._listeners and _handler in self._listeners[event]:
                self._listeners[event].remove(_handler)

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    async def navigate(self, url: str, wait_until: str = "load") -> None:
        """Navigate to URL and wait for page to load."""
        await self.send("Page.enable")
        done: asyncio.Future = asyncio.get_event_loop().create_future()

        async def _on_load(_: dict):
            if not done.done():
                done.set_result(True)

        self.on_event("Page.loadEventFired", _on_load)
        await self.send("Page.navigate", {"url": url})
        await asyncio.wait_for(done, timeout=30)

    async def get_html(self) -> str:
        """Return the full outer HTML of the page."""
        root = await self.send("DOM.getDocument", {"depth": -1})
        node_id = root["root"]["nodeId"]
        result = await self.send("DOM.getOuterHTML", {"nodeId": node_id})
        return result["outerHTML"]

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the page context and return the result."""
        result = await self.send("Runtime.evaluate", {
            "expression":  expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        exc = result.get("exceptionDetails")
        if exc:
            raise RuntimeError(f"JS error: {exc.get('text', exc)}")
        return result.get("result", {}).get("value")

    async def screenshot(self, path: str = "", format: str = "png") -> bytes:
        """
        Take a full-page screenshot and optionally save to *path*.
        Returns raw bytes.
        """
        import base64
        await self.send("Emulation.setDeviceMetricsOverride", {
            "width": 1280, "height": 800, "deviceScaleFactor": 1,
            "mobile": False,
        })
        result = await self.send("Page.captureScreenshot", {
            "format": format,
            "captureBeyondViewport": True,
        })
        data = base64.b64decode(result["data"])
        if path:
            with open(path, "wb") as f:
                f.write(data)
        return data

    async def click(self, selector: str) -> None:
        """Click the first element matching a CSS selector."""
        await self.evaluate(
            f"document.querySelector({json.dumps(selector)}).click()"
        )

    async def type_text(self, selector: str, text: str, clear: bool = True) -> None:
        """Type text into an input element (with optional clear first)."""
        js = f"""
        (function() {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) throw new Error('Element not found: {selector}');
            el.focus();
            {'el.value = ""; el.dispatchEvent(new Event("input", {{bubbles: true}}));' if clear else ''}
            el.value += {json.dumps(text)};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})();
        """
        await self.evaluate(js)

    async def wait_for_selector(
        self, selector: str, timeout: float = 10.0, visible: bool = False
    ) -> None:
        """Poll until the element exists (and optionally is visible)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            found = await self.evaluate(
                f"""
                (function() {{
                    const el = document.querySelector({json.dumps(selector)});
                    if (!el) return false;
                    {'const rect = el.getBoundingClientRect(); return rect.width > 0 && rect.height > 0;' if visible else 'return true;'}
                }})()
                """
            )
            if found:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Selector not found within {timeout}s: {selector}")

    async def get_text(self, selector: str) -> str:
        """Return textContent of the first matching element."""
        return await self.evaluate(
            f"document.querySelector({json.dumps(selector)})?.textContent?.trim() ?? ''"
        )

    async def get_attr(self, selector: str, attr: str) -> str:
        """Return an attribute value from the first matching element."""
        return await self.evaluate(
            f"document.querySelector({json.dumps(selector)})?.getAttribute({json.dumps(attr)}) ?? ''"
        )

    async def upload_file(self, selector: str, file_path: str) -> None:
        """
        Set a file on an <input type=file> element via CDP DOM.setFileInputFiles.
        """
        # Resolve nodeId
        node_result = await self.send("DOM.getDocument", {})
        root_id = node_result["root"]["nodeId"]
        search = await self.send("DOM.querySelectorAll", {
            "nodeId": root_id,
            "selector": selector,
        })
        node_ids = search.get("nodeIds", [])
        if not node_ids:
            raise RuntimeError(f"upload_file: selector not found: {selector}")
        await self.send("DOM.setFileInputFiles", {
            "nodeId": node_ids[0],
            "files": [os.path.abspath(file_path)],
        })

    async def scroll_to_bottom(self) -> None:
        await self.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    async def select_option(self, selector: str, value: str) -> None:
        await self.evaluate(
            f"document.querySelector({json.dumps(selector)}).value = {json.dumps(value)}; "
            f"document.querySelector({json.dumps(selector)}).dispatchEvent(new Event('change', {{bubbles: true}}))"
        )
