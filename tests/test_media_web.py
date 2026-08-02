from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.agent.huggingface_vision import (
    HuggingFaceVisionRequestError,
    VisionAnalysisResult,
)
from home_repair_agent.agent.mock_model import (
    RuleBasedRepairMockModel,
    ScriptedModelClient,
)
from home_repair_agent.agent.models import (
    AssistantToolCalls,
    ModelTurn,
    ToolCall,
    ToolResultMessage,
)
from home_repair_agent.web.app import create_app


class _VisionStub:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def analyze(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        context: str | None = None,
    ) -> VisionAnalysisResult:
        del context
        self.calls += 1
        if self.fail:
            raise HuggingFaceVisionRequestError("test failure without payload")
        if not image_bytes or mime_type != "image/png":
            raise AssertionError("the VLM must receive normalized verified image data")
        return VisionAnalysisResult(
            service_query="水龍頭漏水",
            problem_summary="水龍頭接縫附近疑似滲水",
            safety_warnings=["先關閉附近水源，避免積水滑倒。"],
            confidence=0.82,
            uncertain=True,
        )


def _png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), color=(40, 120, 180)).save(output, format="PNG")
    return output.getvalue()


class MediaWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.media_root = tempfile.TemporaryDirectory()
        self.vision = _VisionStub()
        reference_time = datetime(2026, 7, 27, 10, tzinfo=TAIPEI_TIMEZONE)
        self.patches = (
            patch.dict(
                os.environ,
                {
                    "WEB_MODEL_PROVIDER": "huggingface",
                    "MEDIA_ROOT": self.media_root.name,
                },
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(RuleBasedRepairMockModel(), "HF text test double"),
            ),
            patch(
                "home_repair_agent.web.app.HuggingFaceVisionClient.from_environment",
                return_value=self.vision,
            ),
        )
        for active_patch in self.patches:
            active_patch.start()
        self.client_context = TestClient(create_app(reference_time=reference_time))
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.media_root.cleanup()

    def create_session(self) -> dict[str, object]:
        response = self.client.post("/api/sessions")
        self.assertEqual(201, response.status_code)
        return response.json()

    def prepare_confirmed_branch(self) -> dict[str, object]:
        session = self.create_session()
        session_id = session["session_id"]
        message = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市大安區水龍頭漏水"},
        )
        self.assertEqual(200, message.status_code, message.text)
        branch = self.client.post(
            f"/api/sessions/{session_id}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        self.assertEqual(200, branch.status_code, branch.text)
        return branch.json()

    def upload_and_confirm(self) -> dict[str, object]:
        session = self.prepare_confirmed_branch()
        session_id = session["session_id"]
        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        media = upload.json()["media"]
        analysis = media["analysis"]
        confirmation = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": media["media_id"],
                "analysis_revision": analysis["analysis_revision"],
                "service_query": analysis["service_query"],
                "problem_summary": analysis["problem_summary"],
                "safety_warnings": analysis["safety_warnings"],
            },
        )
        self.assertEqual(200, confirmation.status_code, confirmation.text)
        return confirmation.json()

    def prepare_summary(self) -> dict[str, object]:
        session = self.upload_and_confirm()
        session_id = session["session_id"]
        consultation_form = session["consultation_form"]
        self.assertEqual("repair_form_v1", consultation_form["form_key"])
        projected_values = {
            "issue_category": "faucet_leak",
            "issue_description": "廚房水龍頭接縫持續滴水，每分鐘約十滴。",
            "water_shutoff": "yes",
            "contact_method": "app",
        }
        answers = {
            topic["topic_key"]: projected_values[topic["topic_key"]]
            for topic in consultation_form["topics"]
            if topic["topic_key"] != "preferred_time"
        }

        form = self.client.post(
            f"/api/sessions/{session_id}/form",
            json={
                "answers": answers,
                "preferred_start": "2026-08-01T13:00:00+08:00",
                "preferred_end": "2026-08-01T17:00:00+08:00",
            },
        )
        self.assertEqual(200, form.status_code, form.text)
        summary_session = form.json()
        self.assertEqual("awaiting_summary_confirmation", summary_session["state"])
        self.assertEqual([], summary_session["candidates"])
        self.assertFalse(summary_session["active_task"]["summary"]["confirmed"])
        return summary_session

    @staticmethod
    def summary_confirmation_payload(
        session: dict[str, object],
    ) -> dict[str, object]:
        task = session["active_task"]
        summary = task["summary"]
        return {
            "active_task_id": task["active_task_id"],
            "summary_id": summary["summary_id"],
            "summary_version": summary["version"],
            "confirm": True,
        }

    def prepare_match(self) -> dict[str, object]:
        summary_session = self.prepare_summary()
        session_id = summary_session["session_id"]
        confirmation = self.client.post(
            f"/api/sessions/{session_id}/summary/confirm",
            json=self.summary_confirmation_payload(summary_session),
        )
        self.assertEqual(200, confirmation.status_code, confirmation.text)
        matched = confirmation.json()
        self.assertEqual("matched", matched["state"])
        return matched

    def dispatch(self, session: dict[str, object], provider_id: str) -> dict[str, object]:
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/dispatch",
            json={
                "provider_id": provider_id,
                "confirmed": True,
                "idempotency_key": f"media-dispatch:{provider_id}",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_removing_image_invalidates_unconfirmed_summary_version(self) -> None:
        session = self.prepare_summary()
        session_id = session["session_id"]
        stale_summary = session["active_task"]["summary"]
        stale_payload = self.summary_confirmation_payload(session)
        stale_version = stale_summary["version"]
        self.assertTrue(session["media"]["analysis"]["confirmed"])
        self.assertFalse(stale_summary["confirmed"])

        removed = self.client.delete(f"/api/sessions/{session_id}/image")

        self.assertEqual(200, removed.status_code, removed.text)
        removed_session = removed.json()
        latest_summary = removed_session["active_task"]["summary"]
        self.assertIsNone(removed_session["media"])
        self.assertEqual("awaiting_summary_confirmation", removed_session["state"])
        self.assertEqual([], removed_session["candidates"])
        self.assertGreater(latest_summary["version"], stale_version)
        self.assertFalse(latest_summary["confirmed"])
        self.assertTrue(removed_session["can_confirm_summary"])

        stale = self.client.post(
            f"/api/sessions/{session_id}/summary/confirm",
            json=stale_payload,
        )
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual("STALE_SUMMARY_VERSION", stale.json()["error"]["code"])

        confirmation = self.client.post(
            f"/api/sessions/{session_id}/summary/confirm",
            json=self.summary_confirmation_payload(removed_session),
        )
        self.assertEqual(200, confirmation.status_code, confirmation.text)
        confirmed_session = confirmation.json()
        self.assertIsNone(confirmed_session["media"])
        self.assertEqual("matched", confirmed_session["state"])
        self.assertGreater(len(confirmed_session["candidates"]), 0)
        self.assertTrue(confirmed_session["can_dispatch"])
        self.assertTrue(confirmed_session["active_task"]["summary"]["confirmed"])
        self.assertEqual(
            latest_summary["version"],
            confirmed_session["active_task"]["summary"]["version"],
        )

    def test_upload_requires_external_confirmation_and_valid_image(self) -> None:
        session = self.prepare_confirmed_branch()
        endpoint = f"/api/sessions/{session['session_id']}/image"

        no_consent = self.client.post(
            endpoint,
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "false"},
        )
        corrupt = self.client.post(
            endpoint,
            files={"file": ("repair.png", b"not an image", "image/png")},
            data={"external_processing_confirmed": "true"},
        )

        self.assertEqual(422, no_consent.status_code)
        self.assertEqual(
            "EXTERNAL_PROCESSING_CONFIRMATION_REQUIRED",
            no_consent.json()["error"]["code"],
        )
        self.assertEqual(422, corrupt.status_code)
        self.assertEqual("INVALID_IMAGE", corrupt.json()["error"]["code"])
        self.assertEqual(0, self.vision.calls)
        self.assertEqual([], os.listdir(self.media_root.name))

    def test_image_first_requires_branch_then_analysis_confirmation(self) -> None:
        session = self.create_session()
        session_id = session["session_id"]

        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )

        self.assertEqual(200, upload.status_code, upload.text)
        uploaded = upload.json()
        media = uploaded["media"]
        analysis = media["analysis"]
        self.assertIsNone(uploaded["active_task"]["branch"])
        self.assertEqual(
            "faucet_leak",
            uploaded["repair_routing"]["pending_branch"],
        )
        self.assertIsNone(media["branch"])
        self.assertFalse(analysis["confirmed"])
        self.assertIsNone(uploaded["service"])
        self.assertIsNone(uploaded["location"])
        self.assertIsNone(uploaded["consultation_form"])
        self.assertEqual([], uploaded["candidates"])
        self.assertFalse(uploaded["can_send_message"])

        early_confirmation = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": media["media_id"],
                "analysis_revision": analysis["analysis_revision"],
                "service_query": analysis["service_query"],
                "problem_summary": analysis["problem_summary"],
                "safety_warnings": analysis["safety_warnings"],
            },
        )
        self.assertEqual(409, early_confirmation.status_code, early_confirmation.text)
        self.assertEqual(
            "IMAGE_BRANCH_CONFIRMATION_REQUIRED",
            early_confirmation.json()["error"]["code"],
        )

        branch = self.client.post(
            f"/api/sessions/{session_id}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        self.assertEqual(200, branch.status_code, branch.text)
        branched = branch.json()
        self.assertEqual("faucet_leak", branched["active_task"]["branch"])
        self.assertEqual("faucet_leak", branched["media"]["branch"])
        self.assertFalse(branched["media"]["analysis"]["confirmed"])
        self.assertIsNone(branched["location"])
        self.assertIsNone(branched["consultation_form"])
        self.assertEqual([], branched["candidates"])
        self.assertFalse(branched["can_send_message"])

        confirmed = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": media["media_id"],
                "analysis_revision": analysis["analysis_revision"],
                "service_query": analysis["service_query"],
                "problem_summary": analysis["problem_summary"],
                "safety_warnings": analysis["safety_warnings"],
            },
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        confirmed_session = confirmed.json()
        self.assertTrue(confirmed_session["media"]["analysis"]["confirmed"])
        self.assertEqual("image_confirmed", confirmed_session["service_source"])
        self.assertIsNone(confirmed_session["consultation_form"])
        self.assertTrue(confirmed_session["can_send_message"])

        location = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市大安區"},
        )
        self.assertEqual(200, location.status_code, location.text)
        located = location.json()
        self.assertEqual("臺北市大安區", located["location"]["full_name"])
        self.assertEqual("repair_form_v1", located["consultation_form"]["form_key"])
        self.assertEqual([], located["candidates"])

    def test_removing_an_image_first_upload_cancels_its_branch_proposal(self) -> None:
        session = self.create_session()
        session_id = session["session_id"]
        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        self.assertIsNotNone(upload.json()["repair_routing"])

        removed = self.client.delete(f"/api/sessions/{session_id}/image")

        self.assertEqual(200, removed.status_code, removed.text)
        body = removed.json()
        self.assertIsNone(body["media"])
        self.assertIsNone(body["repair_routing"])
        self.assertIsNone(body["active_task"])
        self.assertTrue(body["can_send_message"])
        remaining_files = [
            filename for root, _dirs, files in os.walk(self.media_root.name) for filename in files
        ]
        self.assertEqual([], remaining_files)

        reupload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("replacement.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, reupload.status_code, reupload.text)
        self.assertEqual(
            "faucet_leak",
            reupload.json()["repair_routing"]["pending_branch"],
        )

    def test_vlm_failure_cleans_up_the_uploaded_file_without_fallback(self) -> None:
        session = self.prepare_confirmed_branch()
        self.vision.fail = True

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )

        self.assertEqual(503, response.status_code)
        self.assertEqual("IMAGE_ANALYSIS_FAILED", response.json()["error"]["code"])
        self.assertIsNone(self.client.get(f"/api/sessions/{session['session_id']}").json()["media"])
        remaining_files = [
            filename for root, _dirs, files in os.walk(self.media_root.name) for filename in files
        ]
        self.assertEqual([], remaining_files)

    def test_unconfirmed_analysis_is_preview_only_until_catalog_revalidation(self) -> None:
        session = self.prepare_confirmed_branch()
        session_id = session["session_id"]
        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("client-name.png", _png_bytes(), "text/plain")},
            data={"external_processing_confirmed": "true"},
        )

        self.assertEqual(200, upload.status_code, upload.text)
        body = upload.json()
        self.assertFalse(body["media"]["analysis"]["confirmed"])
        self.assertEqual(17, body["service"]["service_id"])
        self.assertEqual("faucet_leak", body["active_task"]["branch"])
        self.assertFalse(body["can_send_message"])
        self.assertNotIn("image_path", upload.text)

        blocked = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "台北市大安區"},
        )
        preview = self.client.get(f"/api/sessions/{session_id}/image")
        analysis = body["media"]["analysis"]
        confirmed = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": body["media"]["media_id"],
                "analysis_revision": analysis["analysis_revision"],
                "service_query": analysis["service_query"],
                "problem_summary": "使用者確認：接縫正在滴水",
                "safety_warnings": analysis["safety_warnings"],
            },
        )

        self.assertEqual(409, blocked.status_code)
        self.assertEqual("IMAGE_CONFIRMATION_REQUIRED", blocked.json()["error"]["code"])
        self.assertEqual(200, preview.status_code)
        self.assertEqual("image/png", preview.headers["content-type"])
        self.assertEqual("no-store", preview.headers["cache-control"])
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        confirmed_body = confirmed.json()
        self.assertTrue(confirmed_body["media"]["analysis"]["confirmed"])
        self.assertEqual(
            "使用者已修正模型建議。", confirmed_body["media"]["analysis"]["correction"]
        )
        self.assertEqual("水電修繕", confirmed_body["service"]["name"])
        self.assertTrue(confirmed_body["can_send_message"])

    def test_image_confirmation_rejects_inconsistent_unique_service_payloads(self) -> None:
        for malformed in ("empty", "multiple"):
            with self.subTest(malformed=malformed):
                session = self.prepare_confirmed_branch()
                session_id = session["session_id"]
                upload = self.client.post(
                    f"/api/sessions/{session_id}/image",
                    files={"file": ("repair.png", _png_bytes(), "image/png")},
                    data={"external_processing_confirmed": "true"},
                )
                self.assertEqual(200, upload.status_code, upload.text)
                analysis = upload.json()["media"]["analysis"]
                tool_client = self.client.app.state.web_sessions._tool_client
                original_call = tool_client.call_tool

                async def malformed_call(
                    *,
                    name,
                    arguments,
                    _original_call=original_call,
                    _malformed=malformed,
                ):
                    execution = await _original_call(name=name, arguments=arguments)
                    if name != "search_services":
                        return execution
                    payload = deepcopy(execution.payload)
                    service = deepcopy(payload["data"]["services"][0])
                    payload["data"]["count"] = 1
                    payload["data"]["services"] = (
                        [] if _malformed == "empty" else [service, deepcopy(service)]
                    )
                    return execution.model_copy(update={"payload": payload})

                with patch.object(tool_client, "call_tool", side_effect=malformed_call):
                    confirmation = self.client.post(
                        f"/api/sessions/{session_id}/image/confirm",
                        json={
                            "media_id": upload.json()["media"]["media_id"],
                            "analysis_revision": analysis["analysis_revision"],
                            "service_query": analysis["service_query"],
                            "problem_summary": analysis["problem_summary"],
                            "safety_warnings": analysis["safety_warnings"],
                        },
                    )

                self.assertEqual(422, confirmation.status_code, confirmation.text)
                self.assertEqual(
                    "SERVICE_REVALIDATION_AMBIGUOUS",
                    confirmation.json()["error"]["code"],
                )
                unchanged = self.client.get(f"/api/sessions/{session_id}").json()
                self.assertFalse(unchanged["media"]["analysis"]["confirmed"])
                self.assertEqual("text_tool", unchanged["service_source"])

    def test_stale_confirmation_cannot_bind_an_old_analysis_to_a_replacement_image(
        self,
    ) -> None:
        session = self.prepare_confirmed_branch()
        session_id = session["session_id"]
        first_upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("first.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, first_upload.status_code, first_upload.text)
        first_media = first_upload.json()["media"]

        replacement = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("replacement.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, replacement.status_code, replacement.text)
        replacement_media = replacement.json()["media"]
        self.assertNotEqual(first_media["media_id"], replacement_media["media_id"])

        stale = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": first_media["media_id"],
                "analysis_revision": first_media["analysis"]["analysis_revision"],
                "service_query": first_media["analysis"]["service_query"],
                "problem_summary": first_media["analysis"]["problem_summary"],
                "safety_warnings": first_media["analysis"]["safety_warnings"],
            },
        )

        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual("IMAGE_CONFIRMATION_STALE", stale.json()["error"]["code"])
        current = self.client.get(f"/api/sessions/{session_id}").json()
        self.assertEqual(replacement_media["media_id"], current["media"]["media_id"])
        self.assertFalse(current["media"]["analysis"]["confirmed"])
        self.assertEqual("text_tool", current["service_source"])

    def test_stale_analysis_revision_cannot_overwrite_a_newer_confirmation(self) -> None:
        session = self.prepare_confirmed_branch()
        session_id = session["session_id"]
        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        media = upload.json()["media"]
        analysis = media["analysis"]
        accepted_payload = {
            "media_id": media["media_id"],
            "analysis_revision": analysis["analysis_revision"],
            "service_query": analysis["service_query"],
            "problem_summary": "第一個頁籤確認的最新內容",
            "safety_warnings": analysis["safety_warnings"],
        }

        accepted = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json=accepted_payload,
        )
        self.assertEqual(200, accepted.status_code, accepted.text)
        accepted_analysis = accepted.json()["media"]["analysis"]
        self.assertNotEqual(
            analysis["analysis_revision"],
            accepted_analysis["analysis_revision"],
        )

        stale_payload = {
            **accepted_payload,
            "problem_summary": "舊頁籤試圖覆寫的新內容",
        }
        stale = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json=stale_payload,
        )
        self.assertEqual(409, stale.status_code, stale.text)
        self.assertEqual("IMAGE_CONFIRMATION_STALE", stale.json()["error"]["code"])

        replay = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json=accepted_payload,
        )
        self.assertEqual(200, replay.status_code, replay.text)
        replay_analysis = replay.json()["media"]["analysis"]
        self.assertEqual(
            accepted_analysis["analysis_revision"],
            replay_analysis["analysis_revision"],
        )
        self.assertEqual(
            "第一個頁籤確認的最新內容",
            replay_analysis["problem_summary"],
        )

    def test_rule_based_text_flow_keeps_image_confirmation_across_county_and_district(
        self,
    ) -> None:
        session = self.create_session()
        session_id = session["session_id"]
        proposal = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "水龍頭漏水"},
        )
        self.assertEqual(200, proposal.status_code, proposal.text)
        branch = self.client.post(
            f"/api/sessions/{session_id}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        self.assertEqual(200, branch.status_code, branch.text)
        self.assertEqual("clarifying", branch.json()["state"])

        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        media = upload.json()["media"]
        confirmed = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": media["media_id"],
                "analysis_revision": media["analysis"]["analysis_revision"],
                "service_query": media["analysis"]["service_query"],
                "problem_summary": media["analysis"]["problem_summary"],
                "safety_warnings": media["analysis"]["safety_warnings"],
            },
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        confirmed_body = confirmed.json()
        search_count = [entry["name"] for entry in confirmed_body["tool_trace"]].count(
            "search_services"
        )
        self.assertEqual("image_confirmed", confirmed_body["service_source"])

        county = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市"},
        )
        self.assertEqual(200, county.status_code, county.text)
        county_body = county.json()
        self.assertEqual("clarifying", county_body["state"])
        self.assertIsNone(county_body["consultation_form"])
        self.assertEqual("image_confirmed", county_body["service_source"])
        self.assertIn("行政區", county_body["messages"][-1]["text"])

        district = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "大安區"},
        )
        self.assertEqual(200, district.status_code, district.text)
        completed = district.json()
        self.assertEqual("awaiting_form", completed["state"])
        self.assertEqual("臺北市大安區", completed["location"]["full_name"])
        self.assertEqual("image_confirmed", completed["service_source"])
        self.assertEqual(
            search_count,
            [entry["name"] for entry in completed["tool_trace"]].count("search_services"),
        )

    def test_rule_based_text_flow_accepts_one_complete_location_after_image_confirm(
        self,
    ) -> None:
        session = self.create_session()
        session_id = session["session_id"]
        proposal = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "水龍頭漏水"},
        )
        self.assertEqual(200, proposal.status_code, proposal.text)
        branch = self.client.post(
            f"/api/sessions/{session_id}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        self.assertEqual(200, branch.status_code, branch.text)
        upload = self.client.post(
            f"/api/sessions/{session_id}/image",
            files={"file": ("repair.png", _png_bytes(), "image/png")},
            data={"external_processing_confirmed": "true"},
        )
        self.assertEqual(200, upload.status_code, upload.text)
        media = upload.json()["media"]
        confirmation = self.client.post(
            f"/api/sessions/{session_id}/image/confirm",
            json={
                "media_id": media["media_id"],
                "analysis_revision": media["analysis"]["analysis_revision"],
                "service_query": media["analysis"]["service_query"],
                "problem_summary": media["analysis"]["problem_summary"],
                "safety_warnings": media["analysis"]["safety_warnings"],
            },
        )
        self.assertEqual(200, confirmation.status_code, confirmation.text)
        search_count = [entry["name"] for entry in confirmation.json()["tool_trace"]].count(
            "search_services"
        )

        location = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市大安區"},
        )
        self.assertEqual(200, location.status_code, location.text)
        body = location.json()
        self.assertEqual("awaiting_form", body["state"])
        self.assertEqual("臺北市大安區", body["location"]["full_name"])
        self.assertEqual("image_confirmed", body["service_source"])
        self.assertEqual(
            search_count,
            [entry["name"] for entry in body["tool_trace"]].count("search_services"),
        )

    def test_remove_and_reset_delete_unsubmitted_media(self) -> None:
        first = self.upload_and_confirm()
        first_id = first["session_id"]
        removed = self.client.delete(f"/api/sessions/{first_id}/image")
        self.assertEqual(200, removed.status_code)
        self.assertIsNone(removed.json()["media"])
        self.assertEqual(404, self.client.get(f"/api/sessions/{first_id}/image").status_code)

        second = self.upload_and_confirm()
        reset = self.client.post(f"/api/sessions/{second['session_id']}/reset")
        self.assertEqual(200, reset.status_code)
        self.assertIsNone(reset.json()["media"])
        remaining_files = [
            filename for root, _dirs, files in os.walk(self.media_root.name) for filename in files
        ]
        self.assertEqual([], remaining_files)

    def test_confirmed_image_dispatch_projects_case_analysis_for_provider(self) -> None:
        matched = self.prepare_match()
        dispatched = self.dispatch(matched, "SYN-PROVIDER-001")
        case_id = dispatched["dispatch"]["case_id"]
        assigned = {"X-Demo-Provider-Id": "SYN-PROVIDER-001"}

        detail = self.client.get(f"/api/provider/cases/{case_id}", headers=assigned)
        image = self.client.get(
            f"/api/provider/cases/{case_id}/image",
            headers=assigned,
        )

        self.assertEqual(200, detail.status_code, detail.text)
        self.assertEqual(200, image.status_code, image.text)
        self.assertTrue(dispatched["dispatch"]["has_image"])
        self.assertTrue(detail.json()["has_image"])
        analysis = detail.json()["image_analysis"]
        self.assertTrue(analysis["confirmed"])
        self.assertEqual("水龍頭接縫附近疑似滲水", analysis["problem_summary"])
        self.assertNotIn("analysis_revision", analysis)

    def test_provider_image_access_obeys_assignment_and_status(self) -> None:
        matched = self.prepare_match()
        first = self.dispatch(matched, "SYN-PROVIDER-001")
        case_id = first["dispatch"]["case_id"]
        assigned = {"X-Demo-Provider-Id": "SYN-PROVIDER-001"}
        other = {"X-Demo-Provider-Id": "SYN-PROVIDER-002"}

        detail = self.client.get(f"/api/provider/cases/{case_id}", headers=assigned)
        pending_image = self.client.get(
            f"/api/provider/cases/{case_id}/image",
            headers=assigned,
        )
        unauthorized = self.client.get(
            f"/api/provider/cases/{case_id}/image",
            headers=other,
        )

        self.assertTrue(first["dispatch"]["has_image"])
        self.assertNotIn("image_path", first["dispatch"])
        self.assertTrue(detail.json()["has_image"])
        self.assertNotIn("image_path", detail.json())
        self.assertEqual(200, pending_image.status_code)
        self.assertEqual("no-store", pending_image.headers["cache-control"])
        self.assertIn("inline;", pending_image.headers["content-disposition"])
        self.assertEqual(404, unauthorized.status_code)

        rejected = self.client.post(
            f"/api/provider/cases/{case_id}/decision",
            headers=assigned,
            json={
                "decision": "reject",
                "confirmed": True,
                "idempotency_key": f"media-reject:{case_id}",
            },
        )
        self.assertEqual(200, rejected.status_code)
        self.assertFalse(rejected.json()["has_image"])
        self.assertIsNone(rejected.json()["image_analysis"])
        self.assertEqual(
            404,
            self.client.get(
                f"/api/provider/cases/{case_id}/image",
                headers=assigned,
            ).status_code,
        )

        refreshed = self.client.get(f"/api/sessions/{matched['session_id']}").json()
        second = self.dispatch(refreshed, "SYN-PROVIDER-002")
        second_case_id = second["dispatch"]["case_id"]
        accepted = self.client.post(
            f"/api/provider/cases/{second_case_id}/decision",
            headers=other,
            json={
                "decision": "accept",
                "confirmed": True,
                "idempotency_key": f"media-accept:{second_case_id}",
            },
        )
        accepted_image = self.client.get(
            f"/api/provider/cases/{second_case_id}/image",
            headers=other,
        )
        self.assertEqual(200, accepted.status_code)
        self.assertEqual(200, accepted_image.status_code)


