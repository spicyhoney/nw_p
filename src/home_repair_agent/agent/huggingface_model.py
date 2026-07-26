from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

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

DEFAULT_HF_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_HF_PROVIDER = "auto"
DEFAULT_HF_MAX_TOKENS = 512
DEFAULT_SYSTEM_PROMPT = """\
你是居家修繕服務助理。請使用繁體中文，並遵守以下規則：
1. 服務、行政區、表單、師傅、時段與 ID 只能來自工具結果，不可自行猜測。
2. 依序確認服務、行政區與諮詢表單；缺少必填資訊時，每次只追問一個問題。
3. 工具回傳 ok=false 時，向使用者詢問缺少或需要修正的資訊。
4. 表單必填資訊足夠後，才可查詢師傅候選。
5. 目前工具都是唯讀；不得聲稱已建立案件、保留時段、預約或下單。
6. 只收集完成當前修繕諮詢所需的最少資訊。
"""


class HuggingFaceChatClient(Protocol):
    """Small synchronous surface provided by huggingface_hub.InferenceClient."""

    def chat_completion(self, **kwargs: Any) -> object: ...


class HuggingFaceModelError(RuntimeError):
    """Base error whose message excludes provider payloads and credentials."""


class HuggingFaceConfigurationError(HuggingFaceModelError):
    """The Hugging Face adapter is not configured for a live request."""


class HuggingFaceRequestError(HuggingFaceModelError):
    """The hosted inference request failed."""


class HuggingFaceResponseError(HuggingFaceModelError):
    """The hosted model response cannot satisfy the ModelClient contract."""


