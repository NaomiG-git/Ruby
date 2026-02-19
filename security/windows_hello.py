"""
security/windows_hello.py
-------------------------
Ruby Windows Hello Biometric Vault Unlock

Provides a Windows Hello (fingerprint, face, PIN) prompt to gate access to
the Ruby encrypted vault. On systems where Windows Hello is not available,
falls back gracefully.

How it works:
  1. Ruby's vault is sealed with a DPAPI-protected AES key (see vault.py).
  2. Optionally, you can require a Windows Hello verification step BEFORE
     the vault is unsealed — so even if another process runs as your user,
     it cannot unseal the vault without a biometric challenge.
  3. The challenge is performed via the Windows Runtime (WinRT)
     UserConsentVerifier API, accessed through the `winrt` Python package.

Requirements (Windows only):
    pip install winrt-Windows.Security.Credentials.UI
    pip install winrt-Windows.Foundation

Usage:
    from security.windows_hello import WindowsHello

    hello = WindowsHello()
    if hello.is_available():
        hello.verify(reason="Unlock Ruby vault")  # raises if user cancels/fails
    else:
        print("Windows Hello not available — skipping biometric check.")
"""

import sys
from typing import Optional

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HelloNotAvailableError(Exception):
    """Windows Hello is not configured or not available on this device."""

class HelloVerificationFailedError(Exception):
    """The user cancelled or failed the biometric/PIN verification."""


# ---------------------------------------------------------------------------
# Availability levels (mirrors WinRT UserConsentVerifierAvailability)
# ---------------------------------------------------------------------------

class HelloAvailability:
    AVAILABLE            = "Available"
    DEVICE_BUSY          = "DeviceBusy"
    DEVICE_NOT_PRESENT   = "DeviceNotPresent"
    DISABLED_BY_POLICY   = "DisabledByPolicy"
    NOT_CONFIGURED_FOR_USER = "NotConfiguredForUser"
    UNKNOWN              = "Unknown"


# ---------------------------------------------------------------------------
# WindowsHello
# ---------------------------------------------------------------------------

