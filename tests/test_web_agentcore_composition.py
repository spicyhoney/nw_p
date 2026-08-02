from __future__ import annotations

import os
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.web.app import create_app


class _RemoteToolClient:
    async def list_tools(self):  # pragma: no cover - composition tests do not invoke tools.
        return []

    async def call_tool(self, *, name: str, arguments: dict[str, object]):
        del name, arguments
        raise AssertionError("The composition test must not invoke a remote tool.")


class WebAgentCoreCompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reference_time = datetime(2026, 7, 27, 10, tzinfo=TAIPEI_TIMEZONE)

    def test_remote_transport_enters_once_and_is_shared_by_runner_and_service(self) -> None:
        remote_client = _RemoteToolClient()
        lifecycle: list[str] = []

        @asynccontextmanager
        async def remote_context():
            lifecycle.append("enter")
            try:
                yield remote_client
            finally:
                lifecycle.append("exit")

        with (
            patch.dict(
                os.environ,
                {"TOOL_TRANSPORT": "agentcore_remote_mcp", "WEB_MODEL_PROVIDER": "mock"},
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app.create_agentcore_mcp_tool_client",
                return_value=remote_context(),
            ) as factory,
            patch("home_repair_agent.web.app.create_mcp_server") as local_server,
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            service = client.app.state.web_sessions
            self.assertIs(remote_client, service._tool_client)
            self.assertIs(remote_client, service._runner._tool_client)
            self.assertEqual(["enter"], lifecycle)
            self.assertEqual(200, client.get("/api/health").status_code)

        factory.assert_called_once_with()
        local_server.assert_not_called()
        self.assertEqual(["enter", "exit"], lifecycle)

    def test_remote_initialization_failure_blocks_startup_without_local_fallback(self) -> None:
        @asynccontextmanager
        async def failing_remote_context():
            raise RuntimeError("remote initialization unavailable")
            yield  # pragma: no cover - required only to define an async context manager.

        with (
            patch.dict(
                os.environ,
                {"TOOL_TRANSPORT": "agentcore_remote_mcp", "WEB_MODEL_PROVIDER": "mock"},
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app.create_agentcore_mcp_tool_client",
                return_value=failing_remote_context(),
            ) as factory,
            patch("home_repair_agent.web.app.create_mcp_server") as local_server,
            self.assertRaisesRegex(RuntimeError, "remote initialization unavailable"),
            TestClient(create_app(reference_time=self.reference_time)),
        ):
            pass

        factory.assert_called_once_with()
        local_server.assert_not_called()

    def test_invalid_transport_blocks_startup_without_any_transport_factory(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"TOOL_TRANSPORT": "untrusted-fallback", "WEB_MODEL_PROVIDER": "mock"},
                clear=False,
            ),
            patch("home_repair_agent.web.app.create_agentcore_mcp_tool_client") as remote_factory,
            patch("home_repair_agent.web.app.create_mcp_server") as local_server,
            self.assertRaisesRegex(RuntimeError, "TOOL_TRANSPORT must be one of"),
            TestClient(create_app(reference_time=self.reference_time)),
        ):
            pass

        remote_factory.assert_not_called()
        local_server.assert_not_called()

    def test_local_transport_remains_the_default_tool_client(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"TOOL_TRANSPORT": "local", "WEB_MODEL_PROVIDER": "mock"},
                clear=False,
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            service = client.app.state.web_sessions
            self.assertIsInstance(service._tool_client, MCPToolClient)
            self.assertIs(service._tool_client, service._runner._tool_client)


if __name__ == "__main__":
    unittest.main()
