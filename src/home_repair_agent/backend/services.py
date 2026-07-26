from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.models import (
    AvailableProviderSlot,
    ConsultationForm,
    MatchScoreBreakdown,
    ProviderMatchCandidate,
    ProviderMatchResult,
    ResolvedLocation,
    ServiceSearchResult,
)
from home_repair_agent.backend.ports import ReadRepository

DEFAULT_SERVICE_LIMIT = 10
MAX_SERVICE_LIMIT = 25
MAX_QUERY_LENGTH = 200
MAX_LOCATION_LENGTH = 20
DEFAULT_MATCH_LIMIT = 3
MAX_MATCH_LIMIT = 10
MAX_MATCH_CANDIDATE_POOL = 100
MAX_LOCATION_ID_LENGTH = 100
MAX_MATCH_WINDOW = timedelta(days=31)
MATCH_SCHEDULE_WEIGHT = 0.40
MATCH_RATING_WEIGHT = 0.35
MATCH_EXPERIENCE_WEIGHT = 0.20
MATCH_FEE_WEIGHT = 0.05


class ReadServiceLayer:
    """Business rules shared by future FastAPI and MCP read adapters."""

    def __init__(self, repository: ReadRepository) -> None:
        self._repository = repository

    def search_services(
        self,
        query: str | None = None,
        *,
        limit: int = DEFAULT_SERVICE_LIMIT,
    ) -> ServiceSearchResult:
        normalized_query = _normalize_search_query(query)
        normalized_limit = _validate_limit(limit)
        services = self._repository.search_services(
            query=normalized_query,
            limit=normalized_limit,
        )
        return ServiceSearchResult(
            query=normalized_query or None,
            count=len(services),
            services=services,
        )

    def resolve_location(
        self,
        *,
        county_name: str,
        district_name: str,
    ) -> ResolvedLocation:
        normalized_county = _normalize_location_name(county_name, field="county_name")
        normalized_district = _normalize_location_name(
            district_name,
            field="district_name",
        )
        candidates = self._repository.find_locations(
            county_name=normalized_county,
            county_base=_without_suffix(normalized_county, ("縣", "市")),
            district_name=normalized_district,
            district_base=_without_suffix(
                normalized_district,
                ("區", "鄉", "鎮", "市"),
            ),
        )

        if not candidates:
            raise ServiceLayerError(
                code="LOCATION_NOT_FOUND",
                message="找不到可供 Agent 使用的縣市與行政區組合。",
                details={
                    "county_name": normalized_county,
                    "district_name": normalized_district,
                },
            )
        if len(candidates) > 1:
            raise ServiceLayerError(
                code="LOCATION_AMBIGUOUS",
                message="行政區結果不唯一，不能自行猜測。",
                details={
                    "county_name": normalized_county,
                    "district_name": normalized_district,
                    "candidate_location_ids": [
                        candidate.location_id for candidate in candidates
                    ],
                },
            )
        return candidates[0]

    def get_consultation_form(self, *, service_id: int) -> ConsultationForm:
        normalized_service_id = _validate_service_id(service_id)
        forms = self._repository.list_consultation_forms(
            service_id=normalized_service_id
        )
        if not forms:
            raise ServiceLayerError(
                code="FORM_NOT_FOUND",
                message="此服務目前沒有可供 Agent 使用的啟用中諮詢表單。",
                details={"service_id": normalized_service_id},
            )

        latest_version = max(form.version for form in forms)
        latest_forms = [form for form in forms if form.version == latest_version]
        if len(latest_forms) > 1:
            raise ServiceLayerError(
                code="FORM_AMBIGUOUS",
                message="同一服務存在多份相同最新版號的表單，不能自行選擇。",
                details={
                    "service_id": normalized_service_id,
                    "version": latest_version,
                    "candidate_form_keys": [
                        form.form_key for form in latest_forms
                    ],
                },
            )
        return latest_forms[0]

    def match_service_providers(
        self,
        *,
        service_id: int,
        location_id: str,
        preferred_start: datetime | None = None,
        preferred_end: datetime | None = None,
        limit: int = DEFAULT_MATCH_LIMIT,
    ) -> ProviderMatchResult:
        normalized_service_id = _validate_service_id(service_id)
        normalized_location_id = _normalize_location_id(location_id)
        normalized_start, normalized_end = _validate_time_window(
            preferred_start,
            preferred_end,
        )
        normalized_limit = _validate_match_limit(limit)

        slots = self._repository.list_available_provider_slots(
            service_id=normalized_service_id,
            location_id=normalized_location_id,
            preferred_start=normalized_start,
            preferred_end=normalized_end,
            candidate_limit=MAX_MATCH_CANDIDATE_POOL,
        )
        eligible_slots = [
            slot
            for slot in slots
            if slot.service_id == normalized_service_id
            and slot.location_id == normalized_location_id
            and (
                normalized_start is None
                or _schedule_fit(slot, normalized_start, normalized_end) > 0
            )
        ]
        candidates = _rank_provider_slots(
            eligible_slots,
            preferred_start=normalized_start,
            preferred_end=normalized_end,
            limit=normalized_limit,
        )
        return ProviderMatchResult(
            service_id=normalized_service_id,
            location_id=normalized_location_id,
            preferred_start=normalized_start,
            preferred_end=normalized_end,
            count=len(candidates),
            candidates=candidates,
        )


