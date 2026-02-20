"""
skills/registry.py
------------------
Ruby – Skill Registry

Community skill registry client.  Supports:
  - Browsing the official Ruby skill registry (GitHub-based index)
  - Installing skills from the registry or from a Git URL
  - Uninstalling skills
  - Listing installed skills
  - Checking for updates
  - Vault-stored install manifest

CLI usage (via __main__ entry):
    python -m skills install search_web
    python -m skills install https://github.com/alice/ruby_weather_skill
    python -m skills uninstall search_web
    python -m skills list
    python -m skills search "email"
    python -m skills update

Registry format
---------------
The official index lives at REGISTRY_URL (a JSON file):
    [
      {
        "name": "search_web",
        "description": "Search the web using DuckDuckGo.",
        "author": "ruby-core",
        "git_url": "https://github.com/ruby-ai/skill-search-web",
        "version": "1.0.0",
        "tags": ["search", "web"]
      },
      ...
    ]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ruby.skills.registry")

REGISTRY_URL  = "https://raw.githubusercontent.com/ruby-ai/skill-registry/main/index.json"
INSTALLED_DIR = Path(__file__).parent / "installed"
MANIFEST_KEY  = "skill_manifest"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RegistryEntry:
    name:        str
    description: str
    author:      str
    git_url:     str
    version:     str = ""
    tags:        list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "RegistryEntry":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            author=d.get("author", ""),
            git_url=d.get("git_url", ""),
            version=d.get("version", ""),
            tags=d.get("tags", []),
        )


@dataclass
class InstalledSkill:
    name:      str
    git_url:   str
    version:   str
    installed: str   # ISO datetime string

    @classmethod
    def from_dict(cls, d: dict) -> "InstalledSkill":
        return cls(**d)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """
    Community skill registry client.

    Parameters
    ----------
    vault     : Vault | None  — for persisting install manifest
    loader    : SkillLoader | None — auto-reload after install/uninstall
    """

    def __init__(self, vault=None, loader=None):
        self._vault  = vault
        self._loader = loader
        INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
        self._manifest: dict[str, InstalledSkill] = {}
        self._load_manifest()

    # ------------------------------------------------------------------
    # Registry browsing
    # ------------------------------------------------------------------

    async def fetch_index(self) -> list[RegistryEntry]:
        """Download the official registry index."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(REGISTRY_URL)
                resp.raise_for_status()
                data = resp.json()
                return [RegistryEntry.from_dict(e) for e in data]
        except Exception as exc:
            logger.warning("[Registry] Could not fetch index: %s", exc)
            return []

    async def search(self, query: str) -> list[RegistryEntry]:
        """Search registry by name, description, or tags."""
        index = await self.fetch_index()
        q = query.lower()
        return [
            e for e in index
            if q in e.name.lower()
            or q in e.description.lower()
            or any(q in t.lower() for t in e.tags)
        ]

    async def find(self, name: str) -> Optional[RegistryEntry]:
        """Find an exact entry by skill name."""
        index = await self.fetch_index()
        for e in index:
            if e.name == name:
                return e
        return None

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    async def install(self, name_or_url: str) -> bool:
        """
        Install a skill by registry name or Git URL.
        Returns True on success.
        """
        git_url = name_or_url if "://" in name_or_url or name_or_url.startswith("git@") else None

        if git_url is None:
            entry = await self.find(name_or_url)
            if not entry:
                logger.error("[Registry] Skill %r not found in registry.", name_or_url)
                return False
            git_url  = entry.git_url
            pkg_name = entry.name
            version  = entry.version
        else:
            pkg_name = name_or_url.rstrip("/").split("/")[-1].replace(".git", "")
            version  = "git"

        dest = INSTALLED_DIR / pkg_name
        if dest.exists():
            logger.info("[Registry] Updating existing skill: %s", pkg_name)
            ok = self._git_pull(dest)
        else:
            logger.info("[Registry] Installing skill %s from %s", pkg_name, git_url)
            ok = self._git_clone(git_url, dest)

        if ok:
            self._install_requirements(dest)
            from datetime import datetime, timezone
            self._manifest[pkg_name] = InstalledSkill(
                name=pkg_name, git_url=git_url, version=version,
                installed=datetime.now(timezone.utc).isoformat(),
            )
            self._save_manifest()
            if self._loader:
                self._loader.load_package(dest)
            logger.info("[Registry] ✓ Installed: %s", pkg_name)

        return ok

    # ------------------------------------------------------------------
    # Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, name: str) -> bool:
        dest = INSTALLED_DIR / name
        if not dest.exists():
            logger.warning("[Registry] Skill not installed: %s", name)
            return False
        shutil.rmtree(dest)
        self._manifest.pop(name, None)
        self._save_manifest()
        if self._loader:
            # Remove all tools from this skill package
            to_remove = [
                skill.name for skill in self._loader.list_tools()
                if skill.package == name
            ]
            for tool_name in to_remove:
                self._loader.unload(tool_name)
        logger.info("[Registry] Uninstalled: %s", name)
        return True

    # ------------------------------------------------------------------
    # Update all
    # ------------------------------------------------------------------

    async def update_all(self) -> dict[str, bool]:
        """Pull the latest version of every installed skill.  Returns {name: ok}."""
        results: dict[str, bool] = {}
        for name in list(self._manifest):
            dest = INSTALLED_DIR / name
            if dest.exists():
                ok = self._git_pull(dest)
                if ok:
                    self._install_requirements(dest)
                    if self._loader:
                        self._loader.load_package(dest)
                results[name] = ok
        self._save_manifest()
        return results

    # ------------------------------------------------------------------
    # List installed
    # ------------------------------------------------------------------

    def list_installed(self) -> list[InstalledSkill]:
        return list(self._manifest.values())

    def is_installed(self, name: str) -> bool:
        return name in self._manifest

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _git_clone(url: str, dest: Path) -> bool:
        try:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)],
                check=True, capture_output=True, text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error("[Registry] git clone failed: %s", e.stderr.strip())
            return False
        except FileNotFoundError:
            logger.error("[Registry] git not found on PATH.")
            return False

    @staticmethod
    def _git_pull(dest: Path) -> bool:
        try:
            subprocess.run(
                ["git", "pull"], cwd=str(dest),
                check=True, capture_output=True, text=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            logger.error("[Registry] git pull failed: %s", e.stderr.strip())
            return False

    @staticmethod
    def _install_requirements(dest: Path) -> None:
        req = dest / "requirements.txt"
        if req.exists():
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                    check=True, capture_output=True,
                )
                logger.info("[Registry] Installed requirements for %s", dest.name)
            except subprocess.CalledProcessError as e:
                logger.warning("[Registry] pip install warning for %s: %s", dest.name, e)

    # ------------------------------------------------------------------
    # Manifest persistence
    # ------------------------------------------------------------------

    def _load_manifest(self) -> None:
        if self._vault:
            raw = self._vault.get(MANIFEST_KEY)
            if raw:
                for k, v in (raw if isinstance(raw, dict) else {}).items():
                    self._manifest[k] = InstalledSkill.from_dict(v)
        else:
            mf = INSTALLED_DIR / ".manifest.json"
            if mf.exists():
                with open(mf) as f:
                    data = json.load(f)
                for k, v in data.items():
                    self._manifest[k] = InstalledSkill.from_dict(v)

    def _save_manifest(self) -> None:
        data = {k: v.to_dict() for k, v in self._manifest.items()}
        if self._vault:
            self._vault.set(MANIFEST_KEY, data)
        else:
            mf = INSTALLED_DIR / ".manifest.json"
            with open(mf, "w") as f:
                json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point:  python -m skills <command>
