from __future__ import annotations

from home_repair_agent.agent.models import (
    AgentStopReason,
    AgentTurnResult,
    AssistantMessage,
    AssistantToolCalls,
    ConversationSession,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
    ToolResultMessage,
    ToolTraceEntry,
    UserMessage,
)
from home_repair_agent.agent.ports import ModelClient, ToolClient

DEFAULT_MAX_MODEL_STEPS = 8
DEFAULT_MAX_TOOL_CALLS_PER_STEP = 4

SAFE_MODEL_ERROR_REPLY = "目前無法產生可靠回覆，請稍後再試。"
SAFE_TOOL_CATALOG_ERROR_REPLY = "目前無法取得服務工具，請稍後再試。"
SAFE_MAX_STEPS_REPLY = "目前無法在安全步數內完成處理，請補充需求後再試。"
SAFE_TOOL_LIMIT_REPLY = "這次要求的工具操作過多，已停止處理以避免錯誤。"


class AgentRunner:
    """Run model -> MCP tools -> model until a final reply or safety stop."""

    def __init__(
        self,
        *,
        model_client: ModelClient,
        tool_client: ToolClient,
        max_model_steps: int = DEFAULT_MAX_MODEL_STEPS,
        max_tool_calls_per_step: int = DEFAULT_MAX_TOOL_CALLS_PER_STEP,
        allowed_tool_names: set[str] | None = None,
    ) -> None:
        if max_model_steps <= 0:
            raise ValueError("max_model_steps must be positive")
        if max_tool_calls_per_step <= 0:
            raise ValueError("max_tool_calls_per_step must be positive")
        self._model_client = model_client
        self._tool_client = tool_client
        self._max_model_steps = max_model_steps
        self._max_tool_calls_per_step = max_tool_calls_per_step
        self._allowed_tool_names = allowed_tool_names

    async def run_turn(
        self,
        *,
        session: ConversationSession,
        user_text: str,
    ) -> AgentTurnResult:
        session.messages.append(UserMessage(text=user_text))
        trace: list[ToolTraceEntry] = []

        try:
            tool_catalog = await self._tool_client.list_tools()
        except Exception:  # noqa: BLE001 - mask external tool-provider details
            return _finish(
                session=session,
                reply=SAFE_TOOL_CATALOG_ERROR_REPLY,
                stop_reason="tool_catalog_error",
                trace=trace,
            )

        tools = [tool for tool in tool_catalog if self._is_allowed_read_tool(tool)]
        allowed_tool_names = {tool.name for tool in tools}
        for _ in range(self._max_model_steps):
            try:
                model_turn = await self._model_client.complete(
                    messages=tuple(session.messages),
                    tools=tuple(tools),
                )
            except Exception:  # noqa: BLE001 - mask external model details
                return _finish(
                    session=session,
                    reply=SAFE_MODEL_ERROR_REPLY,
                    stop_reason="model_error",
                    trace=trace,
                )

            if model_turn.reply is not None:
                return _finish(
                    session=session,
                    reply=model_turn.reply,
                    stop_reason="completed",
                    trace=trace,
                )

            if len(model_turn.tool_calls) > self._max_tool_calls_per_step:
                return _finish(
                    session=session,
                    reply=SAFE_TOOL_LIMIT_REPLY,
                    stop_reason="tool_limit",
                    trace=trace,
                )

            session.messages.append(AssistantToolCalls(calls=model_turn.tool_calls))
            for tool_call in model_turn.tool_calls:
                execution = await self._execute_tool(
                    tool_call=tool_call,
                    allowed_tool_names=allowed_tool_names,
                )
                session.messages.append(
                    ToolResultMessage(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        mcp_is_error=execution.mcp_is_error,
                        payload=execution.payload,
                    )
                )
                trace.append(
                    ToolTraceEntry(
                        call_id=tool_call.call_id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        mcp_is_error=execution.mcp_is_error,
                        result=execution.payload,
                    )
                )

        return _finish(
            session=session,
            reply=SAFE_MAX_STEPS_REPLY,
            stop_reason="max_steps",
            trace=trace,
        )

    def _is_allowed_read_tool(self, tool: ToolDefinition) -> bool:
        if tool.annotations.get("readOnlyHint") is not True:
            return False
        return self._allowed_tool_names is None or tool.name in self._allowed_tool_names

    async def _execute_tool(
        self,
        *,
        tool_call: ToolCall,
        allowed_tool_names: set[str],
    ) -> ToolExecutionResult:
        if tool_call.name not in allowed_tool_names:
            return ToolExecutionResult(
                mcp_is_error=True,
                payload=_safe_tool_error(
                    code="UNKNOWN_TOOL",
                    message="模型要求了不在白名單內的工具。",
                    details={"tool_name": tool_call.name},
                ),
            )
        try:
            return await self._tool_client.call_tool(
                name=tool_call.name,
                arguments=tool_call.arguments,
            )
        except Exception:  # noqa: BLE001 - mask external tool-provider details
            return ToolExecutionResult(
                mcp_is_error=True,
                payload=_safe_tool_error(
                    code="TOOL_CLIENT_ERROR",
                    message="工具暫時無法執行。",
                ),
            )


def _safe_tool_error(
    *,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }


def _finish(
    *,
    session: ConversationSession,
    reply: str,
    stop_reason: AgentStopReason,
    trace: list[ToolTraceEntry],
) -> AgentTurnResult:
    session.messages.append(AssistantMessage(text=reply))
    return AgentTurnResult(
        session_id=session.session_id,
        reply=reply,
        stop_reason=stop_reason,
        tool_trace=trace,
    )
