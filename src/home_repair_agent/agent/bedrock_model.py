from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from home_repair_agent.agent.huggingface_model import DEFAULT_SYSTEM_PROMPT
from home_repair_agent.agent.models import (
    AssistantMessage,
    AssistantToolCalls,
    ConversationMessage,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)

DEFAULT_BEDROCK_MAX_TOKENS = 512
DEFAULT_BEDROCK_TIMEOUT_SECONDS = 60
COMPETITION_BEDROCK_REGIONS = frozenset({"us-east-1", "us-west-2"})


class BedrockRuntimeClient(Protocol):
    """Small synchronous surface provided by boto3's Bedrock Runtime client."""

    def converse(self, **kwargs: Any) -> object: ...


class BedrockModelError(RuntimeError):
    """Base error whose message excludes provider payloads and credentials."""


class BedrockConfigurationError(BedrockModelError):
    """The Bedrock adapter is not configured for a live request."""


class BedrockRequestError(BedrockModelError):
    """The Bedrock Converse request failed."""


class BedrockResponseError(BedrockModelError):
    """The Bedrock response cannot satisfy the ModelClient contract."""


class BedrockModelClient:
    """Translate the provider-neutral ModelClient port to Bedrock Converse."""

    def __init__(
        self,
        *,
        client: BedrockRuntimeClient,
        model_id: str,
        region: str,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_BEDROCK_MAX_TOKENS,
        timeout_seconds: int = DEFAULT_BEDROCK_TIMEOUT_SECONDS,
    ) -> None:
        normalized_model_id = model_id.strip()
        normalized_region = region.strip()
        if not normalized_model_id:
            raise ValueError("model_id must not be empty")
        if normalized_region not in COMPETITION_BEDROCK_REGIONS:
            raise ValueError("region must be an allowed competition Region")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._client = client
        self._model_id = normalized_model_id
        self._region = normalized_region
        self._system_prompt = system_prompt.strip() if system_prompt else None
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(model_id={self._model_id!r}, "
            f"region={self._region!r}, timeout_seconds={self._timeout_seconds!r})"
        )

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def region(self) -> str:
        return self._region

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @classmethod
    def from_environment(
        cls,
        *,
        client: BedrockRuntimeClient | None = None,
        environ: Mapping[str, str] | None = None,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
    ) -> BedrockModelClient:
        environment = os.environ if environ is None else environ
        region = environment.get("BEDROCK_REGION", "").strip()
        model_id = environment.get("BEDROCK_MODEL_ID", "").strip()
        if not region:
            raise BedrockConfigurationError("BEDROCK_REGION is required for Bedrock mode.")
        if region not in COMPETITION_BEDROCK_REGIONS:
            raise BedrockConfigurationError(
                "BEDROCK_REGION must be us-east-1 or us-west-2 for this competition."
            )
        if not model_id:
            raise BedrockConfigurationError("BEDROCK_MODEL_ID is required for Bedrock mode.")

        max_tokens = _parse_positive_int(
            environment.get("BEDROCK_MAX_TOKENS"),
            name="BEDROCK_MAX_TOKENS",
            default=DEFAULT_BEDROCK_MAX_TOKENS,
        )
        timeout_seconds = _parse_positive_int(
            environment.get("BEDROCK_TIMEOUT_SECONDS"),
            name="BEDROCK_TIMEOUT_SECONDS",
            default=DEFAULT_BEDROCK_TIMEOUT_SECONDS,
        )
        resolved_client = client or _create_bedrock_runtime_client(
            region=region,
            timeout_seconds=timeout_seconds,
        )
        return cls(
            client=resolved_client,
            model_id=model_id,
            region=region,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        request = self._build_request(messages=messages, tools=tools)
        try:
            response = await asyncio.to_thread(self._client.converse, **request)
        except Exception:  # noqa: BLE001 - mask all provider and transport details
            raise BedrockRequestError("Amazon Bedrock Converse request failed.") from None
        return _parse_response(response)

    def _build_request(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "modelId": self._model_id,
            "messages": _to_bedrock_messages(messages),
            "inferenceConfig": {"maxTokens": self._max_tokens},
        }
        if self._system_prompt:
            request["system"] = [{"text": self._system_prompt}]
        if tools:
            request["toolConfig"] = {
                "tools": [_to_bedrock_tool(tool) for tool in tools],
            }
        return request


def _create_bedrock_runtime_client(
    *,
    region: str,
    timeout_seconds: int,
) -> BedrockRuntimeClient:
    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import NoCredentialsError, PartialCredentialsError
    except ImportError:
        raise BedrockConfigurationError(
            'boto3 is required; install the project with the "app" extra.'
        ) from None

    try:
        session = boto3.Session(region_name=region)
        credentials = session.get_credentials()
        if credentials is None:
            raise BedrockConfigurationError(
                "AWS credentials are required for Bedrock mode."
            )
        frozen = credentials.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            raise BedrockConfigurationError(
                "Complete AWS credentials are required for Bedrock mode."
            )
        return cast(
            BedrockRuntimeClient,
            session.client(
                "bedrock-runtime",
                config=Config(
                    connect_timeout=timeout_seconds,
                    read_timeout=timeout_seconds,
                    retries={"total_max_attempts": 1, "mode": "standard"},
                    user_agent_extra="nw-p-bedrock-poc",
                ),
            ),
        )
    except BedrockConfigurationError:
        raise
    except (NoCredentialsError, PartialCredentialsError):
        raise BedrockConfigurationError(
            "Complete AWS credentials are required for Bedrock mode."
        ) from None
    except Exception:  # noqa: BLE001 - mask SDK credential-provider details
        raise BedrockConfigurationError(
            "Could not create the Amazon Bedrock Runtime client."
        ) from None


def _parse_positive_int(raw_value: str | None, *, name: str, default: int) -> int:
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise BedrockConfigurationError(f"{name} must be a positive integer.") from error
    if parsed <= 0:
        raise BedrockConfigurationError(f"{name} must be a positive integer.")
    return parsed


def _to_bedrock_messages(
    messages: Sequence[ConversationMessage],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": [{"text": message.text}]})
        elif isinstance(message, AssistantMessage):
            converted.append(
                {"role": "assistant", "content": [{"text": message.text}]}
            )
        elif isinstance(message, AssistantToolCalls):
            converted.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": call.call_id,
                                "name": call.name,
                                "input": _json_object(
                                    call.arguments,
                                    error_message=(
                                        "Agent tool arguments must be a JSON object."
                                    ),
                                ),
                            }
                        }
                        for call in message.calls
                    ],
                }
            )
        elif isinstance(message, ToolResultMessage):
            result_block = {
                "toolResult": {
                    "toolUseId": message.call_id,
                    "content": [
                        {
                            "json": _json_object(
                                message.payload,
                                error_message="Agent tool result must be a JSON object.",
                            )
                        }
                    ],
                    "status": "error" if message.mcp_is_error else "success",
                }
            }
            if converted and _contains_only_tool_results(converted[-1]):
                converted[-1]["content"].append(result_block)
            else:
                converted.append({"role": "user", "content": [result_block]})
        else:  # pragma: no cover - closed union, defensive for future message types
            raise BedrockResponseError("Unsupported conversation message type.")

    if not converted:
        raise BedrockResponseError("Bedrock conversation must contain at least one message.")
    return converted


