"""Unified tool manager for native and MCP tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from agentkit.config.models import ToolsConfig
from agentkit.tools.mcp_client import MCPClientManager
from agentkit.tools.native import NativeTool, get_registered_tools
from agentkit.tools.schema import mcp_tool_to_openai_schema, native_tool_to_openai_schema


class ToolDeniedError(Exception):
    """Raised when a tool is denied by permission config."""
    pass


class ToolRejectedError(Exception):
    """Raised when the user rejects a tool confirmation request."""
    pass


class ToolManager:
    """Manages all tools (native + MCP) with a unified interface.

    Tool naming:
    - Native tools: just their function name (e.g., "calculate")
    - MCP tools: namespaced as "servername__toolname" (e.g., "filesystem__read_file")
    """

    def __init__(self, config: ToolsConfig):
        self._config = config
        self._native_tools: dict[str, NativeTool] = {}
        self._mcp_manager: MCPClientManager | None = None
        # Maps namespaced_name -> (server_name, original_tool_name)
        self._mcp_tool_routing: dict[str, tuple[str, str]] = {}
        self._mcp_tool_schemas: list[dict[str, Any]] = []
        # Permission confirmation callback: async fn(tool_name, arguments) -> bool
        # Returns True to allow, False to reject. If None, all tools auto-allowed.
        self._confirm_callback: Callable[[str, dict[str, Any]], Any] | None = None

    def set_confirm_callback(self, callback: Callable[[str, dict[str, Any]], Any] | None) -> None:
        """Set the async callback for tool confirmation requests."""
        self._confirm_callback = callback

    async def initialize(self) -> None:
        """Initialize all tool sources."""
        # Load native tools from registry
        if self._config.enable_native:
            self._native_tools = get_registered_tools()

        # Initialize MCP connections
        if self._config.mcp_servers:
            self._mcp_manager = MCPClientManager(self._config.mcp_servers)
            server_tools = await self._mcp_manager.initialize()

            # Build routing table and schemas
            for server_name, tools in server_tools.items():
                for tool_info in tools:
                    namespaced = f"{server_name}__{tool_info['name']}"
                    self._mcp_tool_routing[namespaced] = (server_name, tool_info["name"])
                    self._mcp_tool_schemas.append(
                        mcp_tool_to_openai_schema(
                            server_name=server_name,
                            tool_name=tool_info["name"],
                            description=tool_info["description"],
                            input_schema=tool_info["input_schema"],
                        )
                    )

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas in OpenAI function-calling format."""
        schemas: list[dict[str, Any]] = []

        # Native tools
        for tool in self._native_tools.values():
            schemas.append(native_tool_to_openai_schema(tool))

        # MCP tools
        schemas.extend(self._mcp_tool_schemas)

        return schemas

    def _check_permission(self, name: str) -> str:
        """Check tool permission level. Returns 'allow', 'confirm', or 'deny'."""
        perms = self._config.permissions
        if name in perms.deny:
            return "deny"
        if name in perms.require_confirm:
            return "confirm"
        if name in perms.auto_allow:
            return "allow"
        # Default: tools not listed anywhere are auto-allowed
        return "allow"

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool by name with given arguments.

        Routes between native and MCP tools automatically.
        Checks permissions before execution.
        """
        # Permission check
        perm = self._check_permission(name)
        if perm == "deny":
            return f"[权限拒绝] 工具 '{name}' 已被配置禁用。如需使用请修改 config.toml [tools.permissions]"
        if perm == "confirm" and self._confirm_callback:
            approved = await self._confirm_callback(name, arguments)
            if not approved:
                return f"[用户拒绝] 工具 '{name}' 的执行已被用户取消"

        # Check native tools first
        if name in self._native_tools:
            return await self._native_tools[name].execute(arguments)

        # Check MCP tools (namespaced: servername__toolname)
        if name in self._mcp_tool_routing:
            server_name, tool_name = self._mcp_tool_routing[name]
            if self._mcp_manager:
                return await self._mcp_manager.call_tool(server_name, tool_name, arguments)

        return f"Error: Unknown tool '{name}'"

    def list_tools(self, lang: str = "en") -> list[dict[str, str]]:
        """List all available tools with name and description.

        If lang is provided, tries to use localized tool descriptions for display.
        """
        from agentkit.cli.i18n import tool_desc

        tools = []
        for t in self._native_tools.values():
            desc = tool_desc(t.name, lang) or t.description  # type: ignore[arg-type]
            tools.append({"name": t.name, "source": "native", "description": desc})
        for namespaced, (server, original) in self._mcp_tool_routing.items():
            tools.append({"name": namespaced, "source": f"mcp:{server}", "description": original})
        return tools

    async def shutdown(self) -> None:
        """Clean up tool connections."""
        if self._mcp_manager:
            await self._mcp_manager.shutdown()
