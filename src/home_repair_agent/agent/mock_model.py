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
    "match_service_providers",
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

        match_result = _latest_tool_result(messages, "match_service_providers")
        form_result = _latest_tool_result(messages, "get_consultation_form")
        location_result = _latest_tool_result(messages, "resolve_location")
        service_result = _latest_tool_result(messages, "search_services")

        if match_result is not None:
            return _summarize_match_result(match_result)

        if form_result is not None:
            return _continue_form_collection(
                messages,
                form_result,
                service_result=service_result,
                location_result=location_result,
            )

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

            location_text = _all_user_text(messages)
            if (
                location_result is not None
                and not _is_success(location_result.payload)
                and _has_user_after(messages, location_result)
            ):
                location_text = _latest_user_text(messages)
            location_candidates = _extract_locations(location_text)
            if _county_mention_count(location_text) > 1 or len(location_candidates) > 1:
                return ModelTurn.answer(
                    "偵測到多個地點，為避免選錯，請只提供更正後的完整縣市與行政區，"
                    "例如「新北市板橋區」。"
                )
            location = location_candidates[0] if location_candidates else None
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
    *,
    service_result: ToolResultMessage | None,
    location_result: ToolResultMessage | None,
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
        service_id = _unique_service_id(service_result)
        location_id = _resolved_location_id(location_result)
        if service_id is None or location_id is None:
            return ModelTurn.answer("必要資訊已收集，但目前無法安全確認服務或地點 ID。")
        return ModelTurn.use_tools(
            _tool_call(
                messages,
                name="match_service_providers",
                arguments={
                    "service_id": service_id,
                    "location_id": location_id,
                    "limit": 3,
                },
            )
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


def _resolved_location_id(result: ToolResultMessage | None) -> str | None:
    if result is None or not _is_success(result.payload):
        return None
    data = result.payload.get("data")
    if not isinstance(data, dict):
        return None
    location_id = data.get("location_id")
    return location_id if isinstance(location_id, str) and location_id else None


def _summarize_match_result(result: ToolResultMessage) -> ModelTurn:
    if not _is_success(result.payload):
        return ModelTurn.answer("必要資訊已收集，但目前無法取得師傅候選，請稍後再試。")

    data = result.payload.get("data")
    if not isinstance(data, dict) or data.get("data_source") != "synthetic":
        return ModelTurn.answer("媒合結果缺少可驗證的 synthetic 來源標籤，已停止顯示。")
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        return ModelTurn.answer("媒合結果格式異常，已停止顯示。")
    if not candidates:
        return ModelTurn.answer(
            "必要資訊已收集，但目前沒有符合條件的 synthetic 師傅候選；我不會自行捏造人選。"
        )

    first = candidates[0]
    if not isinstance(first, dict) or first.get("source_type") != "synthetic":
        return ModelTurn.answer("候選資料缺少可驗證的 synthetic 來源標籤，已停止顯示。")
    display_name = first.get("display_name")
    starts_at = first.get("starts_at")
    ends_at = first.get("ends_at")
    match_score = first.get("match_score")
    if (
        not isinstance(display_name, str)
        or not isinstance(starts_at, str)
        or not isinstance(ends_at, str)
        or not isinstance(match_score, int | float)
    ):
        return ModelTurn.answer("候選資料格式異常，已停止顯示。")

    return ModelTurn.answer(
        f"找到 {len(candidates)} 位 synthetic 師傅候選。"
        f"首選「{display_name}」，可用時段 {starts_at} 至 {ends_at}，"
        f"媒合分數 {match_score:.4f}。目前只提供候選，尚未建立案件，也未保留時段。"
    )


def _is_success(payload: dict[str, Any]) -> bool:
    return payload.get("ok") is True and isinstance(payload.get("data"), dict)


def _all_user_text(messages: Sequence[ConversationMessage]) -> str:
    return " ".join(
        message.text for message in messages if isinstance(message, UserMessage)
    ).replace("台", "臺")


def _latest_user_text(messages: Sequence[ConversationMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, UserMessage):
            return message.text.replace("台", "臺")
    return ""


def _extract_locations(text: str) -> list[tuple[str, str]]:
    normalized_text = text.replace("台", "臺")
    county_mentions: list[tuple[int, int, str]] = []
    for county_name in COUNTY_NAMES:
        county_mentions.extend(
            (match.start(), match.end(), county_name)
            for match in re.finditer(re.escape(county_name), normalized_text)
        )
    county_mentions.sort()

    locations: list[tuple[str, str]] = []
    for index, (_, county_end, county_name) in enumerate(county_mentions):
        next_county_start = (
            county_mentions[index + 1][0]
            if index + 1 < len(county_mentions)
            else len(normalized_text)
        )
        locations.extend(
            (county_name, district_match.group(1))
            for district_match in DISTRICT_PATTERN.finditer(
                normalized_text[county_end:next_county_start]
            )
        )
    return locations


def _county_mention_count(text: str) -> int:
    normalized_text = text.replace("台", "臺")
    return sum(normalized_text.count(county_name) for county_name in COUNTY_NAMES)


def _extract_location(text: str) -> tuple[str, str] | None:
    locations = _extract_locations(text)
    return locations[0] if len(locations) == 1 else None


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
