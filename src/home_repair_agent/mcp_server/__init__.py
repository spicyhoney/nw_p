"""MCP adapters that expose the backend Service Layer to AI agents."""

from home_repair_agent.mcp_server.server import create_mcp_server

__all__ = ["create_mcp_server"]
