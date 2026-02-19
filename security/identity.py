"""
security/identity.py
--------------------
Ruby Cryptographic Peer Identity Verification

Provides HMAC-SHA256 signed pairing tokens for authenticating external
clients (messaging channel adapters, mobile nodes, etc.) that want to
connect to Ruby's gateway.

Key improvements over OpenClaw:
  - Tokens are cryptographically signed (HMAC-SHA256) — cannot be forged
  - Each token has a short TTL (default 5 minutes) — limits exposure window
  - Replay protection via a nonce store — each token can only be used once
  - Supports peer allowlist with HMAC-signed entries

Usage:
    from security.identity import IdentityManager

    id_mgr = IdentityManager()

    # On Ruby's side — generate a pairing token and show it to the user
    token = id_mgr.create_pairing_token(peer_id="whatsapp:+1234567890")
    print(f"Pair with this token: {token}")

    # On the peer side — verify the token when the peer connects
    peer_id = id_mgr.verify_pairing_token(token)  # returns peer_id or raises

    # Allowlist management
    id_mgr.allow_peer("telegram:user123")
    id_mgr.revoke_peer("telegram:user123")
    print(id_mgr.list_allowed_peers())
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional

_IS_WINDOWS = __import__("sys").platform == "win32"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TOKEN_TTL    = 5 * 60       # 5 minutes in seconds
NONCE_STORE_TTL      = 24 * 60 * 60 # Keep used nonces for 24 hours
SIGNING_KEY_BYTES    = 32           # 256-bit HMAC key
TOKEN_VERSION        = "1"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class IdentityError(Exception):
    """Raised when a pairing token is invalid, expired, or replayed."""

class TokenExpiredError(IdentityError):
    """Token has passed its TTL."""

class TokenReplayError(IdentityError):
    """Token has already been used."""

class TokenInvalidError(IdentityError):
    """Token signature or structure is invalid."""

class PeerNotAllowedError(IdentityError):
    """Peer is not in the allowlist."""


# ---------------------------------------------------------------------------
# IdentityManager
# ---------------------------------------------------------------------------

class IdentityManager:
    """
    Manages pairing tokens and the peer allowlist for Ruby's gateway.

    Parameters
    ----------
    config_dir : Path | None
        Override the default config directory
        (%APPDATA%\\Ruby\\security\\  on Windows, ~/.ruby/security/ elsewhere).
    token_ttl : int
        Token lifetime in seconds (default: 300 = 5 minutes).
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        token_ttl: int = DEFAULT_TOKEN_TTL,
    ):
        self._dir = Path(config_dir) if config_dir else self._default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._token_ttl = token_ttl

        self._signing_key = self._load_or_create_signing_key()
        self._nonce_store: dict[str, float] = {}   # nonce → expiry timestamp
        self._allowlist: dict[str, str] = {}        # peer_id → HMAC signature
        self._load_allowlist()

    # ------------------------------------------------------------------
    # Pairing token API
    # ------------------------------------------------------------------

    def create_pairing_token(self, peer_id: str) -> str:
        """
        Create a signed, time-limited pairing token for *peer_id*.

        Token format (URL-safe, colon-delimited):
            {version}:{peer_id_b64}:{issued_at}:{nonce}:{hmac}
        """
        issued_at = str(int(time.time()))
        nonce     = secrets.token_hex(16)
        payload   = self._make_payload(TOKEN_VERSION, peer_id, issued_at, nonce)
        signature = self._sign(payload)
        token = f"{TOKEN_VERSION}:{_b64enc(peer_id)}:{issued_at}:{nonce}:{signature}"
        return token

    def verify_pairing_token(self, token: str) -> str:
        """
        Verify a pairing token and return the authenticated *peer_id*.

        Raises
        ------
        TokenInvalidError   — bad structure or wrong signature
        TokenExpiredError   — token has passed its TTL
        TokenReplayError    — this exact token has already been used
        """
        parts = token.split(":")
        if len(parts) != 5:
            raise TokenInvalidError("Malformed pairing token.")

        version, peer_id_b64, issued_at_str, nonce, given_sig = parts

        if version != TOKEN_VERSION:
            raise TokenInvalidError(f"Unsupported token version: {version!r}")

        # Verify signature FIRST (before anything else — timing-safe)
        payload   = self._make_payload(version, _b64dec(peer_id_b64), issued_at_str, nonce)
        expected  = self._sign(payload)
        if not hmac.compare_digest(expected, given_sig):
            raise TokenInvalidError("Token signature is invalid.")

        # Check expiry
        issued_at = int(issued_at_str)
        age = time.time() - issued_at
        if age < 0 or age > self._token_ttl:
            raise TokenExpiredError(
                f"Token expired ({int(age)}s old; TTL is {self._token_ttl}s)."
            )

        # Replay protection
        self._evict_expired_nonces()
        if nonce in self._nonce_store:
            raise TokenReplayError("This token has already been used.")
        self._nonce_store[nonce] = time.time() + NONCE_STORE_TTL

        return _b64dec(peer_id_b64)

    # ------------------------------------------------------------------
    # Allowlist API
    # ------------------------------------------------------------------

    def allow_peer(self, peer_id: str) -> None:
        """Add *peer_id* to the signed allowlist and persist it."""
        sig = self._sign(f"allow:{peer_id}")
        self._allowlist[peer_id] = sig
        self._save_allowlist()
        print(f"[Identity] Peer allowed: {peer_id}")

    def revoke_peer(self, peer_id: str) -> None:
        """Remove *peer_id* from the allowlist."""
        if peer_id not in self._allowlist:
            raise KeyError(f"Peer not in allowlist: {peer_id!r}")
        del self._allowlist[peer_id]
        self._save_allowlist()
        print(f"[Identity] Peer revoked: {peer_id}")

    def is_peer_allowed(self, peer_id: str) -> bool:
        """Return True if *peer_id* is in the allowlist and the entry is untampered."""
        if peer_id not in self._allowlist:
            return False
        expected = self._sign(f"allow:{peer_id}")
        return hmac.compare_digest(expected, self._allowlist[peer_id])

    def assert_peer_allowed(self, peer_id: str) -> None:
        """Raise PeerNotAllowedError if the peer is not in the (verified) allowlist."""
        if not self.is_peer_allowed(peer_id):
            raise PeerNotAllowedError(f"Peer not authorised: {peer_id!r}")

    def list_allowed_peers(self) -> list[str]:
        """Return all allowlisted peer IDs whose signatures are valid."""
        return [p for p in self._allowlist if self.is_peer_allowed(p)]

    # ------------------------------------------------------------------
    # Signing key management
    # ------------------------------------------------------------------

    def rotate_signing_key(self) -> None:
        """
        Generate a new signing key and persist it.
        All previously issued tokens become invalid immediately.
        """
        self._signing_key = secrets.token_bytes(SIGNING_KEY_BYTES)
        self._save_signing_key(self._signing_key)
        # Re-sign allowlist entries with the new key
        self._allowlist = {pid: self._sign(f"allow:{pid}") for pid in self._allowlist}
        self._save_allowlist()
        print("[Identity] Signing key rotated. All previous tokens are now invalid.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sign(self, message: str) -> str:
        return hmac.new(
            self._signing_key,
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _make_payload(version: str, peer_id: str, issued_at: str, nonce: str) -> str:
        return f"{version}|{peer_id}|{issued_at}|{nonce}"

    def _evict_expired_nonces(self) -> None:
        now = time.time()
        self._nonce_store = {n: exp for n, exp in self._nonce_store.items() if exp > now}

    # ------------------------------------------------------------------
    # Signing key persistence
    # ------------------------------------------------------------------

    def _load_or_create_signing_key(self) -> bytes:
        key_file = self._dir / "signing.key"
        if key_file.exists():
            raw = key_file.read_bytes()
            if len(raw) == SIGNING_KEY_BYTES:
                return raw
        # Generate a fresh key
        key = secrets.token_bytes(SIGNING_KEY_BYTES)
        self._save_signing_key(key)
        return key

    def _save_signing_key(self, key: bytes) -> None:
        key_file = self._dir / "signing.key"
        key_file.write_bytes(key)
        # Restrict permissions
        if not _IS_WINDOWS:
            os.chmod(key_file, 0o600)

    # ------------------------------------------------------------------
    # Allowlist persistence
    # ------------------------------------------------------------------

    def _allowlist_path(self) -> Path:
        return self._dir / "allowlist.json"

    def _load_allowlist(self) -> None:
        p = self._allowlist_path()
        if p.exists():
            try:
                data = json.loads(p.read_text("utf-8"))
                # Validate each entry's signature before loading
                self._allowlist = {
                    pid: sig for pid, sig in data.items()
                    if hmac.compare_digest(self._sign(f"allow:{pid}"), sig)
                }
                tampered = len(data) - len(self._allowlist)
                if tampered:
                    print(f"[Identity] WARNING: {tampered} tampered allowlist entries were discarded.")
            except Exception:
                self._allowlist = {}
        else:
            self._allowlist = {}

    def _save_allowlist(self) -> None:
        p = self._allowlist_path()
        p.write_text(json.dumps(self._allowlist, indent=2), encoding="utf-8")
        if not _IS_WINDOWS:
            os.chmod(p, 0o600)

    # ------------------------------------------------------------------
    # Path helper
    # ------------------------------------------------------------------

    @staticmethod
    def _default_dir() -> Path:
        if _IS_WINDOWS:
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path.home() / ".ruby"
        return base / "Ruby" / "security"


# ---------------------------------------------------------------------------
# Base64 helpers (URL-safe, no padding issues)
# ---------------------------------------------------------------------------

import base64 as _base64

def _b64enc(s: str) -> str:
    return _base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")

def _b64dec(s: str) -> str:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return _base64.urlsafe_b64decode(s).decode("utf-8")
