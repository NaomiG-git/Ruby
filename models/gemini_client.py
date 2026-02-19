"""
models/gemini_client.py
-----------------------
Ruby – Google Gemini OAuth Client

Authenticates with Google using your existing Google account (Gemini Advanced /
Google One AI Premium subscription) via a standard Google OAuth 2.0 PKCE flow —
no API key required. Tokens are stored securely in Ruby's encrypted vault.

Flow:
  1. First run: opens browser → user signs in with Google account
  2. OAuth callback on localhost → tokens stored in vault
  3. Subsequent runs: access token refreshed silently using stored refresh token
  4. Expired refresh token: re-triggers browser login

Supports:
  - Streaming chat (yields text chunks)
  - Non-streaming chat
  - Multi-turn conversation (message history)
  - Model selection (gemini-3-ultra, gemini-3-flash, gemini-2.0-flash, etc.)
  - File/image input (multimodal)

Usage:
    from models.gemini_client import GeminiClient

    client = GeminiClient()
    client.authenticate()   # opens browser on first run

    # Non-streaming
    response = client.chat([{"role": "user", "content": "Hello Ruby!"}])
    print(response)

    # Streaming
    for chunk in client.stream([{"role": "user", "content": "Tell me a story"}]):
        print(chunk, end="", flush=True)

    # With an image
    response = client.chat([{
        "role": "user",
        "content": [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_path", "path": "screenshot.png"},
        ]
    }])
"""

import base64
import hashlib
import json
import mimetypes
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Generator, Optional
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import httpx
except ImportError:
    raise ImportError("httpx is required: pip install httpx")

# ---------------------------------------------------------------------------
# Google OAuth configuration
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL   = "https://oauth2.googleapis.com/revoke"

# Google AI / Gemini API
GEMINI_API_BASE     = "https://generativelanguage.googleapis.com/v1beta"

# OAuth client — installed-app / PKCE (no client secret exposed)
GOOGLE_CLIENT_ID    = "608560683311-e1pi5csdkm2kf1pbe0p6qh7o8kl7flt4.apps.googleusercontent.com"
GOOGLE_REDIRECT_URI = "http://localhost:54322/callback"
GOOGLE_SCOPES       = " ".join([
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/generative-language",       # Gemini API
    "https://www.googleapis.com/auth/generative-language.tuning",
])

CALLBACK_PORT      = 54322
DEFAULT_MODEL      = "gemini-3-ultra"              # update as Google releases
VAULT_KEY_ACCESS   = "gemini_access_token"
VAULT_KEY_REFRESH  = "gemini_refresh_token"
VAULT_KEY_EXPIRY   = "gemini_token_expiry"

# Model aliases
MODEL_ALIASES = {
    "gemini-3-ultra":  "gemini-3.0-ultra-latest",
    "gemini-3-flash":  "gemini-3.0-flash-latest",
    "gemini-2-flash":  "gemini-2.0-flash",
    "gemini-pro":      "gemini-1.5-pro-latest",
    "gemini-flash":    "gemini-1.5-flash-latest",
}


# ---------------------------------------------------------------------------
# GeminiClient
# ---------------------------------------------------------------------------

class GeminiAuthError(Exception):
    """Raised when Google authentication fails."""

