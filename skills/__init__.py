"""
skills/__init__.py
------------------
Ruby – Skills Platform

Provides the @skill_tool decorator, skill loader, and community registry client.

Public API
----------
    from skills import (
        skill_tool,   # decorator
        SkillLoader,  # discover & call tools
        SkillRegistry, # community skill install/uninstall/update
    )

Quick-start
-----------
    from skills import SkillLoader

    loader = SkillLoader()
    loader.load_all()
    schemas = loader.openai_schemas()   # pass to OpenAI functions param
    result  = await loader.call("search_web", query="asyncio tutorial")

Built-in skills location  : skills/builtins/
User-installed skills     : skills/installed/
Community registry        : https://github.com/ruby-ai/skill-registry

CLI commands
------------
    python -m skills install   search_web
    python -m skills uninstall search_web
    python -m skills list
    python -m skills search "weather"
    python -m skills update
"""

from .base     import skill_tool, ToolMetadata, ToolParam, is_skill_tool, get_tool_meta
from .loader   import SkillLoader, LoadedSkill
from .registry import SkillRegistry, RegistryEntry, InstalledSkill

__all__ = [
    "skill_tool",
    "ToolMetadata",
    "ToolParam",
    "is_skill_tool",
    "get_tool_meta",
    "SkillLoader",
    "LoadedSkill",
    "SkillRegistry",
    "RegistryEntry",
    "InstalledSkill",
]
