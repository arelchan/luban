"""Tool schema conversion utilities."""

from __future__ import annotations

from typing import Any

from agentkit.tools.native import NativeTool


def native_tool_to_openai_schema(tool: NativeTool) -> dict[str, Any]:
    """Convert a NativeTool to OpenAI function-calling schema format.

    This is the format expected by LiteLLM (OpenAI-compatible).
    """
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.schema,
        },
    }


def mcp_tool_to_openai_schema(
    server_name: str, tool_name: str, description: str, input_schema: dict[str, Any]
) -> dict[str, Any]:
    """Convert an MCP tool to OpenAI function-calling schema format.

    MCP tools are namespaced as 'servername__toolname' to avoid collisions.
    """
    namespaced_name = f"{server_name}__{tool_name}"
    return {
        "type": "function",
        "function": {
            "name": namespaced_name,
            "description": description,
            "parameters": input_schema,
        },
    }
