"""
security/audit.py
-----------------
Ruby Security Audit CLI Tool

Scans Ruby's configuration, vault, allowlists, and file permissions for
security risks and misconfigurations. Inspired by `openclaw security audit`
but extended with Windows-specific checks and auto-fix support.

Usage (command line):
    python -m security.audit
    python -m security.audit --deep
    python -m security.audit --fix
    python -m security.audit --json
    python -m security.audit --deep --fix --json

Usage (programmatic):
    from security.audit import SecurityAudit
    report = SecurityAudit().run(deep=True, fix=False)
    print(report.summary())
"""

import argparse
import json
import os
import sys
import stat
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
import time

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class Severity:
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    INFO     = "INFO"

_SEVERITY_ORDER = {
    Severity.CRITICAL: 0,
    Severity.HIGH:     1,
    Severity.MEDIUM:   2,
    Severity.LOW:      3,
    Severity.INFO:     4,
}

_SEVERITY_COLOUR = {
    Severity.CRITICAL: "\033[91m",  # bright red
    Severity.HIGH:     "\033[31m",  # red
    Severity.MEDIUM:   "\033[33m",  # yellow
    Severity.LOW:      "\033[34m",  # blue
    Severity.INFO:     "\033[32m",  # green
}
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    check_id:    str
    severity:    str
    title:       str
    description: str
    fix:         Optional[str] = None       # human-readable fix suggestion
    auto_fixed:  bool          = False      # set to True if --fix resolved it

