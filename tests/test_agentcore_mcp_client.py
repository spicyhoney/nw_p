from __future__ import annotations

import asyncio
import logging
import time
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Self

import httpx

from home_repair_agent.agent.agentcore_mcp_client import (
    AgentCoreMCPConfigurationError,
    AgentCoreMCPError,
    AgentCoreMCPSettings,
    AgentCoreMCPToolClient,
    AgentCoreSigV4Auth,
    create_agentcore_mcp_tool_client,
)


def _synthetic_runtime_arn() -> str:
    account = "".join("0" for _ in range(12))
    return f"arn:aws:bedrock-agentcore:us-west-2:{account}:runtime/synthetic-test"


def _settings(*, qualifier: str = "DEFAULT") -> AgentCoreMCPSettings:
    return AgentCoreMCPSettings.from_env(
        {
            "AGENTCORE_RUNTIME_ARN": _synthetic_runtime_arn(),
            "AGENTCORE_REGION": "us-west-2",
            "AGENTCORE_QUALIFIER": qualifier,
        }
    )


class FakeFrozenCredentials:
    access_key = "a"
    secret_key = "b"
    token = None


class FakeCredentials:
    def __init__(
        self,
        *,
        expiry_time: datetime | None = None,
        failure_detail: str | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._expiry_time = expiry_time
        self.failure_detail = failure_detail
        self.delay_seconds = delay_seconds
        self.freeze_count = 0

    def get_frozen_credentials(self) -> FakeFrozenCredentials:
        self.freeze_count += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.failure_detail is not None:
            raise RuntimeError(self.failure_detail)
        return FakeFrozenCredentials()


class FakeBotoSession:
    def __init__(self, credentials: FakeCredentials | None) -> None:
        self.credentials = credentials
        self.get_count = 0

    def get_credentials(self) -> FakeCredentials | None:
        self.get_count += 1
        return self.credentials


class FakeHTTPClient:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> Self:
        self.events.append("http_enter")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.events.append("http_exit")


class FakeTransport:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self) -> tuple[object, object, Any]:
        self.events.append("transport_enter")
        return object(), object(), lambda: None

    async def __aexit__(self, *args: object) -> None:
        self.events.append("transport_exit")


class FakeMCPClientSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.initialize_failure: str | None = None
        self.list_failure: str | None = None
        self.call_failure: str | None = None
        self.cancel_initialize = False
        self.result_is_error = False
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __aenter__(self) -> Self:
        self.events.append("session_enter")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.events.append("session_exit")

    async def initialize(self) -> None:
        self.events.append("initialize")
        if self.cancel_initialize:
            raise asyncio.CancelledError()
        if self.initialize_failure is not None:
            raise RuntimeError(self.initialize_failure)

    async def list_tools(self) -> Any:
        if self.list_failure is not None:
            raise RuntimeError(self.list_failure)
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search_services",
                    title="Search services",
                    description="Search the controlled catalog",
                    inputSchema={"type": "object"},
                    annotations=None,
                )
            ]
        )

    async def call_tool(self, name: str, arguments: dict[str, object]) -> Any:
        self.calls.append((name, arguments))
        if self.call_failure is not None:
            raise RuntimeError(self.call_failure)
        return SimpleNamespace(
            structuredContent={
                "ok": not self.result_is_error,
                "data": {"count": 1} if not self.result_is_error else None,
                "error": (
                    {"code": "REMOTE_ERROR", "message": "Unable to complete request."}
                    if self.result_is_error
                    else None
                ),
            },
            content=[],
            isError=self.result_is_error,
        )


class FakeConnectionFactories:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.session = FakeMCPClientSession(self.events)
        self.requested_url: str | None = None
        self.received_auth: httpx.Auth | None = None
        self.received_timeout: httpx.Timeout | None = None
        self.log_transport_url = False

    def http_client_factory(
        self,
        *,
        auth: httpx.Auth,
        timeout: httpx.Timeout,
    ) -> FakeHTTPClient:
        self.received_auth = auth
        self.received_timeout = timeout
        return FakeHTTPClient(self.events)

    def transport_factory(
        self,
        url: str,
        *,
        http_client: FakeHTTPClient,
    ) -> FakeTransport:
        del http_client
        self.requested_url = url
        if self.log_transport_url:
            logging.getLogger("httpx").info("HTTP Request: POST %s", url)
        return FakeTransport(self.events)

    def client_session_factory(
        self,
        read_stream: object,
        write_stream: object,
    ) -> FakeMCPClientSession:
        del read_stream, write_stream
        return self.session


