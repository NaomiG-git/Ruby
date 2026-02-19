"""Memory utilities."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def format_memory_string(memories: Any) -> str:
    """Format diverse memory types into a coherent string for the LLM context.
    
    Args:
        memories: Dictionary of memory lists by type/category or a flat list of items.
        
    Returns:
        Formatted memory string
    """
    if not memories:
        return ""

    # Convert flat list to category dict if needed
    if isinstance(memories, list):
        cat_map = {}
        for item in memories:
            cat = item.get("category", "other")
            if cat not in cat_map:
                cat_map[cat] = []
            cat_map[cat].append(item)
        memories = cat_map

    if not isinstance(memories, dict):
        return ""

    sections = []

    # 1. Core Profile
    if "profile" in memories and memories["profile"]:
        lines = ["# User Profile"]
        for item in memories["profile"]:
            lines.append(f"- {item.get('summary', item.get('content', ''))}")
        sections.append("\n".join(lines))

    # 2. Key Facts/Knowledge
    if "knowledge" in memories and memories["knowledge"]:
        lines = ["# Known Facts"]
        for item in memories["knowledge"]:
            lines.append(f"- {item.get('summary', item.get('content', ''))}")
        sections.append("\n".join(lines))

    # 3. Preferences
    if "preferences" in memories and memories["preferences"]:
        lines = ["# Preferences"]
        for item in memories["preferences"]:
            lines.append(f"- {item.get('summary', item.get('content', ''))}")
        sections.append("\n".join(lines))

    # 4. Past Interactions (Events)
    if "event" in memories and memories["event"]:
        lines = ["# Relevant Past Events"]
        for item in memories["event"]:
            date_str = ""
            if item.get("happened_at"):
                try:
                    dt = datetime.fromisoformat(str(item["happened_at"]))
                    date_str = f"[{dt.strftime('%Y-%m-%d')}] "
                except (ValueError, TypeError):
                    pass
            lines.append(f"- {date_str}{item.get('summary', item.get('content', ''))}")
        sections.append("\n".join(lines))

    # 5. Generic items (anything else)
    generic_items = []
    for category, items in memories.items():
        if category not in ("profile", "knowledge", "preferences", "event", "resources"):
            for item in items:
                generic_items.append(f"- [{category.title()}] {item.get('summary', item.get('content', ''))}")
    
    if generic_items:
        sections.append("# Other Context\n" + "\n".join(generic_items))

    return "\n\n".join(sections)
