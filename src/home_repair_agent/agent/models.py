from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentModel(BaseModel):
    """Strict JSON model shared by Agent ports and adapters."""

    model_config = ConfigDict(extra="forbid")


class ToolDefinition(AgentModel):
    name: str = Field(min_length=1)
    title: str | None = None
    description: str = ""
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = Field(default_factory=dict)


class ToolCall(AgentModel):
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class UserMessage(AgentModel):
    kind: Literal["user"] = "user"
    text: str = Field(min_length=1, max_length=4000)


class AssistantMessage(AgentModel):
    kind: Literal["assistant"] = "assistant"
    text: str = Field(min_length=1)


class AssistantToolCalls(AgentModel):
    kind: Literal["assistant_tool_calls"] = "assistant_tool_calls"
    calls: list[ToolCall] = Field(min_length=1)


class ToolResultMessage(AgentModel):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    mcp_is_error: bool
    payload: dict[str, Any]


ConversationMessage = Annotated[
    UserMessage | AssistantMessage | AssistantToolCalls | ToolResultMessage,
    Field(discriminator="kind"),
]


class ModelTurn(AgentModel):
    """Exactly one model action: answer the user or request tools."""

    reply: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action(self) -> ModelTurn:
        has_reply = bool(self.reply and self.reply.strip())
        has_tools = bool(self.tool_calls)
        if has_reply == has_tools:
            raise ValueError("model turn must contain either reply or tool_calls")
        if self.reply is not None:
            self.reply = self.reply.strip()
        return self

    @classmethod
    def answer(cls, reply: str) -> ModelTurn:
        return cls(reply=reply)

    @classmethod
    def use_tools(cls, *tool_calls: ToolCall) -> ModelTurn:
        return cls(tool_calls=list(tool_calls))


class ToolExecutionResult(AgentModel):
    mcp_is_error: bool
    payload: dict[str, Any]


class ToolTraceEntry(AgentModel):
    call_id: str
    name: str
    arguments: dict[str, Any]
    mcp_is_error: bool
    result: dict[str, Any]


class ConversationSession(AgentModel):
    session_id: str = Field(min_length=1)
    messages: list[ConversationMessage] = Field(default_factory=list)


AgentStopReason = Literal[
    "completed",
    "max_steps",
    "model_error",
    "tool_catalog_error",
    "tool_limit",
]


class AgentTurnResult(AgentModel):
    session_id: str
    reply: str
    stop_reason: AgentStopReason
    tool_trace: list[ToolTraceEntry] = Field(default_factory=list)
