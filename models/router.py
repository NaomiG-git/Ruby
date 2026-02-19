"""
models/router.py
----------------
Ruby – Unified Model Router

Single interface for all of Ruby's AI providers (OpenAI ChatGPT, Google Gemini).
Handles:
  - Provider + model selection via the `/model` command
  - Automatic fallback chain (primary → fallback) on errors
  - Streaming and non-streaming unified API
  - Per-session model switching
  - Status reporting

Usage:
    from models.router import ModelRouter

    router = ModelRouter()
    router.authenticate_all()          # sign in to all configured providers

    # Chat (uses primary model)
    response = router.chat("What's the weather like?")

    # Stream
    for chunk in router.stream("Write me a poem"):
        print(chunk, end="", flush=True)

    # Switch models via /model command (as Ruby would handle it)
    router.handle_model_command("/model gemini-3-ultra")
    router.handle_model_command("/model gpt-4o")
    router.handle_model_command("/model list")
    router.handle_model_command("/model status")
"""

import time
from dataclasses import dataclass, field
from typing import Generator, Optional

from .openai_client import OpenAIClient, OpenAIAuthError
from .gemini_client import GeminiClient, GeminiAuthError


# ---------------------------------------------------------------------------
# Available models catalogue
# ---------------------------------------------------------------------------

@dataclass
class ModelInfo:
    id:           str
    provider:     str          # "openai" | "gemini"
    display_name: str
    description:  str
    is_fast:      bool = False  # True for mini/flash models (speed-optimised)

AVAILABLE_MODELS = [
    # ----- OpenAI -----
    ModelInfo("gpt-4o",        "openai", "GPT-4o",        "OpenAI's most capable multimodal model"),
    ModelInfo("gpt-4o-mini",   "openai", "GPT-4o mini",   "Fast, efficient — great for quick tasks",      is_fast=True),
    ModelInfo("o3",            "openai", "o3",             "OpenAI's advanced reasoning model"),
    ModelInfo("o4-mini",       "openai", "o4-mini",        "Fast reasoning model",                         is_fast=True),
    # ----- Google Gemini -----
    ModelInfo("gemini-3-ultra","gemini", "Gemini 3 Ultra", "Google's most capable model (subscription)"),
    ModelInfo("gemini-3-flash","gemini", "Gemini 3 Flash", "Fast Gemini 3 model",                          is_fast=True),
    ModelInfo("gemini-2-flash","gemini", "Gemini 2.0 Flash","Gemini 2.0 — fast and capable",               is_fast=True),
    ModelInfo("gemini-pro",    "gemini", "Gemini 1.5 Pro", "Gemini 1.5 Pro — large context"),
]

_MODEL_MAP: dict[str, ModelInfo] = {m.id: m for m in AVAILABLE_MODELS}


# ---------------------------------------------------------------------------
# Fallback chain defaults
# ---------------------------------------------------------------------------

DEFAULT_PRIMARY  = "gpt-4o"
DEFAULT_FALLBACK = "gemini-3-flash"   # fast fallback if primary fails


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class RouterError(Exception):
    """Raised when all models in the fallback chain are unavailable."""

