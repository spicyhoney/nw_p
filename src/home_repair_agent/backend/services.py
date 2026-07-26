from __future__ import annotations

import unicodedata

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.models import (
    ConsultationForm,
    ResolvedLocation,
    ServiceSearchResult,
)
from home_repair_agent.backend.ports import ReadRepository


DEFAULT_SERVICE_LIMIT = 10
MAX_SERVICE_LIMIT = 25
MAX_QUERY_LENGTH = 200
MAX_LOCATION_LENGTH = 20


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
