"""FastAPI server for the MemU Agent."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from typing import Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager

from config.settings import get_settings
from src.agent.controller import AgentController
from src.llm.factory import ProviderFactory

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory for absolute paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UI_DIR = BASE_DIR / "ui" / "web"

class EventManager:
    """Manages simple server-side event broadcasting."""
    def __init__(self):
        self.subscribers = []

    def broadcast(self, event_type: str, content: Any):
        event = {"type": event_type, "content": content}
        for sub in self.subscribers:
            sub(event)

event_manager = EventManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan."""
    # Startup
    logger.info("Application starting up...")
    agent = get_agent()
    await agent.start_service()
    yield
    # Shutdown
    logger.info("Application shutting down...")
    if _agent:
        _agent.stop_service()

app = FastAPI(
    title="Ruby Assistant Interface",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Agent Controller (Lazy Init)
_agent: AgentController | None = None
_settings = get_settings()


def get_agent() -> AgentController:
    """Get or initialize the agent controller."""
    global _agent
    if _agent is None:
        try:
            # Pass the broadcast function to the agent
            _agent = AgentController(_settings, event_callback=event_manager.broadcast)
        except Exception as e:
            logger.error(f"Failed to init agent: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    return _agent


class ChatRequest(BaseModel):
    message: str
    images: list[str] | None = None  # List of base64 data URLs


class SwitchProviderRequest(BaseModel):
    provider: str
    model: str | None = None


class UpdateConfigRequest(BaseModel):
    hybrid_routing: bool | None = None


# --- API Endpoints ---

@app.get("/api/health")
async def health_check():
    """Simple health check."""
    return {"status": "ok", "agent": "Ruby"}


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Send a message to the agent and stream events."""
    agent = get_agent()
    
    async def event_generator():
        try:
            async for event in agent.stream_events(request.message, images=request.images):
                # Send valid JSON line
                yield json.dumps(event) + "\n"
        except Exception as e:
            logger.error(f"Chat stream error: {e}")
            yield json.dumps({"type": "error", "content": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@app.get("/api/history")
async def get_history(response: Response):
    """Get conversation history."""
    # Prevent browser caching
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    
    agent = get_agent()
    return {"history": agent._state.to_chat_format()}


@app.post("/api/reset")
async def reset_history():
    """Clear conversation history."""
    agent = get_agent()
    agent.clear_history()
    return {"status": "cleared"}


@app.post("/api/switch")
async def switch_provider(request: SwitchProviderRequest):
    """Switch LLM provider."""
    agent = get_agent()
    try:
        agent.switch_provider(request.provider, request.model)
        return {
            "status": "success",
            "provider": agent.provider_name,
            "model": agent._llm.current_model
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/config")
async def update_config(request: UpdateConfigRequest):
    """Update agent configuration."""
    if request.hybrid_routing is not None:
        _settings.hybrid_routing = request.hybrid_routing
    return {"status": "success"}


@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    agent = get_agent()
    return {
        "agent_name": _settings.agent_name,
        "provider": agent.provider_name,
        "model": agent._llm.current_model,
        "hybrid_routing": getattr(_settings, "hybrid_routing", False),
        "available_providers": ["openai", "anthropic", "google", "ollama"]
    }

@app.get("/api/screenshot")
async def take_screenshot():
    """Capture a screenshot and return as base64."""
    try:
        from PIL import ImageGrab
        import io
        import base64
        
        screenshot = ImageGrab.grab()
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        base64_encoded = base64.b64encode(img_byte_arr).decode('utf-8')
        return {"image": f"data:image/png;base64,{base64_encoded}"}
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/events")
async def sse_events(request: Request):
    """Server-Sent Events endpoint for real-time UI updates."""
    async def event_stream():
        import asyncio
        queue = asyncio.Queue()
        
        def on_event(event):
            queue.put_nowait(event)
            
        event_manager.subscribers.append(on_event)
        try:
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            event_manager.subscribers.remove(on_event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# --- Static Files ---

app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/")
async def read_root():
    """Serve the main index.html."""
    index_path = UI_DIR / "index.html"
    if not index_path.exists():
        logger.error(f"index.html not found at {index_path}")
        return HTMLResponse(content="<h1>Error: index.html not found</h1>", status_code=404)
    
    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

