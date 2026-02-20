"""
skills/builtins/web_search/__init__.py
---------------------------------------
Ruby built-in skill: Web Search (DuckDuckGo Instant Answer API, no key needed)
"""

from __future__ import annotations

import asyncio
import urllib.parse
from skills.base import skill_tool


@skill_tool(
    name="search_web",
    description=(
        "Search the web using DuckDuckGo and return a concise summary of results. "
        "Use this to look up current events, facts, prices, weather, etc."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "The search query.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5).",
            "default": 5,
        },
    },
    required=["query"],
)
async def search_web(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo and return formatted results."""
    import httpx

    # DuckDuckGo Instant Answer API (no API key required)
    url = "https://api.duckduckgo.com/"
    params = {
        "q":      query,
        "format": "json",
        "no_html": "1",
        "no_redirect": "1",
        "skip_disambig": "1",
    }
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(url, params=params)
        data = resp.json()

    lines: list[str] = []

    # Abstract (direct answer)
    abstract = data.get("AbstractText", "").strip()
    if abstract:
        source = data.get("AbstractSource", "")
        lines.append(f"**Summary ({source}):** {abstract}")

    # Answer (instant answer box)
    answer = data.get("Answer", "").strip()
    if answer:
        lines.append(f"**Answer:** {answer}")

    # RelatedTopics (search results)
    topics = data.get("RelatedTopics", [])
    count = 0
    for topic in topics:
        if count >= max_results:
            break
        if isinstance(topic, dict) and "Text" in topic:
            text = topic["Text"].strip()
            href = topic.get("FirstURL", "")
            if text:
                lines.append(f"- {text}" + (f" ({href})" if href else ""))
                count += 1
        elif isinstance(topic, dict) and "Topics" in topic:
            # Nested topic group
            for sub in topic["Topics"]:
                if count >= max_results:
                    break
                if isinstance(sub, dict) and "Text" in sub:
                    text = sub["Text"].strip()
                    href = sub.get("FirstURL", "")
                    if text:
                        lines.append(f"- {text}" + (f" ({href})" if href else ""))
                        count += 1

    if not lines:
        # Fallback: surface the raw DuckDuckGo definition
        definition = data.get("Definition", "").strip()
        if definition:
            lines.append(f"**Definition:** {definition}")
        else:
            lines.append(f"No instant answer found for: {query!r}")

    return "\n".join(lines)
