"""
browser/__init__.py
-------------------
Ruby – Browser Automation

Provides AI-assisted web browsing using either Playwright (preferred)
or a direct Chrome DevTools Protocol (CDP) connection.

Public API
----------
    from browser import BrowserSession, CDPSession, ChromeProcess

Quick-start (simple scrape)
---------------------------
    from browser import BrowserSession

    async with BrowserSession(headless=True) as b:
        await b.navigate("https://example.com")
        text = await b.get_text("h1")
        print(text)

Quick-start (AI-assisted)
-------------------------
    from browser  import BrowserSession
    from models   import ModelRouter

    router = ModelRouter()

    async with BrowserSession() as b:
        await b.navigate("https://news.ycombinator.com")
        answer = await b.instruct(
            "List the top 5 stories and their scores.",
            router=router,
        )
        print(answer)

Backend selection
-----------------
    BrowserSession(use_playwright=True)   # uses Playwright if installed (default)
    BrowserSession(use_playwright=False)  # forces raw CDP via websockets/aiohttp

Requirements (install one backend)
-----------------------------------
    pip install playwright && python -m playwright install chromium
    # or
    pip install websockets              # for raw CDP backend

Optional dependency additions for requirements.txt:
    playwright>=1.43.0
    websockets>=12.0
"""

from .browser import BrowserSession
from .cdp     import CDPSession, ChromeProcess

__all__ = [
    "BrowserSession",
    "CDPSession",
    "ChromeProcess",
]
