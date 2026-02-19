"""Built-in web tools."""

from duckduckgo_search import DDGS
import httpx
import re
import os
from bs4 import BeautifulSoup
from src.agent.tools import FunctionTool
from config.settings import get_settings


def _search_web_sync(query: str, max_results: int = 5) -> str:
    """Synchronous implementation of web search."""
    # Backends are no longer used in new DDGS
    errors = []
    
    try:
        results = []
        with DDGS() as ddgs:
            # text() returns an iterator of dicts
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"Title: {r['title']}\nURL: {r['href']}\nSnippet: {r['body']}\n")
        
        if results:
            return "\n---\n".join(results)
        else:
            errors.append(f"DDGS returned no results.")
            
    except Exception as e:
        errors.append(f"DDGS error: {e}")
            
    # Fallback to Google Search
    try:
        from googlesearch import search
        g_results = []
        for url in search(query, num_results=max_results):
            g_results.append(f"URL: {url}\n(Google Search Result)")
        
        if g_results:
            return "Note: Used Google Search fallback.\n\n" + "\n---\n".join(g_results)
        else:
            errors.append("Google Search returned no results.")
    except Exception as e:
        errors.append(f"Google Search error: {e}")
            
    return f"No results found. Debug info: {'; '.join(errors)}"


async def _search_web_visible(query: str) -> str:
    """Fallback: Search using a visible browser window (bypasses bot detection)."""
    print(f"DEBUG: Starting visual search for '{query}'")
    try:
        from playwright.async_api import async_playwright
        settings = get_settings()
        
        async with async_playwright() as p:
            # Use a temporary context for search to avoid lock issues with the main persistent context
            # This ensures we don't hang waiting for a lock
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            
            try:
                page = await context.new_page()
                url = f"https://html.duckduckgo.com/html/?q={query}"
                print(f"DEBUG: Navigating to {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
                # Check for blocking
                content = await page.content()
                if "If this persists" in content:
                    print("DEBUG: Visual search blocked by DDG")
                    return None # Blocked
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                results = []
                
                # DDG HTML structure
                for link in soup.find_all('div', class_='result'):
                    title_tag = link.find('a', class_='result__a')
                    snippet_tag = link.find('a', class_='result__snippet')
                    
                    if title_tag and snippet_tag:
                        title = title_tag.get_text(strip=True)
                        href = title_tag['href']
                        # Fix DDG relative URLs
                        if href.startswith('//'):
                            href = 'https:' + href
                        # Unquote DDG redirect URLs if possible
                        if "uddg=" in href:
                            from urllib.parse import unquote, parse_qs, urlparse
                            try:
                                parsed = urlparse(href)
                                qs = parse_qs(parsed.query)
                                if 'uddg' in qs:
                                    href = unquote(qs['uddg'][0])
                            except:
                                pass
                                
                        snippet = snippet_tag.get_text(strip=True)
                        results.append(f"Title: {title}\nURL: {href}\nSnippet: {snippet}\n")
                        
                    if len(results) >= 5:
                        break
                
                print(f"DEBUG: Visual search found {len(results)} results")
                if results:
                    return "Note: Used Visual Browser Fallback.\n\n" + "\n---\n".join(results)
                    
            finally:
                await context.close()
                await browser.close()
                
    except Exception as e:
        print(f"DEBUG: Visual search error: {e}")
        return f"Visual Browser Error: {e}"
    
    return None


async def search_web(query: str, max_results: int = 5) -> str:
    """Search the web for a query using DuckDuckGo.
    
    Args:
        query: The search query.
        max_results: Maximum number of results to return (default: 5).
    """
    import asyncio
    import json
    
    # helper to parse string results back to dicts for canvas
    def parse_results_to_dicts(text_result):
        if not text_result or "No results found" in text_result:
            return []
        
        items = []
        # Split by the separator we used
        chunks = text_result.split("\n---\n")
        
        for p in chunks:
            lines = p.split("\n")
            item = {}
            for line in lines:
                if line.startswith("Title: "): item["title"] = line[7:]
                if line.startswith("URL: "): item["url"] = line[5:]
                if line.startswith("Snippet: "): item["snippet"] = line[9:]
            
            if "title" in item and "url" in item:
                items.append(item)
        return items

    result = ""
    # 1. Try DDGS (Fast, Sync) via thread
    try:
        # Run sync DDGS in a separate thread to avoid blocking the event loop
        result = await asyncio.wait_for(
            asyncio.to_thread(_search_web_sync, query, max_results), 
            timeout=10.0
        )
    except Exception as e:
        print(f"DEBUG: DDGS search failed: {e}")
        pass

    # 2. Fallback to Visual Search (Async, Robust) if DDGS failed or returned no results
    if not result or result.startswith("No results found"):
        try:
            print("DEBUG: Falling back to visual search...")
            visual_result = await asyncio.wait_for(_search_web_visible(query), timeout=45.0)
            if visual_result:
                result = visual_result
            elif not result:
                result = "No results found."
        except asyncio.TimeoutError:
            result = "Search timed out."
        except Exception as e:
            result = f"Search failed due to a technical error: {e}. Please check your internet connection."

    # Construct Dual Output
    structured_items = parse_results_to_dicts(result)
    
    if structured_items:
        canvas_data = {
            "type": "search_results",
            "query": query,
            "results": structured_items
        }
        return json.dumps({
            "__llm_content__": result,
            "__canvas__": canvas_data
        })
    
    # Return error state to Canvas if no results found
    return json.dumps({
        "__llm_content__": result, 
        "__canvas__": {
            "type": "search_error",
            "query": query,
            "error": result
        }
    })


async def browse_url(url: str) -> str:
    """Read the text content of a specific web page using a headless browser.
    
    IMPORTANT: Do NOT use this tool for YouTube, Vimeo, or other video platforms if the user wants to "see" or "watch" the content. 
    Use the `watch_video` tool instead to get visual frames. Only use `browse_url` for static text-based sites (blogs, articles, documentation).
    
    Args:
        url: The full URL to browse.
    """
    try:
        from playwright.async_api import async_playwright
        settings = get_settings()
        
        # Ensure data dir exists (Playwright creates it, but good to be safe with parent paths)
        os.makedirs(settings.browser_user_data_dir, exist_ok=True)
        
        async with async_playwright() as p:
            # Use non-persistent context for simple browsing to avoid lock contamination
            # unless login is specifically needed (which is handled by web_login)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            try:
                page = await context.new_page()
                print(f"DEBUG: Browsing {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # Small wait to let potential JS load content
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    print("DEBUG: Network idle wait timed out (continuing)")
                
                content = await page.content()
            finally:
                await context.close()
                await browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.extract()
            
            # Get text
            text = soup.get_text()
            
            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            final_text = f"Content of {url}:\n\n{text[:8000]}" # Limit to 8k chars
            
            # Return dual output for Canvas
            import json
            return json.dumps({
                "__llm_content__": final_text,
                "__canvas__": {
                    "type": "ocr", # Reuse OCR type for simple text display
                    "text": final_text
                }
            })
            
    except Exception as e:
        # Fallback to visual browsing if headless fails (often due to bot detection)
        print(f"DEBUG: Headless browse failed: {e}. Retrying with visible browser...")
        try:
            from playwright.async_api import async_playwright
            settings = get_settings()
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                
                try:
                    page = await context.new_page()
                    # Shorter timeout for fallback
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_load_state("networkidle", timeout=5000)
                    content = await page.content()
                finally:
                    await context.close()
                    await browser.close()
            
            # Process content (same as above)
            soup = BeautifulSoup(content, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            final_text = f"Content of {url} (Visual Fallback):\n\n{text[:8000]}"
            
            import json
            return json.dumps({
                "__llm_content__": final_text,
                "__canvas__": {
                    "type": "ocr",
                    "text": final_text
                }
            })
            
        except Exception as visual_e:
            error_msg = f"Error browsing {url}: {e} (Visual fallback also failed: {visual_e})"
            import json
            return json.dumps({
                "__llm_content__": error_msg,
                "__canvas__": {
                    "type": "search_error",
                    "query": url,
                    "error": error_msg
                }
            })


async def web_login(url: str) -> str:
    """Open a visible browser window for the user to log in to a website.
    The session/cookies will be saved so the agent can access it later.
    
    Args:
        url: The login URL (e.g., https://substack.com/sign-in)
    """
    try:
        from playwright.async_api import async_playwright
        settings = get_settings()
        
        os.makedirs(settings.browser_user_data_dir, exist_ok=True)
        
        print(f"Opening browser for login at {url}...")
        
        async with async_playwright() as p:
            # Headless=False so user can see it
            context = await p.chromium.launch_persistent_context(
                user_data_dir=settings.browser_user_data_dir,
                headless=False,
                viewport=None 
            )
            
            page = await context.new_page()
            await page.goto(url)
            
            # Wait for user to close the browser manually or a long timeout
            print("Please log in and then close the browser window.")
            
            # We wait until the context is closed (user closes window)
            # But Playwright doesn't have a simple "wait_for_close" on context level easily exposed in async
            # So we'll poll or just wait a fixed time, but better is to wait for close.
            # Simplified approach: Wait for a very long time or until page is closed?
            
            try:
                # Wait for the user to close the page/browser
                await page.wait_for_event("close", timeout=300000) # 5 minutes to login
            except Exception:
                pass # Timeout or closed
            
            await context.close()
            
        return f"Login session saved for {url}. You can now ask me to browse this site."
    except Exception as e:
        return f"Error during login flow: {e}"


WEB_TOOLS = [
    FunctionTool(search_web),
    FunctionTool(browse_url),
    FunctionTool(web_login),
]


WEB_TOOLS = [
    FunctionTool(search_web),
    FunctionTool(browse_url),
    FunctionTool(web_login),
]
