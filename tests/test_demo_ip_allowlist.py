from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from home_repair_agent.web.app import create_app
from home_repair_agent.web.models import ProviderView

APPROVED_IP = "60.250.15.18"
UNAPPROVED_IP = "203.0.113.40"


def _session_service() -> Mock:
    service = Mock()
    service.case_workflow = Mock()
    service.provider = ProviderView(key="bedrock", label="Bedrock", is_external=True)
    service.send_message = AsyncMock()
    return service


class DemoIpAllowlistTests(unittest.TestCase):
    def test_allowlist_is_disabled_by_default(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            TestClient(
                create_app(session_service=_session_service()),
                client=(UNAPPROVED_IP, 50000),
            ) as client,
        ):
            response = client.get("/api/health")

        self.assertEqual(200, response.status_code)

    def test_exact_allowed_ip_and_loopback_can_access_all_routes(self) -> None:
        environment = {"DEMO_ALLOWED_IPS": APPROVED_IP}
        for client_ip in (APPROVED_IP, "127.0.0.1", "::1"):
            with self.subTest(client_ip=client_ip):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    TestClient(
                        create_app(session_service=_session_service()),
                        client=(client_ip, 50000),
                    ) as client,
                ):
                    root = client.get("/")
                    health = client.get("/api/health")

                self.assertEqual(200, root.status_code)
                self.assertEqual(200, health.status_code)

    def test_unapproved_ip_is_blocked_before_session_service_or_model(self) -> None:
        service = _session_service()
        with (
            patch.dict(os.environ, {"DEMO_ALLOWED_IPS": APPROVED_IP}, clear=True),
            TestClient(
                create_app(session_service=service),
                client=(UNAPPROVED_IP, 50000),
            ) as client,
        ):
            response = client.post(
                "/api/sessions/session-id/messages",
                json={"text": "synthetic repair request"},
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("DEMO_IP_NOT_ALLOWED", response.json()["error"]["code"])
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual("DENY", response.headers["x-frame-options"])
        service.send_message.assert_not_awaited()

    def test_health_and_static_routes_are_also_protected(self) -> None:
        with (
            patch.dict(os.environ, {"DEMO_ALLOWED_IPS": APPROVED_IP}, clear=True),
            TestClient(
                create_app(session_service=_session_service()),
                client=(UNAPPROVED_IP, 50000),
            ) as client,
        ):
            health = client.get("/api/health")
            static_asset = client.get("/static/app.js")

        self.assertEqual(403, health.status_code)
        self.assertEqual(403, static_asset.status_code)

    def test_cf_connecting_ip_is_trusted_only_for_opted_in_loopback_proxy(self) -> None:
        environment = {
            "DEMO_ALLOWED_IPS": APPROVED_IP,
            "DEMO_TRUST_CF_CONNECTING_IP": "true",
        }
        cases = (
            ("127.0.0.1", APPROVED_IP, 200),
            ("127.0.0.1", UNAPPROVED_IP, 403),
            (UNAPPROVED_IP, APPROVED_IP, 403),
        )
        for direct_ip, header_ip, expected_status in cases:
            with self.subTest(direct_ip=direct_ip, header_ip=header_ip):
                with (
                    patch.dict(os.environ, environment, clear=True),
                    TestClient(
                        create_app(session_service=_session_service()),
                        client=(direct_ip, 50000),
                    ) as client,
                ):
                    response = client.get(
                        "/api/health",
                        headers={"CF-Connecting-IP": header_ip},
                    )

                self.assertEqual(expected_status, response.status_code)

    def test_invalid_cf_header_fails_closed_when_trusted(self) -> None:
        environment = {
            "DEMO_ALLOWED_IPS": APPROVED_IP,
            "DEMO_TRUST_CF_CONNECTING_IP": "true",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            TestClient(
                create_app(session_service=_session_service()),
                client=("127.0.0.1", 50000),
            ) as client,
        ):
            response = client.get(
                "/api/health",
                headers={"CF-Connecting-IP": "not-an-ip"},
            )

        self.assertEqual(403, response.status_code)

    def test_invalid_configuration_fails_fast(self) -> None:
        invalid_environments = (
            {"DEMO_ALLOWED_IPS": ""},
            {"DEMO_ALLOWED_IPS": f"{APPROVED_IP},"},
            {"DEMO_ALLOWED_IPS": "60.250.15.0/24"},
            {
                "DEMO_ALLOWED_IPS": APPROVED_IP,
                "DEMO_TRUST_CF_CONNECTING_IP": "yes",
            },
            {"DEMO_TRUST_CF_CONNECTING_IP": "true"},
        )
        for environment in invalid_environments:
            with (
                self.subTest(environment=environment),
                patch.dict(os.environ, environment, clear=True),
                self.assertRaisesRegex(RuntimeError, "DEMO_"),
            ):
                create_app(session_service=_session_service())


if __name__ == "__main__":
    unittest.main()