def _contains_only_tool_results(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, list)
        and bool(content)
        and all(isinstance(block, dict) and "toolResult" in block for block in content)
    )


def _to_bedrock_tool(tool: ToolDefinition) -> dict[str, Any]:
    tool_spec: dict[str, Any] = {
        "name": tool.name,
        "inputSchema": {
            "json": _json_object(
                tool.input_schema,
                error_message="Tool input schema must be a JSON object.",
            )
        },
    }
    description = tool.description.strip() or (tool.title or "").strip()
    if description:
        tool_spec["description"] = description
    return {"toolSpec": tool_spec}


def _parse_response(response: object) -> ModelTurn:
    output = _mapping_field(response, "output")
    message = _mapping_field(output, "message")
    content = _mapping_field(message, "content")
    if not isinstance(content, list) or not content:
        raise BedrockResponseError("Bedrock response is missing assistant content.")

    tool_calls: list[ToolCall] = []
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            raise BedrockResponseError("Bedrock response contains an invalid content block.")
        raw_tool_use = block.get("toolUse")
        if raw_tool_use is not None:
            tool_calls.append(_parse_tool_use(raw_tool_use))
        raw_text = block.get("text")
        if isinstance(raw_text, str) and raw_text.strip():
            text_parts.append(raw_text.strip())

    if tool_calls:
        return ModelTurn.use_tools(*tool_calls)
    if text_parts:
        return ModelTurn.answer("\n".join(text_parts))
    raise BedrockResponseError("Bedrock response contains neither text nor tool use.")


def _parse_tool_use(raw_tool_use: object) -> ToolCall:
    call_id = _mapping_field(raw_tool_use, "toolUseId")
    name = _mapping_field(raw_tool_use, "name")
    raw_arguments = _mapping_field(raw_tool_use, "input")
    if not isinstance(call_id, str) or not call_id:
        raise BedrockResponseError("Bedrock tool use is missing an ID.")
    if not isinstance(name, str) or not name:
        raise BedrockResponseError("Bedrock tool use is missing a name.")
    if not isinstance(raw_arguments, Mapping):
        raise BedrockResponseError("Bedrock tool arguments must be a JSON object.")
    return ToolCall(
        call_id=call_id,
        name=name,
        arguments=_json_object(
            dict(raw_arguments),
            error_message="Bedrock tool arguments must be a JSON object.",
        ),
    )


def _json_object(value: object, *, error_message: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BedrockResponseError(error_message)
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
        normalized = json.loads(serialized)
    except (TypeError, ValueError) as error:
        raise BedrockResponseError(error_message) from error
    if not isinstance(normalized, dict):  # pragma: no cover - Mapping always encodes as object
        raise BedrockResponseError(error_message)
    return normalized


def _mapping_field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return None
