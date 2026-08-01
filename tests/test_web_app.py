from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock, call, patch

from fastapi.testclient import TestClient

from home_repair_agent.agent.demo import (
    TAIPEI_TIMEZONE,
    _build_curated_consultation_form,
)
from home_repair_agent.agent.mock_model import ScriptedModelClient
from home_repair_agent.agent.models import (
    AssistantMessage,
    AssistantToolCalls,
    ModelTurn,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from home_repair_agent.backend.models import ResolvedLocation
from home_repair_agent.backend.postgres_case_repository import (
    PostgresCaseWorkflowRepository,
)
from home_repair_agent.web.app import _resolve_case_repository, create_app
from home_repair_agent.web.demo_case_repository import DemoCaseWorkflowRepository
from home_repair_agent.web.service import _valid_form_contract

BRANCH_MESSAGES = {
    "faucet_leak": "臺北市大安區水龍頭漏水",
    "toilet_issue": "臺北市大安區馬桶無法沖水",
    "pipe_issue": "臺北市大安區水管堵塞",
    "electrical_issue": "臺北市大安區插座沒電",
    "other": "臺北市大安區有其他水電問題需要處理",
}


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

    def propose_branch(
        self,
        branch: str,
        *,
        text: str | None = None,
    ) -> dict[str, object]:
        session = self.create_session()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": text or BRANCH_MESSAGES[branch]},
        )
        self.assertEqual(200, response.status_code)
        proposal = response.json()
        self.assertIsNone(proposal["active_task"]["branch"])
        self.assertIn(branch, proposal["repair_routing"]["alternatives"])
        self.assertEqual([], proposal["tool_trace"])
        return proposal

    def confirm_branch(
        self,
        proposal: dict[str, object],
        branch: str,
        *,
        confirm: bool = True,
    ) -> dict[str, object]:
        response = self.client.post(
            f"/api/sessions/{proposal['session_id']}/branch/confirm",
            json={"branch": branch, "confirm": confirm},
        )
        self.assertEqual(200, response.status_code)
        return response.json()

    def prepare_form(
        self,
        branch: str = "faucet_leak",
        *,
        text: str | None = None,
    ) -> dict[str, object]:
        proposal = self.propose_branch(branch, text=text)
        session = self.confirm_branch(proposal, branch)
        self.assertEqual("awaiting_form", session["state"])
        self.assertEqual(branch, session["active_task"]["branch"])
        self.assertEqual("repair_form_v1", session["consultation_form"]["form_key"])
        self.assertEqual(17, session["service"]["service_id"])
        return session

    def valid_form_payload(
        self,
        session: dict[str, object],
        *,
        branch: str | None = None,
        start: str = "2026-08-01T13:00:00+08:00",
        end: str = "2026-08-01T17:00:00+08:00",
    ) -> dict[str, object]:
        branch = branch or session["active_task"]["branch"]
        answers: dict[str, object] = {}
        for topic in session["consultation_form"]["topics"]:
            key = topic["topic_key"]
            if key == "preferred_time":
                continue
            if key == "issue_category":
                answers[key] = branch
            elif key == "issue_description":
                answers[key] = f"{branch} 的 synthetic 測試狀況描述。"
            elif key == "water_shutoff":
                answers[key] = "yes"
            elif key in {"budget", "urgency"} and not topic["is_required"]:
                answers[key] = "skipped"
            elif topic["input_type"] == "single_select":
                answers[key] = topic["options"][0]["value"]
            elif topic["input_type"] == "multi_select":
                answers[key] = [topic["options"][0]["value"]]
            elif topic["is_required"]:
                answers[key] = f"{key} synthetic 測試值"
        return {
            "answers": answers,
            "preferred_start": start,
            "preferred_end": end,
        }

    def prepare_summary(self, branch: str = "faucet_leak") -> dict[str, object]:
        session = self.prepare_form(branch)
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=self.valid_form_payload(session, branch=branch),
        )
        self.assertEqual(200, response.status_code)
        return response.json()

    @staticmethod
    def summary_confirmation_payload(
        session: dict[str, object],
        *,
        confirm: bool = True,
    ) -> dict[str, object]:
        task = session["active_task"]
        summary = task["summary"]
        return {
            "active_task_id": task["active_task_id"],
            "summary_id": summary["summary_id"],
            "summary_version": summary["version"],
            "confirm": confirm,
        }

    def prepare_match(self, branch: str = "faucet_leak") -> dict[str, object]:
        session = self.prepare_summary(branch)
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/summary/confirm",
            json=self.summary_confirmation_payload(session),
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

    @staticmethod
    def checklist_by_key(session: dict[str, object]) -> dict[str, dict[str, object]]:
        return {item["key"]: item for item in session["checklist"]}

    @staticmethod
    def topic_keys(session: dict[str, object]) -> set[str]:
        return {topic["topic_key"] for topic in session["consultation_form"]["topics"]}

    def test_root_serves_the_operational_demo_and_asset(self) -> None:
        response = self.client.get("/")
        asset = self.client.get("/static/repair-workbench.webp")

        self.assertEqual(200, response.status_code)
        self.assertIn("修繕小隊長", response.text)
        self.assertIn("routing-section", response.text)
        self.assertIn("summary-confirm", response.text)
        self.assertIn("請勿輸入真實姓名", response.text)
        self.assertEqual(200, asset.status_code)
        self.assertEqual("image/webp", asset.headers["content-type"])
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    def test_health_declares_the_provider_workflow_demo_mode(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "ok": True,
                "service": "home-repair-web",
                "mode": "provider-workflow-demo",
                "model_provider": "mock",
            },
            response.json(),
        )
        self.assertEqual("no-store", response.headers["cache-control"])

    def test_fake_bedrock_mode_exposes_only_the_safe_provider_contract(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "WEB_MODEL_PROVIDER": "bedrock",
                    "AWS_PROFILE": "private-profile-marker",
                },
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(Mock(), "Amazon Bedrock test double"),
            ) as resolver,
            TestClient(create_app()) as client,
        ):
            health = client.get("/api/health")
            session = client.post("/api/sessions")

        self.assertEqual(200, health.status_code)
        self.assertEqual("bedrock", health.json()["model_provider"])
        self.assertEqual(201, session.status_code)
        self.assertEqual(
            {
                "key": "bedrock",
                "label": "Amazon Bedrock test double",
                "is_external": True,
            },
            session.json()["provider"],
        )
        resolver.assert_called_once_with("bedrock")
        public_response = f"{health.text}\n{session.text}"
        for forbidden in (
            "AWS_PROFILE",
            "private-profile-marker",
            "account_id",
            "arn:aws",
            "credential",
        ):
            self.assertNotIn(forbidden, public_response)

    def test_first_message_only_proposes_routing_until_explicit_confirmation(self) -> None:
        proposal = self.propose_branch("faucet_leak")

        self.assertEqual("routing_pending", proposal["state"])
        self.assertEqual("high", proposal["repair_routing"]["confidence"])
        self.assertIsNone(proposal["repair_routing"]["canonical_service_id"])
        self.assertEqual("faucet_leak", proposal["repair_routing"]["repair_branch"])
        self.assertIsNone(proposal["service"])
        self.assertIsNone(proposal["consultation_form"])
        self.assertFalse(proposal["can_submit_form"])

        session = self.confirm_branch(proposal, "faucet_leak")

        self.assertEqual("awaiting_form", session["state"])
        self.assertEqual("水電修繕", session["service"]["name"])
        self.assertEqual("臺北市大安區", session["location"]["full_name"])
        self.assertEqual("repair_form_v1", session["consultation_form"]["form_key"])
        self.assertEqual(
            ["search_services", "resolve_location", "get_consultation_form"],
            [entry["name"] for entry in session["tool_trace"]],
        )
        self.assertTrue(session["can_submit_form"])
        self.assertFalse(session["can_confirm_summary"])

    def test_branch_confirmation_revalidates_catalog_and_form_before_state_commit(
        self,
    ) -> None:
        malformed_contracts = (
            "service_count",
            "service_id",
            "form_key",
            "form_service_id",
            "version",
            "categories",
            "applicability",
        )
        for malformed_contract in malformed_contracts:
            with self.subTest(malformed_contract=malformed_contract):
                proposal = self.propose_branch("faucet_leak")
                tool_client = self.client.app.state.web_sessions._tool_client
                original_call = tool_client.call_tool

                async def malformed_call(
                    *,
                    name,
                    arguments,
                    _original_call=original_call,
                    _malformed_contract=malformed_contract,
                ):
                    execution = await _original_call(name=name, arguments=arguments)
                    payload = deepcopy(execution.payload)
                    if name == "search_services":
                        if _malformed_contract == "service_count":
                            payload["data"]["count"] = 2
                        elif _malformed_contract == "service_id":
                            payload["data"]["services"][0]["service_id"] = 99
                        return execution.model_copy(update={"payload": payload})
                    if name != "get_consultation_form":
                        return execution
                    if _malformed_contract == "form_key":
                        payload["data"]["form_key"] = "unexpected_form"
                    elif _malformed_contract == "form_service_id":
                        payload["data"]["service_id"] = 99
                    elif _malformed_contract == "version":
                        payload["data"]["version"] = 2
                    elif _malformed_contract == "categories":
                        category = next(
                            topic
                            for topic in payload["data"]["topics"]
                            if topic["topic_key"] == "issue_category"
                        )
                        category["options"] = category["options"][:-1]
                    elif _malformed_contract == "applicability":
                        water_shutoff = next(
                            topic
                            for topic in payload["data"]["topics"]
                            if topic["topic_key"] == "water_shutoff"
                        )
                        water_shutoff["config"] = {}
                    return execution.model_copy(update={"payload": payload})

                with patch.object(
                    tool_client,
                    "call_tool",
                    side_effect=malformed_call,
                ) as guarded_call:
                    response = self.client.post(
                        f"/api/sessions/{proposal['session_id']}/branch/confirm",
                        json={"branch": "faucet_leak", "confirm": True},
                    )

                self.assertEqual(503, response.status_code)
                self.assertEqual(
                    "BRANCH_VALIDATION_FAILED",
                    response.json()["error"]["code"],
                )
                expected_calls = [
                    call(
                        name="search_services",
                        arguments={"query": "水電修繕", "limit": 5},
                    )
                ]
                if malformed_contract not in {"service_count", "service_id"}:
                    expected_calls.append(
                        call(
                            name="get_consultation_form",
                            arguments={"service_id": 17},
                        )
                    )
                self.assertEqual(expected_calls, guarded_call.await_args_list)
                unchanged = self.client.get(f"/api/sessions/{proposal['session_id']}").json()
                self.assertEqual("routing_pending", unchanged["state"])
                self.assertIsNone(unchanged["active_task"]["branch"])
                self.assertIsNone(unchanged["service"])
                self.assertIsNone(unchanged["consultation_form"])
                self.assertEqual([], unchanged["tool_trace"])

    def test_repair_form_contract_rejects_malformed_applicability_and_version(
        self,
    ) -> None:
        valid_form = _build_curated_consultation_form()
        self.assertTrue(_valid_form_contract(valid_form))

        invalid_forms = {
            "form_key": valid_form.model_copy(
                update={"form_key": "unexpected_form"},
                deep=True,
            ),
            "service_id": valid_form.model_copy(update={"service_id": 99}, deep=True),
            "version": valid_form.model_copy(update={"version": 2}, deep=True),
        }
        category_topic = next(
            topic for topic in valid_form.topics if topic.topic_key == "issue_category"
        )
        missing_category = valid_form.model_copy(deep=True)
        next(
            topic for topic in missing_category.topics if topic.topic_key == "issue_category"
        ).options = category_topic.options[:-1]
        duplicate_category = valid_form.model_copy(deep=True)
        next(
            topic for topic in duplicate_category.topics if topic.topic_key == "issue_category"
        ).options = [*category_topic.options, category_topic.options[0].model_copy(deep=True)]
        unknown_category = valid_form.model_copy(deep=True)
        unknown_options = [option.model_copy(deep=True) for option in category_topic.options]
        unknown_options[-1].value = "roof_issue"
        next(
            topic for topic in unknown_category.topics if topic.topic_key == "issue_category"
        ).options = unknown_options
        invalid_forms.update(
            {
                "missing_category": missing_category,
                "duplicate_category": duplicate_category,
                "unknown_category": unknown_category,
            }
        )
        applicability_cases = {
            "empty_config": None,
            "scalar": "faucet_leak",
            "electrical_added": [
                "faucet_leak",
                "toilet_issue",
                "pipe_issue",
                "electrical_issue",
            ],
            "other_added": [
                "faucet_leak",
                "toilet_issue",
                "pipe_issue",
                "other",
            ],
            "unknown_added": [
                "faucet_leak",
                "toilet_issue",
                "pipe_issue",
                "roof_issue",
            ],
        }
        for name, applicability in applicability_cases.items():
            malformed = valid_form.model_copy(deep=True)
            water_shutoff = next(
                topic for topic in malformed.topics if topic.topic_key == "water_shutoff"
            )
            water_shutoff.config = (
                {} if applicability is None else {"applicable_issue_categories": applicability}
            )
            invalid_forms[name] = malformed

        for name, malformed in invalid_forms.items():
            with self.subTest(name=name):
                self.assertFalse(_valid_form_contract(malformed))

    def test_first_unsupported_message_enters_safe_stop(self) -> None:
        session = self.create_session()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "我想預約居家清潔和餐點外送"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("error", result["state"])
        self.assertTrue(result["repair_routing"]["unsupported"])
        self.assertIsNone(result["repair_routing"]["canonical_service_id"])
        self.assertIsNone(result["active_task"]["branch"])
        self.assertIsNone(result["service"])
        self.assertIsNone(result["consultation_form"])
        self.assertFalse(result["can_send_message"])
        self.assertFalse(result["can_submit_form"])
        self.assertFalse(result["can_confirm_summary"])
        self.assertFalse(result["can_dispatch"])
        self.assertEqual([], result["tool_trace"])

    def test_all_five_branches_require_confirmation_and_use_one_active_task(self) -> None:
        for branch in BRANCH_MESSAGES:
            with self.subTest(branch=branch):
                session = self.prepare_form(branch)
                options = next(
                    topic["options"]
                    for topic in session["consultation_form"]["topics"]
                    if topic["topic_key"] == "issue_category"
                )
                self.assertEqual([branch], [option["value"] for option in options])
                self.assertEqual(branch, session["active_task"]["branch"])
                self.assertNotIn("tasks", session)

    def test_multi_intent_is_not_split_and_requires_one_branch_selection(self) -> None:
        proposal = self.propose_branch(
            "faucet_leak",
            text="臺北市大安區水龍頭漏水，而且插座沒電",
        )

        self.assertEqual("medium", proposal["repair_routing"]["confidence"])
        self.assertEqual(
            {"faucet_leak", "electrical_issue"},
            set(proposal["repair_routing"]["alternatives"]),
        )
        self.assertIsNone(proposal["active_task"]["branch"])
        self.assertIsNone(proposal["consultation_form"])

        selected = self.confirm_branch(proposal, "faucet_leak")
        self.assertEqual("faucet_leak", selected["active_task"]["branch"])
        self.assertEqual("awaiting_form", selected["state"])

    def test_consumed_multi_intent_proposal_cannot_be_replayed_to_switch(self) -> None:
        proposal = self.propose_branch(
            "faucet_leak",
            text="臺北市大安區水龍頭漏水，而且插座沒電",
        )
        selected = self.confirm_branch(proposal, "faucet_leak")

        replay = self.client.post(
            f"/api/sessions/{selected['session_id']}/branch/confirm",
            json={"branch": "electrical_issue", "confirm": True},
        )

        self.assertEqual(409, replay.status_code)
        self.assertEqual("BRANCH_CONFIRMATION_NOT_PENDING", replay.json()["error"]["code"])
        refreshed = self.client.get(f"/api/sessions/{selected['session_id']}").json()
        self.assertEqual("faucet_leak", refreshed["active_task"]["branch"])

    def test_missing_county_never_defaults_to_taipei(self) -> None:
        proposal = self.propose_branch(
            "faucet_leak",
            text="大安區水龍頭漏水",
        )
        session = self.confirm_branch(proposal, "faucet_leak")

        self.assertEqual("clarifying", session["state"])
        self.assertIsNone(session["location"])
        self.assertIsNone(session["consultation_form"])
        self.assertIn("county_name", session["active_task"]["missing_fields"])
        self.assertIn("完整", session["messages"][-1]["text"])

        completed = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "臺北市大安區"},
        )
        self.assertEqual(200, completed.status_code)
        self.assertEqual("臺北市大安區", completed.json()["location"]["full_name"])

    def test_location_parts_before_branch_confirmation_accumulate_across_turns(
        self,
    ) -> None:
        session = self.create_session()
        session_id = session["session_id"]

        for text in ("新北市", "板橋區"):
            response = self.client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": text},
            )
            self.assertEqual(200, response.status_code)
            collecting = response.json()
            self.assertEqual("collecting_need", collecting["state"])
            self.assertTrue(collecting["can_send_message"])
            self.assertIsNone(collecting["service"])
            self.assertIsNone(collecting["location"])
            self.assertEqual([], collecting["tool_trace"])

        proposal_response = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "浴室水龍頭漏水。"},
        )
        self.assertEqual(200, proposal_response.status_code)
        proposal = proposal_response.json()
        self.assertEqual("routing_pending", proposal["state"])

        confirmed = self.confirm_branch(proposal, "faucet_leak")

        self.assertEqual("awaiting_form", confirmed["state"])
        self.assertEqual("新北市板橋區", confirmed["location"]["full_name"])
        self.assertEqual(
            ["search_services", "resolve_location", "get_consultation_form"],
            [entry["name"] for entry in confirmed["tool_trace"]],
        )

    def test_county_then_issue_then_district_unlocks_form_only_at_the_end(self) -> None:
        session = self.create_session()
        session_id = session["session_id"]

        county = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市"},
        )
        self.assertEqual(200, county.status_code, county.text)
        self.assertIsNone(county.json()["consultation_form"])

        proposal = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "水龍頭漏水"},
        )
        self.assertEqual(200, proposal.status_code, proposal.text)
        confirmed = self.confirm_branch(proposal.json(), "faucet_leak")

        self.assertEqual("clarifying", confirmed["state"])
        self.assertEqual("臺北市", confirmed["active_task"]["collected_fields"]["county_name"])
        self.assertIsNone(confirmed["location"])
        self.assertIsNone(confirmed["consultation_form"])
        self.assertTrue(confirmed["can_send_message"])
        self.assertFalse(confirmed["can_submit_form"])

        completed = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "大安區"},
        )
        self.assertEqual(200, completed.status_code, completed.text)
        body = completed.json()
        self.assertEqual("awaiting_form", body["state"])
        self.assertEqual("臺北市大安區", body["location"]["full_name"])
        self.assertEqual("repair_form_v1", body["consultation_form"]["form_key"])

    def test_issue_then_county_then_district_unlocks_form_only_at_the_end(self) -> None:
        proposal = self.propose_branch("faucet_leak", text="水龍頭漏水")
        confirmed = self.confirm_branch(proposal, "faucet_leak")
        session_id = confirmed["session_id"]

        county = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "臺北市"},
        )
        self.assertEqual(200, county.status_code, county.text)
        county_body = county.json()
        self.assertEqual("clarifying", county_body["state"])
        self.assertIsNone(county_body["location"])
        self.assertIsNone(county_body["consultation_form"])
        self.assertIn("district_name", county_body["active_task"]["missing_fields"])

        completed = self.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": "大安區"},
        )
        self.assertEqual(200, completed.status_code, completed.text)
        body = completed.json()
        self.assertEqual("awaiting_form", body["state"])
        self.assertEqual("臺北市大安區", body["location"]["full_name"])
        self.assertTrue(body["can_submit_form"])

    def test_ambiguous_issue_without_a_branch_remains_open_for_clarification(self) -> None:
        session = self.create_session()

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "家裡一直有水聲，但不知道哪裡壞掉。"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("collecting_need", result["state"])
        self.assertTrue(result["can_send_message"])
        self.assertIsNone(result["active_task"]["branch"])
        self.assertIsNone(result["service"])
        self.assertIsNone(result["location"])
        self.assertEqual([], result["tool_trace"])

    def test_manual_checklist_toggle_persists_through_session_refresh(self) -> None:
        session = self.prepare_form()
        session_id = session["session_id"]
        endpoint = f"/api/sessions/{session_id}/checklist/service"

        checked = self.client.put(endpoint, json={"checked": True})
        refreshed = self.client.get(f"/api/sessions/{session_id}")
        unchecked = self.client.put(endpoint, json={"checked": False})

        self.assertEqual(200, checked.status_code)
        self.assertTrue(self.checklist_by_key(checked.json())["service"]["checked"])
        self.assertTrue(self.checklist_by_key(refreshed.json())["service"]["checked"])
        self.assertEqual(200, unchecked.status_code)
        self.assertFalse(self.checklist_by_key(unchecked.json())["service"]["checked"])

    def test_unknown_checklist_item_is_rejected_without_changing_state(self) -> None:
        session = self.create_session()
        response = self.client.put(
            f"/api/sessions/{session['session_id']}/checklist/model_confirmed",
            json={"checked": True},
        )
        refreshed = self.client.get(f"/api/sessions/{session['session_id']}").json()

        self.assertEqual(422, response.status_code)
        self.assertTrue(all(not item["checked"] for item in refreshed["checklist"]))

    def test_form_submission_only_saves_and_builds_an_editable_summary(self) -> None:
        session = self.prepare_form()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=self.valid_form_payload(session),
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("awaiting_summary_confirmation", result["state"])
        self.assertEqual([], result["candidates"])
        self.assertNotIn(
            "match_service_providers",
            [entry["name"] for entry in result["tool_trace"]],
        )
        self.assertTrue(result["can_submit_form"])
        self.assertTrue(result["can_confirm_summary"])
        self.assertFalse(result["can_dispatch"])
        summary = result["active_task"]["summary"]
        self.assertEqual(1, summary["version"])
        self.assertFalse(summary["confirmed"])
        self.assertEqual("repair_form_v1", summary["form_key"])
        self.assertEqual("skipped", summary["answers"]["budget"])
        self.assertEqual("skipped", summary["answers"]["urgency"])

    def test_optional_budget_and_urgency_preserve_answer_states(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload(session)
        payload["answers"]["budget"] = "declined_to_answer"
        payload["answers"]["urgency"] = "urgent"

        accepted = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )

        self.assertEqual(200, accepted.status_code)
        answers = accepted.json()["active_task"]["summary"]["answers"]
        self.assertEqual("declined_to_answer", answers["budget"])
        self.assertEqual("urgent", answers["urgency"])
        self.assertEqual([], accepted.json()["candidates"])

        payload["answers"]["urgency"] = "immediate"
        rejected = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(422, rejected.status_code)
        self.assertEqual("INVALID_FORM_ANSWERS", rejected.json()["error"]["code"])
        self.assertIn("urgency", rejected.json()["error"]["fields"])

    def test_only_latest_summary_version_can_trigger_matching(self) -> None:
        session = self.prepare_summary()
        stale_payload = self.summary_confirmation_payload(session)
        stale_version = stale_payload["summary_version"]
        updated_payload = self.valid_form_payload(session)
        updated_payload["answers"]["issue_description"] = "更新後的 synthetic 描述。"
        updated = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=updated_payload,
        )
        self.assertEqual(200, updated.status_code)
        self.assertGreater(
            updated.json()["active_task"]["summary"]["version"],
            stale_version,
        )

        stale = self.client.post(
            f"/api/sessions/{session['session_id']}/summary/confirm",
            json=stale_payload,
        )
        self.assertEqual(409, stale.status_code)
        self.assertEqual("STALE_SUMMARY_VERSION", stale.json()["error"]["code"])
        self.assertEqual([], stale.json().get("candidates", []))

    def test_summary_confirmation_calls_matching_and_returns_candidates(self) -> None:
        result = self.prepare_match()

        self.assertEqual("matched", result["state"])
        self.assertEqual(2, len(result["candidates"]))
        self.assertTrue(
            all(candidate["source_type"] == "synthetic" for candidate in result["candidates"])
        )
        self.assertEqual("match_service_providers", result["tool_trace"][-1]["name"])
        self.assertTrue(result["active_task"]["summary"]["confirmed"])
        self.assertTrue(result["can_dispatch"])

    def test_unconfirmed_summary_cannot_match_or_dispatch(self) -> None:
        session = self.prepare_summary()
        endpoint = f"/api/sessions/{session['session_id']}/summary/confirm"

        unconfirmed = self.client.post(
            endpoint,
            json=self.summary_confirmation_payload(session, confirm=False),
        )
        dispatch = self.client.post(
            f"/api/sessions/{session['session_id']}/dispatch",
            json=self.dispatch_payload(),
        )

        self.assertEqual(422, unconfirmed.status_code)
        self.assertEqual("SUMMARY_CONFIRMATION_REQUIRED", unconfirmed.json()["error"]["code"])
        self.assertEqual(409, dispatch.status_code)
        self.assertEqual("SUMMARY_CONFIRMATION_REQUIRED", dispatch.json()["error"]["code"])

    def test_other_requires_a_descriptive_issue_description(self) -> None:
        session = self.prepare_form("other")
        payload = self.valid_form_payload(session, branch="other")
        payload["answers"]["issue_description"] = "其他。"

        invalid = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(422, invalid.status_code)
        self.assertEqual("INVALID_FORM_ANSWERS", invalid.json()["error"]["code"])
        self.assertIn("issue_description", invalid.json()["error"]["fields"])

        payload["answers"]["issue_description"] = "浴室蓮蓬頭接頭持續滲水。"
        valid = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(200, valid.status_code)
        self.assertEqual("other", valid.json()["active_task"]["branch"])
        self.assertEqual(
            "浴室蓮蓬頭接頭持續滲水。",
            valid.json()["answers"]["issue_description"],
        )

    def test_electrical_branch_excludes_water_shutoff_everywhere(self) -> None:
        session = self.prepare_form("electrical_issue")
        self.assertNotIn("water_shutoff", self.topic_keys(session))
        payload = self.valid_form_payload(session, branch="electrical_issue")
        self.assertNotIn("water_shutoff", payload["answers"])

        injected = self.valid_form_payload(session, branch="electrical_issue")
        injected["answers"]["water_shutoff"] = "yes"
        rejected = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=injected,
        )
        self.assertEqual(422, rejected.status_code)
        self.assertEqual("UNKNOWN_FORM_FIELD", rejected.json()["error"]["code"])

        saved = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(200, saved.status_code)
        self.assertNotIn("water_shutoff", saved.json()["answers"])
        self.assertNotIn(
            "water_shutoff",
            saved.json()["active_task"]["summary"]["answers"],
        )

    def test_branch_switch_requires_confirmation_and_clears_branch_data(self) -> None:
        session = self.prepare_summary("faucet_leak")
        self.assertIn("water_shutoff", session["answers"])
        original_location = session["location"]
        original_start = session["preferred_start"]

        pending = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "其實是插座沒電，要改處理電路問題"},
        )
        self.assertEqual(200, pending.status_code)
        pending_body = pending.json()
        self.assertEqual("replacement_pending", pending_body["state"])
        self.assertEqual("faucet_leak", pending_body["active_task"]["branch"])
        self.assertIn("water_shutoff", pending_body["answers"])

        switched = self.client.post(
            f"/api/sessions/{session['session_id']}/branch/confirm",
            json={"branch": "electrical_issue", "confirm": True},
        )
        self.assertEqual(200, switched.status_code)
        result = switched.json()
        self.assertEqual("electrical_issue", result["active_task"]["branch"])
        self.assertEqual(original_location, result["location"])
        self.assertEqual(original_start, result["preferred_start"])
        self.assertNotIn("water_shutoff", result["answers"])
        self.assertNotIn("water_shutoff", self.topic_keys(result))
        self.assertTrue(result["active_task"]["shared_slots_need_confirmation"])
        self.assertIsNone(result["active_task"]["summary"])
        self.assertEqual([], result["candidates"])

    def test_branch_switch_with_location_text_clears_old_location(self) -> None:
        session = self.prepare_summary("faucet_leak")
        original_start = session["preferred_start"]

        pending = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "其實要改成新北市板橋區的插座沒電"},
        )
        self.assertEqual(200, pending.status_code)
        self.assertEqual("replacement_pending", pending.json()["state"])

        switched = self.client.post(
            f"/api/sessions/{session['session_id']}/branch/confirm",
            json={"branch": "electrical_issue", "confirm": True},
        )

        self.assertEqual(200, switched.status_code)
        result = switched.json()
        self.assertEqual("clarifying", result["state"])
        self.assertEqual("electrical_issue", result["active_task"]["branch"])
        self.assertIsNone(result["location"])
        self.assertIsNone(result["consultation_form"])
        self.assertEqual(original_start, result["preferred_start"])
        self.assertTrue(result["active_task"]["shared_slots_need_confirmation"])
        self.assertFalse(result["can_submit_form"])
        self.assertIn("完整縣市＋行政區", result["messages"][-1]["text"])

        completed = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "新北市板橋區"},
        )
        self.assertEqual(200, completed.status_code)
        self.assertEqual("新北市板橋區", completed.json()["location"]["full_name"])
        self.assertEqual("awaiting_form", completed.json()["state"])

    def test_location_correction_revalidates_and_makes_the_old_summary_stale(self) -> None:
        proposal = self.propose_branch(
            "faucet_leak",
            text="新北市板橋區水龍頭漏水",
        )
        ready = self.confirm_branch(proposal, "faucet_leak")
        saved_response = self.client.post(
            f"/api/sessions/{ready['session_id']}/form",
            json=self.valid_form_payload(ready),
        )
        self.assertEqual(200, saved_response.status_code)
        saved = saved_response.json()
        stale_summary = self.summary_confirmation_payload(saved)

        correction = self.client.post(
            f"/api/sessions/{ready['session_id']}/messages",
            json={"text": "改成臺北市大安區。"},
        )

        self.assertEqual(200, correction.status_code)
        corrected = correction.json()
        self.assertEqual("awaiting_form", corrected["state"])
        self.assertEqual("臺北市大安區", corrected["location"]["full_name"])
        self.assertEqual("repair_form_v1", corrected["consultation_form"]["form_key"])
        self.assertTrue(corrected["active_task"]["shared_slots_need_confirmation"])
        self.assertIsNone(corrected["active_task"]["summary"])
        self.assertEqual([], corrected["candidates"])
        self.assertTrue(corrected["can_submit_form"])
        self.assertFalse(corrected["can_confirm_summary"])
        self.assertFalse(corrected["can_dispatch"])
        self.assertEqual(
            1,
            sum(entry["name"] == "resolve_location" for entry in corrected["tool_trace"]),
        )
        self.assertEqual(
            1,
            sum(entry["name"] == "get_consultation_form" for entry in corrected["tool_trace"]),
        )
        self.assertNotIn(
            "match_service_providers",
            [entry["name"] for entry in corrected["tool_trace"]],
        )

        resaved_response = self.client.post(
            f"/api/sessions/{ready['session_id']}/form",
            json=self.valid_form_payload(corrected),
        )
        self.assertEqual(200, resaved_response.status_code)
        resaved = resaved_response.json()
        self.assertGreater(
            resaved["active_task"]["summary"]["version"],
            stale_summary["summary_version"],
        )

        stale = self.client.post(
            f"/api/sessions/{ready['session_id']}/summary/confirm",
            json=stale_summary,
        )
        self.assertEqual(409, stale.status_code)
        self.assertEqual("STALE_SUMMARY_VERSION", stale.json()["error"]["code"])

    def test_incomplete_location_correction_clears_old_location_without_guessing(
        self,
    ) -> None:
        ready = self.prepare_form(
            "faucet_leak",
            text="新北市板橋區水龍頭漏水",
        )

        correction = self.client.post(
            f"/api/sessions/{ready['session_id']}/messages",
            json={"text": "改成大安區。"},
        )

        self.assertEqual(200, correction.status_code)
        corrected = correction.json()
        self.assertEqual("clarifying", corrected["state"])
        self.assertIsNone(corrected["location"])
        self.assertIsNone(corrected["consultation_form"])
        self.assertFalse(corrected["can_submit_form"])
        self.assertIn("完整的縣市與行政區", corrected["messages"][-1]["text"])

        completed = self.client.post(
            f"/api/sessions/{ready['session_id']}/messages",
            json={"text": "臺北市大安區"},
        )
        self.assertEqual(200, completed.status_code)
        completed_body = completed.json()
        self.assertEqual("awaiting_form", completed_body["state"])
        self.assertEqual("臺北市大安區", completed_body["location"]["full_name"])
        self.assertTrue(completed_body["can_submit_form"])

    def test_location_like_issue_text_does_not_silently_replace_location(self) -> None:
        ready = self.prepare_form(
            "faucet_leak",
            text="新北市板橋區水龍頭漏水",
        )

        response = self.client.post(
            f"/api/sessions/{ready['session_id']}/messages",
            json={"text": "施工區域在浴室。"},
        )

        self.assertEqual(409, response.status_code)
        self.assertEqual("FORM_ALREADY_READY", response.json()["error"]["code"])
        unchanged = self.client.get(f"/api/sessions/{ready['session_id']}").json()
        self.assertEqual("新北市板橋區", unchanged["location"]["full_name"])
        self.assertEqual("repair_form_v1", unchanged["consultation_form"]["form_key"])

    def test_replacement_pending_blocks_old_summary_confirmation(self) -> None:
        session = self.prepare_summary("faucet_leak")
        summary_payload = self.summary_confirmation_payload(session)
        pending = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "其實要改處理插座沒電"},
        )
        self.assertEqual(200, pending.status_code)
        self.assertFalse(pending.json()["can_confirm_summary"])
        self.assertFalse(pending.json()["can_submit_form"])

        confirmation = self.client.post(
            f"/api/sessions/{session['session_id']}/summary/confirm",
            json=summary_payload,
        )
        self.assertEqual(409, confirmation.status_code)
        self.assertEqual("BRANCH_CONFIRMATION_REQUIRED", confirmation.json()["error"]["code"])
        self.assertEqual(
            [], self.client.get(f"/api/sessions/{session['session_id']}").json()["candidates"]
        )

    def test_safety_message_is_not_hidden_by_a_ready_form(self) -> None:
        session = self.prepare_form("electrical_issue")
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={"text": "插座正在冒火花而且有焦味"},
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("error", result["state"])
        self.assertIn("遠離", result["messages"][-1]["text"])
        self.assertFalse(result["can_submit_form"])
        self.assertFalse(result["can_confirm_summary"])
        self.assertFalse(result["can_dispatch"])

    def test_explicit_danger_terms_stop_before_branch_confirmation(self) -> None:
        danger_messages = (
            "插座疑似漏電",
            "有人碰到插座觸電",
            "插座已經起火",
            "家中發生火災",
            "屋內聞到瓦斯",
            "現場有人身危險",
            "插座傳出焦味",
        )
        for message in danger_messages:
            with self.subTest(message=message):
                session = self.create_session()
                response = self.client.post(
                    f"/api/sessions/{session['session_id']}/messages",
                    json={"text": message},
                )

                self.assertEqual(200, response.status_code)
                result = response.json()
                self.assertEqual("error", result["state"])
                self.assertFalse(result["can_send_message"])
                self.assertFalse(result["can_submit_form"])
                self.assertFalse(result["can_confirm_summary"])
                self.assertFalse(result["can_dispatch"])
                self.assertEqual([], result["tool_trace"])

    def test_form_rejects_unknown_fields_instead_of_guessing(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload(session)
        payload["answers"]["invented_service_code"] = "7"

        response = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(422, response.status_code)
        self.assertEqual("UNKNOWN_FORM_FIELD", response.json()["error"]["code"])

    def test_form_requires_taipei_aware_future_time_window(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload(session)
        payload["preferred_start"] = "2026-08-01T13:00:00"
        missing_timezone = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(422, missing_timezone.status_code)
        self.assertIn("+08:00", missing_timezone.text)

        payload = self.valid_form_payload(
            session,
            start="2026-07-26T13:00:00+08:00",
            end="2026-07-26T17:00:00+08:00",
        )
        past = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        )
        self.assertEqual(422, past.status_code)
        self.assertEqual("INVALID_TIME_WINDOW", past.json()["error"]["code"])

    def test_empty_matching_result_is_shown_without_inventing_a_provider(self) -> None:
        session = self.prepare_form()
        payload = self.valid_form_payload(
            session,
            start="2026-08-01T20:00:00+08:00",
            end="2026-08-01T22:00:00+08:00",
        )
        saved = self.client.post(
            f"/api/sessions/{session['session_id']}/form",
            json=payload,
        ).json()
        response = self.client.post(
            f"/api/sessions/{session['session_id']}/summary/confirm",
            json=self.summary_confirmation_payload(saved),
        )

        self.assertEqual(200, response.status_code)
        result = response.json()
        self.assertEqual("no_candidates", result["state"])
        self.assertEqual([], result["candidates"])
        self.assertIn("不會自行捏造人選", result["messages"][-1]["text"])

    def test_web_model_cannot_route_or_match_as_a_business_fact(self) -> None:
        model = _MatchingAttemptModel()
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "review model"),
            ),
            TestClient(create_app()) as client,
        ):
            session = client.post("/api/sessions").json()
            proposal = client.post(
                f"/api/sessions/{session['session_id']}/messages",
                json={"text": "臺北市大安區水龍頭漏水"},
            ).json()
            self.assertEqual("faucet_leak", proposal["repair_routing"]["repair_branch"])
            self.assertEqual(0, model.calls)
            response = client.post(
                f"/api/sessions/{session['session_id']}/branch/confirm",
                json={"branch": "faucet_leak", "confirm": True},
            )

        self.assertEqual(200, response.status_code)
        self.assertNotIn("match_service_providers", model.exposed_tool_names)
        self.assertEqual("error", response.json()["state"])
        self.assertEqual([], response.json()["candidates"])

    def test_reset_clears_active_task_without_creating_a_case(self) -> None:
        session = self.prepare_form()
        service = self.client.app.state.web_sessions
        record_before_reset = service._sessions[session["session_id"]]
        response = self.client.post(f"/api/sessions/{session['session_id']}/reset")
        record_after_reset = service._sessions[session["session_id"]]

        self.assertEqual(200, response.status_code)
        self.assertIs(record_before_reset, record_after_reset)
        self.assertIs(record_before_reset.lock, record_after_reset.lock)
        reset = response.json()
        self.assertEqual("collecting_need", reset["state"])
        self.assertIsNone(reset["active_task"])
        self.assertIsNone(reset["repair_routing"])
        self.assertIsNone(reset["service"])
        self.assertEqual([], reset["candidates"])

    def test_faucet_and_electrical_http_e2e_reach_dispatch(self) -> None:
        journeys = (
            ("faucet_leak", "我家水龍頭一直漏水，在大安區"),
            ("electrical_issue", "家裡插座一直冒火花"),
        )
        for branch, first_message in journeys:
            with self.subTest(branch=branch):
                proposal = self.propose_branch(branch, text=first_message)
                self.assertEqual("routing_pending", proposal["state"])
                self.assertIsNone(proposal["repair_routing"]["canonical_service_id"])
                self.assertIsNone(proposal["location"])
                self.assertIsNone(proposal["consultation_form"])
                self.assertIsNone(proposal["dispatch"])
                self.assertFalse(proposal["can_dispatch"])
                if branch == "electrical_issue":
                    self.assertIn("遠離", proposal["messages"][-1]["text"])

                confirmed = self.confirm_branch(proposal, branch)
                self.assertEqual("clarifying", confirmed["state"])
                self.assertEqual(17, confirmed["repair_routing"]["canonical_service_id"])
                self.assertIsNone(confirmed["location"])
                self.assertIsNone(confirmed["consultation_form"])
                self.assertEqual(
                    ["search_services"],
                    [entry["name"] for entry in confirmed["tool_trace"]],
                )

                location_response = self.client.post(
                    f"/api/sessions/{proposal['session_id']}/messages",
                    json={"text": "臺北市大安區"},
                )
                self.assertEqual(200, location_response.status_code)
                form_ready = location_response.json()
                self.assertEqual("awaiting_form", form_ready["state"])
                self.assertEqual("臺北市大安區", form_ready["location"]["full_name"])
                if branch == "electrical_issue":
                    self.assertNotIn("water_shutoff", self.topic_keys(form_ready))

                saved_response = self.client.post(
                    f"/api/sessions/{proposal['session_id']}/form",
                    json=self.valid_form_payload(form_ready, branch=branch),
                )
                self.assertEqual(200, saved_response.status_code)
                saved = saved_response.json()
                summary = saved["active_task"]["summary"]
                match_response = self.client.post(
                    f"/api/sessions/{proposal['session_id']}/summary/confirm",
                    json=self.summary_confirmation_payload(saved),
                )
                self.assertEqual(200, match_response.status_code)
                matched = match_response.json()
                self.assertEqual("matched", matched["state"])
                self.assertIsNone(matched["dispatch"])

                dispatch_payload = self.dispatch_payload()
                dispatch_payload["idempotency_key"] = f"dispatch:e2e:{branch}"
                dispatched = self.client.post(
                    f"/api/sessions/{matched['session_id']}/dispatch",
                    json=dispatch_payload,
                )
                self.assertEqual(200, dispatched.status_code)
                body = dispatched.json()
                self.assertEqual("dispatch_pending", body["state"])
                case_id = body["dispatch"]["case_id"]
                detail = self.client.get(
                    f"/api/provider/cases/{case_id}",
                    headers={"X-Demo-Provider-Id": "SYN-PROVIDER-001"},
                )
                self.assertEqual(200, detail.status_code)
                self.assertEqual("repair_form_v1", summary["form_key"])
                if branch == "faucet_leak":
                    self.assertIn("water_shutoff", detail.json()["answers"])
                else:
                    self.assertNotIn("water_shutoff", detail.json()["answers"])

    def test_dispatch_requires_confirmation_and_is_idempotent(self) -> None:
        matched = self.prepare_match()
        endpoint = f"/api/sessions/{matched['session_id']}/dispatch"

        unconfirmed = self.client.post(endpoint, json=self.dispatch_payload(confirmed=False))
        first = self.client.post(endpoint, json=self.dispatch_payload())
        second = self.client.post(endpoint, json=self.dispatch_payload())

        self.assertEqual(422, unconfirmed.status_code)
        self.assertEqual("CONFIRMATION_REQUIRED", unconfirmed.json()["error"]["code"])
        self.assertEqual(200, first.status_code)
        self.assertEqual(200, second.status_code)
        self.assertEqual(first.json()["dispatch"]["case_id"], second.json()["dispatch"]["case_id"])

    def test_case_and_provider_states_reject_form_rewrite(self) -> None:
        expected_states = {
            None: "dispatch_pending",
            "accept": "provider_accepted",
            "reject": "provider_rejected",
        }
        for decision, expected_state in expected_states.items():
            with self.subTest(decision=decision):
                matched = self.prepare_match()
                dispatch_payload = self.dispatch_payload()
                dispatch_payload["idempotency_key"] = f"dispatch:form-lock:{decision or 'pending'}"
                dispatched = self.client.post(
                    f"/api/sessions/{matched['session_id']}/dispatch",
                    json=dispatch_payload,
                ).json()
                case_id = dispatched["dispatch"]["case_id"]
                if decision is not None:
                    provider_response = self.client.post(
                        f"/api/provider/cases/{case_id}/decision",
                        headers={"X-Demo-Provider-Id": "SYN-PROVIDER-001"},
                        json={
                            "decision": decision,
                            "confirmed": True,
                            "idempotency_key": f"{decision}:form-lock:{case_id}",
                        },
                    )
                    self.assertEqual(200, provider_response.status_code)
                locked = self.client.get(f"/api/sessions/{matched['session_id']}").json()
                self.assertEqual(expected_state, locked["state"])
                original_answers = locked["answers"]
                original_summary = locked["active_task"]["summary"]
                payload = self.valid_form_payload(locked)
                payload["answers"]["issue_description"] = "不得寫入的 synthetic 變更。"

                response = self.client.post(
                    f"/api/sessions/{matched['session_id']}/form",
                    json=payload,
                )

                self.assertEqual(409, response.status_code)
                self.assertEqual(
                    "CASE_ALREADY_SUBMITTED",
                    response.json()["error"]["code"],
                )
                unchanged = self.client.get(f"/api/sessions/{matched['session_id']}").json()
                self.assertEqual(expected_state, unchanged["state"])
                self.assertEqual(original_answers, unchanged["answers"])
                self.assertEqual(original_summary, unchanged["active_task"]["summary"])

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

        self.assertEqual(422, response.status_code)
        self.assertEqual("INVALID_TIME_WINDOW", response.json()["error"]["code"])

    def test_provider_page_and_synthetic_identities_are_available(self) -> None:
        page = self.client.get("/provider")
        identities = self.client.get("/api/provider/identities")

        self.assertEqual(200, page.status_code)
        self.assertIn("廠商工作台", page.text)
        self.assertEqual(200, identities.status_code)
        self.assertEqual(
            ["SYN-PROVIDER-001", "SYN-PROVIDER-002"],
            [identity["provider_id"] for identity in identities.json()["identities"]],
        )

    def test_assigned_provider_accepts_and_consumer_sees_order_status(self) -> None:
        matched = self.prepare_match()
        dispatched = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        ).json()
        case_id = dispatched["dispatch"]["case_id"]
        provider_headers = {"X-Demo-Provider-Id": "SYN-PROVIDER-001"}

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
        consumer = self.client.get(f"/api/sessions/{matched['session_id']}")

        self.assertEqual("masked", pending.json()["contact"]["access"])
        self.assertEqual("0912***678", pending.json()["contact"]["mobile"])
        self.assertNotIn("Demo 路", pending.json()["contact"]["address"])
        self.assertEqual(404, unauthorized.status_code)
        self.assertEqual(200, accepted.status_code)
        self.assertEqual("accepted", accepted.json()["status"])
        self.assertEqual("full", accepted.json()["contact"]["access"])
        self.assertEqual("0912-345-678", accepted.json()["contact"]["mobile"])
        self.assertTrue(accepted.json()["order_no"].startswith("SYN-ORDER-"))
        self.assertEqual("provider_accepted", consumer.json()["state"])

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
        consumer = self.client.get(f"/api/sessions/{matched['session_id']}").json()
        second = self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(provider_id="SYN-PROVIDER-002"),
        )

        self.assertEqual(200, rejection.status_code)
        self.assertEqual("provider_rejected", consumer["state"])
        self.assertTrue(consumer["can_dispatch"])
        self.assertEqual(200, second.status_code)
        self.assertEqual("SYN-PROVIDER-002", second.json()["dispatch"]["provider_id"])

    def test_reset_rejects_erasing_an_audited_case(self) -> None:
        matched = self.prepare_match()
        self.client.post(
            f"/api/sessions/{matched['session_id']}/dispatch",
            json=self.dispatch_payload(),
        )
        response = self.client.post(f"/api/sessions/{matched['session_id']}/reset")

        self.assertEqual(409, response.status_code)
        self.assertEqual("CASE_ALREADY_SUBMITTED", response.json()["error"]["code"])

    def test_factory_rejects_mismatched_case_workflow_injection(self) -> None:
        session_service = Mock()
        session_service.case_workflow = object()

        with self.assertRaisesRegex(ValueError, "same CaseWorkflowService"):
            create_app(session_service=session_service, case_workflow=object())

    def test_unknown_session_returns_safe_404(self) -> None:
        response = self.client.get("/api/sessions/not-a-session")

        self.assertEqual(404, response.status_code)
        self.assertEqual("SESSION_NOT_FOUND", response.json()["error"]["code"])


