from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp.shared.memory import create_connected_server_and_client_session

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE, DemoReadRepository
from home_repair_agent.agent.huggingface_model import (
    HuggingFaceConfigurationError,
    HuggingFaceModelClient,
)
from home_repair_agent.agent.loop import AgentRunner
from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.models import (
    AgentTurnResult,
    ConversationSession,
    ToolTraceEntry,
)
from home_repair_agent.agent.ports import ModelClient, ToolClient
from home_repair_agent.backend.case_services import CaseWorkflowService
from home_repair_agent.backend.repair_conversation import RepairBranch
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.server import create_mcp_server
from home_repair_agent.web.demo_case_repository import DemoCaseWorkflowRepository
from home_repair_agent.web.models import BranchConfirmRequest, ProviderView, SessionView
from home_repair_agent.web.service import (
    WEB_CHAT_TOOL_NAMES,
    WebSessionError,
    WebSessionService,
)

EVIDENCE_SCHEMA_VERSION = "hf_web_eval_v1"
PUBLIC_LOCATION_NAMES = frozenset({"臺北市", "台北市", "大安區", "新北市", "板橋區"})
TERMINAL_OR_MATCHED_STATES = frozenset(
    {
        "matched",
        "no_candidates",
        "dispatch_pending",
        "provider_accepted",
        "provider_rejected",
    }
)


@dataclass(frozen=True)
class EvalScenario:
    case_id: str
    title: str
    messages: tuple[str, ...]
    branch_confirmations: tuple[RepairBranch, ...] = ()
    expected_branch: RepairBranch | None = None
    expected_location_name: str | None = None
    expected_state: str | None = None
    required_tools: tuple[str, ...] = ()
    minimum_model_turns: int = 0
    expect_verified_service_and_form: bool = False
    expect_no_verified_location: bool = False
    expect_model_error: bool = False
    use_failure_model: bool = False


HF_WEB_EVAL_SCENARIOS = (
    EvalScenario(
        case_id="complete_requirement",
        title="一次提供完整需求",
        messages=("臺北市大安區水龍頭漏水。",),
        branch_confirmations=(RepairBranch.FAUCET_LEAK,),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_location_name="臺北市大安區",
        expected_state="awaiting_form",
        required_tools=("search_services", "resolve_location", "get_consultation_form"),
        minimum_model_turns=1,
        expect_verified_service_and_form=True,
    ),
    EvalScenario(
        case_id="location_across_turns",
        title="縣市、行政區與問題分多輪提供",
        messages=("新北市", "板橋區", "浴室水龍頭漏水。"),
        branch_confirmations=(RepairBranch.FAUCET_LEAK,),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_location_name="新北市板橋區",
        expected_state="awaiting_form",
        required_tools=("search_services", "resolve_location", "get_consultation_form"),
        minimum_model_turns=1,
        expect_verified_service_and_form=True,
    ),
    EvalScenario(
        case_id="location_correction",
        title="更正已提供的地點",
        messages=("新北市板橋區水龍頭漏水。", "改成臺北市大安區。"),
        branch_confirmations=(RepairBranch.FAUCET_LEAK,),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_location_name="臺北市大安區",
        expected_state="awaiting_form",
        required_tools=("search_services", "resolve_location", "get_consultation_form"),
        minimum_model_turns=2,
        expect_verified_service_and_form=True,
    ),
    EvalScenario(
        case_id="issue_correction",
        title="更正已提供的修繕問題",
        messages=("臺北市大安區馬桶堵塞。", "其實是水龍頭漏水。"),
        branch_confirmations=(RepairBranch.TOILET_ISSUE, RepairBranch.FAUCET_LEAK),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_location_name="臺北市大安區",
        expected_state="awaiting_form",
        required_tools=("search_services", "resolve_location", "get_consultation_form"),
        minimum_model_turns=1,
        expect_verified_service_and_form=True,
    ),
    EvalScenario(
        case_id="ambiguous_issue",
        title="無法判斷來源的水聲",
        messages=("家裡一直有水聲，但不知道哪裡壞掉。",),
        expected_state="collecting_need",
        expect_no_verified_location=True,
    ),
    EvalScenario(
        case_id="ambiguous_location",
        title="多地點且尚未選定",
        messages=("臺北市大安區或新北市板橋區，還沒決定；水龍頭漏水。",),
        branch_confirmations=(RepairBranch.FAUCET_LEAK,),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_state="clarifying",
        required_tools=("search_services",),
        minimum_model_turns=1,
        expect_no_verified_location=True,
    ),
    EvalScenario(
        case_id="provider_failure",
        title="provider timeout／error 不得 fallback",
        messages=("臺北市大安區水龍頭漏水。",),
        branch_confirmations=(RepairBranch.FAUCET_LEAK,),
        expected_branch=RepairBranch.FAUCET_LEAK,
        expected_state="error",
        minimum_model_turns=1,
        expect_model_error=True,
        use_failure_model=True,
    ),
)