def _normalize_search_query(value: str | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ServiceLayerError(
            code="INVALID_QUERY",
            message="服務查詢文字必須是字串。",
        )
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if len(normalized) > MAX_QUERY_LENGTH:
        raise ServiceLayerError(
            code="INVALID_QUERY",
            message=f"服務查詢文字不可超過 {MAX_QUERY_LENGTH} 個字元。",
            details={"max_length": MAX_QUERY_LENGTH},
        )
    return normalized


def _validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceLayerError(
            code="INVALID_LIMIT",
            message="查詢筆數必須是整數。",
        )
    if not 1 <= value <= MAX_SERVICE_LIMIT:
        raise ServiceLayerError(
            code="INVALID_LIMIT",
            message=f"查詢筆數必須介於 1 與 {MAX_SERVICE_LIMIT} 之間。",
            details={"minimum": 1, "maximum": MAX_SERVICE_LIMIT},
        )
    return value


def _normalize_location_name(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ServiceLayerError(
            code="INVALID_LOCATION",
            message=f"{field} 必須是字串。",
            details={"field": field},
        )
    normalized = "".join(unicodedata.normalize("NFKC", value).split())
    normalized = normalized.replace("台", "臺")
    if not normalized:
        raise ServiceLayerError(
            code="INVALID_LOCATION",
            message=f"{field} 不可為空。",
            details={"field": field},
        )
    if len(normalized) > MAX_LOCATION_LENGTH:
        raise ServiceLayerError(
            code="INVALID_LOCATION",
            message=f"{field} 不可超過 {MAX_LOCATION_LENGTH} 個字元。",
            details={"field": field, "max_length": MAX_LOCATION_LENGTH},
        )
    return normalized


def _without_suffix(value: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def _validate_service_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ServiceLayerError(
            code="INVALID_SERVICE_ID",
            message="service_id 必須是正整數。",
        )
    return value


def _normalize_location_id(value: str) -> str:
    if not isinstance(value, str):
        raise ServiceLayerError(
            code="INVALID_LOCATION_ID",
            message="location_id 必須是字串。",
        )
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized:
        raise ServiceLayerError(
            code="INVALID_LOCATION_ID",
            message="location_id 不可為空。",
        )
    if len(normalized) > MAX_LOCATION_ID_LENGTH:
        raise ServiceLayerError(
            code="INVALID_LOCATION_ID",
            message=f"location_id 不可超過 {MAX_LOCATION_ID_LENGTH} 個字元。",
            details={"max_length": MAX_LOCATION_ID_LENGTH},
        )
    return normalized


def _validate_match_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceLayerError(
            code="INVALID_MATCH_LIMIT",
            message="媒合候選數量必須是整數。",
        )
    if not 1 <= value <= MAX_MATCH_LIMIT:
        raise ServiceLayerError(
            code="INVALID_MATCH_LIMIT",
            message=f"媒合候選數量必須介於 1 與 {MAX_MATCH_LIMIT} 之間。",
            details={"minimum": 1, "maximum": MAX_MATCH_LIMIT},
        )
    return value


def _validate_time_window(
    preferred_start: datetime | None,
    preferred_end: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if (preferred_start is None) != (preferred_end is None):
        raise ServiceLayerError(
            code="INVALID_TIME_WINDOW",
            message="preferred_start 與 preferred_end 必須同時提供或同時省略。",
        )
    if preferred_start is None or preferred_end is None:
        return None, None

    for field, value in (
        ("preferred_start", preferred_start),
        ("preferred_end", preferred_end),
    ):
        if not isinstance(value, datetime):
            raise ServiceLayerError(
                code="INVALID_TIME_WINDOW",
                message=f"{field} 必須是日期時間。",
                details={"field": field},
            )
        if value.tzinfo is None or value.utcoffset() is None:
            raise ServiceLayerError(
                code="INVALID_TIME_WINDOW",
                message=f"{field} 必須包含時區。",
                details={"field": field},
            )

    if preferred_end <= preferred_start:
        raise ServiceLayerError(
            code="INVALID_TIME_WINDOW",
            message="preferred_end 必須晚於 preferred_start。",
        )
    if preferred_end - preferred_start > MAX_MATCH_WINDOW:
        raise ServiceLayerError(
            code="INVALID_TIME_WINDOW",
            message="媒合時段範圍不可超過 31 天。",
            details={"maximum_days": 31},
        )
    return preferred_start, preferred_end


def _rank_provider_slots(
    slots: list[AvailableProviderSlot],
    *,
    preferred_start: datetime | None,
    preferred_end: datetime | None,
    limit: int,
) -> list[ProviderMatchCandidate]:
    if not slots:
        return []

    max_completed_jobs = max(max(slot.completed_jobs for slot in slots), 1)
    fees = [slot.base_inspection_fee for slot in slots]
    minimum_fee = min(fees)
    maximum_fee = max(fees)
    ranked: list[ProviderMatchCandidate] = []

    for slot in slots:
        schedule_fit = (
            1.0
            if preferred_start is None or preferred_end is None
            else _schedule_fit(slot, preferred_start, preferred_end)
        )
        rating_score = slot.rating / 5
        experience_score = slot.completed_jobs / max_completed_jobs
        fee_score = (
            1.0
            if maximum_fee == minimum_fee
            else (maximum_fee - slot.base_inspection_fee)
            / (maximum_fee - minimum_fee)
        )
        match_score = round(
            schedule_fit * MATCH_SCHEDULE_WEIGHT
            + rating_score * MATCH_RATING_WEIGHT
            + experience_score * MATCH_EXPERIENCE_WEIGHT
            + fee_score * MATCH_FEE_WEIGHT,
            4,
        )
        ranked.append(
            ProviderMatchCandidate(
                provider_id=slot.provider_id,
                display_name=slot.display_name,
                location_name=slot.location_name,
                availability_id=slot.availability_id,
                starts_at=slot.starts_at,
                ends_at=slot.ends_at,
                rating=slot.rating,
                completed_jobs=slot.completed_jobs,
                base_inspection_fee=slot.base_inspection_fee,
                match_score=match_score,
                score_breakdown=MatchScoreBreakdown(
                    schedule_fit=round(schedule_fit, 4),
                    rating=round(rating_score, 4),
                    experience=round(experience_score, 4),
                    fee=round(fee_score, 4),
                ),
                reasons=_match_reasons(
                    slot,
                    schedule_fit=schedule_fit,
                    has_preferred_window=preferred_start is not None,
                ),
            )
        )

    ranked.sort(
        key=lambda candidate: (
            -candidate.match_score,
            -candidate.rating,
            -candidate.completed_jobs,
            candidate.base_inspection_fee,
            candidate.starts_at,
            candidate.provider_id,
            candidate.availability_id,
        )
    )
    unique_providers: list[ProviderMatchCandidate] = []
    seen_provider_ids: set[str] = set()
    for candidate in ranked:
        if candidate.provider_id in seen_provider_ids:
            continue
        seen_provider_ids.add(candidate.provider_id)
        unique_providers.append(candidate)
        if len(unique_providers) >= limit:
            break
    return unique_providers


def _schedule_fit(
    slot: AvailableProviderSlot,
    preferred_start: datetime,
    preferred_end: datetime,
) -> float:
    overlap_start = max(slot.starts_at, preferred_start)
    overlap_end = min(slot.ends_at, preferred_end)
    if overlap_end <= overlap_start:
        return 0.0
    requested_seconds = (preferred_end - preferred_start).total_seconds()
    overlap_seconds = (overlap_end - overlap_start).total_seconds()
    return min(overlap_seconds / requested_seconds, 1.0)


def _match_reasons(
    slot: AvailableProviderSlot,
    *,
    schedule_fit: float,
    has_preferred_window: bool,
) -> list[str]:
    schedule_reason = (
        f"可用時段與偏好重疊 {round(schedule_fit * 100)}%"
        if has_preferred_window
        else "目前有可預約時段"
    )
    fee = f"{slot.base_inspection_fee:,.2f}".rstrip("0").rstrip(".")
    return [
        "服務項目符合",
        f"可服務{slot.location_name}",
        schedule_reason,
        f"評分 {slot.rating:.1f}",
        f"已完成 {slot.completed_jobs} 件",
        f"基本勘驗費 NT${fee}",
    ]
