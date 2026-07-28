from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.agent.models import ModelTurn, ToolCall
from home_repair_agent.web.app import create_app


class _MatchingAttemptModel:
    def __init__(self) -> None:
        self.calls = 0
        self.exposed_tool_names: set[str] = set()

    async def complete(self, *, messages, tools) -> ModelTurn:
        del messages
        self.calls += 1
        self.exposed_tool_names = {tool.name for tool in tools}
        if self.calls == 1:
            return ModelTurn.use_tools(
                ToolCall(
                    call_id="unsafe-match-attempt",
                    name="match_service_providers",
                    arguments={},
                )
            )
        return ModelTurn.answer("已停止未經人工確認的媒合要求。")


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        reference_time = datetime(2026, 7, 27, 10, tzinfo=TAIPEI_TIMEZONE)
        self.client_context = TestClient(create_app(reference_time=reference_time))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)

    def create_session(self) -> dict[str, object]:
        response = self.client.post("/api/sessions")

        self.assertEqual(201, response.status_code)
        return response.json()

    def prepare_form(self) -> dict[str, object]:
        session = self.create_session()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "台北市大安區水龍頭漏水"},
        )

        self.assertEqual(200, response.status_code)
        return response.json()

    def valid_form_payload(self) -> dict[str, object]:
        return {
            "answers": {
                "issue_category": "leaking_faucet",
                "notes": "大約每分鐘滴水。",
            },
            "preferred_start": "2026-08-01T13:00:00+08:00",
            "preferred_end": "2026-08-01T17:00:00+08:00",
        }

    def prepare_match(self) -> dict[str, object]:
        session = self.prepare_form()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=self.valid_form_payload(),
        )

        self.assertEqual(200, response.status_code)
        return response.json()

    def dispatch_payload(
        self,
        *,
        provider_id: str = "SYN-PROVIDER-001",
        confirmed: bool = True,
    ) -> dict[str, object]:
        return {
            "provider_id": provider_id,
            "confirmed": confirmed,
            "idempotency_key": f"dispatch:test:{provider_id}",
        }

    def test_root_serves_the_operational_demo_and_asset(self) -> None:
        response = self.client.get("/")
        asset = self.client.get("/static/repair-workbench.webp")

        self.assertEqual(200, response.status_code)
        self.assertIn("修繕小隊長", response.text)
        self.assertIn("consultation-form", response.text)
        self.assertIn("請勿輸入真實姓名", response.text)
        self.assertEqual(200, asset.status_code)
        self.assertEqual("image/webp", asset.headers["content-type"])
        self.assertIn(
            "frame-ancestors 'none'",
            response.headers["content-security-policy"],
        )

    def test_health_declares_the_provider_workflow_demo_mode(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "ok": True,
                "service": "home-repair-web",
                "mode": "provider-workflow-demo",
            },
            response.json(),
        )
        self.assertEqual("no-store", response.headers["cache-control"])

    def test_first_message_returns_structured_form_state_after_three_tools(self) -> None:
        session = self.prepare_form()

        self.assertEqual("awaiting_form", session["state"])
        self.assertEqual("水電修繕", session["service"]["name"])
        self.assertEqual("臺北市大安區", session["location"]["full_name"])
        self.assertEqual(
            "demo_repair_form_v1",
            session["consultation_form"]["form_key"],
        )
        self.assertFalse(session["can_send_message"])
        self.assertTrue(session["can_submit_form"])
        self.assertEqual(
            [
                "search_services",
                "resolve_location",
                "get_consultation_form",
            ],
            [entry["name"] for entry in session["tool_trace"]],
        )
        preferred_time = next(
            topic
            for topic in session["consultation_form"]["topics"]
            if topic["topic_key"] == "preferred_time"
        )
        self.assertEqual("datetime_range", preferred_time["config"]["control"])
        self.assertEqual("Asia/Taipei", preferred_time["config"]["timezone"])

    def test_form_submission_calls_matching_tool_and_returns_synthetic_candidates(self) -> None:
        session = self.prepare_form()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=self.valid_form_payload(),
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("matched", result["state"])
        self.assertEqual(2, len(result["candidates"]))
        self.assertTrue(
            all(candidate["source_type"] == "synthetic" for candidate in result["candidates"])
        )
        self.assertEqual(
            "match_service_providers",
            result["tool_trace"][-1]["name"],
        )
        self.assertEqual("2026-08-01T13:00:00+08:00", result["preferred_start"])
        self.assertIn("leaking_faucet", result["answers"].values())
        self.assertFalse(result["can_send_message"])
        self.assertFalse(result["can_submit_form"])
        self.assertTrue(result["can_dispatch"])
        self.assertIsNone(result["dispatch"])

    def test_web_model_cannot_match_before_manual_form_confirmation(self) -> None:
        model = _MatchingAttemptModel()
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "review model"),
            ),
            TestClient(create_app()) as client,
        ):
            session = client.post("/api/sessions").json()
            response = client.post(
                f"/api/sessions/{session['session_id']}/messages",
                json={"text": "請直接幫我配對師傅"},
            )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertNotIn(
            "match_service_providers",
            model.exposed_tool_names,
        )
        self.assertEqual("error", result["state"])
        self.assertEqual([], result["candidates"])
        self.assertFalse(result["tool_trace"][-1]["ok"])

    def test_completed_match_rejects_duplicate_form_submission(self) -> None:
        session = self.prepare_form()
        endpoint = f"/api/sessions/{session['session_id']}/form"
        first = self.client.post(endpoint, json=self.valid_form_payload())
        second = self.client.post(endpoint, json=self.valid_form_payload())

        self.assertEqual(200, first.status_code)
        self.assertEqual(409, second.status_code)
        self.assertEqual(
            "MATCH_ALREADY_COMPLETED",
            second.json()["error"]["code"],
        )

    def test_form_rejects_unknown_fields_instead_of_guessing(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload()
        payload["answers"]["invented_service_code"] = "7"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("UNKNOWN_FORM_FIELD", response.json()["error"]["code"])
        self.assertIn(
            "invented_service_code",
            response.json()["error"]["fields"],
        )

    def test_form_requires_the_official_required_option(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload()
        payload["answers"]["issue_category"] = "invented_option"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_FORM_ANSWERS", response.json()["error"]["code"])
        self.assertIn("issue_category", response.json()["error"]["fields"])

    def test_form_requires_taipei_aware_time_window(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload()
        payload["preferred_start"] = "2026-08-01T13:00:00"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(422, response.status_code)
        self.assertIn("+08:00", response.text)

    def test_form_rejects_a_past_time_window(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload()
        payload["preferred_start"] = "2026-07-26T13:00:00+08:00"
        payload["preferred_end"] = "2026-07-26T17:00:00+08:00"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_TIME_WINDOW", response.json()["error"]["code"])

    def test_empty_matching_result_is_shown_without_inventing_a_provider(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload()
        payload["preferred_start"] = "2026-08-01T20:00:00+08:00"
        payload["preferred_end"] = "2026-08-01T22:00:00+08:00"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("no_candidates", result["state"])
        self.assertEqual([], result["candidates"])
        self.assertIn("不會自行捏造人選", result["messages"][-1]["text"])

    def test_reset_clears_structured_state_without_creating_a_case(self) -> None:
        session = self.prepare_form()
        service = self.client.app.state.web_sessions
        record_before_reset = service._sessions[session["session_id"]]
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/reset",
        )
        record_after_reset = service._sessions[session["session_id"]]

        self.assertEqual(200, response.status_code)
        self.assertIs(record_before_reset, record_after_reset)
        self.assertIs(record_before_reset.lock, record_after_reset.lock)
        reset = response.json()
        self.assertEqual(session["session_id"], reset["session_id"])
        self.assertEqual("collecting_need", reset["state"])
        self.assertIsNone(reset["service"])
        self.assertIsNone(reset["consultation_form"])
        self.assertEqual([], reset["candidates"])
        self.assertEqual(1, len(reset["messages"]))

    def test_provider_page_and_synthetic_identities_are_available(self) -> None:
        page = self.client.get("/provider")
        identities = self.client.get("/api/provider/identities")

        self.assertEqual(200, page.status_code)
        self.assertIn("廠商工作台", page.text)
        self.assertIn('id="detail-order"', page.text)
        self.assertEqual(200, identities.status_code)
        self.assertEqual(
            ["SYN-PROVIDER-001", "SYN-PROVIDER-002"],
            [identity["provider_id"] for identity in identities.json()["identities"]],
        )
        self.assertTrue(
            all(
                identity["source_type"] == "synthetic"
                for identity in identities.json()["identities"]
            )
        )

    def test_dispatch_requires_confirmation_and_is_idempotent(self) -> None:
        matched = self.prepare_match()
        endpoint = f"/api/sessions/{matched['session_id']}/dispatch"

        unconfirmed = self.client.post(
            endpoint,
            json=self.dispatch_payload(confirmed=False),
        )
        first = self.client.post(endpoint, json=self.dispatch_payload())
        second = self.client.post(endpoint, json=self.dispatch_payload())

        self.assertEqual(422, unconfirmed.status_code)
        self.assertEqual(
            "CONFIRMATION_REQUIRED",
            unconfirmed.json()["error"]["code"],
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(
            first.json()["dispatch"]["case_id"],
            second.json()["dispatch"]["case_id"],
        )
        self.assertEqual("dispatch_pending", first.json()["state"])
        self.assertFalse(first.json()["can_dispatch"])
        self.assertEqual(
            "complete",
            next(step["state"] for step in first.json()["progress"] if step["key"] == "matching"),
        )

    def test_dispatch_rejects_a_window_that_expired_after_matching(self) -> None:
        matched = self.prepare_match()
        self.client.app.state.web_sessions._now = lambda: datetime(
            2026,
            8,
            1,
            13,
            30,
            tzinfo=TAIPEI_TIMEZONE,
        )

        response = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        )
        session = self.client.get(
            f"/api/sessions/{matched['session_id']}",
        ).json()

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_TIME_WINDOW", response.json()["error"]["code"])
        self.assertEqual("matched", session["state"])
        self.assertIsNone(session["dispatch"])

    def test_factory_rejects_mismatched_case_workflow_injection(self) -> None:
        session_service = Mock()
        session_service.case_workflow = object()

        with self.assertRaisesRegex(ValueError, "same CaseWorkflowService"):
            create_app(
                session_service=session_service,
                case_workflow=object(),
            )

    def test_assigned_provider_accepts_and_consumer_sees_order_status(self) -> None:
        matched = self.prepare_match()
        dispatched = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        ).json()
        case_id = dispatched["dispatch"]["case_id"]
        provider_headers = {"X-Demo-Provider-Id": "SYN-PROVIDER-001"}

        listing = self.client.get(
            "/api/provider/cases",
            headers=provider_headers,
        )
        pending = self.client.get(
            f"/api/provider/cases/{case_id}",
            headers=provider_headers,
        )
        unauthorized = self.client.get(
            f"/api/provider/cases/{case_id}",
            headers={"X-Demo-Provider-Id": "SYN-PROVIDER-002"},
        )
        accepted = self.client.post(
            f"/api/provider/cases/{case_id}/decision",
            headers=provider_headers,
            json={
                "decision": "accept",
                "confirmed": True,
                "idempotency_key": f"accept:{case_id}",
            },
        )
        consumer = self.client.get(
            f"/api/sessions/{matched['session_id']}",
        )

        self.assertEqual(200, listing.status_code)
        self.assertEqual(1, listing.json()["count"])
        self.assertEqual("pending_provider", listing.json()["cases"][0]["status"])
        self.assertEqual("林○安", listing.json()["cases"][0]["contact_name_masked"])

        self.assertEqual(200, pending.status_code)
        self.assertEqual("masked", pending.json()["contact"]["access"])
        self.assertEqual("0912***678", pending.json()["contact"]["mobile"])
        self.assertNotIn("Demo 路", pending.json()["contact"]["address"])
        self.assertEqual(404, unauthorized.status_code)

        self.assertEqual(200, accepted.status_code)
        self.assertEqual("accepted", accepted.json()["status"])
        self.assertEqual("full", accepted.json()["contact"]["access"])
        self.assertEqual("0912-345-678", accepted.json()["contact"]["mobile"])
        self.assertTrue(accepted.json()["order_no"].startswith("SYN-ORDER-"))

        self.assertEqual(200, consumer.status_code)
        self.assertEqual("provider_accepted", consumer.json()["state"])
        self.assertEqual(
            accepted.json()["order_no"],
            consumer.json()["dispatch"]["order_no"],
        )

    def test_rejected_case_can_be_dispatched_to_the_next_candidate(self) -> None:
        matched = self.prepare_match()
        first = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        ).json()
        first_case_id = first["dispatch"]["case_id"]
        rejection = self.client.post(
            f"/api/provider/cases/{first_case_id}/decision",
            headers={"X-Demo-Provider-Id": "SYN-PROVIDER-001"},
            json={
                "decision": "reject",
                "confirmed": True,
                "idempotency_key": f"reject:{first_case_id}",
            },
        )
        consumer = self.client.get(
            f"/api/sessions/{matched['session_id']}",
        ).json()
        second = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(provider_id="SYN-PROVIDER-002"),
        )

        self.assertEqual(200, rejection.status_code)
        self.assertEqual("unavailable", rejection.json()["contact"]["access"])
        self.assertEqual("provider_rejected", consumer["state"])
        self.assertTrue(consumer["can_dispatch"])
        self.assertEqual(
            ["SYN-PROVIDER-001"],
            consumer["dispatch"]["rejected_provider_ids"],
        )
        self.assertEqual(200, second.status_code)
        self.assertEqual(
            "SYN-PROVIDER-002",
            second.json()["dispatch"]["provider_id"],
        )
        self.assertEqual("dispatch_pending", second.json()["state"])

    def test_reset_rejects_erasing_an_audited_case(self) -> None:
        matched = self.prepare_match()
        self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        )

        response = self.client.post(
            f"/api/sessions/{matched['session_id']}/reset",
        )

        self.assertEqual(409, response.status_code)
        self.assertEqual("CASE_ALREADY_SUBMITTED", response.json()["error"]["code"])

    def test_unknown_session_returns_safe_404(self) -> None:
        response = self.client.get("/api/sessions/not-a-session")

        self.assertEqual(404, response.status_code)
        self.assertEqual("SESSION_NOT_FOUND", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
