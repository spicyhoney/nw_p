from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.web.app import create_app


class GuidedFormChatTests(unittest.TestCase):
    def setUp(self) -> None:
        reference_time = datetime(2026, 8, 2, 10, tzinfo=TAIPEI_TIMEZONE)
        self.client_context = TestClient(create_app(reference_time=reference_time))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)

    def prepare_guided_form(self) -> dict[str, object]:
        session = self.client.post("/api/sessions").json()
        proposal = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "臺北市大安區水龍頭漏水"},
        )
        self.assertEqual(200, proposal.status_code, proposal.text)
        confirmation = self.client.post(
            f"/api/sessions/{session['session_id']}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        self.assertEqual(200, confirmation.status_code, confirmation.text)
        ready = confirmation.json()
        self.assertEqual("repair_form_v1", ready["consultation_form"]["form_key"])
        self.assertTrue(ready["guided_form_active"])
        self.assertIsNone(ready["active_task"]["summary"])
        return ready

    def answer(self, session_id: str, text: str) -> dict[str, object]:
        response = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": text},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_chat_prefills_only_after_all_required_fields_then_requires_manual_save(
        self,
    ) -> None:
        ready = self.prepare_guided_form()
        session_id = ready["session_id"]

        described = self.answer(session_id, "廚房水龍頭關閉後仍持續滴水。")
        self.assertTrue(described["guided_form_active"])
        self.assertEqual(
            "廚房水龍頭關閉後仍持續滴水。",
            described["answers"]["issue_description"],
        )

        shutoff = self.answer(session_id, "可以關閉水源")
        self.assertEqual("yes", shutoff["answers"]["water_shutoff"])
        self.assertTrue(shutoff["guided_form_active"])

        scheduled = self.answer(
            session_id,
            "希望 2026-08-08 13:00 到 17:00，台北時間",
        )
        self.assertEqual("2026-08-08T13:00:00+08:00", scheduled["preferred_start"])
        self.assertEqual("2026-08-08T17:00:00+08:00", scheduled["preferred_end"])
        self.assertTrue(scheduled["guided_form_active"])

        completed = self.answer(session_id, "請用 App 訊息聯絡")
        self.assertFalse(completed["guided_form_active"])
        self.assertEqual("app", completed["answers"]["contact_method"])
        self.assertIsNone(completed["active_task"]["summary"])
        self.assertEqual([], completed["candidates"])
        self.assertIsNone(completed["dispatch"])
        self.assertFalse(completed["can_confirm_summary"])
        self.assertFalse(completed["can_dispatch"])
        self.assertIn("尚未產生摘要、媒合或派單", completed["messages"][-1]["text"])

        answers = dict(completed["answers"])
        answers["issue_description"] = "浴室水龍頭接縫持續滴水。"
        saved = self.client.post(
            f"/api/sessions/{session_id}/form",
            json={
                "answers": answers,
                "preferred_start": completed["preferred_start"],
                "preferred_end": completed["preferred_end"],
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        saved_body = saved.json()
        self.assertEqual("awaiting_summary_confirmation", saved_body["state"])
        self.assertEqual(
            "浴室水龍頭接縫持續滴水。",
            saved_body["active_task"]["summary"]["answers"]["issue_description"],
        )
        self.assertEqual([], saved_body["candidates"])
        self.assertIsNone(saved_body["dispatch"])
        self.assertFalse(saved_body["can_dispatch"])

    def test_invalid_choice_and_relative_time_fail_closed_without_advancing(self) -> None:
        ready = self.prepare_guided_form()
        session_id = ready["session_id"]
        self.answer(session_id, "廚房水龍頭接縫持續滴水。")

        invalid_choice = self.answer(session_id, "大概吧")
        self.assertNotIn("water_shutoff", invalid_choice["answers"])
        self.assertTrue(invalid_choice["guided_form_active"])
        self.assertIn("無法對應", invalid_choice["messages"][-1]["text"])

        self.answer(session_id, "不確定")
        relative_time = self.answer(session_id, "明天下午")
        self.assertIsNone(relative_time["preferred_start"])
        self.assertIsNone(relative_time["preferred_end"])
        self.assertTrue(relative_time["guided_form_active"])
        self.assertIn("不會猜測", relative_time["messages"][-1]["text"])
        self.assertIsNone(relative_time["active_task"]["summary"])
        self.assertEqual([], relative_time["candidates"])
        self.assertIsNone(relative_time["dispatch"])

    def test_form_is_hidden_while_guided_collection_is_active(self) -> None:
        app_js = (
            Path(__file__).parents[1] / "src" / "home_repair_agent" / "web" / "static" / "app.js"
        ).read_text(encoding="utf-8")
        self.assertIn("const guidedFormActive = Boolean(store.session.guided_form_active);", app_js)
        self.assertIn("if (!form || formLocked || guidedFormActive)", app_js)


if __name__ == "__main__":
    unittest.main()
