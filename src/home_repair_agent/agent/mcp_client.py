from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.types import TextContent

from home_repair_agent.agent.models import (
    ToolDefinition,
    ToolExecutionResult,
)


class MCPToolClient:
    """Translate an initialized MCP ClientSession into the Agent ToolClient port."""

    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def list_tools(self) -> list[ToolDefinition]:
        result = await self._session.list_tools()
        return [
            ToolDefinition(
                name=tool.name,
                title=tool.title,
                description=tool.description or "",
                input_schema=tool.inputSchema,
                annotations=_dump_annotations(tool.annotations),
            )
            for tool in result.tools
        ]

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, object],
    ) -> ToolExecutionResult:
        result = await self._session.call_tool(name, arguments)
        if result.structuredContent is not None:
            payload = result.structuredContent
        else:
            payload = {
                "content": "\n".join(
                    block.text for block in result.content if isinstance(block, TextContent)
                )
            }
        return ToolExecutionResult(
            mcp_is_error=result.isError,
            payload=payload,
        )


def _dump_annotations(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return value.model_dump(by_alias=True, exclude_none=True)
