"""Canvas rendering tools for the Ruby Agent."""

import json
from src.agent.tools import FunctionTool

async def render_to_canvas(content: str | dict, title: str | None = None) -> str:
    """Renders HTML, SVG, or text content directly to Ruby's Canvas workspace.
    
    Args:
        content: The HTML, SVG, Markdown content, or a structured dict (for web_preview/pin_preview).
        title: Optional title for the canvas card.
    """
    if not content:
        return "Error: No content provided to render."
        
    # If content is already a dict, assume it's a structured payload (e.g. {type: 'web_preview', ...})
    if isinstance(content, dict):
        payload = content
    # Build a simple wrapper if it's raw HTML/SVG string
    elif isinstance(content, str) and content.strip().startswith('<'):
        payload = content
    else:
        # Markdown-ish or simple string
        payload = {
            "title": title or "Ruby's Workspace",
            "body": str(content)
        }
        
    return json.dumps({"__canvas__": payload})

CANVAS_TOOLS = [
    FunctionTool(
        func=render_to_canvas,
        name="render_to_canvas",
        description="Pushes rich content (HTML, SVG, or data) to Ruby's visual Canvas workspace. Use this to show diagrams, tables, or built applications."
    )
]
