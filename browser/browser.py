"""
browser/browser.py
------------------
Ruby – High-level Browser Automation

`BrowserSession` is a context-manager wrapper around `CDPSession` that adds:
  - Automatic Chromium process lifecycle management
  - Playwright backend (preferred when installed)
  - Screenshot-to-base64 for vision model usage
  - Form-filling helpers
  - Smart page-content extraction (Markdown simplification)
  - Vault-stored per-site cookies / localStorage
  - AI-assisted automation: `browser.instruct("click the login button")`

Backend priority
----------------
1. Playwright (python-playwright) — richest API, auto-install browsers
2. CDP direct (browser/cdp.py) — zero extra deps beyond websockets/aiohttp

Usage (as context manager)
--------------------------
    from browser import BrowserSession

    async with BrowserSession(headless=True) as browser:
        await browser.navigate("https://example.com")
        text = await browser.get_text("h1")
        await browser.screenshot("/tmp/shot.png")

Usage with AI instructions
--------------------------
    async with BrowserSession() as browser:
        await browser.navigate("https://news.ycombinator.com")
        result = await browser.instruct(
            "Find the top 5 story titles and their scores.",
            router=router,
        )
        print(result)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import sys
from typing import Any, Optional

from .cdp import CDPSession, ChromeProcess

logger = logging.getLogger("ruby.browser")

# ---------------------------------------------------------------------------
# Playwright availability check
# ---------------------------------------------------------------------------

def _playwright_available() -> bool:
    try:
        import importlib
        return importlib.util.find_spec("playwright") is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# BrowserSession
# ---------------------------------------------------------------------------

class BrowserSession:
    """
    High-level browser session.  Manages Chromium lifecycle and exposes
    a clean async API for navigation, interaction, and AI-assisted automation.

    Parameters
    ----------
    headless       : bool   — launch without a visible window (default: False)
    port           : int    — CDP debugging port (default: 9222)
    executable     : str    — path to Chromium/Chrome binary (auto-detected)
    user_data_dir  : str    — profile directory (auto: tmp/ruby_chrome_profile)
    use_playwright : bool   — prefer Playwright if installed (default: True)
    vault          : Vault  — for cookie persistence (optional)
    """

    def __init__(
        self,
        headless: bool = False,
        port: int = 9222,
        executable: str = "",
        user_data_dir: str = "",
        use_playwright: bool = True,
        vault=None,
    ):
        self.headless    = headless
        self.port        = port
        self.executable  = executable
        self.user_data_dir = user_data_dir
        self._vault      = vault

        self._use_pw = use_playwright and _playwright_available()

        # Playwright handles
        self._pw              = None
        self._pw_browser      = None
        self._pw_context      = None
        self._pw_page         = None

        # CDP handles
        self._chrome: Optional[ChromeProcess] = None
        self._cdp:    Optional[CDPSession]    = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrowserSession":
        await self.launch()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        if self._use_pw:
            await self._launch_playwright()
        else:
            await self._launch_cdp()

    async def close(self) -> None:
        if self._use_pw:
            await self._close_playwright()
        else:
            await self._close_cdp()

    async def _launch_playwright(self) -> None:
        from playwright.async_api import async_playwright  # type: ignore
        self._pw = await async_playwright().__aenter__()
        launch_args = {"headless": self.headless}
        if self.executable:
            launch_args["executable_path"] = self.executable
        self._pw_browser = await self._pw.chromium.launch(**launch_args)
        self._pw_context = await self._pw_browser.new_context()
        self._pw_page    = await self._pw_context.new_page()
        logger.info("[Browser] Playwright Chromium launched.")

    async def _close_playwright(self) -> None:
        if self._pw_browser:
            await self._pw_browser.close()
        if self._pw:
            await self._pw.__aexit__(None, None, None)

    async def _launch_cdp(self) -> None:
        self._chrome = ChromeProcess(
            executable=self.executable,
            port=self.port,
            user_data_dir=self.user_data_dir,
            headless=self.headless,
        )
        self._chrome.launch()
        await self._chrome.wait_ready(timeout=15)
        self._cdp = CDPSession(port=self.port)
        await self._cdp.connect()
        logger.info("[Browser] CDP session connected (port %d).", self.port)

    async def _close_cdp(self) -> None:
        if self._cdp:
            await self._cdp.close()
        if self._chrome:
            self._chrome.terminate()

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        logger.info("[Browser] Navigating to %s", url)
        if self._use_pw:
            await self._pw_page.goto(url, wait_until="load", timeout=30_000)
        else:
            await self._cdp.navigate(url)

    async def reload(self) -> None:
        if self._use_pw:
            await self._pw_page.reload(wait_until="load")
        else:
            await self._cdp.evaluate("location.reload()")

    async def go_back(self) -> None:
        if self._use_pw:
            await self._pw_page.go_back(wait_until="load")
        else:
            await self._cdp.evaluate("history.back()")

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    async def click(self, selector: str) -> None:
        if self._use_pw:
            await self._pw_page.click(selector)
        else:
            await self._cdp.click(selector)

    async def type_text(self, selector: str, text: str, clear: bool = True) -> None:
        if self._use_pw:
            if clear:
                await self._pw_page.fill(selector, "")
            await self._pw_page.type(selector, text)
        else:
            await self._cdp.type_text(selector, text, clear=clear)

    async def select_option(self, selector: str, value: str) -> None:
        if self._use_pw:
            await self._pw_page.select_option(selector, value)
        else:
            await self._cdp.select_option(selector, value)

    async def upload_file(self, selector: str, file_path: str) -> None:
        if self._use_pw:
            async with self._pw_page.expect_file_chooser() as fc_info:
                await self._pw_page.click(selector)
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
        else:
            await self._cdp.upload_file(selector, file_path)

    async def press_key(self, key: str) -> None:
        if self._use_pw:
            await self._pw_page.keyboard.press(key)
        else:
            await self._cdp.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": key,
            })
            await self._cdp.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": key,
            })

    async def scroll_to_bottom(self) -> None:
        if self._use_pw:
            await self._pw_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        else:
            await self._cdp.scroll_to_bottom()

    # ------------------------------------------------------------------
    # Read content
    # ------------------------------------------------------------------

    async def get_html(self) -> str:
        if self._use_pw:
            return await self._pw_page.content()
        return await self._cdp.get_html()

    async def get_text(self, selector: str = "body") -> str:
        if self._use_pw:
            el = self._pw_page.locator(selector).first
            return await el.inner_text()
        return await self._cdp.get_text(selector)

    async def get_attr(self, selector: str, attr: str) -> str:
        if self._use_pw:
            return (await self._pw_page.get_attribute(selector, attr)) or ""
        return await self._cdp.get_attr(selector, attr)

    async def evaluate(self, js: str) -> Any:
        if self._use_pw:
            return await self._pw_page.evaluate(js)
        return await self._cdp.evaluate(js)

    async def wait_for_selector(
        self, selector: str, timeout: float = 10.0, visible: bool = False
    ) -> None:
        if self._use_pw:
            state = "visible" if visible else "attached"
            await self._pw_page.wait_for_selector(
                selector, state=state, timeout=int(timeout * 1000)
            )
        else:
            await self._cdp.wait_for_selector(selector, timeout, visible)

    async def current_url(self) -> str:
        if self._use_pw:
            return self._pw_page.url
        return await self._cdp.evaluate("location.href")

    async def title(self) -> str:
        if self._use_pw:
            return await self._pw_page.title()
        return await self._cdp.evaluate("document.title")

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    async def screenshot(
        self, path: str = "", full_page: bool = True, format: str = "png"
    ) -> bytes:
        """Take a screenshot.  Returns raw bytes and optionally saves to *path*."""
        if self._use_pw:
            data = await self._pw_page.screenshot(
                path=path or None, full_page=full_page, type=format
            )
        else:
            data = await self._cdp.screenshot(path=path, format=format)
        return data

    async def screenshot_b64(self, full_page: bool = True) -> str:
        """Return screenshot as base64 string (for vision model input)."""
        raw = await self.screenshot(full_page=full_page)
        return base64.b64encode(raw).decode()

    # ------------------------------------------------------------------
    # Page content → clean Markdown (for AI context)
    # ------------------------------------------------------------------

    async def get_markdown(self) -> str:
        """
        Extract visible page text and structure it as Markdown.
        Much cheaper to feed to an LLM than raw HTML.
        """
        js = """
        (function extractText() {
            const skip = new Set(['SCRIPT','STYLE','NOSCRIPT','META','LINK','HEAD']);
            function walk(node) {
                if (skip.has(node.nodeName)) return '';
                if (node.nodeType === Node.TEXT_NODE) {
                    const t = node.textContent.trim();
                    return t ? t + ' ' : '';
                }
                const tag = node.nodeName;
                const children = Array.from(node.childNodes).map(walk).join('');
                if (!children.trim()) return '';
                if (/^H[1-6]$/.test(tag)) {
                    const n = tag[1];
                    return '\\n' + '#'.repeat(n) + ' ' + children.trim() + '\\n';
                }
                if (tag === 'A') {
                    const href = node.getAttribute('href') || '';
                    return `[${children.trim()}](${href}) `;
                }
                if (tag === 'LI') return '- ' + children.trim() + '\\n';
                if (tag === 'P' || tag === 'DIV') return children + '\\n';
                return children;
            }
            return walk(document.body);
        })()
        """
        raw = await self.evaluate(js)
        # Collapse excessive blank lines
        cleaned = re.sub(r"\n{3,}", "\n\n", str(raw)).strip()
        return cleaned

    # ------------------------------------------------------------------
    # Fill a form from a dict {selector: value}
    # ------------------------------------------------------------------

    async def fill_form(self, fields: dict[str, str]) -> None:
        """
        Fill a web form from a mapping of CSS selector → value.

        For <select> elements, uses select_option; for all others, type_text.
        """
        for selector, value in fields.items():
            tag = await self.evaluate(
                f"document.querySelector({repr(selector)})?.tagName?.toLowerCase() ?? ''"
            )
            if tag == "select":
                await self.select_option(selector, value)
            else:
                await self.type_text(selector, value, clear=True)
        logger.info("[Browser] Filled %d form fields.", len(fields))

    # ------------------------------------------------------------------
    # AI-assisted instruction
    # ------------------------------------------------------------------

    async def instruct(
        self,
        instruction: str,
        router=None,
        include_screenshot: bool = True,
        include_markdown: bool = True,
        max_actions: int = 10,
    ) -> str:
        """
        Send a natural-language instruction to Ruby's model router.
        Provides page content (and optionally a screenshot) as context.
        Returns the model's response text.

        The model can reply with action JSON to drive the browser further:
            {"action": "click", "selector": "#submit"}
            {"action": "type",  "selector": "#search", "text": "hello"}
            {"action": "navigate", "url": "https://..."}
            {"action": "done", "result": "..."}
        """
        if router is None:
            raise ValueError("instruct() requires a ModelRouter instance.")

        md   = await self.get_markdown() if include_markdown else ""
        ss   = await self.screenshot_b64() if include_screenshot else ""
        url  = await self.current_url()
        ttl  = await self.title()

        system_context = (
            f"You are Ruby, an AI life partner with browser automation capabilities.\n"
            f"Current page: {ttl} ({url})\n\n"
            f"Page content (Markdown):\n{md[:8000]}\n\n"
            "If you need to interact with the page, respond ONLY with a JSON action object "
            "(no markdown fences). Valid actions:\n"
            '  {"action":"click","selector":"CSS_SELECTOR"}\n'
            '  {"action":"type","selector":"CSS_SELECTOR","text":"TEXT"}\n'
            '  {"action":"navigate","url":"URL"}\n'
            '  {"action":"scroll"}\n'
            '  {"action":"done","result":"FINAL ANSWER"}\n'
            "If no further interaction is needed, respond normally in plain text."
        )

        prompt = f"{system_context}\n\nInstruction: {instruction}"

        result_text = ""
        for _ in range(max_actions):
            response_chunks: list[str] = []
            async for chunk in router.stream(prompt):
                response_chunks.append(chunk)
            response = "".join(response_chunks).strip()

            # Try to parse as action JSON
            parsed = _try_parse_action(response)
            if parsed is None:
                # Model gave a plain-text answer
                result_text = response
                break

            action = parsed.get("action", "")
            if action == "done":
                result_text = parsed.get("result", response)
                break
            elif action == "click":
                await self.click(parsed["selector"])
                await asyncio.sleep(1)
            elif action == "type":
                await self.type_text(parsed["selector"], parsed.get("text", ""))
            elif action == "navigate":
                await self.navigate(parsed["url"])
                await asyncio.sleep(2)
            elif action == "scroll":
                await self.scroll_to_bottom()
                await asyncio.sleep(0.5)

            # Re-capture page state for next iteration
            md = await self.get_markdown() if include_markdown else ""
            url = await self.current_url()
            ttl = await self.title()
            prompt = (
                f"Page now: {ttl} ({url})\nContent:\n{md[:8000]}\n\n"
                f"Original instruction: {instruction}\nContinue or say done."
            )

        return result_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_parse_action(text: str) -> dict | None:
    """Try to parse the model response as a JSON action dict."""
    import json
    text = text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "action" in obj:
            return obj
    except Exception:
        pass
    return None