def _client(
    factories: FakeConnectionFactories,
    *,
    credentials: FakeCredentials | None = None,
) -> AgentCoreMCPToolClient:
    return AgentCoreMCPToolClient(
        _settings(qualifier="DEFAULT"),
        boto3_session=FakeBotoSession(credentials or FakeCredentials()),
        http_client_factory=factories.http_client_factory,
        transport_factory=factories.transport_factory,
        client_session_factory=factories.client_session_factory,
    )


class AgentCoreMCPSettingsTests(unittest.TestCase):
    def test_settings_are_controlled_and_runtime_identifier_is_masked(self) -> None:
        runtime_arn = _synthetic_runtime_arn()
        settings = _settings(qualifier="DEMO")

        self.assertEqual("us-west-2", settings.region)
        self.assertEqual("DEMO", settings.qualifier)
        self.assertNotIn(runtime_arn, repr(settings))
        self.assertEqual("**********", str(settings.runtime_arn))

        with self.assertRaises(AgentCoreMCPConfigurationError) as missing:
            AgentCoreMCPSettings.from_env({})
        self.assertNotIn(runtime_arn, str(missing.exception))

        with self.assertRaises(AgentCoreMCPConfigurationError) as invalid:
            AgentCoreMCPSettings.from_env(
                {
                    "AGENTCORE_RUNTIME_ARN": runtime_arn,
                    "AGENTCORE_REGION": "us-east-1",
                }
            )
        self.assertNotIn(runtime_arn, str(invalid.exception))

    def test_factory_rejects_ambiguous_configuration(self) -> None:
        with self.assertRaises(AgentCoreMCPConfigurationError):
            create_agentcore_mcp_tool_client(settings=_settings(), environ={})

    def test_sigv4_loads_refreshable_credentials_for_every_request(self) -> None:
        credentials = FakeCredentials(expiry_time=datetime.now(UTC) + timedelta(minutes=5))
        session = FakeBotoSession(credentials)
        auth = AgentCoreSigV4Auth(
            credential_session=session,
            region="us-west-2",
        )

        for _ in range(2):
            request = httpx.Request(
                "POST",
                "https://example.invalid/invocations",
                content=b"{}",
            )
            signed_request = next(iter(auth.auth_flow(request)))
            self.assertIn("authorization", signed_request.headers)

        self.assertEqual(2, session.get_count)
        self.assertEqual(2, credentials.freeze_count)


class AgentCoreMCPToolClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_sigv4_refresh_does_not_block_the_event_loop(self) -> None:
        credentials = FakeCredentials(delay_seconds=0.08)
        auth = AgentCoreSigV4Auth(
            credential_session=FakeBotoSession(credentials),
            region="us-west-2",
        )
        request = httpx.Request(
            "POST",
            "https://example.invalid/invocations",
            content=b"{}",
        )

        async def sign() -> httpx.Request:
            return await anext(auth.async_auth_flow(request))

        signing = asyncio.create_task(sign())
        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.04)
        signed = await signing

        self.assertIn("authorization", signed.headers)

    async def test_initialize_list_call_and_close_use_existing_mapping(self) -> None:
        factories = FakeConnectionFactories()
        client = _client(factories)

        async with client as connected:
            self.assertIs(client, connected)
            self.assertEqual(
                ["http_enter", "transport_enter", "session_enter", "initialize"],
                factories.events,
            )
            tools = await connected.list_tools()
            result = await connected.call_tool(
                name="search_services",
                arguments={"query": "synthetic leak"},
            )

        self.assertEqual(["search_services"], [tool.name for tool in tools])
        self.assertEqual({"type": "object"}, tools[0].input_schema)
        self.assertFalse(result.mcp_is_error)
        self.assertEqual(1, result.payload["data"]["count"])
        self.assertEqual(
            [("search_services", {"query": "synthetic leak"})],
            factories.session.calls,
        )
        self.assertEqual(
            [
                "http_enter",
                "transport_enter",
                "session_enter",
                "initialize",
                "session_exit",
                "transport_exit",
                "http_exit",
            ],
            factories.events,
        )
        self.assertIn("qualifier=DEFAULT", factories.requested_url or "")

    async def test_mcp_error_result_preserves_tool_result_mapping(self) -> None:
        factories = FakeConnectionFactories()
        factories.session.result_is_error = True

        async with _client(factories) as connected:
            result = await connected.call_tool(name="search_services", arguments={})

        self.assertTrue(result.mcp_is_error)
        self.assertFalse(result.payload["ok"])
        self.assertEqual("REMOTE_ERROR", result.payload["error"]["code"])

    async def test_initialize_failure_is_masked_and_closes_every_context(self) -> None:
        factories = FakeConnectionFactories()
        runtime_arn = _synthetic_runtime_arn()
        factories.session.initialize_failure = f"upstream-detail {runtime_arn}"

        with self.assertRaises(AgentCoreMCPError) as raised:
            async with _client(factories):
                self.fail("an initialization failure must not yield a client")

        message = str(raised.exception)
        self.assertNotIn(runtime_arn, message)
        self.assertNotIn("upstream-detail", message)
        self.assertEqual(
            [
                "http_enter",
                "transport_enter",
                "session_enter",
                "initialize",
                "session_exit",
                "transport_exit",
                "http_exit",
            ],
            factories.events,
        )

    async def test_initialize_cancellation_closes_every_entered_context(self) -> None:
        factories = FakeConnectionFactories()
        factories.session.cancel_initialize = True

        with self.assertRaises(asyncio.CancelledError):
            async with _client(factories):
                self.fail("a cancelled initialization must not yield a client")

        self.assertEqual(
            [
                "http_enter",
                "transport_enter",
                "session_enter",
                "initialize",
                "session_exit",
                "transport_exit",
                "http_exit",
            ],
            factories.events,
        )

    async def test_transport_logs_redact_runtime_identifier(self) -> None:
        factories = FakeConnectionFactories()
        factories.log_transport_url = True
        runtime_arn = _synthetic_runtime_arn()
        account_id = runtime_arn.split(":")[4]

        with self.assertLogs("httpx", level="INFO") as captured:
            async with _client(factories):
                pass

        output = "\n".join(captured.output)
        self.assertNotIn(runtime_arn, output)
        self.assertNotIn(account_id, output)
        self.assertNotIn("synthetic-test", output)
        self.assertIn("[REDACTED]", output)

    async def test_expired_credentials_fail_before_transport_without_details(self) -> None:
        factories = FakeConnectionFactories()
        runtime_arn = _synthetic_runtime_arn()
        credentials = FakeCredentials(
            expiry_time=datetime.now(UTC) - timedelta(seconds=1),
            failure_detail=f"upstream-detail {runtime_arn}",
        )

        with self.assertRaises(AgentCoreMCPError) as raised:
            async with _client(factories, credentials=credentials):
                self.fail("expired credentials must fail closed")

        message = str(raised.exception)
        self.assertNotIn(runtime_arn, message)
        self.assertNotIn("upstream-detail", message)
        self.assertEqual([], factories.events)

    async def test_missing_credentials_fail_before_transport(self) -> None:
        factories = FakeConnectionFactories()
        client = AgentCoreMCPToolClient(
            _settings(),
            boto3_session=FakeBotoSession(None),
            http_client_factory=factories.http_client_factory,
            transport_factory=factories.transport_factory,
            client_session_factory=factories.client_session_factory,
        )

        with self.assertRaisesRegex(
            AgentCoreMCPError,
            "AWS credentials are unavailable or expired",
        ):
            async with client:
                self.fail("missing credentials must fail closed")
        self.assertEqual([], factories.events)

    async def test_remote_operation_exceptions_never_expose_payload_or_arn(self) -> None:
        factories = FakeConnectionFactories()
        runtime_arn = _synthetic_runtime_arn()
        detail = f"upstream-detail {runtime_arn}"

        async with _client(factories) as connected:
            factories.session.list_failure = detail
            with self.assertRaises(AgentCoreMCPError) as list_error:
                await connected.list_tools()
            factories.session.list_failure = None
            factories.session.call_failure = detail
            with self.assertRaises(AgentCoreMCPError) as call_error:
                await connected.call_tool(name="search_services", arguments={})

        for error in (list_error.exception, call_error.exception):
            message = str(error)
            self.assertNotIn(runtime_arn, message)
            self.assertNotIn("upstream-detail", message)

    async def test_calls_outside_context_fail_closed(self) -> None:
        factories = FakeConnectionFactories()
        client = _client(factories)

        with self.assertRaisesRegex(AgentCoreMCPError, "not connected"):
            await client.list_tools()
        async with client:
            pass
        with self.assertRaisesRegex(AgentCoreMCPError, "not connected"):
            await client.call_tool(name="search_services", arguments={})


if __name__ == "__main__":
    unittest.main()
