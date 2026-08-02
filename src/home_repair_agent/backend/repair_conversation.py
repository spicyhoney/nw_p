"""Deterministic, closed-world routing for home repair conversations.

The router only proposes one of the declared repair branches. Callers must show the
proposal to the user and obtain confirmation before using it in later workflow steps.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from home_repair_agent.backend.conversation_policy import assess_repair_safety


class RepairBranch(str, Enum):
    """Closed set of repair conversation branches."""

    FAUCET_LEAK = "faucet_leak"
    TOILET_ISSUE = "toilet_issue"
    PIPE_ISSUE = "pipe_issue"
    ELECTRICAL_ISSUE = "electrical_issue"
    OTHER = "other"


class RoutingConfidence(str, Enum):
    """Qualitative confidence for a routing proposal."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RepairRoutingResult(BaseModel):
    """Strict result returned by the deterministic repair router."""

    model_config = ConfigDict(extra="forbid")

    branch: RepairBranch | None = None
    confidence: RoutingConfidence
    alternatives: list[RepairBranch] = Field(default_factory=list)
    unsupported: bool = False
    clarification_question: str | None = None
    multiple_requests: bool = False
    cross_service: bool = False
    non_target_service: bool = False
    safety_stop: bool = False
    safety_message: str | None = None


_BRANCH_ORDER = (
    RepairBranch.FAUCET_LEAK,
    RepairBranch.TOILET_ISSUE,
    RepairBranch.PIPE_ISSUE,
    RepairBranch.ELECTRICAL_ISSUE,
)
_BRANCH_LABELS = {
    RepairBranch.FAUCET_LEAK: "水龍頭漏水",
    RepairBranch.TOILET_ISSUE: "馬桶問題",
    RepairBranch.PIPE_ISSUE: "管線或水管問題",
    RepairBranch.ELECTRICAL_ISSUE: "插座、電路或電線問題",
    RepairBranch.OTHER: "其他水電問題",
}

_HIGH_CONFIDENCE_KEYWORDS = {
    RepairBranch.FAUCET_LEAK: (
        "水龍頭漏水",
        "水龍頭滴水",
        "水龍頭滲水",
        "龍頭漏水",
        "龍頭滴水",
        "龍頭滲水",
    ),
    RepairBranch.TOILET_ISSUE: ("馬桶",),
    RepairBranch.PIPE_ISSUE: (
        "管線",
        "水管",
        "爆管",
    ),
    RepairBranch.ELECTRICAL_ISSUE: (
        "插座",
        "電路",
        "電線",
        "冒火花",
        "漏電",
        "短路",
        "跳電",
    ),
}
_MEDIUM_CONFIDENCE_KEYWORDS = {
    RepairBranch.FAUCET_LEAK: ("水龍頭", "龍頭"),
    RepairBranch.TOILET_ISSUE: ("便器", "沖水設備"),
    RepairBranch.PIPE_ISSUE: ("管路", "排水管", "給水管"),
    RepairBranch.ELECTRICAL_ISSUE: (
        "斷路器",
        "配電盤",
        "電箱",
        "電源開關",
    ),
}
_OTHER_REPAIR_ANCHORS = (
    "其他水電",
    "水電",
    "漏水",
    "滲水",
    "積水",
    "淹水",
    "排水",
    "水壓",
    "沒水",
    "停水",
    "沒電",
    "停電",
    "用電異常",
    "電力異常",
    "熱水器",
    "洗手台",
    "洗臉盆",
    "水槽",
    "蓮蓬頭",
    "淋浴設備",
    "燈具",
    "電燈",
    "居家水電修繕",
    "水電維修",
)
_NON_TARGET_SERVICE_KEYWORDS = (
    "居家清潔",
    "清潔",
    "打掃",
    "餐點外送",
    "餐飲外送",
    "外送餐點",
    "外送",
    "訂餐",
)