class WindowsHello:
    """
    Windows Hello biometric verification gate.

    On non-Windows platforms or if the `winrt` package is not installed,
    all methods degrade gracefully (is_available() → False, verify() is a no-op).
    """

    def __init__(self) -> None:
        self._winrt_available = False
        self._ucv = None  # UserConsentVerifier class

        if not _IS_WINDOWS:
            return

        try:
            # winrt Python bindings (pip install winrt-Windows.Security.Credentials.UI)
            from winrt.windows.security.credentials.ui import (
                UserConsentVerifier,
                UserConsentVerifierAvailability,
                UserConsentVerificationResult,
            )
            self._UserConsentVerifier             = UserConsentVerifier
            self._UserConsentVerifierAvailability = UserConsentVerifierAvailability
            self._UserConsentVerificationResult   = UserConsentVerificationResult
            self._winrt_available = True
        except ImportError:
            # Fall back to subprocess-based PowerShell check (lighter weight)
            self._winrt_available = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def availability(self) -> str:
        """
        Return a HelloAvailability string describing whether Windows Hello
        is usable on this device for this user.
        """
        if not _IS_WINDOWS:
            return HelloAvailability.DEVICE_NOT_PRESENT

        if self._winrt_available:
            return self._check_winrt_availability()
        else:
            return self._check_powershell_availability()

    def is_available(self) -> bool:
        """Return True if Windows Hello is available and configured for this user."""
        return self.availability() == HelloAvailability.AVAILABLE

    def verify(self, reason: str = "Authenticate with Ruby") -> None:
        """
        Prompt the user with a Windows Hello biometric/PIN challenge.

        Parameters
        ----------
        reason : str
            The message shown in the Windows Hello dialog.

        Raises
        ------
        HelloNotAvailableError       — Windows Hello is not set up.
        HelloVerificationFailedError — User cancelled or failed verification.
        """
        if not _IS_WINDOWS:
            # Non-Windows: skip silently (development mode)
            return

        avail = self.availability()
        if avail != HelloAvailability.AVAILABLE:
            raise HelloNotAvailableError(
                f"Windows Hello is not available on this device: {avail}. "
                "Please set up a PIN, fingerprint, or face in Windows Settings → Accounts → Sign-in options."
            )

        if self._winrt_available:
            self._verify_winrt(reason)
        else:
            self._verify_powershell(reason)

    # ------------------------------------------------------------------
    # WinRT implementation
    # ------------------------------------------------------------------

    def _check_winrt_availability(self) -> str:
        import asyncio
        try:
            avail = asyncio.run(
                self._UserConsentVerifier.check_availability_async()
            )
            # Map WinRT enum → our string constants
            Avail = self._UserConsentVerifierAvailability
            mapping = {
                Avail.AVAILABLE:                 HelloAvailability.AVAILABLE,
                Avail.DEVICE_BUSY:               HelloAvailability.DEVICE_BUSY,
                Avail.DEVICE_NOT_PRESENT:        HelloAvailability.DEVICE_NOT_PRESENT,
                Avail.DISABLED_BY_POLICY:        HelloAvailability.DISABLED_BY_POLICY,
                Avail.NOT_CONFIGURED_FOR_USER:   HelloAvailability.NOT_CONFIGURED_FOR_USER,
            }
            return mapping.get(avail, HelloAvailability.UNKNOWN)
        except Exception:
            return HelloAvailability.UNKNOWN

    def _verify_winrt(self, reason: str) -> None:
        import asyncio
        try:
            result = asyncio.run(
                self._UserConsentVerifier.request_verification_async(reason)
            )
            Result = self._UserConsentVerificationResult
            if result == Result.VERIFIED:
                return  # success
            elif result == Result.DEVICE_BUSY:
                raise HelloVerificationFailedError("Biometric device is busy. Please try again.")
            elif result == Result.DEVICE_NOT_PRESENT:
                raise HelloNotAvailableError("No biometric device present.")
            elif result == Result.DISABLED_BY_POLICY:
                raise HelloNotAvailableError("Windows Hello is disabled by policy on this device.")
            elif result == Result.NOT_CONFIGURED_FOR_USER:
                raise HelloNotAvailableError(
                    "Windows Hello is not configured for your account. "
                    "Set it up in Settings → Accounts → Sign-in options."
                )
            else:
                # Cancelled, retry limit exceeded, etc.
                raise HelloVerificationFailedError(
                    f"Windows Hello verification was not completed (result: {result}). "
                    "Access to the Ruby vault was denied."
                )
        except (HelloNotAvailableError, HelloVerificationFailedError):
            raise
        except Exception as exc:
            raise HelloVerificationFailedError(f"Windows Hello verification error: {exc}") from exc

    # ------------------------------------------------------------------
    # PowerShell fallback (no winrt package)
    # ------------------------------------------------------------------

    def _check_powershell_availability(self) -> str:
        """Best-effort check via PowerShell if winrt is not installed."""
        try:
            import subprocess
            script = (
                "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
                "$async = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, "
                "ContentType=WindowsRuntime]::CheckAvailabilityAsync(); "
                "$task = [WindowsRuntimeSystemExtensions]::AsTask($async); "
                "$task.Wait(); Write-Output $task.Result"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip()
            if "Available" in output:
                return HelloAvailability.AVAILABLE
            elif "NotConfiguredForUser" in output:
                return HelloAvailability.NOT_CONFIGURED_FOR_USER
            elif "DisabledByPolicy" in output:
                return HelloAvailability.DISABLED_BY_POLICY
            else:
                return HelloAvailability.UNKNOWN
        except Exception:
            return HelloAvailability.UNKNOWN

    def _verify_powershell(self, reason: str) -> None:
        """
        Trigger a Windows Hello prompt via PowerShell (fallback when winrt is unavailable).
        """
        try:
            import subprocess
            safe_reason = reason.replace('"', "'")
            script = (
                "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
                "$async = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, "
                f"ContentType=WindowsRuntime]::RequestVerificationAsync(\\\"{safe_reason}\\\"); "
                "$task = [WindowsRuntimeSystemExtensions]::AsTask($async); "
                "$task.Wait(); Write-Output $task.Result"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=60
            )
            output = result.stdout.strip()
            if output == "Verified":
                return
            elif output in ("Canceled", "RetryLimitExceeded", ""):
                raise HelloVerificationFailedError(
                    "Windows Hello verification was cancelled or failed. "
                    "Access to the Ruby vault was denied."
                )
            else:
                raise HelloVerificationFailedError(f"Unexpected Windows Hello result: {output!r}")
        except (HelloNotAvailableError, HelloVerificationFailedError):
            raise
        except Exception as exc:
            raise HelloVerificationFailedError(f"Windows Hello PowerShell error: {exc}") from exc


# ---------------------------------------------------------------------------
# Convenience guard — use this at vault open time
# ---------------------------------------------------------------------------

def require_hello_if_available(reason: str = "Unlock Ruby vault") -> bool:
    """
    Prompt Windows Hello if available. Returns True if verified (or unavailable).
    Raises HelloVerificationFailedError if the user fails/cancels.

    Designed to be called before Vault._ensure_loaded().
    """
    hello = WindowsHello()
    if hello.is_available():
        hello.verify(reason)
        return True
    return False
