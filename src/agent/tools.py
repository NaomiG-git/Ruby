"""Agent tool abstractions."""

from __future__ import annotations

import inspect
import typing
from abc import ABC, abstractmethod
from typing import Any, Callable, Type


class Tool(ABC):
    """Abstract base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the tool."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON schema defining the parameters the tool accepts."""
        pass

    @abstractmethod
    async def __call__(self, **kwargs: Any) -> Any:
        """Execute the tool with the given arguments."""
        pass


class FunctionTool(Tool):
    """A tool that wraps a Python function."""

    def __init__(self, func: Callable, name: str | None = None, description: str | None = None):
        self._func = func
        self._name = name or func.__name__
        self._description = description or func.__doc__ or ""
        self._parameters = self._get_schema()

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def __call__(self, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(self._func):
            return await self._func(**kwargs)
        return self._func(**kwargs)

    def _get_schema(self) -> dict[str, Any]:
        """Generate JSON schema from function signature."""
        schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        
        sig = inspect.signature(self._func)
        type_hints = typing.get_type_hints(self._func)
        
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            
            if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                continue
                
            # Handle Type Hints
            param_type = type_hints.get(param_name, str)
            origin = typing.get_origin(param_type)
            args = typing.get_args(param_type)
            
            json_type = "string"
            json_format = None
            items = None
            
            if param_type == int:
                json_type = "integer"
            elif param_type == float:
                json_type = "number"
            elif param_type == bool:
                json_type = "boolean"
            elif origin is list or origin is typing.List:
                json_type = "array"
                item_type = args[0] if args else str
                
                # Recursive-ish type check for item
                item_origin = typing.get_origin(item_type)
                
                if item_type == int: 
                    items = {"type": "integer"}
                elif item_type == float: 
                    items = {"type": "number"}
                elif item_type == bool: 
                    items = {"type": "boolean"}
                elif item_origin is dict or item_origin is typing.Dict:
                     items = {"type": "object"}
                elif item_type == dict:
                     items = {"type": "object"}
                else:
                    items = {"type": "string"}
            elif origin is dict or origin is typing.Dict:
                 json_type = "object"

            prop_schema = {
                "type": json_type,
                "description": param_name,
            }
            if items:
                prop_schema["items"] = items
            
            schema["properties"][param_name] = prop_schema
            
            if param.default == inspect.Parameter.empty:
                schema["required"].append(param_name)
                
        return schema
