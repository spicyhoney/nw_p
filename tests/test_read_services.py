from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.models import (
    AvailableProviderSlot,
    ConsultationForm,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)
from home_repair_agent.backend.postgres_repository import (
    FIND_LOCATIONS_SQL,
    LIST_AVAILABLE_PROVIDER_SLOTS_SQL,
    LIST_CONSULTATION_FORMS_SQL,
    SEARCH_SERVICES_SQL,
    _assemble_forms,
)
from home_repair_agent.backend.services import ReadServiceLayer


def _service(service_id: int = 17) -> ServiceSummary:
    return ServiceSummary(
        service_id=service_id,
        service_vendor_id=11,
        vendor_name="修繕服務",
        service_type="10",
        service_type_name="水電修繕",
        name="水電修繕",
        description="",
        aliases=["水電", "水龍頭漏水"],
    )


def _location(location_id: str = "NLSC-63000030") -> ResolvedLocation:
    return ResolvedLocation(
        location_id=location_id,
        county_name="台北市",
        district_name="大安區",
        full_name="台北市大安區",
        postal_code=None,
    )


def _form(form_key: str, version: int) -> ConsultationForm:
    return ConsultationForm(
        form_key=form_key,
        service_id=17,
        version=version,
        name="居家水電修繕諮詢單",
        description="",
        topics=[
            FormTopic(
                topic_key="issue_category",
                input_type="single_select",
                title="需要處理的問題",
                is_required=True,
                sort_order=1,
            )
        ],
    )


def _slot(
    *,
    provider_id: str = "SYN-PROVIDER-001",
    availability_id: str = "SYN-SLOT-001",
    start_hour: int = 13,
    end_hour: int = 17,
    rating: float = 4.8,
    completed_jobs: int = 128,
    fee: float = 300,
) -> AvailableProviderSlot:
    taipei_timezone = timezone(timedelta(hours=8))
    return AvailableProviderSlot(
        provider_id=provider_id,
        display_name=f"師傅 {provider_id[-3:]}",
        service_id=17,
        rating=rating,
        completed_jobs=completed_jobs,
        base_inspection_fee=fee,
        location_id="NLSC-63000030",
        location_name="台北市大安區",
        availability_id=availability_id,
        starts_at=datetime(2026, 7, 27, start_hour, tzinfo=taipei_timezone),
        ends_at=datetime(2026, 7, 27, end_hour, tzinfo=taipei_timezone),
    )


class StubReadRepository:
    def __init__(self) -> None:
        self.service_results: list[ServiceSummary] = []
        self.location_results: list[ResolvedLocation] = []
        self.form_results: list[ConsultationForm] = []
        self.slot_results: list[AvailableProviderSlot] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        self.calls.append(("search_services", {"query": query, "limit": limit}))
        return self.service_results

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        self.calls.append(
            (
                "find_locations",
                {
                    "county_name": county_name,
                    "county_base": county_base,
                    "district_name": district_name,
                    "district_base": district_base,
                },
            )
        )
        return self.location_results

    def list_consultation_forms(
        self,
        *,
        service_id: int,
    ) -> list[ConsultationForm]:
        self.calls.append(
            ("list_consultation_forms", {"service_id": service_id})
        )
        return self.form_results

    def list_available_provider_slots(
        self,
        *,
        service_id: int,
        location_id: str,
        preferred_start: datetime | None,
        preferred_end: datetime | None,
        candidate_limit: int,
    ) -> list[AvailableProviderSlot]:
        self.calls.append(
            (
                "list_available_provider_slots",
                {
                    "service_id": service_id,
                    "location_id": location_id,
                    "preferred_start": preferred_start,
                    "preferred_end": preferred_end,
                    "candidate_limit": candidate_limit,
                },
            )
        )
        return self.slot_results


class ReadServiceLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = StubReadRepository()
        self.service_layer = ReadServiceLayer(self.repository)

    def test_search_services_normalizes_query_and_returns_count(self) -> None:
        self.repository.service_results = [_service()]

        result = self.service_layer.search_services(
            "  水龍頭　漏水  ",
            limit=3,
        )

        self.assertEqual("水龍頭 漏水", result.query)
        self.assertEqual(1, result.count)
        self.assertEqual(17, result.services[0].service_id)
        self.assertEqual(
            ("search_services", {"query": "水龍頭 漏水", "limit": 3}),
            self.repository.calls[0],
        )

    def test_search_services_without_query_lists_catalog(self) -> None:
        self.repository.service_results = [_service(17), _service(4)]

        result = self.service_layer.search_services()

        self.assertIsNone(result.query)
        self.assertEqual(2, result.count)
        self.assertEqual(
            ("search_services", {"query": "", "limit": 10}),
            self.repository.calls[0],
        )

    def test_search_services_rejects_invalid_query_and_limit(self) -> None:
        invalid_cases = [
            ({"query": 123}, "INVALID_QUERY"),
            ({"query": "x" * 201}, "INVALID_QUERY"),
            ({"limit": True}, "INVALID_LIMIT"),
            ({"limit": 0}, "INVALID_LIMIT"),
            ({"limit": 26}, "INVALID_LIMIT"),
        ]
        for arguments, expected_code in invalid_cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ServiceLayerError) as raised:
                    self.service_layer.search_services(**arguments)
                self.assertEqual(expected_code, raised.exception.code)

        self.assertEqual([], self.repository.calls)

    def test_resolve_location_normalizes_tai_and_optional_suffixes(self) -> None:
        self.repository.location_results = [_location()]

        result = self.service_layer.resolve_location(
            county_name=" 台北市 ",
            district_name="大安",
        )

        self.assertEqual("NLSC-63000030", result.location_id)
        self.assertEqual(
            (
                "find_locations",
                {
                    "county_name": "臺北市",
                    "county_base": "臺北",
                    "district_name": "大安",
                    "district_base": "大安",
                },
            ),
            self.repository.calls[0],
        )

    def test_resolve_location_does_not_guess_missing_result(self) -> None:
        with self.assertRaises(ServiceLayerError) as raised:
            self.service_layer.resolve_location(
                county_name="台北市",
                district_name="不存在區",
            )

        self.assertEqual("LOCATION_NOT_FOUND", raised.exception.code)

    def test_resolve_location_does_not_guess_ambiguous_result(self) -> None:
        self.repository.location_results = [
            _location("NLSC-A"),
            _location("NLSC-B"),
        ]

        with self.assertRaises(ServiceLayerError) as raised:
            self.service_layer.resolve_location(
                county_name="台北市",
                district_name="大安區",
            )

        self.assertEqual("LOCATION_AMBIGUOUS", raised.exception.code)
        self.assertEqual(
            ["NLSC-A", "NLSC-B"],
            raised.exception.details["candidate_location_ids"],
        )

    def test_get_consultation_form_uses_unique_latest_version(self) -> None:
        self.repository.form_results = [
            _form("repair_form_v1", 1),
            _form("repair_form_v2", 2),
        ]

        result = self.service_layer.get_consultation_form(service_id=17)

        self.assertEqual("repair_form_v2", result.form_key)
        self.assertEqual(2, result.version)

    def test_get_consultation_form_rejects_missing_or_ambiguous_form(self) -> None:
        with self.assertRaises(ServiceLayerError) as missing:
            self.service_layer.get_consultation_form(service_id=2)
        self.assertEqual("FORM_NOT_FOUND", missing.exception.code)

        self.repository.form_results = [
            _form("repair_form_v2a", 2),
            _form("repair_form_v2b", 2),
        ]
        with self.assertRaises(ServiceLayerError) as ambiguous:
            self.service_layer.get_consultation_form(service_id=17)
        self.assertEqual("FORM_AMBIGUOUS", ambiguous.exception.code)

    def test_get_consultation_form_rejects_invalid_service_id(self) -> None:
        for value in (True, 0, -1, "17"):
            with self.subTest(value=value):
                with self.assertRaises(ServiceLayerError) as raised:
                    self.service_layer.get_consultation_form(service_id=value)
                self.assertEqual("INVALID_SERVICE_ID", raised.exception.code)

        self.assertEqual([], self.repository.calls)

    def test_match_service_providers_ranks_and_deduplicates_candidates(
        self,
    ) -> None:
        self.repository.slot_results = [
            _slot(),
            _slot(
                provider_id="SYN-PROVIDER-002",
                availability_id="SYN-SLOT-002",
                start_hour=14,
                end_hour=18,
                rating=4.6,
                completed_jobs=86,
                fee=250,
            ),
            _slot(
                provider_id="SYN-PROVIDER-001",
                availability_id="SYN-SLOT-004",
                start_hour=15,
                end_hour=18,
                fee=350,
            ),
            _slot(
                provider_id="SYN-PROVIDER-003",
                availability_id="SYN-SLOT-003",
                start_hour=9,
                end_hour=12,
                rating=5,
                completed_jobs=999,
                fee=100,
            ),
        ]
        taipei_timezone = timezone(timedelta(hours=8))
        preferred_start = datetime(2026, 7, 27, 13, tzinfo=taipei_timezone)
        preferred_end = datetime(2026, 7, 27, 17, tzinfo=taipei_timezone)

        result = self.service_layer.match_service_providers(
            service_id=17,
            location_id=" NLSC-63000030 ",
            preferred_start=preferred_start,
            preferred_end=preferred_end,
            limit=3,
        )

        self.assertEqual(2, result.count)
        self.assertEqual(
            ["SYN-PROVIDER-001", "SYN-PROVIDER-002"],
            [candidate.provider_id for candidate in result.candidates],
        )
        self.assertGreater(
            result.candidates[0].match_score,
            result.candidates[1].match_score,
        )
        self.assertEqual("synthetic", result.data_source)
        self.assertEqual("synthetic", result.candidates[0].source_type)
        self.assertEqual("台北市大安區", result.candidates[0].location_name)
        self.assertEqual(1.0, result.candidates[0].score_breakdown.schedule_fit)
        self.assertIn(
            "可用時段與偏好重疊 100%",
            result.candidates[0].reasons,
        )
        self.assertEqual(
            (
                "list_available_provider_slots",
                {
                    "service_id": 17,
                    "location_id": "NLSC-63000030",
                    "preferred_start": preferred_start,
                    "preferred_end": preferred_end,
                    "candidate_limit": 100,
                },
            ),
            self.repository.calls[0],
        )

    def test_match_service_providers_returns_empty_without_guessing(self) -> None:
        result = self.service_layer.match_service_providers(
            service_id=17,
            location_id="NLSC-65000010",
        )

        self.assertEqual(0, result.count)
        self.assertEqual([], result.candidates)
        self.assertIsNone(result.preferred_start)
        self.assertIsNone(result.preferred_end)

    def test_match_service_providers_rejects_invalid_inputs(self) -> None:
        aware_start = datetime(2026, 7, 27, 13, tzinfo=UTC)
        aware_end = datetime(2026, 7, 27, 17, tzinfo=UTC)
        invalid_cases = [
            ({"service_id": 0, "location_id": "NLSC-A"}, "INVALID_SERVICE_ID"),
            ({"service_id": 17, "location_id": ""}, "INVALID_LOCATION_ID"),
            ({"service_id": 17, "location_id": 123}, "INVALID_LOCATION_ID"),
            (
                {
                    "service_id": 17,
                    "location_id": "NLSC-A",
                    "preferred_start": aware_start,
                },
                "INVALID_TIME_WINDOW",
            ),
            (
                {
                    "service_id": 17,
                    "location_id": "NLSC-A",
                    "preferred_start": aware_start.replace(tzinfo=None),
                    "preferred_end": aware_end.replace(tzinfo=None),
                },
                "INVALID_TIME_WINDOW",
            ),
            (
                {
                    "service_id": 17,
                    "location_id": "NLSC-A",
                    "preferred_start": aware_end,
                    "preferred_end": aware_start,
                },
                "INVALID_TIME_WINDOW",
            ),
            (
                {
                    "service_id": 17,
                    "location_id": "NLSC-A",
                    "preferred_start": aware_start,
                    "preferred_end": aware_start + timedelta(days=32),
                },
                "INVALID_TIME_WINDOW",
            ),
            (
                {"service_id": 17, "location_id": "NLSC-A", "limit": 0},
                "INVALID_MATCH_LIMIT",
            ),
            (
                {"service_id": 17, "location_id": "NLSC-A", "limit": 11},
                "INVALID_MATCH_LIMIT",
            ),
            (
                {"service_id": 17, "location_id": "NLSC-A", "limit": True},
                "INVALID_MATCH_LIMIT",
            ),
        ]
        for arguments, expected_code in invalid_cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(ServiceLayerError) as raised:
                    self.service_layer.match_service_providers(**arguments)
                self.assertEqual(expected_code, raised.exception.code)

        self.assertEqual([], self.repository.calls)

    def test_provider_slot_requires_ordered_timezone_aware_times(self) -> None:
        valid_slot = _slot()
        invalid_windows = [
            {
                "starts_at": valid_slot.starts_at.replace(tzinfo=None),
                "ends_at": valid_slot.ends_at.replace(tzinfo=None),
            },
            {
                "starts_at": valid_slot.ends_at,
                "ends_at": valid_slot.starts_at,
            },
        ]
        for window in invalid_windows:
            with self.subTest(window=window), self.assertRaises(ValidationError):
                AvailableProviderSlot.model_validate(
                    {
                        **valid_slot.model_dump(),
                        **window,
                    }
                )

    def test_expected_error_has_stable_agent_safe_shape(self) -> None:
        error = ServiceLayerError(
            code="LOCATION_NOT_FOUND",
            message="找不到行政區。",
            details={"county_name": "臺北市"},
        )

        self.assertEqual(
            {
                "ok": False,
                "error": {
                    "code": "LOCATION_NOT_FOUND",
                    "message": "找不到行政區。",
                    "details": {"county_name": "臺北市"},
                },
            },
            error.as_dict(),
        )


