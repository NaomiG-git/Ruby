"""
skills/base.py
--------------
Ruby – Skills Platform: Base Decorator & Tool Metadata

Provides the @skill_tool decorator used by all skill implementations.
Decorated functions carry metadata (name, description, parameter schema)
that Ruby's router uses to expose them to the AI as callable tools.

Usage inside a skill's __init__.py:

    from skills.base import skill_tool

    @skill_tool(
        name="search_web",
        description="Search the web and return top results.",
        parameters={
            "query":       {"type": "string",  "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results", "default": 5},
        },
        required=["query"],
    )
    def search_web(query: str, max_results: int = 5) -> list[dict]:
        ...
"""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# ToolParam — schema for a single parameter
# ---------------------------------------------------------------------------

@dataclass
class ToolParam:
    name:        str
    type:        str               # "string" | "integer" | "number" | "boolean" | "array" | "object"
    description: str = ""
    required:    bool = True
    default:     Any  = inspect.Parameter.empty

    def to_json_schema(self) -> dict:
        schema: dict = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.default is not inspect.Parameter.empty:
            schema["default"] = self.default
        return schema


# ---------------------------------------------------------------------------
# ToolMetadata — attached to decorated functions as .__tool_meta__
# ---------------------------------------------------------------------------

@dataclass
class ToolMetadata:
    name:        str
    description: str
    parameters:  dict[str, ToolParam] = field(default_factory=dict)
    required:    list[str]            = field(default_factory=list)
    skill_name:  str                  = ""      # set by loader

    def to_openai_schema(self) -> dict:
        """Return an OpenAI function-calling schema dict."""
        properties = {k: v.to_json_schema() for k, v in self.parameters.items()}
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters": {
                    "type":       "object",
                    "properties": properties,
                    "required":   self.required,
                },
            },
        }

    def to_gemini_schema(self) -> dict:
        """Return a Gemini function-declaration schema dict."""
        properties = {k: v.to_json_schema() for k, v in self.parameters.items()}
        return {
            "name":        self.name,
            "description": self.description,
            "parameters": {
                "type":       "object",
                "properties": properties,
                "required":   self.required,
            },
        }


# ---------------------------------------------------------------------------
# @skill_tool decorator
# ---------------------------------------------------------------------------

def skill_tool(
    name: Optional[str] = None,
    description: str = "",
    parameters: Optional[dict[str, dict]] = None,
    required: Optional[list[str]] = None,
) -> Callable:
    """
    Decorator that marks a function as a Ruby skill tool.

    Parameters
    ----------
    name : str | None
        Tool name (defaults to the function name).
    description : str
        Human-readable description of what the tool does.
    parameters : dict[str, dict] | None
        Parameter schema.  Each key is a parameter name; each value is a dict
        with keys: type, description, default (optional).
    required : list[str] | None
        Names of required parameters (defaults to all parameters that have no default).

    The decorated function will have a .__tool_meta__ attribute of type ToolMetadata.
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        tool_desc = description or (inspect.getdoc(fn) or "")

        # Build ToolParam objects
        params: dict[str, ToolParam] = {}
        raw_params = parameters or {}
        sig = inspect.signature(fn)

        for pname, pdict in raw_params.items():
            sig_param = sig.parameters.get(pname)
            default = (
                sig_param.default
                if sig_param and sig_param.default is not inspect.Parameter.empty
                else inspect.Parameter.empty
            )
            if "default" in pdict:
                default = pdict["default"]
            params[pname] = ToolParam(
                name=pname,
                type=pdict.get("type", "string"),
                description=pdict.get("description", ""),
                required=pname in (required or []),
                default=default,
            )

        # Default required: params with no default
        auto_required = [
            p for p, v in params.items()
            if v.default is inspect.Parameter.empty
        ] if required is None else required

        meta = ToolMetadata(
            name=tool_name,
            description=tool_desc,
            parameters=params,
            required=auto_required,
        )

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        wrapper.__tool_meta__ = meta  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_skill_tool(fn: Any) -> bool:
    """Return True if fn has been decorated with @skill_tool."""
    return callable(fn) and hasattr(fn, "__tool_meta__")


def get_tool_meta(fn: Any) -> Optional[ToolMetadata]:
    """Return the ToolMetadata attached to fn, or None."""
    return getattr(fn, "__tool_meta__", None)
