from __future__ import annotations

import unittest
from typing import Any

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.models import (
    ConsultationForm,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)
from home_repair_agent.backend.postgres_repository import (
    FIND_LOCATIONS_SQL,
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


class StubReadRepository:
    def __init__(self) -> None:
        self.service_results: list[ServiceSummary] = []
        self.location_results: list[ResolvedLocation] = []
        self.form_results: list[ConsultationForm] = []
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
        )
        for statement in statements:
            with self.subTest(statement=statement[:40]):
                self.assertIn("agent.", statement)
                self.assertNotIn("core.", statement)
                self.assertNotIn("quarantine.", statement)
                self.assertNotIn("staging.", statement)

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
