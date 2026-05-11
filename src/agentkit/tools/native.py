"""Native tool decorator and registry."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any, get_type_hints

# Global registry of native tools
_TOOL_REGISTRY: dict[str, "NativeTool"] = {}


class NativeTool:
    """A registered native tool with its function and schema."""

    def __init__(self, func: Callable, name: str, description: str, schema: dict[str, Any]):
        self.func = func
        self.name = name
        self.description = description
        self.schema = schema

    async def execute(self, arguments: dict[str, Any]) -> str:
        """Execute the tool function with given arguments."""
        result = self.func(**arguments)
        # Handle async functions
        if inspect.isawaitable(result):
            result = await result
        # Convert result to string
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


def tool(func: Callable | None = None, *, name: str | None = None, description: str | None = None):
    """Decorator to register a function as a native tool.

    Usage:
        @tool
        def get_time(timezone: str = "UTC") -> str:
            '''Get the current time in a given timezone.'''
            ...

        @tool(name="calculator", description="Evaluate math expressions")
        def calc(expression: str) -> str:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        tool_description = description or _clean_docstring(fn.__doc__) or f"Tool: {tool_name}"

        # Build JSON schema from type hints
        schema = _build_schema(fn)

        native_tool = NativeTool(
            func=fn,
            name=tool_name,
            description=tool_description,
            schema=schema,
        )
        _TOOL_REGISTRY[tool_name] = native_tool
        # Attach metadata to the function
        fn._tool = native_tool  # type: ignore[attr-defined]
        return fn

    if func is not None:
        # @tool without parentheses
        return decorator(func)
    # @tool(...) with arguments
    return decorator


def get_registered_tools() -> dict[str, NativeTool]:
    """Return all registered native tools."""
    return _TOOL_REGISTRY.copy()


def clear_registry() -> None:
    """Clear the tool registry (useful for testing)."""
    _TOOL_REGISTRY.clear()


def _build_schema(func: Callable) -> dict[str, Any]:
    """Build a JSON Schema for a function's parameters from its type hints."""
    hints = get_type_hints(func)
    sig = inspect.signature(func)
    param_docs = _parse_param_docs(func.__doc__ or "")

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = hints.get(param_name, str)
        prop: dict[str, Any] = _type_to_json_schema(param_type)

        # Use docstring-extracted description, fallback to param name
        prop["description"] = param_docs.get(param_name, param_name)

        properties[param_name] = prop

        # If no default value, it's required
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def _clean_docstring(doc: str | None) -> str:
    """Clean a docstring: strip Args section, normalize whitespace."""
    if not doc:
        return ""
    import textwrap
    doc = textwrap.dedent(doc).strip()
    # Remove Args/Returns/Raises sections — these go into parameter descriptions
    lines = doc.split("\n")
    cleaned: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(("args:", "returns:", "raises:", "parameters:")):
            in_section = True
            continue
        if in_section:
            if stripped and not stripped[0].isspace() and ":" not in stripped[:20]:
                # New non-indented line without colon → end of section
                in_section = False
            elif stripped == "" or stripped[0:1] in (" ", "\t"):
                continue
            else:
                # Could be a continuation or a new param — skip
                continue
        if not in_section:
            cleaned.append(line)
    result = "\n".join(cleaned).strip()
    # Normalize indentation (remove common leading whitespace)
    import textwrap
    return textwrap.dedent(result).strip()


def _parse_param_docs(docstring: str) -> dict[str, str]:
    """Parse Google-style Args section from a docstring.

    Returns a dict mapping parameter names to their descriptions.
    """
    import textwrap
    doc = textwrap.dedent(docstring).strip()
    result: dict[str, str] = {}

    lines = doc.split("\n")
    in_args = False
    current_param = ""
    current_desc: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(("args:", "parameters:")):
            in_args = True
            continue
        if in_args:
            if stripped == "":
                continue
            # Check if this is a new section header (Returns:, Raises:, etc.)
            if stripped.endswith(":") and not stripped[0].isspace() and len(stripped.split()) == 1:
                break
            # Check if this line starts a new param: "  param_name: description"
            import re
            param_match = re.match(r"^\s{2,}(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", line)
            if param_match:
                # Save previous param
                if current_param:
                    result[current_param] = " ".join(current_desc).strip()
                current_param = param_match.group(1)
                current_desc = [param_match.group(2)]
            elif current_param and line.startswith("      "):
                # Continuation line (more indented)
                current_desc.append(stripped)

    # Save last param
    if current_param:
        result[current_param] = " ".join(current_desc).strip()

    return result


def _type_to_json_schema(python_type: Any) -> dict[str, Any]:
    """Convert a Python type annotation to JSON Schema."""
    type_map = {
        str: {"type": "string"},
        int: {"type": "integer"},
        float: {"type": "number"},
        bool: {"type": "boolean"},
        list: {"type": "array"},
        dict: {"type": "object"},
    }

    # Handle basic types
    if python_type in type_map:
        return type_map[python_type].copy()

    # Handle Optional, List[X], etc. could be expanded
    origin = getattr(python_type, "__origin__", None)
    if origin is list:
        args = getattr(python_type, "__args__", (str,))
        return {"type": "array", "items": _type_to_json_schema(args[0])}

    # Default to string
    return {"type": "string"}
