from __future__ import annotations

import json
import unittest
from typing import Any

import httpx

from agentcore_remote_mcp_entrypoint import (
    HOST,
    MAX_REQUEST_BODY_BYTES,
    PORT,
    SAFE_REJECTION_BODY,
    MCPRequestGuard,
    _mcp_http_app,
    app,
    mcp,
)


class RecordingASGIApp:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, bytes]] = []

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        self.requests.append((scope["method"], scope["path"], bytes(body)))
        response_body = b'{"downstream":true}'
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(response_body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": response_body})


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    request_id: str = "synthetic-request",
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


async def _request(
    asgi_app: Any,
    body: bytes,
    *,
    method: str = "POST",
    path: str = "/mcp",
) -> httpx.Response:
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://localhost",
    ) as client:
        return await client.request(
            method,
            path,
            content=body,
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
        )


class MCPRequestGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.downstream = RecordingASGIApp()
        self.guard = MCPRequestGuard(self.downstream)

    async def test_control_messages_are_forwarded_without_body_changes(self) -> None:
        payloads = (
            {
                "jsonrpc": "2.0",
                "id": "synthetic-initialize",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "synthetic-test-client", "version": "1.0"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": "synthetic-list",
                "method": "tools/list",
                "params": {},
            },
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            {
                "jsonrpc": "2.0",
                "id": "synthetic-ping",
                "method": "ping",
                "params": {},
            },
        )

        expected_bodies: list[bytes] = []
        for payload in payloads:
            raw_body = _json_bytes(payload)
            expected_bodies.append(raw_body)
            with self.subTest(method=payload["method"]):
                response = await _request(self.guard, raw_body)
                self.assertEqual(200, response.status_code)

        self.assertEqual(
            expected_bodies,
            [request[2] for request in self.downstream.requests],
        )

    async def test_exact_four_tools_and_existing_arguments_are_forwarded(self) -> None:
        calls = (
            _tool_call("search_services", {"query": "合成水龍頭漏水", "limit": 3}),
            _tool_call(
                "resolve_location",
                {"county_name": "測試市", "district_name": "測試區"},
            ),
            _tool_call("get_consultation_form", {"service_id": 17}),
            _tool_call(
                "match_service_providers",
                {
                    "service_id": 17,
                    "location_id": "DEMO-63000030",
                    "preferred_start": "2030-01-05T13:00:00+08:00",
                    "preferred_end": "2030-01-05T17:00:00+08:00",
                    "limit": 2,
                },
            ),
        )

        expected_bodies: list[bytes] = []
        for call in calls:
            raw_body = _json_bytes(call)
            expected_bodies.append(raw_body)
            with self.subTest(tool=call["params"]["name"]):
                response = await _request(self.guard, raw_body)
                self.assertEqual(200, response.status_code)

        self.assertEqual(
            expected_bodies,
            [request[2] for request in self.downstream.requests],
        )

    async def test_valid_batch_is_forwarded(self) -> None:
        batch = [
            {
                "jsonrpc": "2.0",
                "id": "synthetic-ping",
                "method": "ping",
                "params": {},
            },
            _tool_call("search_services", {}),
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        ]
        raw_body = _json_bytes(batch)

        response = await _request(self.guard, raw_body)

        self.assertEqual(200, response.status_code)
        self.assertEqual(raw_body, self.downstream.requests[0][2])

    async def test_invalid_json_rpc_and_unknown_keys_are_rejected(self) -> None:
        invalid_bodies = (
            b"not-json",
            b"[]",
            b"null",
            _json_bytes([{"jsonrpc": "2.0", "id": "synthetic", "method": "ping"}, 7]),
            _json_bytes(
                {
                    "jsonrpc": "2.0",
                    "id": "synthetic",
                    "method": "unknown/method",
                    "params": {},
                }
            ),
            _json_bytes(
                {
                    "jsonrpc": "2.0",
                    "id": "synthetic",
                    "method": "ping",
                    "params": {},
                    "extra": "blocked",
                }
            ),
            (
                b'{"jsonrpc":"2.0","id":"synthetic","method":"ping",'
                b'"method":"tools/list","params":{}}'
            ),
        )

        for raw_body in invalid_bodies:
            with self.subTest(raw_body=raw_body[:24]):
                response = await _request(self.guard, raw_body)
                self.assertEqual(400, response.status_code)
                self.assertEqual(SAFE_REJECTION_BODY, response.content)

        self.assertEqual([], self.downstream.requests)

    async def test_unknown_tools_extra_arguments_and_wrong_types_are_rejected(self) -> None:
        invalid_calls = (
            _tool_call("synthetic_unknown_tool", {}),
            _tool_call("search_services", {"unexpected": "blocked"}),
            _tool_call("resolve_location", {"county_name": "測試市"}),
            _tool_call("get_consultation_form", {"service_id": True}),
            {
                "jsonrpc": "2.0",
                "id": "synthetic",
                "method": "tools/call",
                "params": {
                    "name": "search_services",
                    "arguments": {},
                    "extra": "blocked",
                },
            },
        )

        for call in invalid_calls:
            with self.subTest(call=call):
                response = await _request(self.guard, _json_bytes(call))
                self.assertEqual(400, response.status_code)
                self.assertEqual(SAFE_REJECTION_BODY, response.content)

        self.assertEqual([], self.downstream.requests)

    async def test_sensitive_or_binary_like_content_is_rejected_without_echo(self) -> None:
        synthetic_sensitive_queries = (
            "SYNTHETIC_EMAIL: " + "synthetic.user" + "@example.invalid",
            "SYNTHETIC_TW_PHONE: " + "0900" + "-000-000",
            "SYNTHETIC_EXACT_ADDRESS: 測試路" + "123號",
            "SYNTHETIC_NAME: 姓名：測試使用者",
            "SYNTHETIC_IMAGE: data:image/png;base64,AAAA",
        )

        for query in synthetic_sensitive_queries:
            raw_body = _json_bytes(_tool_call("search_services", {"query": query}))
            with self.subTest(marker=query.split(":", 1)[0]):
                response = await _request(self.guard, raw_body)
                self.assertEqual(400, response.status_code)
                self.assertEqual(SAFE_REJECTION_BODY, response.content)
                self.assertNotIn(query.encode("utf-8"), response.content)

        self.assertEqual([], self.downstream.requests)

    async def test_body_over_64_kib_is_rejected(self) -> None:
        raw_body = _json_bytes(
            _tool_call("search_services", {"query": "X" * MAX_REQUEST_BODY_BYTES})
        )
        self.assertGreater(len(raw_body), MAX_REQUEST_BODY_BYTES)

        response = await _request(self.guard, raw_body)

        self.assertEqual(413, response.status_code)
        self.assertEqual(SAFE_REJECTION_BODY, response.content)
        self.assertEqual([], self.downstream.requests)

    async def test_only_post_to_exact_mcp_path_is_intercepted(self) -> None:
        invalid_body = b"not-json"

        other_path_response = await _request(self.guard, invalid_body, path="/health")
        get_response = await _request(self.guard, invalid_body, method="GET")

        self.assertEqual(200, other_path_response.status_code)
        self.assertEqual(200, get_response.status_code)
        self.assertEqual(
            [("POST", "/health", invalid_body), ("GET", "/mcp", invalid_body)],
            self.downstream.requests,
        )


class MCPEntrypointIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_exported_app_serves_guarded_fastmcp_protocol(self) -> None:
        self.assertEqual(HOST, mcp.settings.host)
        self.assertEqual(PORT, mcp.settings.port)

        initialize = {
            "jsonrpc": "2.0",
            "id": "synthetic-initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "synthetic-asgi-client", "version": "1.0"},
            },
        }
        list_tools = {
            "jsonrpc": "2.0",
            "id": "synthetic-list",
            "method": "tools/list",
            "params": {},
        }
        call_tool = _tool_call(
            "search_services",
            {"query": "水龍頭漏水", "limit": 1},
            request_id="synthetic-call",
        )

        async with _mcp_http_app.router.lifespan_context(_mcp_http_app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://localhost",
                headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                },
            ) as client:
                initialize_response = await client.post("/mcp", content=_json_bytes(initialize))
                tools_response = await client.post("/mcp", content=_json_bytes(list_tools))
                call_response = await client.post("/mcp", content=_json_bytes(call_tool))

        self.assertEqual(200, initialize_response.status_code)
        self.assertEqual(200, tools_response.status_code)
        self.assertEqual(200, call_response.status_code)
        tool_names = {tool["name"] for tool in tools_response.json()["result"]["tools"]}
        self.assertEqual(
            {
                "search_services",
                "resolve_location",
                "get_consultation_form",
                "match_service_providers",
            },
            tool_names,
        )
        self.assertNotIn("error", call_response.json())


if __name__ == "__main__":
    unittest.main()
