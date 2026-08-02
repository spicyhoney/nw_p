"""Deterministic safety and privacy policy for user-controlled repair text.

The policy returns only allowlisted classifications and approved messages. It never
returns the matching input fragment, so callers cannot accidentally echo hazardous or
personal text in API errors, logs, or audit records.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum

from pydantic import BaseModel, ConfigDict


class SafetyDisposition(str, Enum):
    """Closed set of outcomes for repair safety text."""

    NONE = "none"
    REMINDER = "reminder"
    HARD_STOP = "hard_stop"


class RepairSafetyAssessment(BaseModel):
    """Safe result that excludes the original user-controlled text."""

    model_config = ConfigDict(extra="forbid")

    disposition: SafetyDisposition
    message: str | None = None

    @property
    def hard_stop(self) -> bool:
        return self.disposition is SafetyDisposition.HARD_STOP


APPROVED_HARD_STOP_MESSAGE = (
    "訊息包含可能的急迫安全風險，已停止一般媒合。請先遠離危險處，"
    "不要碰觸或自行拆修設備；若有人身危險，請立即聯絡所在地官方緊急服務。"
)
APPROVED_ELECTRICAL_REMINDER = (
    "若有冒火花、裸露電線、短路或異常發熱，請先遠離並避免碰觸設備或自行拆修；"
    "只有在安全且乾燥的位置才能考慮關閉電源，請勿冒險。"
)
APPROVED_MAJOR_WATER_REMINDER = (
    "若正在大量漏水或積水快速擴大，請遠離可能接觸電器或電線的積水區，"
    "不要冒險進入。只有在可安全操作且清楚關閉方式時才關閉供水。"
)

_HARD_STOP_KEYWORDS = (
    "漏電",
    "觸電",
    "起火",
    "火災",
    "瓦斯",
    "人身危險",
    "人身安全",
    "有人受傷",
    "人員受傷",
    "焦味",
    "電線走火",
    "插座燒焦",
    "電線燒焦",
    "電路燒焦",
    "濃煙",
)
_ELECTRICAL_REMINDER_KEYWORDS = (
    "冒火花",
    "短路",
    "電線裸露",
    "異常發熱",
)
_MAJOR_WATER_REMINDER_KEYWORDS = (
    "大量漏水",
    "嚴重漏水",
    "大量滲水",
    "爆管",
    "水管破裂",
    "管線破裂",
    "積水快速擴大",
    "淹水",
    "水噴出",
    "噴水不停",
)

_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?![\w.-])",
    re.IGNORECASE,
)
_MOBILE_PATTERN = re.compile(r"(?<!\d)(?:(?:\+?886)[\s-]?)?0?9\d{2}[\s-]?\d{3}[\s-]?\d{3}(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)0\d{1,2}[\s-]?\d{3,4}[\s-]?\d{4}(?!\d)")
_NAME_PATTERN = re.compile(
    r"(?:我叫|我的名字(?:是|叫|為)|姓名(?:是|為|[:：]))\s*"
    r"[\u3400-\u9fffA-Za-z·]{2,40}"
)
_ADDRESS_ROAD_PATTERN = re.compile(
    r"[\u3400-\u9fff]{2,20}(?:路|街)(?:[一二三四五六七八九十百\d]+段)?"
)
_ADDRESS_DETAIL_PATTERN = re.compile(r"[一二三四五六七八九十百\d]+(?:段|巷|弄|號|樓)(?:之\d+)?")
_TECHNICAL_ROUTE_TERMS = (
    "電路",
    "線路",
    "管路",
    "迴路",
    "回路",
    "水路",
)


def assess_repair_safety(*texts: str) -> RepairSafetyAssessment:
    """Classify text using one shared hazard policy for every input channel."""

    normalized = " ".join(_normalize(text) for text in texts if text)
    if _contains_any(normalized, _HARD_STOP_KEYWORDS):
        return RepairSafetyAssessment(
            disposition=SafetyDisposition.HARD_STOP,
            message=APPROVED_HARD_STOP_MESSAGE,
        )

    reminders: list[str] = []
    if _contains_any(normalized, _ELECTRICAL_REMINDER_KEYWORDS):
        reminders.append(APPROVED_ELECTRICAL_REMINDER)
    if _contains_any(normalized, _MAJOR_WATER_REMINDER_KEYWORDS):
        reminders.append(APPROVED_MAJOR_WATER_REMINDER)
    if reminders:
        return RepairSafetyAssessment(
            disposition=SafetyDisposition.REMINDER,
            message=" ".join(reminders),
        )
    return RepairSafetyAssessment(disposition=SafetyDisposition.NONE)


def contains_disallowed_personal_data(*texts: str) -> bool:
    """Detect Demo-prohibited PII without returning or retaining matched values."""

    for text in texts:
        normalized = _normalize(text)
        if (
            _EMAIL_PATTERN.search(normalized)
            or _MOBILE_PATTERN.search(normalized)
            or _PHONE_PATTERN.search(normalized)
            or _NAME_PATTERN.search(normalized)
            or _contains_precise_address(normalized)
        ):
            return True
    return False


def _contains_precise_address(text: str) -> bool:
    without_technical_terms = text
    for term in _TECHNICAL_ROUTE_TERMS:
        without_technical_terms = without_technical_terms.replace(term, "")
    return bool(
        _ADDRESS_ROAD_PATTERN.search(without_technical_terms)
        or _ADDRESS_DETAIL_PATTERN.search(without_technical_terms)
    )


def _normalize(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("policy text must be a string")
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)
