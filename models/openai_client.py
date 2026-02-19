"""
models/openai_client.py
-----------------------
Ruby – OpenAI (ChatGPT) OAuth Client

Authenticates with OpenAI using your ChatGPT Plus/Pro subscription via a
PKCE OAuth 2.0 flow — no API key required. Tokens are stored securely in
Ruby's encrypted vault (security.vault).

Flow:
  1. First run: opens a browser → user signs in with their OpenAI account
  2. OAuth callback received on localhost → tokens stored in vault
  3. Subsequent runs: token refreshed silently from vault
  4. Expired refresh token: re-triggers browser login

Supports:
  - Streaming chat completions (yields chunks)
  - Non-streaming completions
  - Model selection (gpt-4o, gpt-4o-mini, o3, etc.)
  - Automatic token refresh

Usage:
    from models.openai_client import OpenAIClient

    client = OpenAIClient()
    client.authenticate()  # opens browser on first run

    # Non-streaming
    response = client.chat([{"role": "user", "content": "Hello Ruby!"}])
    print(response)

    # Streaming
    for chunk in client.stream([{"role": "user", "content": "Tell me a story"}]):
        print(chunk, end="", flush=True)
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Generator, Optional
from urllib.parse import parse_qs, urlencode, urlparse
import sys

# ---------------------------------------------------------------------------
# Dependencies — graceful import errors
# ---------------------------------------------------------------------------
try:
    import httpx
except ImportError:
    raise ImportError("httpx is required: pip install httpx")

# ---------------------------------------------------------------------------
# OpenAI OAuth configuration
# ---------------------------------------------------------------------------

OPENAI_AUTH_BASE    = "https://auth.openai.com"
OPENAI_TOKEN_URL    = f"{OPENAI_AUTH_BASE}/oauth/token"
OPENAI_AUTH_URL     = f"{OPENAI_AUTH_BASE}/authorize"
OPENAI_API_BASE     = "https://api.openai.com/v1"
# OAuth app credentials (public PKCE — no client secret needed)
OPENAI_CLIENT_ID    = "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh"   # ChatGPT web client
OPENAI_REDIRECT_URI = "http://localhost:54321/callback"
OPENAI_SCOPES       = "openid profile email offline_access"

CALLBACK_PORT       = 54321
DEFAULT_MODEL       = "gpt-4o"
VAULT_KEY_ACCESS    = "openai_access_token"
VAULT_KEY_REFRESH   = "openai_refresh_token"
VAULT_KEY_EXPIRY    = "openai_token_expiry"


# ---------------------------------------------------------------------------
# OpenAIClient
# ---------------------------------------------------------------------------

class OpenAIAuthError(Exception):
    """Raised when authentication fails or tokens cannot be refreshed."""

class OpenAIClient:
    """
    ChatGPT client authenticated via your OpenAI subscription (OAuth PKCE).

    Parameters
    ----------
    model : str
        Default model to use (e.g. "gpt-4o", "gpt-4o-mini", "o3").
    vault : Vault | None
        Ruby vault instance. If None, a new Vault() is created.
    """

    def __init__(self, model: str = DEFAULT_MODEL, vault=None):
        self._model  = model
        self._vault  = vault or self._default_vault()
        self._access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """
        Ensure we have a valid access token.
        - Loads from vault if available and not expired
        - Refreshes silently if a refresh token exists
        - Opens browser for full login if needed
        """
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
        max_tokens: int = 4096,
    ) -> str:
        """Send a chat request and return the full response text."""
        self._ensure_authenticated()
        payload = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        resp = self._post("/chat/completions", payload)
        return resp["choices"][0]["message"]["content"]

    def stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Generator[str, None, None]:
        """Stream a chat response, yielding text chunks as they arrive."""
        self._ensure_authenticated()
        payload = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with httpx.Client(timeout=120) as client:
            with client.stream(
                "POST",
                f"{OPENAI_API_BASE}/chat/completions",
                headers=self._auth_headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"]
                            if "content" in delta:
                                yield delta["content"]
                        except (json.JSONDecodeError, KeyError):
                            continue

    def set_model(self, model: str) -> None:
        """Switch the active model (e.g. /model gpt-4o-mini)."""
        self._model = model
        print(f"[OpenAI] Model set to: {model}")

    def current_model(self) -> str:
        return self._model

    def logout(self) -> None:
        """Clear stored tokens from the vault."""
        for key in (VAULT_KEY_ACCESS, VAULT_KEY_REFRESH, VAULT_KEY_EXPIRY):
            try:
                self._vault.delete(key)
            except KeyError:
                pass
        self._access_token = None
        print("[OpenAI] Logged out. Tokens removed from vault.")

    # ------------------------------------------------------------------
    # Authentication internals
    # ------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        if not self._access_token or self._is_expired():
            self.authenticate()

    def _load_from_vault(self) -> bool:
        """Try to load a non-expired access token from the vault."""
        try:
            token  = self._vault.retrieve(VAULT_KEY_ACCESS)
            expiry = float(self._vault.retrieve(VAULT_KEY_EXPIRY))
            if time.time() < expiry - 60:  # 60s buffer
                self._access_token = token
                return True
        except (KeyError, ValueError):
            pass
        return False

    def _refresh_from_vault(self) -> bool:
        """Try to silently refresh using the stored refresh token."""
        try:
            refresh_token = self._vault.retrieve(VAULT_KEY_REFRESH)
        except KeyError:
            return False

        try:
            data = {
                "grant_type":    "refresh_token",
                "client_id":     OPENAI_CLIENT_ID,
                "refresh_token": refresh_token,
            }
            resp = httpx.post(OPENAI_TOKEN_URL, data=data, timeout=30)
            resp.raise_for_status()
            return self._store_tokens(resp.json())
        except Exception as exc:
            print(f"[OpenAI] Silent refresh failed: {exc}. Re-authenticating...")
            return False

    def _browser_login(self) -> None:
        """Launch browser-based PKCE OAuth flow."""
        code_verifier  = _pkce_verifier()
        code_challenge = _pkce_challenge(code_verifier)
        state          = secrets.token_urlsafe(16)

        params = {
            "response_type":         "code",
            "client_id":             OPENAI_CLIENT_ID,
            "redirect_uri":          OPENAI_REDIRECT_URI,
            "scope":                 OPENAI_SCOPES,
            "state":                 state,
            "code_challenge":        code_challenge,
            "code_challenge_method": "S256",
        }
        auth_url = f"{OPENAI_AUTH_URL}?{urlencode(params)}"

        print("\n[OpenAI] Opening browser for ChatGPT sign-in...")
        print(f"  If the browser doesn't open, visit:\n  {auth_url}\n")
        webbrowser.open(auth_url)

        # Start local callback server
        auth_code = _wait_for_callback(CALLBACK_PORT, state, timeout=120)
        if not auth_code:
            raise OpenAIAuthError("Authentication timed out or was cancelled.")

        # Exchange code for tokens
        data = {
            "grant_type":    "authorization_code",
            "client_id":     OPENAI_CLIENT_ID,
            "redirect_uri":  OPENAI_REDIRECT_URI,
            "code":          auth_code,
            "code_verifier": code_verifier,
        }
        resp = httpx.post(OPENAI_TOKEN_URL, data=data, timeout=30)
        resp.raise_for_status()
        if not self._store_tokens(resp.json()):
            raise OpenAIAuthError("Failed to store tokens after login.")
        print("[OpenAI] ✓ Authenticated successfully. Tokens saved to vault.")

    def _store_tokens(self, token_data: dict) -> bool:
        """Store access + refresh tokens in the vault. Returns True on success."""
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
            print(f"[OpenAI] Failed to store tokens in vault: {exc}")
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

    def _post(self, path: str, payload: dict) -> dict:
        resp = httpx.post(
            f"{OPENAI_API_BASE}{path}",
            headers=self._auth_headers(),
            json=payload,
            timeout=120,
        )
        if resp.status_code == 401:
            # Try refresh once
            if self._refresh_from_vault():
                resp = httpx.post(
                    f"{OPENAI_API_BASE}{path}",
                    headers=self._auth_headers(),
                    json=payload,
                    timeout=120,
                )
            else:
                raise OpenAIAuthError("Access token expired and refresh failed. Run authenticate().")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _default_vault():
        from security.vault import Vault
        return Vault()


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
        parsed  = urlparse(self.path)
        params  = parse_qs(parsed.query)
        code    = params.get("code",  [None])[0]
        state   = params.get("state", [None])[0]
        error   = params.get("error", [None])[0]

        _auth_result["code"]  = code
        _auth_result["state"] = state
        _auth_result["error"] = error

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if code:
            body = b"<h2>Ruby: Authentication successful!</h2><p>You can close this window.</p>"
        else:
            body = f"<h2>Ruby: Authentication failed</h2><p>{error}</p>".encode()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress server logs

def _wait_for_callback(port: int, expected_state: str, timeout: int = 120) -> Optional[str]:
    """Start a one-shot HTTP server and wait for the OAuth redirect."""
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
        print(f"[OpenAI] OAuth error: {_auth_result['error']}")
        return None
    if _auth_result.get("state") != expected_state:
        print("[OpenAI] OAuth state mismatch — possible CSRF. Aborting.")
        return None
    return _auth_result.get("code")