class MediaConversationContinuityTests(unittest.TestCase):
    def test_confirmed_image_context_continues_through_split_location(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.answer("已確認修繕分支，請提供服務地點。"),
                ModelTurn.answer("已保留圖片確認結果，請再提供行政區。"),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="image-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="image-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("地點已驗證，請填寫諮詢表單。"),
            ]
        )
        vision = _VisionStub()
        reference_time = datetime(2026, 7, 27, 10, tzinfo=TAIPEI_TIMEZONE)
        with (
            tempfile.TemporaryDirectory() as media_root,
            patch.dict(
                os.environ,
                {
                    "WEB_MODEL_PROVIDER": "huggingface",
                    "MEDIA_ROOT": media_root,
                },
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "HF scripted continuation model"),
            ),
            patch(
                "home_repair_agent.web.app.HuggingFaceVisionClient.from_environment",
                return_value=vision,
            ),
            TestClient(create_app(reference_time=reference_time)) as client,
        ):
            session = client.post("/api/sessions").json()
            session_id = session["session_id"]
            proposal = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "水龍頭漏水"},
            )
            self.assertEqual(200, proposal.status_code, proposal.text)
            confirmed_branch = client.post(
                f"/api/sessions/{session_id}/branch/confirm",
                json={"branch": "faucet_leak", "confirm": True},
            )
            self.assertEqual(200, confirmed_branch.status_code, confirmed_branch.text)
            self.assertEqual("clarifying", confirmed_branch.json()["state"])

            upload = client.post(
                f"/api/sessions/{session_id}/image",
                files={"file": ("repair.png", _png_bytes(), "image/png")},
                data={"external_processing_confirmed": "true"},
            )
            self.assertEqual(200, upload.status_code, upload.text)
            media = upload.json()["media"]
            analysis = media["analysis"]
            record = client.app.state.web_sessions._sessions[session_id]
            conversation_before_confirmation = list(record.conversation.messages)
            confirmation = client.post(
                f"/api/sessions/{session_id}/image/confirm",
                json={
                    "media_id": media["media_id"],
                    "analysis_revision": analysis["analysis_revision"],
                    "service_query": analysis["service_query"],
                    "problem_summary": "水龍頭接縫持續漏水，使用者已確認。",
                    "safety_warnings": analysis["safety_warnings"],
                },
            )

            self.assertEqual(200, confirmation.status_code, confirmation.text)
            image_confirmed = confirmation.json()
            self.assertEqual("image_confirmed", image_confirmed["service_source"])
            self.assertEqual(17, image_confirmed["service"]["service_id"])
            self.assertEqual(conversation_before_confirmation, record.conversation.messages)

            county = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "臺北市"},
            )
            self.assertEqual(200, county.status_code, county.text)
            county_body = county.json()
            self.assertEqual("clarifying", county_body["state"])
            self.assertEqual("image_confirmed", county_body["service_source"])
            self.assertIsNone(county_body["location"])
            self.assertIsNone(county_body["consultation_form"])
            self.assertEqual(
                "臺北市",
                county_body["active_task"]["collected_fields"]["county_name"],
            )
            latest_request_messages = model.requests[-1][0]
            latest_user = next(
                message
                for message in reversed(latest_request_messages)
                if getattr(message, "kind", None) == "user"
            )
            self.assertIn("水龍頭接縫持續漏水", latest_user.text)
            self.assertIn("search_services 已唯一驗證服務：水電修繕", latest_user.text)

            district = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "大安區"},
            )
            self.assertEqual(200, district.status_code, district.text)
            complete = district.json()
            self.assertEqual("awaiting_form", complete["state"])
            self.assertEqual("image_confirmed", complete["service_source"])
            self.assertEqual("臺北市大安區", complete["location"]["full_name"])
            self.assertEqual("repair_form_v1", complete["consultation_form"]["form_key"])
            self.assertEqual(
                ["search_services", "resolve_location", "get_consultation_form"],
                [trace["name"] for trace in complete["tool_trace"]],
            )

            pending_calls: set[str] = set()
            for message in record.conversation.messages:
                if isinstance(message, AssistantToolCalls):
                    pending_calls.update(call.call_id for call in message.calls)
                elif isinstance(message, ToolResultMessage):
                    self.assertIn(message.call_id, pending_calls)
                    pending_calls.remove(message.call_id)
            self.assertEqual(set(), pending_calls)

            reset = client.post(f"/api/sessions/{session_id}/reset")
            self.assertEqual(200, reset.status_code, reset.text)
            reset_body = reset.json()
            self.assertIsNone(reset_body["media"])
            self.assertIsNone(reset_body["service"])
            self.assertIsNone(reset_body["service_source"])
            self.assertIsNone(reset_body["location"])
            self.assertIsNone(reset_body["consultation_form"])


