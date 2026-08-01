from __future__ import annotations

import asyncio
import logging

import agentcore_runtime_entrypoint as runtime


def test_runtime_rejects_arbitrary_payloads() -> None:
    payloads: tuple[object, ...] = (
        None,
        {},
        {"prompt": "arbitrary input"},
        {"scenario": runtime.SYNTHETIC_SCENARIO, "prompt": "extra"},
    )

    for payload in payloads:
        assert asyncio.run(runtime.invoke(payload)) == {
            "status": "rejected",
            "error": "synthetic_scenario_required",
        }


def test_runtime_returns_redacted_synthetic_evidence(monkeypatch) -> None:
    expected = {
        "status": "passed",
        "redacted_input": "[synthetic]",
        "execution_environment": "Amazon Bedrock AgentCore Runtime",
    }

    async def fake_run() -> dict[str, object]:
        return expected

    monkeypatch.setattr(runtime, "_run_synthetic_e2e", fake_run)

    assert asyncio.run(runtime.invoke({"scenario": runtime.SYNTHETIC_SCENARIO})) is expected


def test_runtime_failure_is_generic(monkeypatch, caplog) -> None:
    async def fail() -> dict[str, object]:
        raise RuntimeError("provider payload must stay hidden")

    monkeypatch.setattr(runtime, "_run_synthetic_e2e", fail)
    with caplog.at_level(logging.ERROR):
        result = asyncio.run(runtime.invoke({"scenario": runtime.SYNTHETIC_SCENARIO}))

    assert result == {"status": "failed", "error": "runtime_execution_failed"}
    assert "provider payload must stay hidden" not in caplog.text
    assert "agentcore_poc_failed" in caplog.text
