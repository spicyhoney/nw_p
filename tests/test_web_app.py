from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import patch

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

    def test_root_serves_the_operational_demo_and_asset(self) -> None:
        response = self.client.get("/")
        asset = self.client.get("/static/repair-workbench.webp")

        self.assertEqual(200, response.status_code)
        self.assertIn("修繕小隊長", response.text)
        self.assertIn("consultation-form", response.text)
        self.assertEqual(200, asset.status_code)
        self.assertEqual("image/webp", asset.headers["content-type"])
        self.assertIn(
            "frame-ancestors 'none'",
            response.headers["content-security-policy"],
        )

    def test_health_declares_the_read_only_demo_mode(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "ok": True,
                "service": "home-repair-web",
                "mode": "read-only-demo",
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

    def test_unknown_session_returns_safe_404(self) -> None:
        response = self.client.get("/api/sessions/not-a-session")

        self.assertEqual(404, response.status_code)
        self.assertEqual("SESSION_NOT_FOUND", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
