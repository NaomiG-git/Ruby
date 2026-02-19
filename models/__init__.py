"""
models/
-------
Ruby AI Model Support

Provides OAuth-authenticated access to ChatGPT and Gemini using your existing
subscriptions — no API keys required. Tokens stored in Ruby's encrypted vault.

Modules
-------
openai_client.py  — OpenAI (ChatGPT Plus/Pro) via OAuth PKCE
gemini_client.py  — Google Gemini 3 via Google OAuth 2.0
router.py         — Unified model router with fallback chain + /model command

Quick start:
    from models.router import ModelRouter

    router = ModelRouter()
    router.authenticate_all()

    # Chat
    response = router.chat("What can you help me with today?")

    # Stream
    for chunk in router.stream("Summarise the news"):
        print(chunk, end="", flush=True)

    # Switch models
    router.handle_model_command("/model gemini-3-ultra")
    router.handle_model_command("/model list")

Available models:
    OpenAI   : gpt-4o, gpt-4o-mini, o3, o4-mini
    Gemini   : gemini-3-ultra, gemini-3-flash, gemini-2-flash, gemini-pro
"""

from .openai_client import OpenAIClient, OpenAIAuthError
from .gemini_client import GeminiClient, GeminiAuthError
from .router import ModelRouter, RouterError, AVAILABLE_MODELS, ModelInfo

__all__ = [
    "OpenAIClient",
    "OpenAIAuthError",
    "GeminiClient",
    "GeminiAuthError",
    "ModelRouter",
    "RouterError",
    "AVAILABLE_MODELS",
    "ModelInfo",
]
