from __future__ import annotations

import json
import os
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from home_repair_agent.agent.mock_model import RuleBasedRepairMockModel, ScriptedModelClient
from home_repair_agent.agent.models import (
    ConversationMessage,
    ModelTurn,
    ToolCall,
    ToolDefinition,
    ToolTraceEntry,
)
from home_repair_agent.backend.repair_conversation import RepairBranch
from home_repair_agent.web.app import create_app
from scripts.huggingface_web_eval import (
    EVIDENCE_SCHEMA_VERSION,
    HF_WEB_EVAL_SCENARIOS,
    EvalScenario,
    _redacted_arguments,
    _redacted_trace,
    main,
    run_huggingface_web_eval,
)


class NeverCalledModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        del messages, tools
        self.calls += 1
        raise AssertionError("this model must not be used")


class SensitiveFailingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        del messages, tools
        self.calls += 1
        raise TimeoutError("provider payload SECRET_SHOULD_NOT_APPEAR")


def _successful_full_requirement_model() -> ScriptedModelClient:
    return ScriptedModelClient(
        [
            ModelTurn.use_tools(
                ToolCall(
                    call_id="service-1",
                    name="search_services",
                    arguments={"query": "水龍頭漏水", "limit": 5},
                ),
                ToolCall(
                    call_id="location-1",
                    name="resolve_location",
                    arguments={"county_name": "臺北市", "district_name": "大安區"},
                ),
            ),
            ModelTurn.use_tools(
                ToolCall(
                    call_id="form-1",
                    name="get_consultation_form",
                    arguments={"service_id": 17},
                )
            ),
            ModelTurn.answer("請填寫已驗證的水電修繕諮詢表單。"),
        ]
    )


class HuggingFaceWebEvalContractTests(unittest.TestCase):
    def test_catalog_contains_the_seven_required_synthetic_cases(self) -> None:
        self.assertEqual(
            [
                "complete_requirement",
                "location_across_turns",
                "location_correction",
                "issue_correction",
                "ambiguous_issue",
                "ambiguous_location",
                "provider_failure",
            ],
            [scenario.case_id for scenario in HF_WEB_EVAL_SCENARIOS],
        )
        self.assertTrue(all(scenario.messages for scenario in HF_WEB_EVAL_SCENARIOS))

    def test_cli_requires_explicit_live_opt_in_before_calling_runner(self) -> None:
        with (
            patch("scripts.huggingface_web_eval._run_live", new_callable=AsyncMock) as run_live,
            self.assertRaises(SystemExit) as raised,
        ):
            main([])

        self.assertEqual(2, raised.exception.code)
        run_live.assert_not_awaited()

    def test_health_and_session_mark_hf_contract_mode_as_external(self) -> None:
        with (
            tempfile.TemporaryDirectory() as media_root,
            patch.dict(
                os.environ,
                {"WEB_MODEL_PROVIDER": "huggingface", "MEDIA_ROOT": media_root},
                clear=False,
            ),
            patch(
                "home_repair_agent.web.app._resolve_model_client",
                return_value=(RuleBasedRepairMockModel(), "Hugging Face contract double"),
            ),
            patch(
                "home_repair_agent.web.app.HuggingFaceVisionClient.from_environment",
                return_value=object(),
            ),
            TestClient(create_app()) as client,
        ):
            health = client.get("/api/health")
            session = client.post("/api/sessions")

        self.assertEqual("huggingface", health.json()["model_provider"])
        self.assertEqual(
            {
                "key": "huggingface",
                "label": "Hugging Face contract double",
                "is_external": True,
            },
            session.json()["provider"],
        )

    def test_tool_evidence_redacts_queries_unknown_values_and_provider_payload(self) -> None:
        trace = ToolTraceEntry(
            call_id="call-1",
            name="search_services",
            arguments={
                "query": "raw synthetic prompt that must not be copied",
                "limit": 3,
                "unknown": "SECRET_ARGUMENT",
            },
            mcp_is_error=False,
            result={
                "ok": True,
                "data": {
                    "count": 1,
                    "provider_payload": "SECRET_PROVIDER_PAYLOAD",
                },
            },
        )

        evidence = _redacted_trace(trace)
        serialized = json.dumps(evidence)

        self.assertEqual("[synthetic repair issue]", evidence["arguments"]["query"])
        self.assertEqual("[redacted]", evidence["arguments"]["unknown"])
        self.assertEqual({"ok": True, "mcp_is_error": False, "count": 1}, evidence["result"])
        self.assertNotIn("raw synthetic prompt", serialized)
        self.assertNotIn("SECRET_ARGUMENT", serialized)
        self.assertNotIn("SECRET_PROVIDER_PAYLOAD", serialized)

    def test_only_allowlisted_public_location_and_canonical_ids_remain_visible(self) -> None:
        self.assertEqual(
            {
                "county_name": "臺北市",
                "district_name": "[redacted]",
                "service_id": 17,
                "location_id": "DEMO-63000030",
                "other_service_id": "[redacted]",
            },
            _redacted_arguments(
                {
                    "county_name": "臺北市",
                    "district_name": "私密地址",
                    "service_id": 17,
                    "location_id": "DEMO-63000030",
                    "other_service_id": 999,
                }
            ),
        )


class HuggingFaceWebEvalHarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_fake_model_uses_real_web_service_and_mcp_contract(self) -> None:
        scenario = EvalScenario(
            case_id="contract_success",
            title="offline contract success",
            messages=("臺北市大安區水龍頭漏水。",),
            branch_confirmations=(RepairBranch.FAUCET_LEAK,),
            expected_branch=RepairBranch.FAUCET_LEAK,
            expected_location_name="臺北市大安區",
            expected_state="awaiting_form",
            required_tools=(
                "search_services",
                "resolve_location",
                "get_consultation_form",
            ),
            minimum_model_turns=1,
            expect_verified_service_and_form=True,
        )

        evidence = await run_huggingface_web_eval(
            model_client=_successful_full_requirement_model(),
            model_id="fake-hf-contract-model",
            provider="fake-provider",
            scenarios=(scenario,),
            timestamp_utc=datetime(2026, 8, 1, 4, tzinfo=UTC),
        )

        self.assertEqual(EVIDENCE_SCHEMA_VERSION, evidence["schema_version"])
        self.assertEqual("passed", evidence["status"])
        self.assertEqual(1, evidence["passed_case_count"])
        result = evidence["cases"][0]
        self.assertEqual("passed", result["status"])
        self.assertEqual(
            ["search_services", "resolve_location", "get_consultation_form"],
            result["tool_use_order"],
        )
        self.assertEqual("awaiting_form", result["session_state"]["state"])
        self.assertEqual("臺北市大安區", result["session_state"]["verified_location_name"])
        self.assertFalse(result["early_matching_or_dispatch"])
        serialized = json.dumps(evidence, ensure_ascii=False)
        self.assertNotIn("臺北市大安區水龍頭漏水。", serialized)
        self.assertNotIn("請填寫已驗證", serialized)

    async def test_full_catalog_has_no_false_positive_terminal_states(self) -> None:
        evidence = await run_huggingface_web_eval(
            model_client=RuleBasedRepairMockModel(),
            model_id="offline-rule-based-contract-model",
            provider="offline-contract-provider",
            timestamp_utc=datetime(2026, 8, 1, 4, tzinfo=UTC),
        )

        self.assertEqual("passed", evidence["status"])
        self.assertEqual(7, evidence["passed_case_count"])
        self.assertEqual(0, evidence["failed_case_count"])
        by_case = {item["case_id"]: item for item in evidence["cases"]}
        self.assertEqual(
            "collecting_need",
            by_case["ambiguous_issue"]["session_state"]["state"],
        )
        self.assertEqual(
            "awaiting_form",
            by_case["location_across_turns"]["session_state"]["state"],
        )
        self.assertEqual(
            "臺北市大安區",
            by_case["location_correction"]["session_state"]["verified_location_name"],
        )

    async def test_forced_provider_timeout_is_masked_and_never_falls_back(self) -> None:
        scenario = EvalScenario(
            case_id="provider_failure_contract",
            title="offline provider failure contract",
            messages=("臺北市大安區水龍頭漏水。",),
            branch_confirmations=(RepairBranch.FAUCET_LEAK,),
            expected_branch=RepairBranch.FAUCET_LEAK,
            expected_state="error",
            minimum_model_turns=1,
            expect_model_error=True,
            use_failure_model=True,
        )
        unused_model = NeverCalledModel()
        failure_model = SensitiveFailingModel()

        evidence = await run_huggingface_web_eval(
            model_client=unused_model,
            model_id="fake-hf-contract-model",
            provider="fake-provider",
            failure_model=failure_model,
            scenarios=(scenario,),
            timestamp_utc=datetime(2026, 8, 1, 4, tzinfo=UTC),
        )

        self.assertEqual("passed", evidence["status"])
        self.assertEqual(0, unused_model.calls)
        self.assertEqual(1, failure_model.calls)
        result: dict[str, Any] = evidence["cases"][0]
        self.assertEqual(["model_error"], result["stop_reasons"])
        self.assertEqual("error", result["session_state"]["state"])
        self.assertFalse(result["early_matching_or_dispatch"])
        self.assertNotIn("SECRET_SHOULD_NOT_APPEAR", json.dumps(evidence))


if __name__ == "__main__":
    unittest.main()