class RecordingAgentRunner:
    """Record safe AgentTurnResult objects without logging provider requests."""

    def __init__(self, delegate: AgentRunner) -> None:
        self._delegate = delegate
        self.results: list[AgentTurnResult] = []

    async def run_turn(
        self,
        *,
        session: ConversationSession,
        user_text: str,
    ) -> AgentTurnResult:
        result = await self._delegate.run_turn(session=session, user_text=user_text)
        self.results.append(result)
        return result


class ForcedProviderFailureModel:
    """Deterministic failure injection for the no-fallback contract case."""

    async def complete(self, **_kwargs: object) -> object:
        raise TimeoutError("synthetic forced provider timeout; must stay redacted")


async def run_huggingface_web_eval(
    *,
    model_client: ModelClient,
    model_id: str,
    provider: str,
    scenarios: Sequence[EvalScenario] = HF_WEB_EVAL_SCENARIOS,
    failure_model: ModelClient | None = None,
    timestamp_utc: datetime | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Evaluate live HF text behavior through the Web service and real MCP transport.

    Raw user/assistant messages, provider payloads and credentials are deliberately
    excluded from the returned evidence. The caller must explicitly construct the
    live Hugging Face client; this function never falls back to another model.
    """

    completed_at = timestamp_utc or datetime.now(UTC)
    if completed_at.tzinfo is None or completed_at.utcoffset() is None:
        raise ValueError("timestamp_utc must include a timezone")
    completed_at = completed_at.astimezone(UTC)
    server = create_mcp_server(ReadServiceLayer(DemoReadRepository()))
    case_results: list[dict[str, object]] = []

    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as mcp_session:
        tool_client = MCPToolClient(mcp_session)
        for scenario in scenarios:
            selected_model = (
                failure_model or ForcedProviderFailureModel()
                if scenario.use_failure_model
                else model_client
            )
            case_results.append(
                await _run_scenario(
                    scenario=scenario,
                    model_client=selected_model,
                    tool_client=tool_client,
                    monotonic=monotonic,
                )
            )

    passed = sum(result["status"] == "passed" for result in case_results)
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "timestamp_utc": completed_at.isoformat(timespec="seconds"),
        "timestamp_taipei": completed_at.astimezone(TAIPEI_TIMEZONE).isoformat(timespec="seconds"),
        "execution_mode": "explicit_live_huggingface_opt_in",
        "provider": {
            "key": "huggingface",
            "model_id": model_id,
            "inference_provider": provider,
        },
        "mcp_transport": "process-local MCP ClientSession",
        "data_source": "synthetic",
        "redaction": {
            "messages": "labels and character counts only",
            "tool_results": "status metadata only",
            "provider_payloads_recorded": False,
            "credentials_recorded": False,
        },
        "case_count": len(case_results),
        "passed_case_count": passed,
        "failed_case_count": len(case_results) - passed,
        "cases": case_results,
        "persistent_resources_created": [],
        "status": "passed" if passed == len(case_results) else "failed",
    }


async def _run_scenario(
    *,
    scenario: EvalScenario,
    model_client: ModelClient,
    tool_client: ToolClient,
    monotonic: Callable[[], float],
) -> dict[str, object]:
    runner = RecordingAgentRunner(
        AgentRunner(
            model_client=model_client,
            tool_client=tool_client,
            allowed_tool_names=set(WEB_CHAT_TOOL_NAMES),
        )
    )
    now = lambda: datetime.now(TAIPEI_TIMEZONE)
    case_workflow = CaseWorkflowService(DemoCaseWorkflowRepository(), now=now)
    service = WebSessionService(
        runner=runner,  # type: ignore[arg-type] - intentional recording decorator
        tool_client=tool_client,
        case_workflow=case_workflow,
        provider=ProviderView(
            key="huggingface",
            label="Hugging Face synthetic eval",
            is_external=True,
        ),
        now=now,
    )
    view = await service.create_session()
    confirmations = iter(scenario.branch_confirmations)
    actions: list[dict[str, object]] = []
    web_error_codes: list[str] = []
    next_result_index = 0
    started_at = monotonic()

    for turn_index, message in enumerate(scenario.messages, start=1):
        try:
            view = await service.send_message(view.session_id, message)
            operation_status = "ok"
            error_code = None
        except WebSessionError as error:
            operation_status = "web_error"
            error_code = error.code
            web_error_codes.append(error.code)
            view = await service.get_session(view.session_id)

        new_results = runner.results[next_result_index:]
        next_result_index = len(runner.results)
        actions.append(
            _redacted_action(
                scenario=scenario,
                turn_index=turn_index,
                operation="message",
                operation_status=operation_status,
                error_code=error_code,
                view=view,
                results=new_results,
            )
        )

        if operation_status != "ok" or not _branch_confirmation_is_pending(view):
            continue
        try:
            branch = next(confirmations)
        except StopIteration:
            continue
        available = set(view.repair_routing.alternatives if view.repair_routing else ())
        if branch not in available:
            web_error_codes.append("EVAL_EXPECTED_BRANCH_NOT_PROPOSED")
            actions.append(
                _redacted_action(
                    scenario=scenario,
                    turn_index=turn_index,
                    operation="branch_confirmation",
                    operation_status="eval_error",
                    error_code="EVAL_EXPECTED_BRANCH_NOT_PROPOSED",
                    view=view,
                    results=(),
                )
            )
            continue

        try:
            view = await service.confirm_branch(
                view.session_id,
                BranchConfirmRequest(branch=branch, confirm=True),
            )
            operation_status = "ok"
            error_code = None
        except WebSessionError as error:
            operation_status = "web_error"
            error_code = error.code
            web_error_codes.append(error.code)
            view = await service.get_session(view.session_id)
        new_results = runner.results[next_result_index:]
        next_result_index = len(runner.results)
        actions.append(
            _redacted_action(
                scenario=scenario,
                turn_index=turn_index,
                operation="branch_confirmation",
                operation_status=operation_status,
                error_code=error_code,
                view=view,
                results=new_results,
            )
        )

    duration = max(0.0, monotonic() - started_at)
    traces = [entry for result in runner.results for entry in result.tool_trace]
    checks = _evaluate_checks(
        scenario=scenario,
        view=view,
        results=runner.results,
        traces=traces,
        web_error_codes=web_error_codes,
    )
    early_write = _has_early_matching_or_dispatch(view=view, traces=traces)
    return {
        "case_id": scenario.case_id,
        "title": scenario.title,
        "synthetic_message_count": len(scenario.messages),
        "redacted_messages": [
            {
                "turn": index,
                "role": "user",
                "content": f"[synthetic {scenario.case_id} message {index}]",
                "character_count": len(message),
            }
            for index, message in enumerate(scenario.messages, start=1)
        ],
        "actions": actions,
        "tool_use_order": [entry.name for entry in traces],
        "tool_use_trace": [_redacted_trace(entry) for entry in traces],
        "stop_reasons": [result.stop_reason for result in runner.results],
        "session_state": _session_snapshot(view),
        "early_matching_or_dispatch": early_write,
        "web_error_codes": web_error_codes,
        "duration_seconds": round(duration, 3),
        "checks": checks,
        "status": "passed" if all(checks.values()) else "failed",
    }


def _redacted_action(
    *,
    scenario: EvalScenario,
    turn_index: int,
    operation: str,
    operation_status: str,
    error_code: str | None,
    view: SessionView,
    results: Sequence[AgentTurnResult],
) -> dict[str, object]:
    return {
        "turn": turn_index,
        "operation": operation,
        "input": f"[synthetic {scenario.case_id} turn {turn_index}]",
        "outcome": operation_status,
        "error_code": error_code,
        "assistant_outputs": [
            {
                "content": "[redacted assistant response]",
                "character_count": len(result.reply),
                "stop_reason": result.stop_reason,
            }
            for result in results
        ],
        "session_state": _session_snapshot(view),
    }


def _session_snapshot(view: SessionView) -> dict[str, object]:
    location_id = view.location.location_id if view.location is not None else None
    location_name = view.location.full_name if view.location is not None else None
    return {
        "state": view.state,
        "confirmed_branch": (
            view.repair_routing.confirmed_branch.value
            if view.repair_routing is not None and view.repair_routing.confirmed_branch is not None
            else None
        ),
        "canonical_service_verified": (view.service is not None and view.service.service_id == 17),
        "verified_location_id": (
            location_id
            if isinstance(location_id, str) and location_id.startswith("DEMO-")
            else None
        ),
        "verified_location_name": (
            location_name if location_name in {"臺北市大安區", "新北市板橋區"} else None
        ),
        "consultation_form_verified": (
            view.consultation_form is not None
            and view.consultation_form.form_key == "repair_form_v1"
            and view.consultation_form.service_id == 17
        ),
        "candidate_count": len(view.candidates),
        "has_dispatch": view.dispatch is not None,
    }


def _evaluate_checks(
    *,
    scenario: EvalScenario,
    view: SessionView,
    results: Sequence[AgentTurnResult],
    traces: Sequence[ToolTraceEntry],
    web_error_codes: Sequence[str],
) -> dict[str, bool]:
    snapshot = _session_snapshot(view)
    actual_branch = snapshot["confirmed_branch"]
    actual_location = snapshot["verified_location_name"]
    stop_reasons = [result.stop_reason for result in results]
    checks = {
        "provider_contract_is_huggingface": view.provider.key == "huggingface",
        "model_tools_stay_read_only": all(entry.name in WEB_CHAT_TOOL_NAMES for entry in traces),
        "required_tools_observed": set(scenario.required_tools).issubset(
            entry.name for entry in traces
        ),
        "minimum_model_turns_observed": len(results) >= scenario.minimum_model_turns,
        "no_early_matching_or_dispatch": not _has_early_matching_or_dispatch(
            view=view,
            traces=traces,
        ),
        "no_unexpected_web_error": not web_error_codes,
        "expected_model_failure_contract": (
            stop_reasons == ["model_error"]
            if scenario.expect_model_error
            else all(reason == "completed" for reason in stop_reasons)
        ),
    }
    if scenario.expected_state is not None:
        checks["expected_state"] = snapshot["state"] == scenario.expected_state
    elif not scenario.expect_model_error:
        checks["session_did_not_enter_error"] = snapshot["state"] != "error"
    if scenario.expect_verified_service_and_form:
        checks["canonical_service_verified"] = snapshot["canonical_service_verified"] is True
        checks["consultation_form_verified"] = snapshot["consultation_form_verified"] is True
    if scenario.expected_branch is not None:
        checks["expected_branch"] = actual_branch == scenario.expected_branch.value
    if scenario.expected_location_name is not None:
        checks["expected_location"] = actual_location == scenario.expected_location_name
    if scenario.expect_no_verified_location:
        checks["location_not_guessed"] = actual_location is None
    return checks


def _has_early_matching_or_dispatch(
    *,
    view: SessionView,
    traces: Sequence[ToolTraceEntry],
) -> bool:
    return (
        any(entry.name == "match_service_providers" for entry in traces)
        or bool(view.candidates)
        or view.dispatch is not None
        or view.state in TERMINAL_OR_MATCHED_STATES
    )


def _branch_confirmation_is_pending(view: SessionView) -> bool:
    routing = view.repair_routing
    return bool(
        routing is not None
        and routing.alternatives
        and (routing.confirmed_branch is None or routing.replacement_pending)
    )


def _redacted_trace(entry: ToolTraceEntry) -> dict[str, object]:
    data = entry.result.get("data")
    result_summary: dict[str, object] = {
        "ok": entry.result.get("ok") is True,
        "mcp_is_error": entry.mcp_is_error,
    }
    if isinstance(data, dict):
        if isinstance(data.get("count"), int):
            result_summary["count"] = data["count"]
        if data.get("data_source") == "synthetic":
            result_summary["data_source"] = "synthetic"
    error = entry.result.get("error")
    if isinstance(error, dict) and isinstance(error.get("code"), str):
        result_summary["error_code"] = error["code"]
    return {
        "name": entry.name,
        "arguments": _redacted_arguments(entry.arguments),
        "result": result_summary,
    }


def _redacted_arguments(arguments: dict[str, object]) -> dict[str, object]:
    redacted: dict[str, object] = {}
    for key, value in arguments.items():
        if key == "query":
            redacted[key] = "[synthetic repair issue]"
        elif key in {"county_name", "district_name"}:
            redacted[key] = value if value in PUBLIC_LOCATION_NAMES else "[redacted]"
        elif key == "service_id":
            redacted[key] = value if value == 17 else "[redacted]"
        elif key == "location_id":
            redacted[key] = (
                value if isinstance(value, str) and value.startswith("DEMO-") else "[redacted]"
            )
        elif key == "limit" and isinstance(value, int) and not isinstance(value, bool):
            redacted[key] = value
        else:
            redacted[key] = "[redacted]"
    return redacted


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run seven synthetic Hugging Face Web conversation evaluations and print "
            "redacted JSON evidence. No live request is made without --live."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="explicitly allow hosted Hugging Face text-model requests",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print compact JSON instead of indented JSON",
    )
    return parser


async def _run_live() -> dict[str, object]:
    client = HuggingFaceModelClient.from_environment()
    return await run_huggingface_web_eval(
        model_client=client,
        model_id=client.model_id,
        provider=client.provider,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("--live is required; the eval never contacts Hugging Face implicitly")
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    try:
        evidence = asyncio.run(_run_live())
    except HuggingFaceConfigurationError as error:
        parser.error(str(error))
    print(
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
        )
    )
    if evidence["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
