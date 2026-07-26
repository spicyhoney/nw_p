from __future__ import annotations

import re
from collections import deque
from collections.abc import Sequence
from typing import Any

from home_repair_agent.agent.models import (
    AssistantToolCalls,
    ConversationMessage,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)

REQUIRED_READ_TOOLS = {
    "search_services",
    "resolve_location",
    "get_consultation_form",
}
COUNTY_NAMES = (
    "基隆市",
    "臺北市",
    "新北市",
    "桃園市",
    "新竹市",
    "新竹縣",
    "苗栗縣",
    "臺中市",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "臺南市",
    "高雄市",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "臺東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)
DISTRICT_PATTERN = re.compile(r"([\u4e00-\u9fff]{1,4}(?:區|鄉|鎮|市))")


class ScriptedModelClient:
    """Deterministic model double for precise AgentRunner tests."""

    def __init__(self, turns: Sequence[ModelTurn]) -> None:
        self._turns = deque(turns)
        self.requests: list[
            tuple[
                tuple[ConversationMessage, ...],
                tuple[ToolDefinition, ...],
            ]
        ] = []

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        self.requests.append((tuple(messages), tuple(tools)))
        if not self._turns:
            raise RuntimeError("scripted model has no remaining turns")
        return self._turns.popleft()


class RuleBasedRepairMockModel:
    """No-AWS demo model for one repair consultation per session.

    It is intentionally deterministic and is not a substitute for language
    understanding. Its purpose is to exercise the real Agent and MCP loop.
    """

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        available_tools = {tool.name for tool in tools}
        missing_tools = REQUIRED_READ_TOOLS - available_tools
        if missing_tools:
            return ModelTurn.answer("目前缺少必要的修繕查詢工具，請稍後再試。")

        form_result = _latest_tool_result(messages, "get_consultation_form")
        if form_result is not None:
            return _continue_form_collection(messages, form_result)

        location_result = _latest_tool_result(messages, "resolve_location")
        service_result = _latest_tool_result(messages, "search_services")

        if location_result is not None and _is_success(location_result.payload):
            service_id = _unique_service_id(service_result)
            if service_id is None:
                return ModelTurn.answer("目前無法確認唯一的服務項目，請重新描述需求。")
            return ModelTurn.use_tools(
                _tool_call(
                    messages,
                    name="get_consultation_form",
                    arguments={"service_id": service_id},
                )
            )

        if service_result is not None:
            service_id = _unique_service_id(service_result)
            if service_id is None:
                if _has_user_after(messages, service_result):
                    return _search_latest_user(messages)
                return ModelTurn.answer("目前找不到唯一支援的服務，請再具體描述需要處理的問題。")

            location = _extract_location(_all_user_text(messages))
            if location is None:
                return ModelTurn.answer("請提供完整的縣市與行政區，例如「臺北市大安區」。")

            if (
                location_result is not None
                and not _is_success(location_result.payload)
                and not _has_user_after(messages, location_result)
            ):
                return ModelTurn.answer("目前無法唯一確認該行政區，請重新提供完整縣市與行政區。")
            return ModelTurn.use_tools(
                _tool_call(
                    messages,
                    name="resolve_location",
                    arguments={
                        "county_name": location[0],
                        "district_name": location[1],
                    },
                )
            )

        return _search_latest_user(messages)


def _search_latest_user(
    messages: Sequence[ConversationMessage],
) -> ModelTurn:
    user_messages = [message.text for message in messages if isinstance(message, UserMessage)]
    query = user_messages[-1] if user_messages else ""
    return ModelTurn.use_tools(
        _tool_call(
            messages,
            name="search_services",
            arguments={"query": query, "limit": 5},
        )
    )


def _continue_form_collection(
    messages: Sequence[ConversationMessage],
    form_result: ToolResultMessage,
) -> ModelTurn:
    if not _is_success(form_result.payload):
        return ModelTurn.answer("目前找不到可使用的諮詢表單，請改由人工協助。")

    data = form_result.payload.get("data")
    if not isinstance(data, dict):
        return ModelTurn.answer("諮詢表單格式異常，請改由人工協助。")
    topics = data.get("topics")
    if not isinstance(topics, list):
        return ModelTurn.answer("諮詢表單格式異常，請改由人工協助。")

    required_topics = [
        topic for topic in topics if isinstance(topic, dict) and topic.get("is_required") is True
    ]
    answers = _user_messages_after(messages, form_result)
    if len(answers) >= len(required_topics):
        return ModelTurn.answer(
            "必要資訊已收集完成。目前是唯讀原型，尚未建立案件；請確認資料後再進入送出流程。"
        )

    topic = required_topics[len(answers)]
    title = str(topic.get("title") or "請補充此項資訊")
    options = topic.get("options")
    labels = (
        [
            str(option["label"])
            for option in options
            if isinstance(option, dict) and option.get("label")
        ]
        if isinstance(options, list)
        else []
    )
    if labels:
        return ModelTurn.answer(f"{title}？可選：{'、'.join(labels[:5])}")
    return ModelTurn.answer(f"{title}？")


def _latest_tool_result(
    messages: Sequence[ConversationMessage],
    name: str,
) -> ToolResultMessage | None:
    for message in reversed(messages):
        if isinstance(message, ToolResultMessage) and message.name == name:
            return message
    return None


def _unique_service_id(result: ToolResultMessage | None) -> int | None:
    if result is None or not _is_success(result.payload):
        return None
    data = result.payload.get("data")
    if not isinstance(data, dict) or data.get("count") != 1:
        return None
    services = data.get("services")
    if not isinstance(services, list) or len(services) != 1:
        return None
    service = services[0]
    if not isinstance(service, dict):
        return None
    service_id = service.get("service_id")
    return service_id if isinstance(service_id, int) else None


def _is_success(payload: dict[str, Any]) -> bool:
    return payload.get("ok") is True and isinstance(payload.get("data"), dict)


def _all_user_text(messages: Sequence[ConversationMessage]) -> str:
    return " ".join(
        message.text for message in messages if isinstance(message, UserMessage)
    ).replace("台", "臺")


def _extract_location(text: str) -> tuple[str, str] | None:
    county_match: tuple[str, int] | None = None
    for county_name in COUNTY_NAMES:
        position = text.find(county_name)
        if position >= 0:
            county_match = (county_name, position + len(county_name))
            break
    if county_match is None:
        return None

    district_match = DISTRICT_PATTERN.search(text[county_match[1] :])
    if district_match is None:
        return None
    return county_match[0], district_match.group(1)


def _has_user_after(
    messages: Sequence[ConversationMessage],
    target: ToolResultMessage,
) -> bool:
    target_index = _identity_index(messages, target)
    return any(isinstance(message, UserMessage) for message in messages[target_index + 1 :])


def _user_messages_after(
    messages: Sequence[ConversationMessage],
    target: ToolResultMessage,
) -> list[UserMessage]:
    target_index = _identity_index(messages, target)
    return [message for message in messages[target_index + 1 :] if isinstance(message, UserMessage)]


def _identity_index(
    messages: Sequence[ConversationMessage],
    target: ConversationMessage,
) -> int:
    for index, message in enumerate(messages):
        if message is target:
            return index
    raise ValueError("target message is not part of the conversation")


def _tool_call(
    messages: Sequence[ConversationMessage],
    *,
    name: str,
    arguments: dict[str, object],
) -> ToolCall:
    prior_call_count = sum(
        len(message.calls) for message in messages if isinstance(message, AssistantToolCalls)
    )
    return ToolCall(
        call_id=f"mock-call-{prior_call_count + 1}",
        name=name,
        arguments=arguments,
    )
