"""QA testing and UI automation tools for the Ruby Agent."""

import os
import logging
import json
import asyncio
from typing import Any, Dict, List, Optional
from src.agent.tools import FunctionTool
from config.settings import get_settings

logger = logging.getLogger(__name__)

async def browser_inspect(url: str, selector: str | None = None) -> str:
    """Inspect a web page for testing, capturing DOM, logs, and state.
    
    Args:
        url: The URL to test.
        selector: Optional CSS selector to focus on.
    """
    try:
        from playwright.async_api import async_playwright
        settings = get_settings()
        
        results = {
            "url": url,
            "status": "pending",
            "logs": [],
            "errors": [],
            "elements": []
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="MemU-QA-Bot/1.0",
                viewport={'width': 1280, 'height': 720}
            )
            
            page = await context.new_page()
            
            # Capture console logs
            page.on("console", lambda msg: results["logs"].append(f"[{msg.type}] {msg.text}"))
            page.on("pageerror", lambda err: results["errors"].append(str(err)))

            await page.goto(url, wait_until="networkidle", timeout=60000)
            
            results["title"] = await page.title()
            results["status"] = "loaded"

            if selector:
                try:
                    element = await page.wait_for_selector(selector, timeout=5000)
                    if element:
                        results["elements"].append({
                            "selector": selector,
                            "text": await element.inner_text(),
                            "visible": await element.is_visible()
                        })
                except:
                    results["elements"].append({"selector": selector, "error": "Not found or timed out"})

            await browser.close()
            
        return json.dumps(results, indent=2)
    except Exception as e:
        logger.error(f"QA Browser inspect failed: {e}")
        return f"Error inspecting {url}: {str(e)}"

async def desktop_interact(action: str, target: str | None = None, text: str | None = None) -> str:
    """Perform OS-level desktop interactions (mouse, keyboard) for app testing.
    
    Args:
        action: 'click', 'type', 'press', or 'move'.
        target: Image path to click on (using vision) OR coordinates e.g. '500,600'.
        text: Text to type if action is 'type'.
    """
    try:
        import pyautogui
        # Prevent runaway scripts with 0.5s pause between actions
        pyautogui.PAUSE = 0.5
        
        result = ""
        
        if action == "click":
            if target and "," in target:
                x, y = map(int, target.split(","))
                pyautogui.click(x, y)
                result = f"Clicked at {x}, {y}"
            elif target:
                # Try to find image on screen
                try:
                    location = pyautogui.locateOnScreen(target, confidence=0.8)
                    if location:
                        pyautogui.click(location)
                        result = f"Found and clicked image: {target}"
                    else:
                        result = f"Error: Image '{target}' not found on screen."
                except Exception as e:
                    result = f"Error locating image '{target}': {str(e)}"
            else:
                pyautogui.click()
                result = "Performed generic click at current position."
                
        elif action == "type" and text:
            pyautogui.write(text, interval=0.1)
            result = f"Typed: '{text}'"
            
        elif action == "press" and text:
            pyautogui.press(text)
            result = f"Pressed key: '{text}'"
            
        elif action == "move" and target and "," in target:
            x, y = map(int, target.split(","))
            pyautogui.moveTo(x, y)
            result = f"Moved mouse to {x}, {y}"
            
        return result or f"Action '{action}' completed."
    except Exception as e:
        logger.error(f"Desktop interaction failed: {e}")
        return f"Error: {str(e)}"

TESTING_TOOLS = [
    FunctionTool(
        func=browser_inspect,
        name="browser_inspect",
        description="Deeply inspects a web page for QA purposes, returning DOM status, console logs, and errors. Use this to verify if a web app is working correctly."
    ),
    FunctionTool(
        func=desktop_interact,
        name="desktop_interact",
        description="Interacts with the desktop OS directly. Action can be 'click', 'type', 'press', or 'move'. Target can be 'x,y' coords or an image path to find on screen. Use this to test non-web desktop applications."
    )
]