class PostgresReadRepositoryContractTests(unittest.TestCase):
    def test_queries_only_reference_agent_safe_views(self) -> None:
        statements = (
            SEARCH_SERVICES_SQL,
            FIND_LOCATIONS_SQL,
            LIST_CONSULTATION_FORMS_SQL,
            LIST_AVAILABLE_PROVIDER_SLOTS_SQL,
        )
        for statement in statements:
            with self.subTest(statement=statement[:40]):
                self.assertIn("agent.", statement)
                self.assertNotIn("core.", statement)
                self.assertNotIn("quarantine.", statement)
                self.assertNotIn("staging.", statement)
                self.assertNotIn("demo.", statement)

    def test_form_rows_are_assembled_into_topics_and_options(self) -> None:
        rows = [
            {
                "form_key": "repair_form_v1",
                "service_id": 17,
                "version": 1,
                "form_name": "居家水電修繕諮詢單",
                "form_description": "",
                "topic_key": "issue_category",
                "input_type": "single_select",
                "topic_title": "需要處理的問題",
                "is_required": True,
                "topic_sort_order": 1,
                "config": {},
                "option_key": "issue_category:faucet_leak",
                "option_value": "faucet_leak",
                "option_label": "水龍頭漏水",
                "option_sort_order": 1,
            },
            {
                "form_key": "repair_form_v1",
                "service_id": 17,
                "version": 1,
                "form_name": "居家水電修繕諮詢單",
                "form_description": "",
                "topic_key": "issue_category",
                "input_type": "single_select",
                "topic_title": "需要處理的問題",
                "is_required": True,
                "topic_sort_order": 1,
                "config": {},
                "option_key": "issue_category:other",
                "option_value": "other",
                "option_label": "其他水電問題",
                "option_sort_order": 2,
            },
        ]

        forms = _assemble_forms(rows)

        self.assertEqual(1, len(forms))
        self.assertEqual(1, len(forms[0].topics))
        self.assertEqual(2, len(forms[0].topics[0].options))
        self.assertEqual(
            ["faucet_leak", "other"],
            [option.value for option in forms[0].topics[0].options],
        )


if __name__ == "__main__":
    unittest.main()