@dataclass
class AuditReport:
    timestamp:     str
    ruby_version:  str
    platform:      str
    findings:      list[Finding] = field(default_factory=list)
    fixed_count:   int           = 0

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def summary(self) -> str:
        counts = {s: 0 for s in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        lines = [
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "  Ruby Security Audit Report",
            f"  {self.timestamp}  |  {self.platform}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for finding in sorted(self.findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99)):
            colour = _SEVERITY_COLOUR.get(finding.severity, "")
            fixed_tag = " ✔ AUTO-FIXED" if finding.auto_fixed else ""
            lines.append(f"  {colour}[{finding.severity}]{_RESET}  {finding.check_id}: {finding.title}{fixed_tag}")
            lines.append(f"         {finding.description}")
            if finding.fix and not finding.auto_fixed:
                lines.append(f"         → Fix: {finding.fix}")
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  CRITICAL:{counts[Severity.CRITICAL]}  HIGH:{counts[Severity.HIGH]}  "
            f"MEDIUM:{counts[Severity.MEDIUM]}  LOW:{counts[Severity.LOW]}  INFO:{counts[Severity.INFO]}",
            f"  Auto-fixed: {self.fixed_count} issue(s)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def has_critical_or_high(self) -> bool:
        return any(f.severity in (Severity.CRITICAL, Severity.HIGH) for f in self.findings)


# ---------------------------------------------------------------------------
# SecurityAudit
# ---------------------------------------------------------------------------

class SecurityAudit:
    """
    Runs a suite of security checks against Ruby's installation.

    Parameters
    ----------
    ruby_root : Path | None
        Ruby installation root. Defaults to the directory containing
        this file's parent (i.e. the repo root).
    """

    def __init__(self, ruby_root: Optional[Path] = None):
        self._root = Path(ruby_root) if ruby_root else Path(__file__).resolve().parent.parent
        if _IS_WINDOWS:
            self._data_dir = Path(os.environ.get("APPDATA", Path.home())) / "Ruby"
        else:
            self._data_dir = Path.home() / ".ruby" / "Ruby"

    def run(self, deep: bool = False, fix: bool = False) -> AuditReport:
        import platform as _platform
        report = AuditReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            ruby_version=self._get_ruby_version(),
            platform=_platform.platform(),
        )

        # Run all checks
        self._check_vault(report, fix)
        self._check_signing_key(report, fix)
        self._check_allowlist(report, fix)
        self._check_env_secrets(report, fix)
        self._check_plaintext_credentials(report, fix)
        self._check_dpapi(report)

        if deep:
            self._check_file_permissions(report, fix)
            self._check_windows_acls(report, fix)
            self._check_pywin32(report)
            self._check_dependency_versions(report)

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_vault(self, report: AuditReport, fix: bool) -> None:
        vault_file = self._data_dir / "vault" / "vault.enc"
        if not vault_file.exists():
            report.add(Finding(
                check_id="VAULT-001",
                severity=Severity.HIGH,
                title="Vault not initialised",
                description="No encrypted vault found. Credentials may be stored in plaintext elsewhere.",
                fix="Run Ruby once to auto-create the vault, or call Vault() from security.vault.",
            ))
        else:
            # Verify magic bytes
            try:
                raw = vault_file.read_bytes()
                if raw[:4] != b"RUBV":
                    report.add(Finding(
                        check_id="VAULT-002",
                        severity=Severity.CRITICAL,
                        title="Vault file is corrupt or tampered",
                        description=f"Expected magic bytes 'RUBV', got {raw[:4]!r}.",
                        fix="Restore vault from backup or reinitialise.",
                    ))
                else:
                    report.add(Finding(
                        check_id="VAULT-003",
                        severity=Severity.INFO,
                        title="Encrypted vault present",
                        description=f"Vault file found at {vault_file} with valid header.",
                    ))
            except Exception as e:
                report.add(Finding(
                    check_id="VAULT-002",
                    severity=Severity.HIGH,
                    title="Could not read vault file",
                    description=str(e),
                ))

    def _check_signing_key(self, report: AuditReport, fix: bool) -> None:
        key_file = self._data_dir / "security" / "signing.key"
        if not key_file.exists():
            report.add(Finding(
                check_id="ID-001",
                severity=Severity.MEDIUM,
                title="Identity signing key not found",
                description="No signing.key file found. Pairing tokens cannot be verified.",
                fix="Initialise IdentityManager() to auto-generate a signing key.",
            ))
            return

        size = key_file.stat().st_size
        if size != 32:
            report.add(Finding(
                check_id="ID-002",
                severity=Severity.HIGH,
                title="Signing key has unexpected size",
                description=f"Expected 32 bytes, got {size}. The key may be truncated or corrupt.",
                fix="Delete signing.key and let IdentityManager regenerate it.",
            ))
        else:
            report.add(Finding(
                check_id="ID-003",
                severity=Severity.INFO,
                title="Identity signing key present",
                description=f"signing.key found ({size} bytes).",
            ))

        # Check file permissions (Unix only)
        if not _IS_WINDOWS:
            mode = key_file.stat().st_mode & 0o777
            if mode != 0o600:
                auto_fixed = False
                if fix:
                    try:
                        os.chmod(key_file, 0o600)
                        auto_fixed = True
                        report.fixed_count += 1
                    except Exception:
                        pass
                report.add(Finding(
                    check_id="ID-004",
                    severity=Severity.HIGH,
                    title="Signing key has insecure permissions",
                    description=f"signing.key has mode {oct(mode)}, expected 0o600.",
                    fix="Run: chmod 600 signing.key",
                    auto_fixed=auto_fixed,
                ))

    def _check_allowlist(self, report: AuditReport, fix: bool) -> None:
        allowlist_file = self._data_dir / "security" / "allowlist.json"
        if not allowlist_file.exists():
            report.add(Finding(
                check_id="AL-001",
                severity=Severity.INFO,
                title="No allowlist found",
                description="Peer allowlist has not been created yet. All inbound connections will be blocked by default.",
            ))
            return

        try:
            data = json.loads(allowlist_file.read_text("utf-8"))
            report.add(Finding(
                check_id="AL-002",
                severity=Severity.INFO,
                title=f"Allowlist contains {len(data)} peer(s)",
                description="Run `IdentityManager().list_allowed_peers()` for HMAC-verified entries.",
            ))
        except Exception as e:
            report.add(Finding(
                check_id="AL-003",
                severity=Severity.HIGH,
                title="Allowlist file is corrupt",
                description=str(e),
                fix="Delete allowlist.json and re-add peers via IdentityManager().allow_peer().",
            ))

    def _check_env_secrets(self, report: AuditReport, fix: bool) -> None:
        """Warn if secret-looking env vars are set (they survive process leaks)."""
        risky = [k for k in os.environ if any(
            kw in k.upper() for kw in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        )]
        if risky:
            report.add(Finding(
                check_id="ENV-001",
                severity=Severity.MEDIUM,
                title=f"{len(risky)} secret-looking environment variable(s) set",
                description=f"Variables: {', '.join(risky[:8])}{'...' if len(risky) > 8 else ''}. "
                            "Env vars can be read by child processes and logging tools.",
                fix="Move secrets to the encrypted vault instead of environment variables.",
            ))
        else:
            report.add(Finding(
                check_id="ENV-002",
                severity=Severity.INFO,
                title="No secret env vars detected",
                description="No TOKEN/KEY/SECRET/PASSWORD environment variables found in the current process.",
            ))

    def _check_plaintext_credentials(self, report: AuditReport, fix: bool) -> None:
        """Scan common config files for plaintext secrets."""
        suspect_files = [
            self._root / "config.json",
            self._root / "config.yaml",
            self._root / "config.yml",
            self._root / ".env",
            self._root / "settings.py",
            self._root / "settings.json",
        ]
        keywords = ["api_key", "api_secret", "access_token", "password", "client_secret"]
        found_in = []
        for f in suspect_files:
            if f.exists():
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore").lower()
                    if any(kw in text for kw in keywords):
                        found_in.append(f.name)
                except Exception:
                    pass

        if found_in:
            report.add(Finding(
                check_id="PT-001",
                severity=Severity.HIGH,
                title="Possible plaintext secrets in config files",
                description=f"Secret-looking keys found in: {', '.join(found_in)}",
                fix="Move all secrets to the encrypted vault (security.vault.Vault).",
            ))
        else:
            report.add(Finding(
                check_id="PT-002",
                severity=Severity.INFO,
                title="No plaintext secrets found in config files",
                description="Scanned common config files — no obvious plaintext credentials detected.",
            ))

    def _check_dpapi(self, report: AuditReport) -> None:
        if not _IS_WINDOWS:
            report.add(Finding(
                check_id="DPAPI-001",
                severity=Severity.INFO,
                title="DPAPI not applicable",
                description="Windows DPAPI is only available on Windows. Using PBKDF2 fallback.",
            ))
            return

        try:
            import win32crypt  # noqa: F401
            report.add(Finding(
                check_id="DPAPI-002",
                severity=Severity.INFO,
                title="Windows DPAPI available",
                description="pywin32 is installed. Vault will use DPAPI for automatic key protection.",
            ))
        except ImportError:
            report.add(Finding(
                check_id="DPAPI-003",
                severity=Severity.HIGH,
                title="pywin32 not installed — DPAPI unavailable",
                description="The vault will fall back to PBKDF2 key derivation, requiring a passphrase.",
                fix="Run: pip install pywin32",
            ))

    # ------------------------------------------------------------------
    # Deep checks
    # ------------------------------------------------------------------

    def _check_file_permissions(self, report: AuditReport, fix: bool) -> None:
        if _IS_WINDOWS:
            return  # handled by _check_windows_acls
        sensitive = [
            self._data_dir / "vault" / "vault.enc",
            self._data_dir / "vault" / ".dpapi_key",
            self._data_dir / "security" / "signing.key",
            self._data_dir / "security" / "allowlist.json",
        ]
        for f in sensitive:
            if not f.exists():
                continue
            mode = f.stat().st_mode & 0o777
            if mode not in (0o600, 0o400):
                auto_fixed = False
                if fix:
                    try:
                        os.chmod(f, 0o600)
                        auto_fixed = True
                        report.fixed_count += 1
                    except Exception:
                        pass
                report.add(Finding(
                    check_id="PERM-001",
                    severity=Severity.HIGH,
                    title=f"Insecure permissions on {f.name}",
                    description=f"{f} has mode {oct(mode)}, should be 0o600.",
                    fix=f"Run: chmod 600 \"{f}\"",
                    auto_fixed=auto_fixed,
                ))

    def _check_windows_acls(self, report: AuditReport, fix: bool) -> None:
        if not _IS_WINDOWS:
            return
        vault_dir = self._data_dir / "vault"
        if not vault_dir.exists():
            return
        report.add(Finding(
            check_id="ACL-001",
            severity=Severity.INFO,
            title="Windows ACL check",
            description=(
                f"Vault directory: {vault_dir}. "
                "Verify that only your user account has access via: "
                f"icacls \"{vault_dir}\""
            ),
            fix=f'icacls "{vault_dir}" /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F"',
        ))

    def _check_pywin32(self, report: AuditReport) -> None:
        if not _IS_WINDOWS:
            return
        try:
            import win32api
            ver = win32api.GetFileVersionInfo(
                sys.executable, "\\StringFileInfo\\040904B0\\ProductVersion"
            )
            report.add(Finding(
                check_id="DEP-WIN32",
                severity=Severity.INFO,
                title="pywin32 installed",
                description=f"Version info: {ver}",
            ))
        except Exception:
            pass

    def _check_dependency_versions(self, report: AuditReport) -> None:
        checks = {
            "cryptography": "41.0.0",
        }
        for pkg, min_ver in checks.items():
            try:
                import importlib.metadata
                installed = importlib.metadata.version(pkg)
                from packaging.version import Version
                if Version(installed) < Version(min_ver):
                    report.add(Finding(
                        check_id=f"DEP-{pkg.upper()}",
                        severity=Severity.MEDIUM,
                        title=f"{pkg} is outdated",
                        description=f"Installed: {installed}, minimum recommended: {min_ver}.",
                        fix=f"Run: pip install --upgrade {pkg}",
                    ))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_ruby_version(self) -> str:
        ver_file = self._root / "VERSION"
        if ver_file.exists():
            return ver_file.read_text().strip()
        return "unknown"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ruby security audit",
        description="Ruby Security Audit Tool — scans for risks and misconfigurations.",
    )
    parser.add_argument("--deep",  action="store_true", help="Run additional deep checks (file permissions, dependencies).")
    parser.add_argument("--fix",   action="store_true", help="Automatically fix issues where possible.")
    parser.add_argument("--json",  action="store_true", help="Output results in JSON format.")
    args = parser.parse_args()

    audit  = SecurityAudit()
    report = audit.run(deep=args.deep, fix=args.fix)

    if args.json:
        print(report.to_json())
    else:
        print(report.summary())

    # Exit with non-zero code if critical/high findings remain unfixed
    unfixed_serious = [
        f for f in report.findings
        if f.severity in (Severity.CRITICAL, Severity.HIGH) and not f.auto_fixed
    ]
    sys.exit(1 if unfixed_serious else 0)


if __name__ == "__main__":
    main()
