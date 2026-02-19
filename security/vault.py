"""
security/vault.py
-----------------
Ruby Encrypted Credential Vault

Stores all secrets (OAuth tokens, channel credentials, session tokens) using
AES-256-GCM encryption. On Windows, the vault master key is protected by
Windows DPAPI so it unlocks automatically for the logged-in user — no master
password required. On non-Windows systems, falls back to PBKDF2-based key
derivation with a user-supplied passphrase.

Storage location: %APPDATA%\\Ruby\\vault\\vault.enc  (Windows)
                  ~/.ruby/vault/vault.enc             (fallback)

Usage:
    from security.vault import Vault

    vault = Vault()
    vault.store("gmail_oauth_token", "ya29.xxxxx")
    token = vault.retrieve("gmail_oauth_token")
    vault.delete("gmail_oauth_token")
    print(vault.list_keys())
    vault.rotate_key()   # re-encrypts vault under a fresh key
"""

import json
import os
import sys
import secrets
import struct
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    try:
        import win32crypt  # pywin32
        _DPAPI_AVAILABLE = True
    except ImportError:
        _DPAPI_AVAILABLE = False
else:
    _DPAPI_AVAILABLE = False


# ---------------------------------------------------------------------------
# File format constants
# ---------------------------------------------------------------------------
# vault.enc binary layout:
#   [4 bytes] magic "RUBV"
#   [2 bytes] version (little-endian uint16)  → currently 1
#   [1 byte]  key_mode: 0=DPAPI, 1=PBKDF2
#   [32 bytes] wrapped_key  (DPAPI-protected AES key, or PBKDF2 salt)
#   [12 bytes] nonce (GCM)
#   [N bytes]  ciphertext  (GCM-encrypted JSON payload)
#   [16 bytes] GCM auth tag  (appended by AESGCM)

MAGIC = b"RUBV"
VERSION = 1
KEY_MODE_DPAPI  = 0
KEY_MODE_PBKDF2 = 1

PBKDF2_ITERATIONS = 600_000


# ---------------------------------------------------------------------------
# Vault
# ---------------------------------------------------------------------------

class VaultError(Exception):
    """Raised for any vault operation failure."""