class GeminiClient:
    """
    Google Gemini client authenticated via your Google/Gemini subscription (OAuth PKCE).

    Parameters
    ----------
    model : str
        Default model to use. Supports aliases like "gemini-3-ultra".
    vault : Vault | None
        Ruby vault instance. Created automatically if not provided.
    """

    def __init__(self, model: str = DEFAULT_MODEL, vault=None):
        self._model  = self._resolve_model(model)
        self._vault  = vault or self._default_vault()
        self._access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """Ensure a valid access token exists — load, refresh, or full login."""
        if self._load_from_vault():
            return
        if self._refresh_from_vault():
            return
        self._browser_login()

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> str:
        """Send a chat request and return the full response text."""
        self._ensure_authenticated()
        resolved = self._resolve_model(model or self._model)
        payload  = self._build_payload(messages, temperature, max_tokens)

        url = f"{GEMINI_API_BASE}/models/{resolved}:generateContent"
        resp = self._post(url, payload)
        return self._extract_text(resp)

    def stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
    ) -> Generator[str, None, None]:
        """Stream a Gemini response, yielding text chunks."""
        self._ensure_authenticated()
        resolved = self._resolve_model(model or self._model)
        payload  = self._build_payload(messages, temperature, max_tokens)

        url = f"{GEMINI_API_BASE}/models/{resolved}:streamGenerateContent?alt=sse"
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                url,
                headers=self._auth_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            text = self._extract_text(chunk)
                            if text:
                                yield text
                        except (json.JSONDecodeError, KeyError):
                            continue

    def set_model(self, model: str) -> None:
        """Switch the active model (e.g. /model gemini-3-flash)."""
        self._model = self._resolve_model(model)
        print(f"[Gemini] Model set to: {self._model}")

    def current_model(self) -> str:
        return self._model

    def logout(self) -> None:
        """Revoke tokens and clear from vault."""
        try:
            token = self._vault.retrieve(VAULT_KEY_ACCESS)
            httpx.post(GOOGLE_REVOKE_URL, params={"token": token}, timeout=10)
        except Exception:
            pass
        for key in (VAULT_KEY_ACCESS, VAULT_KEY_REFRESH, VAULT_KEY_EXPIRY):
            try:
                self._vault.delete(key)
            except KeyError:
                pass
        self._access_token = None
        print("[Gemini] Logged out. Tokens removed from vault.")

    # ------------------------------------------------------------------
    # Payload construction (handles text + multimodal)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_payload(messages: list[dict], temperature: float, max_tokens: int) -> dict:
        """Convert Ruby's universal message format to Gemini's `contents` format."""
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Map roles: system → feed as leading user turn; assistant → model
            if role == "system":
                system_parts.append({"text": content})
                continue

            gemini_role = "model" if role == "assistant" else "user"

            # Handle multimodal content (list of parts)
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"text": part["text"]})
                    elif part.get("type") == "image_path":
                        parts.append(_image_part_from_path(Path(part["path"])))
                    elif part.get("type") == "image_base64":
                        parts.append({
                            "inline_data": {
                                "mime_type": part.get("mime_type", "image/png"),
                                "data": part["data"],
                            }
                        })
            else:
                parts = [{"text": content}]

            contents.append({"role": gemini_role, "parts": parts})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "temperature":     temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        # Prepend system instruction if present
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        return payload

    @staticmethod
    def _extract_text(resp: dict) -> str:
        """Pull text from a Gemini API response or stream chunk."""
        try:
            candidates = resp.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            return ""

    # ------------------------------------------------------------------
    # Authentication internals
    # ------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        if not self._access_token or self._is_expired():
            self.authenticate()

    def _load_from_vault(self) -> bool:
        try:
            token  = self._vault.retrieve(VAULT_KEY_ACCESS)
            expiry = float(self._vault.retrieve(VAULT_KEY_EXPIRY))
            if time.time() < expiry - 60:
                self._access_token = token
                return True
        except (KeyError, ValueError):
            pass
        return False

    def _refresh_from_vault(self) -> bool:
        try:
            refresh_token = self._vault.retrieve(VAULT_KEY_REFRESH)
        except KeyError:
            return False

        try:
            data = {
                "grant_type":    "refresh_token",
                "client_id":     GOOGLE_CLIENT_ID,
                "refresh_token": refresh_token,
            }
            resp = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=30)
            resp.raise_for_status()
            return self._store_tokens(resp.json())
        except Exception as exc:
            print(f"[Gemini] Silent refresh failed: {exc}. Re-authenticating...")
            return False

    def _browser_login(self) -> None:
        code_verifier  = _pkce_verifier()
        code_challenge = _pkce_challenge(code_verifier)
        state          = secrets.token_urlsafe(16)

        params = {
            "response_type":         "code",
            "client_id":             GOOGLE_CLIENT_ID,
            "redirect_uri":          GOOGLE_REDIRECT_URI,
            "scope":                 GOOGLE_SCOPES,
            "state":                 state,
            "access_type":           "offline",   # request refresh token
            "prompt":                "consent",    # always show consent to get refresh token
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

        print("\n[Gemini] Opening browser for Google sign-in...")
        print(f"  If the browser doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        auth_code = _wait_for_callback(CALLBACK_PORT, state, timeout=120)
        if not auth_code:
            raise GeminiAuthError("Authentication timed out or was cancelled.")

        data = {
            "grant_type":    "authorization_code",
            "client_id":     GOOGLE_CLIENT_ID,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "code":          auth_code,
            "code_verifier": code_verifier,
        }
        resp = httpx.post(GOOGLE_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        if not self._store_tokens(resp.json()):
            raise GeminiAuthError("Failed to store tokens after login.")
        print("[Gemini] ✓ Authenticated successfully. Tokens saved to vault.")

    def _store_tokens(self, token_data: dict) -> bool:
        try:
            access_token  = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in    = token_data.get("expires_in", 3600)

            if not access_token:
                return False

            expiry = time.time() + expires_in
            self._vault.store(VAULT_KEY_ACCESS,  access_token)
            self._vault.store(VAULT_KEY_EXPIRY,  str(expiry))
            if refresh_token:
                self._vault.store(VAULT_KEY_REFRESH, refresh_token)

            self._access_token = access_token
            return True
        except Exception as exc:
            print(f"[Gemini] Failed to store tokens in vault: {exc}")
            return False

    def _is_expired(self) -> bool:
        try:
            expiry = float(self._vault.retrieve(VAULT_KEY_EXPIRY))
            return time.time() >= expiry - 60
        except (KeyError, ValueError):
            return True

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type":  "application/json",
        }

    def _post(self, url: str, payload: dict) -> dict:
        resp = httpx.post(url, headers=self._auth_headers(), json=payload, timeout=120)
        if resp.status_code == 401:
            if self._refresh_from_vault():
                resp = httpx.post(url, headers=self._auth_headers(), json=payload, timeout=120)
            else:
                raise GeminiAuthError("Access token expired and refresh failed. Run authenticate().")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _resolve_model(model: str) -> str:
        return MODEL_ALIASES.get(model, model)

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()


# ---------------------------------------------------------------------------
# Multimodal helper
# ---------------------------------------------------------------------------

def _image_part_from_path(path: Path) -> dict:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"inline_data": {"mime_type": mime, "data": data}}


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _pkce_verifier() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()

def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Local OAuth callback server
# ---------------------------------------------------------------------------

_auth_result: dict = {}

class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        _auth_result["code"]  = params.get("code",  [None])[0]
        _auth_result["state"] = params.get("state", [None])[0]
        _auth_result["error"] = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if _auth_result.get("code"):
            body = b"<h2>Ruby: Google sign-in successful!</h2><p>You can close this window.</p>"
        else:
            body = f"<h2>Ruby: Sign-in failed</h2><p>{_auth_result.get('error')}</p>".encode()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

def _wait_for_callback(port: int, expected_state: str, timeout: int = 120) -> Optional[str]:
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.timeout = timeout
    _auth_result.clear()

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if "code" in _auth_result or "error" in _auth_result:
            break

    server.server_close()

    if _auth_result.get("error"):
        print(f"[Gemini] OAuth error: {_auth_result['error']}")
        return None
    if _auth_result.get("state") != expected_state:
        print("[Gemini] OAuth state mismatch — possible CSRF. Aborting.")
        return None
    return _auth_result.get("code")