class WebToolProvenanceTests(unittest.TestCase):
    reference_time = datetime(2026, 7, 27, 10, tzinfo=TAIPEI_TIMEZONE)

    @staticmethod
    def _create_session(client: TestClient) -> str:
        response = client.post("/api/sessions")
        if response.status_code != 201:
            raise AssertionError(response.text)
        return response.json()["session_id"]

    @staticmethod
    def _propose_and_confirm(
        client: TestClient,
        *,
        session_id: str,
        messages: tuple[str, ...],
    ) -> dict[str, object]:
        proposal = None
        for text in messages:
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": text},
            )
            if response.status_code != 200:
                raise AssertionError(response.text)
            proposal = response.json()
        if proposal is None:
            raise AssertionError("at least one message is required")
        confirmation = client.post(
            f"/api/sessions/{session_id}/branch/confirm",
            json={"branch": "faucet_leak", "confirm": True},
        )
        if confirmation.status_code != 200:
            raise AssertionError(confirmation.text)
        return confirmation.json()

    def test_county_only_cannot_be_completed_by_a_model_guess(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="guessed-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="early-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("已取得表單。"),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="grounded-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="grounded-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("地點與表單已完成驗證。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted provenance model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            rejected = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市", "水龍頭漏水"),
            )

            self.assertEqual("clarifying", rejected["state"])
            self.assertEqual("text_tool", rejected["service_source"])
            self.assertIsNone(rejected["location"])
            self.assertIsNone(rejected["consultation_form"])
            self.assertTrue(rejected["can_send_message"])
            self.assertFalse(rejected["can_submit_form"])
            self.assertEqual(
                "臺北市",
                rejected["active_task"]["collected_fields"]["county_name"],
            )
            self.assertNotIn("county_name", rejected["active_task"]["missing_fields"])
            self.assertIn("district_name", rejected["active_task"]["missing_fields"])
            self.assertEqual(
                [False, False],
                [item["ok"] for item in rejected["tool_trace"][-2:]],
            )

            completed = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "大安區"},
            )

            self.assertEqual(200, completed.status_code, completed.text)
            body = completed.json()
            self.assertEqual("awaiting_form", body["state"], body)
            self.assertEqual("臺北市大安區", body["location"]["full_name"])
            self.assertEqual("repair_form_v1", body["consultation_form"]["form_key"])
            self.assertNotIn(
                "search_services",
                [trace["name"] for trace in body["tool_trace"]],
            )

    def test_failed_location_and_early_form_do_not_deadlock_the_session(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="missing-district",
                        name="resolve_location",
                        arguments={"county_name": "臺北市"},
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="premature-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("請填寫表單。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted premature form model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            result = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市", "水龍頭漏水"),
            )

            self.assertEqual("clarifying", result["state"])
            self.assertIsNone(result["location"])
            self.assertIsNone(result["consultation_form"])
            self.assertTrue(result["can_send_message"])
            self.assertFalse(result["can_submit_form"])
            self.assertIn("完整行政區", result["messages"][-1]["text"])

    def test_invalid_trace_is_atomic_and_error_state_blocks_form_write(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="valid-search",
                        name="search_services",
                        arguments={"query": "水龍頭漏水", "limit": 5},
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="valid-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="valid-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="forbidden-match",
                        name="match_service_providers",
                        arguments={
                            "service_id": 17,
                            "location_id": "SYN-LOC-TPE-DAAN",
                            "limit": 3,
                        },
                    )
                ),
                ModelTurn.answer("已完成所有步驟。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted forbidden tool model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            result = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市大安區水龍頭漏水",),
            )

            self.assertEqual("error", result["state"])
            self.assertEqual("text_tool", result["service_source"])
            self.assertIsNone(result["location"])
            self.assertIsNone(result["consultation_form"])
            self.assertFalse(result["can_submit_form"])
            record = client.app.state.web_sessions._sessions[session_id]
            self.assertEqual(2, len(record.conversation.messages))
            self.assertIsInstance(record.conversation.messages[0], UserMessage)
            self.assertIsInstance(record.conversation.messages[1], AssistantMessage)
            self.assertFalse(
                any(
                    isinstance(message, (AssistantToolCalls, ToolResultMessage))
                    for message in record.conversation.messages
                )
            )

            blocked = client.post(
                f"/api/sessions/{session_id}/form",
                json={
                    "answers": {},
                    "preferred_start": "2026-08-01T13:00:00+08:00",
                    "preferred_end": "2026-08-01T17:00:00+08:00",
                },
            )
            self.assertEqual(409, blocked.status_code, blocked.text)
            self.assertEqual("AGENT_TURN_NOT_VERIFIED", blocked.json()["error"]["code"])

    def test_wrong_form_service_id_is_rejected_without_partial_location(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="valid-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="wrong-form-service",
                        name="get_consultation_form",
                        arguments={"service_id": 99},
                    )
                ),
                ModelTurn.answer("已取得表單。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted wrong id model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            result = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市大安區水龍頭漏水",),
            )

            self.assertEqual("error", result["state"])
            self.assertIsNone(result["location"])
            self.assertIsNone(result["consultation_form"])
            self.assertFalse(result["can_submit_form"])

    def test_location_provenance_accepts_a_natural_language_district_turn(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.answer("請補充行政區。"),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="natural-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="natural-location-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("地點與表單已完成驗證。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted natural location model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            waiting = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市", "水龍頭漏水"),
            )
            self.assertEqual("clarifying", waiting["state"])

            completed = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "我住在大安區"},
            )

            self.assertEqual(200, completed.status_code, completed.text)
            body = completed.json()
            self.assertEqual("awaiting_form", body["state"])
            self.assertEqual("臺北市大安區", body["location"]["full_name"])

    def test_new_county_cannot_reuse_a_district_from_an_old_location(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="cross-wired-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "嘉義市",
                            "district_name": "東區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="cross-wired-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("地點與表單已完成驗證。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted cross-wired location model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            result = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("新竹市東區", "改成嘉義市", "水龍頭漏水"),
            )

            self.assertEqual("clarifying", result["state"])
            self.assertIsNone(result["location"])
            self.assertIsNone(result["consultation_form"])
            self.assertEqual(
                "嘉義市",
                result["active_task"]["collected_fields"]["county_name"],
            )
            self.assertIn("district_name", result["active_task"]["missing_fields"])

    def test_negated_district_is_not_location_provenance(self) -> None:
        messages = (
            "臺北市大安區不是我的服務地點，水龍頭漏水",
            "臺北市除了大安區以外，水龍頭漏水",
            "臺北市我沒有住在大安區，水龍頭漏水",
            "臺北市先不要用大安區，水龍頭漏水",
            "臺北市大安區並非服務地點，水龍頭漏水",
            "臺北市別考慮大安區，水龍頭漏水",
        )
        for message in messages:
            with self.subTest(message=message):
                model = ScriptedModelClient(
                    [
                        ModelTurn.use_tools(
                            ToolCall(
                                call_id="negated-location",
                                name="resolve_location",
                                arguments={
                                    "county_name": "臺北市",
                                    "district_name": "大安區",
                                },
                            )
                        ),
                        ModelTurn.use_tools(
                            ToolCall(
                                call_id="negated-location-form",
                                name="get_consultation_form",
                                arguments={"service_id": 17},
                            )
                        ),
                        ModelTurn.answer("地點與表單已完成驗證。"),
                    ]
                )
                with (
                    patch(
                        "home_repair_agent.web.app._resolve_model_client",
                        return_value=(model, "scripted negated location model"),
                    ),
                    TestClient(create_app(reference_time=self.reference_time)) as client,
                ):
                    session_id = self._create_session(client)
                    result = self._propose_and_confirm(
                        client,
                        session_id=session_id,
                        messages=(message,),
                    )

                    self.assertEqual("clarifying", result["state"])
                    self.assertIsNone(result["location"])
                    self.assertIsNone(result["consultation_form"])
                    self.assertFalse(result["can_submit_form"])

    def test_explicit_same_county_correction_replaces_old_district_evidence(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.answer("請確認完整服務地點。"),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="corrected-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "信義區",
                        },
                    )
                ),
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="corrected-location-form",
                        name="get_consultation_form",
                        arguments={"service_id": 17},
                    )
                ),
                ModelTurn.answer("地點與表單已完成驗證。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted corrected location model"),
            ),
            patch(
                "home_repair_agent.backend.services.ReadServiceLayer.resolve_location",
                return_value=ResolvedLocation(
                    location_id="TEST-63000020",
                    county_name="臺北市",
                    district_name="信義區",
                    full_name="臺北市信義區",
                ),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            waiting = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市大安區水龍頭漏水",),
            )
            self.assertEqual("clarifying", waiting["state"])

            corrected = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": "改成臺北市信義區"},
            )

            self.assertEqual(200, corrected.status_code, corrected.text)
            body = corrected.json()
            self.assertEqual("awaiting_form", body["state"], body)
            self.assertEqual("臺北市信義區", body["location"]["full_name"])
            self.assertTrue(body["can_submit_form"])

    def test_model_cannot_choose_the_first_of_multiple_user_locations(self) -> None:
        model = ScriptedModelClient(
            [
                ModelTurn.use_tools(
                    ToolCall(
                        call_id="picked-first-location",
                        name="resolve_location",
                        arguments={
                            "county_name": "臺北市",
                            "district_name": "大安區",
                        },
                    )
                ),
                ModelTurn.answer("已選擇第一個地點。"),
            ]
        )
        with (
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(model, "scripted multi-location model"),
            ),
            TestClient(create_app(reference_time=self.reference_time)) as client,
        ):
            session_id = self._create_session(client)
            result = self._propose_and_confirm(
                client,
                session_id=session_id,
                messages=("臺北市大安區或新北市板橋區水龍頭漏水",),
            )

            self.assertEqual("clarifying", result["state"])
            self.assertIsNone(result["location"])
            self.assertIsNone(result["consultation_form"])
            self.assertFalse(result["can_submit_form"])


class CaseRepositoryConfigurationTests(unittest.TestCase):
    def test_memory_repository_remains_the_default(self) -> None:
        with patch.dict("os.environ", {"WEB_CASE_REPOSITORY": "memory"}):
            repository = _resolve_case_repository()
        self.assertIsInstance(repository, DemoCaseWorkflowRepository)

    def test_postgres_repository_requires_and_accepts_database_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "WEB_CASE_REPOSITORY": "postgres",
                "DATABASE_URL": "postgresql://example.invalid/demo",
            },
        ):
            repository = _resolve_case_repository()
        self.assertIsInstance(repository, PostgresCaseWorkflowRepository)

        with (
            patch.dict(
                "os.environ",
                {"WEB_CASE_REPOSITORY": "postgres", "DATABASE_URL": ""},
            ),
            self.assertRaisesRegex(RuntimeError, "DATABASE_URL"),
        ):
            _resolve_case_repository()

    def test_unknown_repository_mode_fails_fast(self) -> None:
        with (
            patch.dict("os.environ", {"WEB_CASE_REPOSITORY": "json"}),
            self.assertRaisesRegex(RuntimeError, "memory, postgres"),
        ):
            _resolve_case_repository()


if __name__ == "__main__":
    unittest.main()
