from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from home_repair_agent.agent.bedrock_model import BedrockModelClient
from home_repair_agent.agent.models import (
    AssistantToolCalls,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)

SYNTHETIC_INPUT = (
    "這是無個資的 synthetic 測試。請呼叫 resolve_location 工具，"
    "確認台北市大安區；不要自行產生 location_id。"
)
EXPECTED_LOCATION_ARGUMENTS = {
    "county_name": "台北市",
    "district_name": "大安區",
}


def _tool_definition() -> ToolDefinition:
    return ToolDefinition(
        name="resolve_location",
        title="解析行政區",
        description="把縣市與行政區解析成系統 location_id。",
        input_schema={
            "type": "object",
            "properties": {
                "county_name": {"type": "string"},
                "district_name": {"type": "string"},
            },
            "required": ["county_name", "district_name"],
            "additionalProperties": False,
        },
        annotations={"readOnlyHint": True},
    )


def _validate_location_tool_calls(tool_calls: Sequence[ToolCall]) -> ToolCall:
    if len(tool_calls) != 1:
        raise RuntimeError("Bedrock live smoke must return exactly one resolve_location tool use.")

    tool_call = tool_calls[0]
    if tool_call.name != "resolve_location":
        raise RuntimeError(
            "Bedrock live smoke returned an unexpected tool instead of resolve_location."
        )
    if tool_call.arguments != EXPECTED_LOCATION_ARGUMENTS:
        raise RuntimeError("Bedrock live smoke returned unexpected resolve_location arguments.")
    return tool_call


async def _run() -> dict[str, object]:
    client = BedrockModelClient.from_environment()
    tool = _tool_definition()
    messages = [UserMessage(text=SYNTHETIC_INPUT)]

    first_turn = await client.complete(messages=messages, tools=[tool])
    _validate_location_tool_calls(first_turn.tool_calls)

    messages.append(AssistantToolCalls(calls=first_turn.tool_calls))
    for call in first_turn.tool_calls:
        messages.append(
            ToolResultMessage(
                call_id=call.call_id,
                name=call.name,
                mcp_is_error=False,
                payload={
                    "ok": True,
                    "data": {
                        "location_id": "SYNTHETIC-TPE-DAAN",
                        "county_name": "台北市",
                        "district_name": "大安區",
                        "source_type": "synthetic",
                    },
                    "error": None,
                },
            )
        )

    # Competition rule: keep Bedrock traffic at or below one request per second.
    await asyncio.sleep(1.1)
    final_turn = await client.complete(messages=messages, tools=[tool])
    if final_turn.reply is None:
        raise RuntimeError("Bedrock live smoke did not return a final text answer.")

    return {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "region": client.region,
        "model_id": client.model_id,
        "redacted_input": "[synthetic repair request with public location names]",
        "redacted_output": "[synthetic confirmation reply; no provider payload retained]",
        "output_character_count": len(final_turn.reply),
        "tool_use_trace": [
            {
                "name": call.name,
                "arguments": call.arguments,
            }
            for call in first_turn.tool_calls
        ],
        "status": "passed",
    }


def main() -> None:
    print(json.dumps(asyncio.run(_run()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