class ModelRouter:
    """
    Unified model router for Ruby.

    Parameters
    ----------
    primary_model : str
        The default model to use for all requests.
    fallback_model : str | None
        Model to try if the primary fails. Set to None to disable fallback.
    vault : Vault | None
        Ruby vault passed to both clients.
    """

    def __init__(
        self,
        primary_model:  str = DEFAULT_PRIMARY,
        fallback_model: Optional[str] = DEFAULT_FALLBACK,
        vault=None,
    ):
        self._vault = vault or self._default_vault()
        self._primary_id  = primary_model
        self._fallback_id = fallback_model

        # Initialise provider clients (lazy — auth happens on first use)
        self._openai = OpenAIClient(vault=self._vault)
        self._gemini = GeminiClient(vault=self._vault)

        # Conversation history (maintained across turns)
        self._history: list[dict] = []
        self._system_prompt: Optional[str] = None

        # Stats
        self._request_count  = 0
        self._fallback_count = 0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate_all(self) -> None:
        """Authenticate with all configured providers."""
        print("[Router] Authenticating with OpenAI...")
        try:
            self._openai.authenticate()
            print("[Router] ✓ OpenAI ready")
        except Exception as exc:
            print(f"[Router] ✗ OpenAI auth failed: {exc}")

        print("[Router] Authenticating with Google Gemini...")
        try:
            self._gemini.authenticate()
            print("[Router] ✓ Gemini ready")
        except Exception as exc:
            print(f"[Router] ✗ Gemini auth failed: {exc}")

    def authenticate_openai(self) -> None:
        self._openai.authenticate()

    def authenticate_gemini(self) -> None:
        self._gemini.authenticate()

    # ------------------------------------------------------------------
    # Chat API
    # ------------------------------------------------------------------

    def chat(
        self,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        use_history: bool = True,
    ) -> str:
        """
        Send a message and return the full response.
        Automatically falls back to the secondary model on failure.
        """
        if use_history:
            self._append_user(user_message)

        messages = self._build_messages(user_message, use_history)
        target   = model or self._primary_id

        response, used_model = self._chat_with_fallback(
            messages, target, temperature, max_tokens, stream=False
        )

        if use_history:
            self._append_assistant(response)

        self._request_count += 1
        return response

    def stream(
        self,
        user_message: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        use_history: bool = True,
    ) -> Generator[str, None, None]:
        """
        Stream a response. Yields text chunks. Falls back on failure.
        Conversation history is updated after the stream completes.
        """
        if use_history:
            self._append_user(user_message)

        messages = self._build_messages(user_message, use_history)
        target   = model or self._primary_id
        info     = _MODEL_MAP.get(target)

        # Attempt primary stream
        full_response = ""
        try:
            gen = self._get_stream(messages, target, temperature, max_tokens)
            for chunk in gen:
                full_response += chunk
                yield chunk
        except Exception as primary_exc:
            # Try fallback
            if self._fallback_id and self._fallback_id != target:
                print(f"\n[Router] Primary model failed ({primary_exc}). Trying fallback: {self._fallback_id}")
                self._fallback_count += 1
                try:
                    gen = self._get_stream(messages, self._fallback_id, temperature, max_tokens)
                    for chunk in gen:
                        full_response += chunk
                        yield chunk
                except Exception as fallback_exc:
                    raise RouterError(
                        f"All models failed.\n  Primary ({target}): {primary_exc}\n  Fallback ({self._fallback_id}): {fallback_exc}"
                    )
            else:
                raise RouterError(f"Model {target} failed: {primary_exc}")

        if use_history and full_response:
            self._append_assistant(full_response)

        self._request_count += 1

    # ------------------------------------------------------------------
    # /model command handler
    # ------------------------------------------------------------------

    def handle_model_command(self, command: str) -> str:
        """
        Process a `/model` command from the user and return a response string.

        Commands:
          /model list             — list all available models
          /model status           — show current primary + fallback + stats
          /model <id>             — switch primary model
          /model fallback <id>    — set fallback model
          /model fallback off     — disable fallback
        """
        parts = command.strip().split()
        if len(parts) < 2:
            return self._model_status()

        sub = parts[1].lower()

        if sub == "list":
            return self._model_list()

        if sub == "status":
            return self._model_status()

        if sub == "fallback":
            if len(parts) < 3:
                return f"Current fallback: {self._fallback_id or 'disabled'}"
            target = parts[2].lower()
            if target == "off":
                self._fallback_id = None
                return "Fallback disabled."
            if target not in _MODEL_MAP:
                return f"Unknown model: {target!r}. Use `/model list` to see options."
            self._fallback_id = target
            info = _MODEL_MAP[target]
            return f"Fallback set to: {info.display_name} ({info.provider.upper()})"

        # Switch primary model
        model_id = parts[1].lower()
        if model_id not in _MODEL_MAP:
            close = [m for m in _MODEL_MAP if model_id in m]
            hint  = f" Did you mean: {', '.join(close)}?" if close else ""
            return f"Unknown model: {model_id!r}.{hint} Use `/model list` to see options."

        self._primary_id = model_id
        info = _MODEL_MAP[model_id]
        # Also update the client's active model
        if info.provider == "openai":
            self._openai.set_model(model_id)
        else:
            self._gemini.set_model(model_id)
        return f"✓ Model switched to: **{info.display_name}** ({info.provider.upper()}) — {info.description}"

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def set_system_prompt(self, prompt: str) -> None:
        """Set Ruby's system/persona prompt."""
        self._system_prompt = prompt

    def clear_history(self) -> None:
        """Clear conversation history (start a fresh session)."""
        self._history.clear()

    def get_history(self) -> list[dict]:
        return list(self._history)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "primary_model":    self._primary_id,
            "fallback_model":   self._fallback_id,
            "requests_total":   self._request_count,
            "fallback_hits":    self._fallback_count,
            "history_turns":    len(self._history) // 2,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _chat_with_fallback(
        self, messages, target, temperature, max_tokens, stream
    ) -> tuple[str, str]:
        try:
            return self._get_response(messages, target, temperature, max_tokens), target
        except Exception as primary_exc:
            if self._fallback_id and self._fallback_id != target:
                print(f"[Router] Primary failed ({primary_exc}). Falling back to {self._fallback_id}...")
                self._fallback_count += 1
                try:
                    return self._get_response(messages, self._fallback_id, temperature, max_tokens), self._fallback_id
                except Exception as fallback_exc:
                    raise RouterError(
                        f"All models failed.\n  Primary ({target}): {primary_exc}\n  Fallback ({self._fallback_id}): {fallback_exc}"
                    ) from fallback_exc
            raise RouterError(f"Model {target} failed: {primary_exc}") from primary_exc

    def _get_response(self, messages, model_id, temperature, max_tokens) -> str:
        info = _MODEL_MAP.get(model_id)
        if not info:
            raise ValueError(f"Unknown model: {model_id}")
        if info.provider == "openai":
            return self._openai.chat(messages, model=model_id, temperature=temperature, max_tokens=max_tokens)
        else:
            return self._gemini.chat(messages, model=model_id, temperature=temperature, max_tokens=max_tokens)

    def _get_stream(self, messages, model_id, temperature, max_tokens) -> Generator:
        info = _MODEL_MAP.get(model_id)
        if not info:
            raise ValueError(f"Unknown model: {model_id}")
        if info.provider == "openai":
            return self._openai.stream(messages, model=model_id, temperature=temperature, max_tokens=max_tokens)
        else:
            return self._gemini.stream(messages, model=model_id, temperature=temperature, max_tokens=max_tokens)

    def _build_messages(self, user_message: str, use_history: bool) -> list[dict]:
        messages = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        if use_history:
            messages.extend(self._history)
        else:
            messages.append({"role": "user", "content": user_message})
        return messages

    def _append_user(self, text: str) -> None:
        self._history.append({"role": "user", "content": text})

    def _append_assistant(self, text: str) -> None:
        self._history.append({"role": "assistant", "content": text})

    def _model_list(self) -> str:
        lines = ["**Available Models:**\n"]
        providers = {}
        for m in AVAILABLE_MODELS:
            providers.setdefault(m.provider, []).append(m)

        for provider, models in providers.items():
            lines.append(f"**{provider.upper()}** (sign in with your {provider.title()} subscription)")
            for m in models:
                active = " ← active" if m.id == self._primary_id else ""
                fallback_tag = " ← fallback" if m.id == self._fallback_id else ""
                speed  = " ⚡" if m.is_fast else ""
                lines.append(f"  `{m.id}`{speed}  —  {m.description}{active}{fallback_tag}")
            lines.append("")

        lines.append("Use `/model <id>` to switch  |  `/model fallback <id>` to set fallback")
        return "\n".join(lines)

    def _model_status(self) -> str:
        primary = _MODEL_MAP.get(self._primary_id)
        fallback = _MODEL_MAP.get(self._fallback_id) if self._fallback_id else None
        lines = [
            f"**Active model:**  {primary.display_name if primary else self._primary_id}  ({primary.provider.upper() if primary else '?'})",
            f"**Fallback model:**  {fallback.display_name if fallback else 'disabled'}",
            f"**Requests this session:**  {self._request_count}  (fallback used {self._fallback_count}×)",
            f"**Conversation turns:**  {len(self._history) // 2}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()