# ---------------------------------------------------------------------------

async def _cli(args: list[str]) -> None:
    registry = SkillRegistry()
    from .loader import SkillLoader
    loader = SkillLoader()
    loader.load_all()
    registry._loader = loader

    cmd = args[0] if args else "help"

    if cmd == "install" and len(args) >= 2:
        ok = await registry.install(args[1])
        print("✓ Installed" if ok else "✗ Failed")

    elif cmd == "uninstall" and len(args) >= 2:
        ok = registry.uninstall(args[1])
        print("✓ Uninstalled" if ok else "✗ Not installed")

    elif cmd == "list":
        skills = registry.list_installed()
        if not skills:
            print("No skills installed.")
        for s in skills:
            print(f"  {s.name:30s}  {s.version:10s}  {s.installed[:10]}")

    elif cmd == "search" and len(args) >= 2:
        results = await registry.search(" ".join(args[1:]))
        for e in results:
            installed = "✓" if registry.is_installed(e.name) else " "
            print(f"  [{installed}] {e.name:30s}  {e.description}")
        if not results:
            print("No results found.")

    elif cmd == "update":
        results = await registry.update_all()
        for name, ok in results.items():
            print(f"  {'✓' if ok else '✗'} {name}")

    else:
        print(
            "Usage: python -m skills <command> [args]\n"
            "  install   <name|git_url>  — install a skill\n"
            "  uninstall <name>          — remove a skill\n"
            "  list                      — show installed skills\n"
            "  search    <query>         — search registry\n"
            "  update                    — update all installed skills\n"
        )


if __name__ == "__main__":
    asyncio.run(_cli(sys.argv[1:]))