class MediaWebMockModeTests(unittest.TestCase):
    def test_mock_mode_rejects_image_analysis_without_fallback(self) -> None:
        with (
            tempfile.TemporaryDirectory() as media_root,
            patch.dict(
                os.environ,
                {"WEB_MODEL_PROVIDER": "mock", "MEDIA_ROOT": media_root},
                clear=False,
            ),
            TestClient(create_app()) as client,
        ):
            session = client.post("/api/sessions").json()
            session_id = session["session_id"]
            proposal = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "臺北市大安區水龍頭漏水"},
            )
            self.assertEqual(200, proposal.status_code, proposal.text)
            confirmed = client.post(
                f"/api/sessions/{session_id}/branch/confirm",
                json={"branch": "faucet_leak", "confirm": True},
            )
            self.assertEqual(200, confirmed.status_code, confirmed.text)
            response = client.post(
                f"/api/sessions/{session_id}/image",
                files={"file": ("repair.png", _png_bytes(), "image/png")},
                data={"external_processing_confirmed": "true"},
            )
            self.assertEqual([], os.listdir(media_root))

        self.assertEqual(409, response.status_code)
        self.assertEqual("IMAGE_ANALYSIS_UNAVAILABLE", response.json()["error"]["code"])

    def test_bedrock_text_mode_does_not_create_or_fallback_to_hf_vision(self) -> None:
        with (
            tempfile.TemporaryDirectory() as media_root,
            patch.dict(
                os.environ,
                {"WEB_MODEL_PROVIDER": "bedrock", "MEDIA_ROOT": media_root},
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(RuleBasedRepairMockModel(), "Amazon Bedrock test double"),
            ),
            patch(
                "home_repair_agent.web.app.HuggingFaceVisionClient.from_environment"
            ) as vision_factory,
            TestClient(create_app()) as client,
        ):
            session = client.post("/api/sessions").json()
            session_id = session["session_id"]
            proposal = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "臺北市大安區水龍頭漏水"},
            )
            self.assertEqual(200, proposal.status_code, proposal.text)
            confirmed = client.post(
                f"/api/sessions/{session_id}/branch/confirm",
                json={"branch": "faucet_leak", "confirm": True},
            )
            self.assertEqual(200, confirmed.status_code, confirmed.text)
            response = client.post(
                f"/api/sessions/{session_id}/image",
                files={"file": ("repair.png", _png_bytes(), "image/png")},
                data={"external_processing_confirmed": "true"},
            )

            vision_factory.assert_not_called()
            self.assertEqual([], os.listdir(media_root))

        self.assertEqual(409, response.status_code)
        self.assertEqual("IMAGE_ANALYSIS_UNAVAILABLE", response.json()["error"]["code"])


if __name__ == "__main__":
    unittest.main()