class Vault:
    """
    Ruby encrypted credential vault.

    Parameters
    ----------
    vault_path : str | Path | None
        Override the default vault file location.
    passphrase : str | None
        Required when DPAPI is unavailable (non-Windows or pywin32 missing).
        Ignored on Windows where DPAPI is used automatically.
    """

    def __init__(
        self,
        vault_path: Optional[Path] = None,
        passphrase: Optional[str] = None,
    ):
        self._path = Path(vault_path) if vault_path else self._default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._passphrase = passphrase

        # In-memory state — loaded on first access
        self._data: Optional[dict] = None
        self._aes_key: Optional[bytes] = None
        self._key_mode: int = KEY_MODE_DPAPI if _DPAPI_AVAILABLE else KEY_MODE_PBKDF2
        self._wrapped_key_or_salt: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, key: str, value: str) -> None:
        """Encrypt and store a credential. Overwrites any existing value."""
        self._ensure_loaded()
        self._data[key] = value
        self._save()

    def retrieve(self, key: str) -> str:
        """Return the decrypted value for *key*. Raises KeyError if not found."""
        self._ensure_loaded()
        if key not in self._data:
            raise KeyError(f"No credential stored for key: {key!r}")
        return self._data[key]

    def delete(self, key: str) -> None:
        """Remove a credential from the vault."""
        self._ensure_loaded()
        if key not in self._data:
            raise KeyError(f"No credential stored for key: {key!r}")
        del self._data[key]
        self._save()

    def list_keys(self) -> list[str]:
        """Return all stored credential keys (names only — values stay encrypted)."""
        self._ensure_loaded()
        return list(self._data.keys())

    def rotate_key(self) -> None:
        """
        Re-encrypt the vault under a brand-new AES key.
        Old key material is overwritten on disk immediately.
        """
        self._ensure_loaded()
        # Generate a fresh key and forget the old one
        self._aes_key = secrets.token_bytes(32)
        if self._key_mode == KEY_MODE_DPAPI:
            self._wrapped_key_or_salt = self._dpapi_protect(self._aes_key)
        else:
            self._wrapped_key_or_salt = secrets.token_bytes(32)  # new salt
        self._save()
        print("[Vault] Key rotation complete. Vault re-encrypted with a new key.")

    def is_locked(self) -> bool:
        """Return True if the vault file exists but has not been decrypted yet."""
        return self._path.exists() and self._data is None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load and decrypt the vault from disk if not already in memory."""
        if self._data is not None:
            return
        if self._path.exists():
            self._load()
        else:
            self._initialise_new_vault()

    def _initialise_new_vault(self) -> None:
        """Create a brand-new empty vault with a fresh AES key."""
        self._aes_key = secrets.token_bytes(32)
        if self._key_mode == KEY_MODE_DPAPI:
            self._wrapped_key_or_salt = self._dpapi_protect(self._aes_key)
        else:
            if not self._passphrase:
                raise VaultError(
                    "A passphrase is required to initialise the vault on non-Windows systems."
                )
            self._wrapped_key_or_salt = secrets.token_bytes(32)  # salt
            self._aes_key = self._pbkdf2_key(self._passphrase, self._wrapped_key_or_salt)
        self._data = {}
        self._save()
        # Secure the vault directory
        if _IS_WINDOWS:
            self._set_windows_acl(self._path.parent)

    def _load(self) -> None:
        """Read, verify, and decrypt the vault file."""
        raw = self._path.read_bytes()

        # Parse header
        if len(raw) < 4 + 2 + 1 + 32 + 12 + 16:
            raise VaultError("Vault file is too small — it may be corrupt.")
        if raw[:4] != MAGIC:
            raise VaultError("Vault file has an unrecognised format (bad magic bytes).")

        offset = 4
        (version,) = struct.unpack_from("<H", raw, offset); offset += 2
        if version != VERSION:
            raise VaultError(f"Unsupported vault version: {version}")

        (key_mode,) = struct.unpack_from("<B", raw, offset); offset += 1
        self._key_mode = key_mode

        wrapped = raw[offset: offset + 32]; offset += 32
        self._wrapped_key_or_salt = wrapped

        nonce = raw[offset: offset + 12]; offset += 12
        ciphertext_with_tag = raw[offset:]

        # Recover the AES key
        if key_mode == KEY_MODE_DPAPI:
            if not _DPAPI_AVAILABLE:
                raise VaultError(
                    "This vault was created with Windows DPAPI but pywin32 is not installed."
                )
            self._aes_key = self._dpapi_unprotect(wrapped)
        else:
            if not self._passphrase:
                raise VaultError("A passphrase is required to unlock this vault.")
            self._aes_key = self._pbkdf2_key(self._passphrase, wrapped)

        # Decrypt
        try:
            aesgcm = AESGCM(self._aes_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        except Exception as exc:
            raise VaultError("Vault decryption failed — wrong key or corrupt data.") from exc

        self._data = json.loads(plaintext.decode("utf-8"))

    def _save(self) -> None:
        """Encrypt the in-memory data and write to disk atomically."""
        nonce = secrets.token_bytes(12)
        aesgcm = AESGCM(self._aes_key)
        plaintext = json.dumps(self._data, separators=(",", ":")).encode("utf-8")
        ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext, None)

        header = (
            MAGIC
            + struct.pack("<H", VERSION)
            + struct.pack("<B", self._key_mode)
            + self._wrapped_key_or_salt
        )

        # Write to a temp file, then atomically rename
        tmp = self._path.with_suffix(".enc.tmp")
        tmp.write_bytes(header + nonce + ciphertext_with_tag)
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # DPAPI helpers (Windows only)
    # ------------------------------------------------------------------

    @staticmethod
    def _dpapi_protect(data: bytes) -> bytes:
        """Encrypt *data* with the current Windows user's DPAPI key. Returns up to 32 bytes stored."""
        if not _DPAPI_AVAILABLE:
            raise VaultError("DPAPI is not available.")
        encrypted = win32crypt.CryptProtectData(data, "Ruby Vault Key", None, None, None, 0)
        # Store the length-prefixed DPAPI blob (variable length; pad/trim to 32 won't work —
        # we store the full blob separately and keep 32 bytes as a pointer)
        # Instead: write the full blob to a sidecar file; store a 32-byte hash as the "wrapped" field.
        sidecar = _dpapi_sidecar_path()
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_bytes(encrypted)
        import hashlib
        return hashlib.sha256(encrypted).digest()  # 32-byte fingerprint stored in vault header

    @staticmethod
    def _dpapi_unprotect(fingerprint: bytes) -> bytes:
        """Recover the AES key from the DPAPI sidecar file."""
        if not _DPAPI_AVAILABLE:
            raise VaultError("DPAPI is not available.")
        sidecar = _dpapi_sidecar_path()
        if not sidecar.exists():
            raise VaultError("DPAPI sidecar key file is missing. Vault cannot be unlocked.")
        blob = sidecar.read_bytes()
        aes_key, _ = win32crypt.CryptUnprotectData(blob, None, None, None, 0)
        return aes_key

    # ------------------------------------------------------------------
    # PBKDF2 helper (non-Windows fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def _pbkdf2_key(passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    # ------------------------------------------------------------------
    # Paths & permissions
    # ------------------------------------------------------------------

    @staticmethod
    def _default_path() -> Path:
        if _IS_WINDOWS:
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:
            base = Path.home() / ".ruby"
        return base / "Ruby" / "vault" / "vault.enc"

    @staticmethod
    def _set_windows_acl(directory: Path) -> None:
        """Restrict vault directory to the current user only (best-effort)."""
        try:
            import subprocess
            username = os.environ.get("USERNAME", "")
            if username:
                subprocess.run(
                    ["icacls", str(directory), "/inheritance:r",
                     "/grant:r", f"{username}:(OI)(CI)F"],
                    check=True, capture_output=True
                )
        except Exception:
            pass  # Non-fatal if ACL fails


def _dpapi_sidecar_path() -> Path:
    if _IS_WINDOWS:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".ruby"
    return base / "Ruby" / "vault" / ".dpapi_key"
