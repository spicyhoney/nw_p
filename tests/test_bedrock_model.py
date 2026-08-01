from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from home_repair_agent.agent.bedrock_model import (
    DEFAULT_BEDROCK_MAX_TOKENS,
    BedrockConfigurationError,
    BedrockModelClient,
    BedrockRequestError,
    BedrockResponseError,
    _create_bedrock_runtime_client,
)
from home_repair_agent.agent.models import (
    AssistantMessage,
    AssistantToolCalls,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)


class RecordingBedrockClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.response


class FailingBedrockClient:
    def converse(self, **kwargs: Any) -> object:
        del kwargs
        raise RuntimeError(
            "AccessDenied payload contains AKIA_TEST_ONLY and synthetic private details"
        )


def _answer_response(text: str = "請問您位於哪個行政區？") -> dict[str, object]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
        "stopReason": "end_turn",
    }


def _tool_use_response(*, stop_reason: str = "tool_use") -> dict[str, object]:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "bedrock-call-1",
                            "name": "resolve_location",
                            "input": {
                                "county_name": "台北市",
                                "district_name": "大安區",
                            },
                        }
                    }
                ],
            }
        },
        "stopReason": stop_reason,
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
        },
        annotations={"readOnlyHint": True},
    )


class BedrockConfigurationTests(unittest.TestCase):
    def test_from_environment_requires_explicit_region(self) -> None:
        with self.assertRaisesRegex(BedrockConfigurationError, "BEDROCK_REGION is required"):
            BedrockModelClient.from_environment(
                client=RecordingBedrockClient(_answer_response()),
                environ={"BEDROCK_MODEL_ID": "test-model"},
            )

    def test_from_environment_requires_explicit_model(self) -> None:
        with self.assertRaisesRegex(BedrockConfigurationError, "BEDROCK_MODEL_ID is required"):
            BedrockModelClient.from_environment(
                client=RecordingBedrockClient(_answer_response()),
                environ={"BEDROCK_REGION": "us-west-2"},
            )

    def test_from_environment_rejects_region_outside_competition(self) -> None:
        with self.assertRaisesRegex(BedrockConfigurationError, "us-east-1 or us-west-2"):
            BedrockModelClient.from_environment(
                client=RecordingBedrockClient(_answer_response()),
                environ={
                    "BEDROCK_REGION": "ap-northeast-1",
                    "BEDROCK_MODEL_ID": "test-model",
                },
            )

    def test_environment_values_configure_injected_fake_client(self) -> None:
        model = BedrockModelClient.from_environment(
            client=RecordingBedrockClient(_answer_response()),
            environ={
                "BEDROCK_REGION": "us-west-2",
                "BEDROCK_MODEL_ID": "test-model",
                "BEDROCK_MAX_TOKENS": "123",
                "BEDROCK_TIMEOUT_SECONDS": "45",
                "AWS_SECRET_ACCESS_KEY": "test-only-secret",
            },
        )

        self.assertEqual("test-model", model.model_id)
        self.assertEqual("us-west-2", model.region)
        self.assertEqual(45, model.timeout_seconds)
        self.assertNotIn("test-only-secret", repr(model))

    def test_default_max_tokens_is_applied(self) -> None:
        client = RecordingBedrockClient(_answer_response())
        model = BedrockModelClient.from_environment(
            client=client,
            environ={
                "BEDROCK_REGION": "us-east-1",
                "BEDROCK_MODEL_ID": "test-model",
            },
        )

        request = model._build_request(
            messages=[UserMessage(text="水龍頭漏水")],
            tools=[],
        )

        self.assertEqual(DEFAULT_BEDROCK_MAX_TOKENS, request["inferenceConfig"]["maxTokens"])

    def test_missing_sdk_credentials_fail_before_client_creation(self) -> None:
        class FakeSession:
            def get_credentials(self) -> None:
                return None

            def client(self, *args: object, **kwargs: object) -> object:
                raise AssertionError("client must not be created without credentials")

        with (
            patch("boto3.Session", return_value=FakeSession()),
            self.assertRaisesRegex(
                BedrockConfigurationError,
                "AWS credentials are required",
            ),
        ):
            _create_bedrock_runtime_client(
                region="us-west-2",
                timeout_seconds=10,
            )

    def test_invalid_limits_fail_before_request(self) -> None:
        with self.assertRaisesRegex(
            BedrockConfigurationError,
            "BEDROCK_MAX_TOKENS must be a positive integer",
        ):
            BedrockModelClient.from_environment(
                client=RecordingBedrockClient(_answer_response()),
                environ={
                    "BEDROCK_REGION": "us-west-2",
                    "BEDROCK_MODEL_ID": "test-model",
                    "BEDROCK_MAX_TOKENS": "0",
                },
            )


class BedrockModelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_response_and_request_translation(self) -> None:
        client = RecordingBedrockClient(_answer_response())
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )

        result = await model.complete(
            messages=[UserMessage(text="水龍頭漏水")],
            tools=[_tool_definition()],
        )

        self.assertEqual("請問您位於哪個行政區？", result.reply)
        request = client.requests[0]
        self.assertEqual("test-model", request["modelId"])
        self.assertEqual("水龍頭漏水", request["messages"][0]["content"][0]["text"])
        self.assertIn("不得自行把", request["system"][0]["text"])
        tool_spec = request["toolConfig"]["tools"][0]["toolSpec"]
        self.assertEqual("resolve_location", tool_spec["name"])
        self.assertEqual(
            _tool_definition().input_schema,
            tool_spec["inputSchema"]["json"],
        )

    async def test_provider_neutral_history_is_translated(self) -> None:
        client = RecordingBedrockClient(_answer_response("收到"))
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )

        await model.complete(
            messages=[
                UserMessage(text="台北市大安區"),
                AssistantMessage(text="我先確認行政區。"),
                AssistantToolCalls(
                    calls=[
                        ToolCall(
                            call_id="bedrock-call-1",
                            name="resolve_location",
                            arguments={
                                "county_name": "台北市",
                                "district_name": "大安區",
                            },
                        )
                    ]
                ),
                ToolResultMessage(
                    call_id="bedrock-call-1",
                    name="resolve_location",
                    mcp_is_error=False,
                    payload={
                        "ok": True,
                        "data": {"location_id": "DEMO-63000030"},
                        "error": None,
                    },
                ),
            ],
            tools=[_tool_definition()],
        )

        messages = client.requests[0]["messages"]
        self.assertEqual("assistant", messages[1]["role"])
        tool_use = messages[2]["content"][0]["toolUse"]
        self.assertEqual("bedrock-call-1", tool_use["toolUseId"])
        self.assertEqual("resolve_location", tool_use["name"])
        tool_result = messages[3]["content"][0]["toolResult"]
        self.assertEqual("user", messages[3]["role"])
        self.assertEqual("success", tool_result["status"])
        self.assertEqual(
            "DEMO-63000030",
            tool_result["content"][0]["json"]["data"]["location_id"],
        )

    async def test_consecutive_tool_results_share_one_bedrock_user_message(self) -> None:
        client = RecordingBedrockClient(_answer_response("收到"))
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )
        calls = [
            ToolCall(
                call_id="bedrock-call-1",
                name="resolve_location",
                arguments={"county_name": "台北市", "district_name": "大安區"},
            ),
            ToolCall(
                call_id="bedrock-call-2",
                name="resolve_location",
                arguments={"county_name": "新北市", "district_name": "板橋區"},
            ),
        ]

        await model.complete(
            messages=[
                UserMessage(text="比較兩個 synthetic 地點"),
                AssistantToolCalls(calls=calls),
                ToolResultMessage(
                    call_id="bedrock-call-1",
                    name="resolve_location",
                    mcp_is_error=False,
                    payload={"ok": True, "data": {"location_id": "SYNTHETIC-1"}},
                ),
                ToolResultMessage(
                    call_id="bedrock-call-2",
                    name="resolve_location",
                    mcp_is_error=True,
                    payload={"ok": False, "error": {"code": "SYNTHETIC_ERROR"}},
                ),
            ],
            tools=[_tool_definition()],
        )

        messages = client.requests[0]["messages"]
        self.assertEqual(3, len(messages))
        self.assertEqual("user", messages[2]["role"])
        self.assertEqual(2, len(messages[2]["content"]))
        self.assertEqual("success", messages[2]["content"][0]["toolResult"]["status"])
        self.assertEqual("error", messages[2]["content"][1]["toolResult"]["status"])

    async def test_tool_use_response_is_converted_to_model_turn(self) -> None:
        client = RecordingBedrockClient(_tool_use_response())
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )

        result = await model.complete(
            messages=[UserMessage(text="台北市大安區")],
            tools=[_tool_definition()],
        )

        self.assertIsNone(result.reply)
        self.assertEqual(
            [
                ToolCall(
                    call_id="bedrock-call-1",
                    name="resolve_location",
                    arguments={
                        "county_name": "台北市",
                        "district_name": "大安區",
                    },
                )
            ],
            result.tool_calls,
        )

    async def test_tool_arguments_must_be_json_object(self) -> None:
        client = RecordingBedrockClient(
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "bedrock-call-1",
                                    "name": "resolve_location",
                                    "input": ["台北市", "大安區"],
                                }
                            }
                        ]
                    }
                },
                "stopReason": "tool_use",
            }
        )
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(BedrockResponseError, "JSON object"):
            await model.complete(
                messages=[UserMessage(text="台北市大安區")],
                tools=[_tool_definition()],
            )

    async def test_non_json_nested_tool_arguments_are_rejected(self) -> None:
        client = RecordingBedrockClient(
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "bedrock-call-1",
                                    "name": "resolve_location",
                                    "input": {"unsafe": b"not-json"},
                                }
                            }
                        ]
                    }
                },
                "stopReason": "tool_use",
            }
        )
        model = BedrockModelClient(
            client=client,
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(BedrockResponseError, "JSON object"):
            await model.complete(
                messages=[UserMessage(text="台北市大安區")],
                tools=[_tool_definition()],
            )

    async def test_request_error_is_replaced_with_safe_adapter_error(self) -> None:
        model = BedrockModelClient(
            client=FailingBedrockClient(),
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(
            BedrockRequestError,
            "^Amazon Bedrock Converse request failed",
        ) as raised:
            await model.complete(
                messages=[UserMessage(text="synthetic 水龍頭漏水")],
                tools=[_tool_definition()],
            )

        rendered = str(raised.exception)
        self.assertNotIn("AKIA_TEST_ONLY", rendered)
        self.assertNotIn("synthetic private details", rendered)
        self.assertTrue(raised.exception.__suppress_context__)

    async def test_incomplete_or_filtered_text_stop_reasons_are_rejected(self) -> None:
        for stop_reason in (
            "max_tokens",
            "model_context_window_exceeded",
            "content_filtered",
        ):
            with self.subTest(stop_reason=stop_reason):
                response = _answer_response("這是不應被接受的 partial answer")
                response["stopReason"] = stop_reason
                model = BedrockModelClient(
                    client=RecordingBedrockClient(response),
                    model_id="test-model",
                    region="us-west-2",
                )

                with self.assertRaisesRegex(BedrockResponseError, "stop reason"):
                    await model.complete(
                        messages=[UserMessage(text="synthetic 水龍頭漏水")],
                        tools=[],
                    )

    async def test_malformed_tool_use_stop_reason_is_not_executable(self) -> None:
        model = BedrockModelClient(
            client=RecordingBedrockClient(_tool_use_response(stop_reason="malformed_tool_use")),
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(BedrockResponseError, "stop reason"):
            await model.complete(
                messages=[UserMessage(text="台北市大安區")],
                tools=[_tool_definition()],
            )

    async def test_tool_use_stop_reason_requires_a_tool_call(self) -> None:
        response = _answer_response("不應以 tool_use 接受純文字")
        response["stopReason"] = "tool_use"
        model = BedrockModelClient(
            client=RecordingBedrockClient(response),
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(BedrockResponseError, "missing a valid tool call"):
            await model.complete(
                messages=[UserMessage(text="synthetic 水龍頭漏水")],
                tools=[_tool_definition()],
            )

    async def test_end_turn_stop_reason_rejects_tool_call_content(self) -> None:
        model = BedrockModelClient(
            client=RecordingBedrockClient(_tool_use_response(stop_reason="end_turn")),
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaisesRegex(BedrockResponseError, "must not contain a tool call"):
            await model.complete(
                messages=[UserMessage(text="台北市大安區")],
                tools=[_tool_definition()],
            )

    async def test_empty_response_is_rejected_without_payload_echo(self) -> None:
        model = BedrockModelClient(
            client=RecordingBedrockClient({"provider_payload": "private"}),
            model_id="test-model",
            region="us-west-2",
        )

        with self.assertRaises(BedrockResponseError) as raised:
            await model.complete(
                messages=[UserMessage(text="synthetic 水龍頭漏水")],
                tools=[],
            )

        self.assertNotIn("provider_payload", str(raised.exception))
        self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
