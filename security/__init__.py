"""
security/
---------
Ruby Security Module

Provides encrypted credential storage, cryptographic peer identity
verification, biometric vault unlock, and a security audit CLI.

Quick start:
    from security.vault        import Vault
    from security.identity     import IdentityManager
    from security.windows_hello import WindowsHello, require_hello_if_available
    from security.audit        import SecurityAudit

Modules
-------
vault.py         — AES-256-GCM encrypted credential vault (Windows DPAPI or PBKDF2)
identity.py      — HMAC-SHA256 signed pairing tokens + peer allowlist
windows_hello.py — Windows Hello biometric / PIN vault unlock
audit.py         — Security audit CLI (ruby security audit [--deep] [--fix] [--json])

CLI usage:
    python -m security.audit
    python -m security.audit --deep --fix --json
"""

from .vault         import Vault, VaultError
from .identity      import (
    IdentityManager,
    IdentityError,
    TokenExpiredError,
    TokenReplayError,
    TokenInvalidError,
    PeerNotAllowedError,
)
from .windows_hello import (
    WindowsHello,
    HelloAvailability,
    HelloNotAvailableError,
    HelloVerificationFailedError,
    require_hello_if_available,
)
from .audit import SecurityAudit, AuditReport, Finding, Severity

__all__ = [
    # Vault
    "Vault",
    "VaultError",
    # Identity
    "IdentityManager",
    "IdentityError",
    "TokenExpiredError",
    "TokenReplayError",
    "TokenInvalidError",
    "PeerNotAllowedError",
    # Windows Hello
    "WindowsHello",
    "HelloAvailability",
    "HelloNotAvailableError",
    "HelloVerificationFailedError",
    "require_hello_if_available",
    # Audit
    "SecurityAudit",
    "AuditReport",
    "Finding",
    "Severity",
]
