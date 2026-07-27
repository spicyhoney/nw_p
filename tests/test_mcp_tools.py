from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from home_repair_agent.backend.models import (
    AvailableProviderSlot,
    ConsultationForm,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import (
    _read_port,
    create_mcp_server,
)


def _service() -> ServiceSummary:
    return ServiceSummary(
        service_id=17,
        service_vendor_id=11,
        vendor_name="修繕服務",
        service_type="10",
        service_type_name="水電修繕",
        name="水電修繕",
        aliases=["水電", "水龍頭漏水"],
    )


def _location() -> ResolvedLocation:
    return ResolvedLocation(
        location_id="NLSC-63000030",
        county_name="臺北市",
        district_name="大安區",
        full_name="臺北市大安區",
    )


def _form() -> ConsultationForm:
    return ConsultationForm(
        form_key="repair_form_v1",
        service_id=17,
        version=1,
        name="居家水電修繕諮詢單",
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


def _slot() -> AvailableProviderSlot:
    taipei_timezone = timezone(timedelta(hours=8))
    return AvailableProviderSlot(
        provider_id="SYN-PROVIDER-001",
        display_name="安心修繕 A 組",
        service_id=17,
        rating=4.8,
        completed_jobs=128,
        base_inspection_fee=300,
        location_id="NLSC-63000030",
        location_name="臺北市大安區",
        availability_id="SYN-SLOT-001",
        starts_at=datetime(2026, 7, 27, 13, tzinfo=taipei_timezone),
        ends_at=datetime(2026, 7, 27, 17, tzinfo=taipei_timezone),
    )


class StubReadRepository:
    def __init__(self) -> None:
        self.service_results = [_service()]
        self.location_results = [_location()]
        self.form_results = [_form()]
        self.slot_results = [_slot()]

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        return self.service_results[:limit]

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        return self.location_results

    def list_consultation_forms(
        self,
        *,
        service_id: int,
    ) -> list[ConsultationForm]:
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
        return self.slot_results[:candidate_limit]


class ExplodingReadRepository(StubReadRepository):
    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        raise RuntimeError("could not connect to postgresql://internal-user:secret@db.example")


class MCPToolProtocolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = StubReadRepository()
        self.server = create_mcp_server(ReadServiceLayer(self.repository))

    async def test_lists_exactly_four_read_only_tools(self) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as session:
            result = await session.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(
            {
                "search_services",
                "resolve_location",
                "get_consultation_form",
                "match_service_providers",
            },
            set(tools),
        )
        for tool in tools.values():
            with self.subTest(tool=tool.name):
                self.assertIsNotNone(tool.annotations)
                self.assertTrue(tool.annotations.readOnlyHint)
                self.assertFalse(tool.annotations.destructiveHint)
                self.assertTrue(tool.annotations.idempotentHint)
                self.assertFalse(tool.annotations.openWorldHint)

        self.assertEqual(
            {"county_name", "district_name"},
            set(tools["resolve_location"].inputSchema["required"]),
        )
        self.assertEqual(
            ["service_id"],
            tools["get_consultation_form"].inputSchema["required"],
        )
        self.assertEqual(
            {"service_id", "location_id"},
            set(tools["match_service_providers"].inputSchema["required"]),
        )

    async def test_calls_all_tools_with_structured_success_results(self) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as session:
            service_result = await session.call_tool(
                "search_services",
                {"query": "水龍頭漏水", "limit": 3},
            )
            location_result = await session.call_tool(
                "resolve_location",
                {"county_name": "台北市", "district_name": "大安區"},
            )
            form_result = await session.call_tool(
                "get_consultation_form",
                {"service_id": 17},
            )
            match_result = await session.call_tool(
                "match_service_providers",
                {
                    "service_id": 17,
                    "location_id": "NLSC-63000030",
                    "limit": 3,
                },
            )

        self.assertFalse(service_result.isError)
        self.assertEqual(
            17,
            service_result.structuredContent["data"]["services"][0]["service_id"],
        )
        self.assertEqual(
            "NLSC-63000030",
            location_result.structuredContent["data"]["location_id"],
        )
        self.assertEqual(
            "repair_form_v1",
            form_result.structuredContent["data"]["form_key"],
        )
        self.assertEqual(
            "SYN-PROVIDER-001",
            match_result.structuredContent["data"]["candidates"][0]["provider_id"],
        )
        self.assertEqual(
            "synthetic",
            match_result.structuredContent["data"]["data_source"],
        )
        for result in (
            service_result,
            location_result,
            form_result,
            match_result,
        ):
            with self.subTest(result=result):
                self.assertEqual(True, result.structuredContent["ok"])
                self.assertIsNone(result.structuredContent["error"])

    async def test_match_time_window_error_is_structured(self) -> None:
        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as session:
            result = await session.call_tool(
                "match_service_providers",
                {
                    "service_id": 17,
                    "location_id": "NLSC-63000030",
                    "preferred_start": "2026-07-27T13:00:00+08:00",
                },
            )

        self.assertFalse(result.isError)
        self.assertFalse(result.structuredContent["ok"])
        self.assertEqual(
            "INVALID_TIME_WINDOW",
            result.structuredContent["error"]["code"],
        )

    async def test_domain_error_remains_structured_for_agent_recovery(self) -> None:
        self.repository.location_results = []

        async with create_connected_server_and_client_session(
            self.server,
            raise_exceptions=True,
        ) as session:
            result = await session.call_tool(
                "resolve_location",
                {"county_name": "臺北市", "district_name": "不存在區"},
            )

        self.assertFalse(result.isError)
        self.assertEqual(
            {
                "ok": False,
                "data": None,
                "error": {
                    "code": "LOCATION_NOT_FOUND",
                    "message": "找不到可供 Agent 使用的縣市與行政區組合。",
                    "details": {
                        "county_name": "臺北市",
                        "district_name": "不存在區",
                    },
                },
            },
            result.structuredContent,
        )

    async def test_unexpected_error_is_masked_as_mcp_error(self) -> None:
        server = create_mcp_server(ReadServiceLayer(ExplodingReadRepository()))

        async with create_connected_server_and_client_session(
            server,
            raise_exceptions=True,
        ) as session:
            result = await session.call_tool("search_services", {})

        self.assertTrue(result.isError)
        self.assertIsNone(result.structuredContent)
        self.assertIsInstance(result.content[0], TextContent)
        self.assertIn("SERVICE_UNAVAILABLE", result.content[0].text)
        self.assertNotIn("internal-user", result.content[0].text)
        self.assertNotIn("secret", result.content[0].text)


class MCPServerConfigurationTests(unittest.TestCase):
    def test_database_url_is_required_without_injected_services(self) -> None:
        with (
            mock.patch.dict(os.environ, {"DATABASE_URL": ""}),
            self.assertRaisesRegex(RuntimeError, "DATABASE_URL"),
        ):
            create_mcp_server()

    def test_port_must_be_in_valid_range(self) -> None:
        invalid_values: list[Any] = ["abc", "0", "65536"]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _read_port(value)

        self.assertEqual(8000, _read_port("8000"))


if __name__ == "__main__":
    unittest.main()
