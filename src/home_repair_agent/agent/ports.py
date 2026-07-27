from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from home_repair_agent.agent.models import (
    ConversationMessage,
    ModelTurn,
    ToolDefinition,
    ToolExecutionResult,
)


class ModelClient(Protocol):
    """Model adapter implemented by mock, hosted, and future Bedrock clients."""

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn: ...


class ToolClient(Protocol):
    """Tool transport implemented by MCP client adapters."""

    async def list_tools(self) -> list[ToolDefinition]: ...

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, object],
    ) -> ToolExecutionResult: ...