class HuggingFaceModelClient:
    """Translate the Agent ModelClient port to Hugging Face chat completion."""

    def __init__(
        self,
        *,
        client: HuggingFaceChatClient,
        model_id: str = DEFAULT_HF_MODEL_ID,
        provider: str = DEFAULT_HF_PROVIDER,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
        max_tokens: int = DEFAULT_HF_MAX_TOKENS,
    ) -> None:
        normalized_model_id = model_id.strip()
        normalized_provider = provider.strip()
        if not normalized_model_id:
            raise ValueError("model_id must not be empty")
        if not normalized_provider:
            raise ValueError("provider must not be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        self._client = client
        self._model_id = normalized_model_id
        self._provider = normalized_provider
        self._system_prompt = system_prompt.strip() if system_prompt else None
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider(self) -> str:
        return self._provider

    @classmethod
    def from_environment(
        cls,
        *,
        client: HuggingFaceChatClient | None = None,
        environ: Mapping[str, str] | None = None,
        system_prompt: str | None = DEFAULT_SYSTEM_PROMPT,
    ) -> HuggingFaceModelClient:
        environment = os.environ if environ is None else environ
        token = environment.get("HF_TOKEN", "").strip()
        if not token:
            raise HuggingFaceConfigurationError(
                "HF_TOKEN is required for the Hugging Face model mode."
            )

        model_id = environment.get("HF_MODEL_ID", DEFAULT_HF_MODEL_ID).strip()
        provider = environment.get("HF_PROVIDER", DEFAULT_HF_PROVIDER).strip()
        if not model_id:
            raise HuggingFaceConfigurationError("HF_MODEL_ID must not be empty.")
        if not provider:
            raise HuggingFaceConfigurationError("HF_PROVIDER must not be empty.")
        max_tokens = _parse_positive_int(
            environment.get("HF_MAX_TOKENS"),
            name="HF_MAX_TOKENS",
            default=DEFAULT_HF_MAX_TOKENS,
        )
        resolved_client = client or _create_inference_client(
            token=token,
            provider=provider,
        )
        return cls(
            client=resolved_client,
            model_id=model_id,
            provider=provider,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        request = self._build_request(messages=messages, tools=tools)
        try:
            response = await asyncio.to_thread(
                self._client.chat_completion,
                **request,
            )
        except Exception as error:
            raise HuggingFaceRequestError("Hugging Face inference request failed.") from error
        return _parse_response(response)

    def _build_request(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> dict[str, Any]:
        converted_messages = _to_chat_messages(messages)
        if self._system_prompt:
            converted_messages.insert(
                0,
                {"role": "system", "content": self._system_prompt},
            )

        request: dict[str, Any] = {
            "model": self._model_id,
            "messages": converted_messages,
            "max_tokens": self._max_tokens,
        }
        if tools:
            request["tools"] = [_to_chat_tool(tool) for tool in tools]
            request["tool_choice"] = "auto"
        return request


def _create_inference_client(
    *,
    token: str,
    provider: str,
) -> HuggingFaceChatClient:
    try:
        from huggingface_hub import InferenceClient
    except ImportError as error:
        raise HuggingFaceConfigurationError(
            'huggingface_hub is required; install the project with the "app" extra.'
        ) from error

    try:
        return cast(
            HuggingFaceChatClient,
            InferenceClient(api_key=token, provider=provider),
        )
    except Exception as error:
        raise HuggingFaceConfigurationError(
            "Could not create the Hugging Face inference client."
        ) from error


def _parse_positive_int(
    raw_value: str | None,
    *,
    name: str,
    default: int,
) -> int:
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise HuggingFaceConfigurationError(f"{name} must be a positive integer.") from error
    if parsed <= 0:
        raise HuggingFaceConfigurationError(f"{name} must be a positive integer.")
    return parsed


def _to_chat_messages(
    messages: Sequence[ConversationMessage],
) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            converted.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantMessage):
            converted.append({"role": "assistant", "content": message.text})
        elif isinstance(message, AssistantToolCalls):
            converted.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                        for call in message.calls
                    ],
                }
            )
        elif isinstance(message, ToolResultMessage):
            converted.append(
                {
                    "role": "tool",
                    "tool_call_id": message.call_id,
                    "name": message.name,
                    "content": json.dumps(
                        message.payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            )
        else:  # pragma: no cover - closed union, defensive for future message types
            raise HuggingFaceResponseError("Unsupported conversation message type.")

    if not converted:
        raise HuggingFaceResponseError(
            "Hugging Face conversation must contain at least one message."
        )
    return converted


def _to_chat_tool(tool: ToolDefinition) -> dict[str, Any]:
    function: dict[str, Any] = {
        "name": tool.name,
        "parameters": tool.input_schema,
    }
    description = tool.description.strip() or (tool.title or "").strip()
    if description:
        function["description"] = description
    return {"type": "function", "function": function}


def _parse_response(response: object) -> ModelTurn:
    choices = _field(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise HuggingFaceResponseError("Hugging Face response is missing completion choices.")

    message = _field(choices[0], "message")
    if message is None:
        raise HuggingFaceResponseError("Hugging Face response is missing an assistant message.")

    raw_tool_calls = _field(message, "tool_calls")
    if raw_tool_calls:
        if not isinstance(raw_tool_calls, list):
            raise HuggingFaceResponseError("Hugging Face tool calls must be a list.")
        return ModelTurn.use_tools(*[_parse_tool_call(call) for call in raw_tool_calls])

    content = _field(message, "content")
    if not isinstance(content, str) or not content.strip():
        raise HuggingFaceResponseError(
            "Hugging Face response contains neither text nor tool calls."
        )
    return ModelTurn.answer(content)


def _parse_tool_call(raw_call: object) -> ToolCall:
    call_id = _field(raw_call, "id")
    function = _field(raw_call, "function")
    name = _field(function, "name")
    raw_arguments = _field(function, "arguments")
    if not isinstance(call_id, str) or not call_id:
        raise HuggingFaceResponseError("Hugging Face tool call is missing an ID.")
    if not isinstance(name, str) or not name:
        raise HuggingFaceResponseError("Hugging Face tool call is missing a name.")

    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as error:
            raise HuggingFaceResponseError(
                "Hugging Face tool arguments are not valid JSON."
            ) from error
    else:
        arguments = raw_arguments
    if not isinstance(arguments, dict):
        raise HuggingFaceResponseError("Hugging Face tool arguments must be a JSON object.")
    return ToolCall(call_id=call_id, name=name, arguments=arguments)


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