def route_repair_branch(message: str) -> RepairRoutingResult:
    """Return a deterministic routing proposal without changing workflow state.

    A returned branch is never a diagnosis or confirmation. The caller must ask the
    user to confirm it before continuing to form filling, matching, or any write.
    """

    normalized = _normalize_message(message)
    matching_branches = _matching_branches(normalized)
    has_other_anchor = _contains_any(normalized, _OTHER_REPAIR_ANCHORS)
    has_non_target_service = _contains_any(normalized, _NON_TARGET_SERVICE_KEYWORDS)
    safety = assess_repair_safety(message)

    if has_non_target_service:
        cross_service = bool(matching_branches) or has_other_anchor
        return RepairRoutingResult(
            confidence=RoutingConfidence.LOW,
            alternatives=matching_branches if cross_service else [],
            unsupported=True,
            clarification_question=(
                "訊息同時包含水電與目前不支援的其他服務；本次只能處理一項水電需求，"
                "請移除清潔或外送需求後重新描述。"
                if cross_service
                else "目前只支援居家水電修繕；清潔、餐點外送等服務不在本次範圍。"
            ),
            multiple_requests=cross_service,
            cross_service=cross_service,
            non_target_service=True,
            safety_stop=safety.hard_stop,
            safety_message=safety.message,
        )

    if len(matching_branches) > 1:
        labels = "、".join(_BRANCH_LABELS[branch] for branch in matching_branches)
        return RepairRoutingResult(
            confidence=RoutingConfidence.MEDIUM,
            alternatives=matching_branches,
            clarification_question=(
                f"此分類只是建議；偵測到多項修繕需求，請先選擇一項處理：{labels}。"
            ),
            multiple_requests=True,
            safety_stop=safety.hard_stop,
            safety_message=safety.message,
        )

    if matching_branches:
        branch = matching_branches[0]
        confidence = (
            RoutingConfidence.HIGH
            if _contains_any(normalized, _HIGH_CONFIDENCE_KEYWORDS[branch])
            else RoutingConfidence.MEDIUM
        )
        return RepairRoutingResult(
            branch=branch,
            confidence=confidence,
            clarification_question=(
                f"此分類只是建議；我先判斷為「{_BRANCH_LABELS[branch]}」，請確認是否正確。"
            ),
            safety_stop=safety.hard_stop,
            safety_message=safety.message,
        )

    if has_other_anchor:
        return RepairRoutingResult(
            branch=RepairBranch.OTHER,
            confidence=RoutingConfidence.LOW,
            clarification_question=(
                "目前無法確認具體的水電修繕類型，請完整描述發生位置與現象；此分類仍需由您確認。"
            ),
            safety_stop=safety.hard_stop,
            safety_message=safety.message,
        )

    return RepairRoutingResult(
        confidence=RoutingConfidence.LOW,
        unsupported=True,
        clarification_question=(
            "目前只支援居家水電修繕分類；若確實是水電需求，請完整描述發生位置與現象。"
        ),
        safety_stop=safety.hard_stop,
        safety_message=safety.message,
    )


def is_supported_water_repair_text(message: str) -> bool:
    """Return whether text contains an explicit supported water-repair anchor."""

    result = route_repair_branch(message)
    return not result.unsupported and bool(result.branch or result.alternatives)


def _normalize_message(message: str) -> str:
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    return " ".join(unicodedata.normalize("NFKC", message).casefold().split())


def _matching_branches(message: str) -> list[RepairBranch]:
    return [
        branch
        for branch in _BRANCH_ORDER
        if _contains_any(message, _HIGH_CONFIDENCE_KEYWORDS[branch])
        or _contains_any(message, _MEDIUM_CONFIDENCE_KEYWORDS[branch])
    ]


def _contains_any(message: str, keywords: tuple[str, ...]) -> bool:
    return any(_contains_keyword(message, keyword) for keyword in keywords)


def _contains_keyword(message: str, keyword: str) -> bool:
    if keyword.isascii():
        return (
            re.search(
                rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])",
                message,
            )
            is not None
        )
    return keyword in message
