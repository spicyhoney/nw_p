from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from home_repair_agent.agent.bedrock_model import BedrockModelClient
from scripts.bedrock_mcp_e2e import (
    E2E_SYSTEM_PROMPT,
    run_bedrock_mcp_e2e,
)

LOGGER = logging.getLogger("home_repair_agent.agentcore_poc")
SYNTHETIC_SCENARIO = "synthetic_repair_v1"
app = BedrockAgentCoreApp()


async def _run_synthetic_e2e() -> dict[str, object]:
    client = BedrockModelClient.from_environment(system_prompt=E2E_SYSTEM_PROMPT)
    result = await run_bedrock_mcp_e2e(
        model_client=client,
        region=client.region,
        model_id=client.model_id,
    )
    result.pop("aws_resources_created", None)
    result["execution_environment"] = "Amazon Bedrock AgentCore Runtime"
    result["aws_resources_created_by_invocation"] = []
    return result


@app.entrypoint
async def invoke(payload: object, context: object | None = None) -> dict[str, object]:
    """Run one fixed, no-PII scenario; arbitrary prompts are intentionally rejected."""

    del context
    if not isinstance(payload, Mapping) or dict(payload) != {"scenario": SYNTHETIC_SCENARIO}:
        LOGGER.warning("agentcore_poc_rejected_non_synthetic_input")
        return {"status": "rejected", "error": "synthetic_scenario_required"}

    LOGGER.info("agentcore_poc_started")
    try:
        result = await _run_synthetic_e2e()
    except Exception:  # noqa: BLE001 - the runtime trust boundary must return a fixed error
        LOGGER.error("agentcore_poc_failed")
        return {"status": "failed", "error": "runtime_execution_failed"}

    LOGGER.info("agentcore_poc_passed")
    return result


if __name__ == "__main__":
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    app.run()
