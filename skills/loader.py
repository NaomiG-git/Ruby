"""
skills/loader.py
----------------
Ruby – Skill Loader

Discovers, loads, and registers all @skill_tool functions from:
  1. Built-in skills bundled with Ruby  (skills/builtins/)
  2. User-installed skills              (skills/installed/)
  3. A custom path specified at runtime

Each skill is a Python package with an __init__.py that exports one or more
functions decorated with @skill_tool.

Loaded skills are exposed to the AI as callable tools via the ModelRouter.

Usage
-----
    from skills.loader import SkillLoader

    loader = SkillLoader()
    loader.load_all()

    # Get OpenAI-compatible tool schemas for all loaded tools
    schemas = loader.openai_schemas()

    # Call a tool by name
    result = await loader.call("search_web", query="Python asyncio")

    # Register with ModelRouter
    loader.register_with_router(router)
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

from .base import ToolMetadata, is_skill_tool, get_tool_meta

logger = logging.getLogger("ruby.skills.loader")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SKILLS_DIR    = Path(__file__).parent
_BUILTINS_DIR  = _SKILLS_DIR / "builtins"
_INSTALLED_DIR = _SKILLS_DIR / "installed"


# ---------------------------------------------------------------------------
# Loaded skill record
# ---------------------------------------------------------------------------

class LoadedSkill:
    """A single @skill_tool function that has been successfully loaded."""

    def __init__(self, fn: Callable, skill_package: str):
        self.fn:     Callable     = fn
        self.meta:   ToolMetadata = fn.__tool_meta__
        self.meta.skill_name = skill_package
        self.package = skill_package
        self.is_async = asyncio.iscoroutinefunction(fn)

    @property
    def name(self) -> str:
        return self.meta.name

    async def call(self, **kwargs) -> Any:
        if self.is_async:
            return await self.fn(**kwargs)
        return await asyncio.get_event_loop().run_in_executor(None, lambda: self.fn(**kwargs))

    def openai_schema(self) -> dict:
        return self.meta.to_openai_schema()

    def gemini_schema(self) -> dict:
        return self.meta.to_gemini_schema()

    def __repr__(self) -> str:
        return f"<LoadedSkill name={self.name!r} package={self.package!r}>"


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------

class SkillLoader:
    """
    Discovers and loads all skill packages.

    Parameters
    ----------
    extra_paths : list[str]
        Additional directories to scan for skill packages.
    """

    def __init__(self, extra_paths: list[str] | None = None):
        self._tools:  dict[str, LoadedSkill] = {}   # tool_name → LoadedSkill
        self._extra_paths = [Path(p) for p in (extra_paths or [])]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> int:
        """Load all skills from all known locations.  Returns count of tools loaded."""
        before = len(self._tools)
        for directory in self._scan_dirs():
            self._load_skill_dir(directory)
        loaded = len(self._tools) - before
        logger.info("[Skills] %d tools loaded from %d directories.", loaded, len(self._scan_dirs()))
        return loaded

    def load_package(self, package_dir: str | Path) -> list[LoadedSkill]:
        """Load a single skill package directory.  Returns list of new LoadedSkill objects."""
        return self._load_skill_dir(Path(package_dir))

    def list_tools(self) -> list[LoadedSkill]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> LoadedSkill | None:
        return self._tools.get(name)

    async def call(self, tool_name: str, **kwargs) -> Any:
        """Invoke a tool by name."""
        skill = self._tools.get(tool_name)
        if not skill:
            raise KeyError(f"Unknown tool: {tool_name!r}")
        logger.debug("[Skills] Calling %s with %s", tool_name, kwargs)
        return await skill.call(**kwargs)

    def openai_schemas(self) -> list[dict]:
        """Return OpenAI function-calling schemas for all loaded tools."""
        return [s.openai_schema() for s in self._tools.values()]

    def gemini_schemas(self) -> list[dict]:
        """Return Gemini function-declaration schemas for all loaded tools."""
        return [s.gemini_schema() for s in self._tools.values()]

    def register_with_router(self, router) -> None:
        """
        Register all tools with a ModelRouter instance.

        Expects `router` to have:
          - router.tools: list[dict]         — OpenAI schemas
          - router.tool_call_handler(name, kwargs) → awaitable
        """
        if hasattr(router, "_skill_loader"):
            router._skill_loader = self
        if hasattr(router, "tools"):
            router.tools = self.openai_schemas()
        logger.info("[Skills] Registered %d tools with router.", len(self._tools))

    def unload(self, tool_name: str) -> bool:
        """Remove a tool by name. Returns True if it was present."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            return True
        return False

    def reload_all(self) -> int:
        """Clear and re-discover all skills."""
        self._tools.clear()
        return self.load_all()

    def status(self) -> dict:
        return {
            "tool_count":  len(self._tools),
            "tool_names":  list(self._tools.keys()),
            "scan_dirs":   [str(d) for d in self._scan_dirs()],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scan_dirs(self) -> list[Path]:
        dirs = [_BUILTINS_DIR, _INSTALLED_DIR] + self._extra_paths
        return [d for d in dirs if d.exists()]

    def _load_skill_dir(self, directory: Path) -> list[LoadedSkill]:
        """Scan *directory* for skill packages and load them."""
        new_skills: list[LoadedSkill] = []
        if not directory.is_dir():
            return new_skills

        for entry in sorted(directory.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").exists():
                new_skills.extend(self._load_package(entry))

        return new_skills

    def _load_package(self, package_path: Path) -> list[LoadedSkill]:
        """Import a package and discover @skill_tool functions."""
        pkg_name = f"skills.{package_path.parent.name}.{package_path.name}"
        skills_found: list[LoadedSkill] = []

        try:
            if pkg_name in sys.modules:
                mod = importlib.reload(sys.modules[pkg_name])
            else:
                spec = importlib.util.spec_from_file_location(
                    pkg_name,
                    str(package_path / "__init__.py"),
                    submodule_search_locations=[str(package_path)],
                )
                mod = importlib.util.module_from_spec(spec)
                sys.modules[pkg_name] = mod
                spec.loader.exec_module(mod)

            for attr_name in dir(mod):
                fn = getattr(mod, attr_name, None)
                if is_skill_tool(fn):
                    meta = get_tool_meta(fn)
                    if meta.name in self._tools:
                        logger.warning(
                            "[Skills] Duplicate tool name %r — skipping %s",
                            meta.name, pkg_name,
                        )
                        continue
                    skill = LoadedSkill(fn, skill_package=package_path.name)
                    self._tools[skill.name] = skill
                    skills_found.append(skill)
                    logger.info("[Skills] Loaded tool %r from %s", skill.name, pkg_name)

        except Exception as exc:
            logger.error("[Skills] Failed to load %s: %s", package_path, exc)

        return skills_found
