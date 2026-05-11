"""MCP (Model Context Protocol) client manager."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from agentkit.config.models import MCPServerConfig

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPConnection:
    """A single connection to an MCP server."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: ClientSession | None = None
        self.tools: list[dict[str, Any]] = []

    async def connect(self, exit_stack: AsyncExitStack) -> None:
        """Connect to the MCP server and discover tools."""
        if not MCP_AVAILABLE:
            raise RuntimeError("MCP SDK not installed. Run: pip install mcp")

        server_params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env if self.config.env else None,
        )

        # Use exit_stack to manage the context managers
        read, write = await exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await exit_stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

        # Discover tools
        tools_response = await self.session.list_tools()
        self.tools = []
        for tool in tools_response.tools:
            self.tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
            })

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this MCP server."""
        if not self.session:
            return "Error: MCP server not connected"

        result = await self.session.call_tool(tool_name, arguments=arguments)

        # Extract text content from result
        if result.content:
            texts = []
            for block in result.content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                else:
                    texts.append(str(block))
            return "\n".join(texts)
        return ""


class MCPClientManager:
    """Manages multiple MCP server connections."""

    def __init__(self, server_configs: list[MCPServerConfig]):
        self._configs = [c for c in server_configs if c.enabled]
        self._connections: dict[str, MCPConnection] = {}
        self._exit_stack = AsyncExitStack()

    async def initialize(self) -> dict[str, list[dict[str, Any]]]:
        """Connect to all configured MCP servers.

        Returns a dict of server_name -> list of tool schemas.
        """
        await self._exit_stack.__aenter__()

        all_tools: dict[str, list[dict[str, Any]]] = {}

        for config in self._configs:
            try:
                conn = MCPConnection(config)
                await conn.connect(self._exit_stack)
                self._connections[config.name] = conn
                all_tools[config.name] = conn.tools
            except Exception as e:
                # Don't fail the whole startup if one server fails
                print(f"[Warning] Failed to connect to MCP server '{config.name}': {e}")

        return all_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on a specific server."""
        conn = self._connections.get(server_name)
        if not conn:
            return f"Error: MCP server '{server_name}' not connected"
        return await conn.call_tool(tool_name, arguments)

    def get_connections(self) -> dict[str, MCPConnection]:
        """Get all active connections."""
        return self._connections

    async def shutdown(self) -> None:
        """Close all MCP connections."""
        await self._exit_stack.aclose()
        self._connections.clear()
