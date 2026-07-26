from __future__ import annotations

import unittest
from typing import Any

from home_repair_agent.agent.huggingface_model import (
    DEFAULT_HF_MODEL_ID,
    HuggingFaceConfigurationError,
    HuggingFaceModelClient,
    HuggingFaceRequestError,
    HuggingFaceResponseError,
)
from home_repair_agent.agent.models import (
    AssistantToolCalls,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
)


class RecordingChatClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def chat_completion(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.response


class FailingChatClient:
    def chat_completion(self, **kwargs: Any) -> object:
        del kwargs
        raise RuntimeError("provider response with sensitive details")


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


class HuggingFaceConfigurationTests(unittest.TestCase):
    def test_from_environment_requires_token_instead_of_falling_back(self) -> None:
        with self.assertRaisesRegex(
            HuggingFaceConfigurationError,
            "HF_TOKEN is required",
        ):
            HuggingFaceModelClient.from_environment(environ={})

    def test_environment_values_configure_injected_client(self) -> None:
        chat_client = RecordingChatClient(
            {"choices": [{"message": {"content": "完成", "tool_calls": None}}]}
        )

        model = HuggingFaceModelClient.from_environment(
            client=chat_client,
            environ={
                "HF_TOKEN": "test-only-token",
                "HF_MODEL_ID": "org/model",
                "HF_PROVIDER": "test-provider",
                "HF_MAX_TOKENS": "123",
            },
        )

        self.assertEqual("org/model", model.model_id)
        self.assertEqual("test-provider", model.provider)
        self.assertNotIn("test-only-token", repr(model))

    def test_default_model_is_a_configurable_open_model(self) -> None:
        chat_client = RecordingChatClient(
            {"choices": [{"message": {"content": "完成", "tool_calls": None}}]}
        )

        model = HuggingFaceModelClient.from_environment(
            client=chat_client,
            environ={"HF_TOKEN": "test-only-token"},
        )

        self.assertEqual(DEFAULT_HF_MODEL_ID, model.model_id)

    def test_invalid_max_tokens_is_rejected_before_request(self) -> None:
        with self.assertRaisesRegex(
            HuggingFaceConfigurationError,
            "HF_MAX_TOKENS must be a positive integer",
        ):
            HuggingFaceModelClient.from_environment(
                client=RecordingChatClient({}),
                environ={
                    "HF_TOKEN": "test-only-token",
                    "HF_MAX_TOKENS": "many",
                },
            )

    def test_empty_model_id_is_a_configuration_error(self) -> None:
        with self.assertRaisesRegex(
            HuggingFaceConfigurationError,
            "HF_MODEL_ID must not be empty",
        ):
            HuggingFaceModelClient.from_environment(
                client=RecordingChatClient({}),
                environ={
                    "HF_TOKEN": "test-only-token",
                    "HF_MODEL_ID": " ",
                },
            )


class HuggingFaceModelClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_response_and_request_translation(self) -> None:
        chat_client = RecordingChatClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": "請問您位於哪個行政區？",
                            "tool_calls": None,
                        }
                    }
                ]
            }
        )
        model = HuggingFaceModelClient(
            client=chat_client,
            model_id="org/model",
            provider="test-provider",
        )

        result = await model.complete(
            messages=[UserMessage(text="水龍頭漏水")],
            tools=[_tool_definition()],
        )

        self.assertEqual("請問您位於哪個行政區？", result.reply)
        request = chat_client.requests[0]
        self.assertEqual("org/model", request["model"])
        self.assertEqual("auto", request["tool_choice"])
        self.assertEqual("system", request["messages"][0]["role"])
        self.assertEqual(
            {"role": "user", "content": "水龍頭漏水"},
            request["messages"][1],
        )
        self.assertEqual(
            "resolve_location",
            request["tools"][0]["function"]["name"],
        )
        self.assertEqual(
            _tool_definition().input_schema,
            request["tools"][0]["function"]["parameters"],
        )

    async def test_tool_call_response_is_converted_to_model_turn(self) -> None:
        chat_client = RecordingChatClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "hf-call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "resolve_location",
                                        "arguments": (
                                            '{"county_name":"台北市","district_name":"大安區"}'
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        model = HuggingFaceModelClient(client=chat_client)

        result = await model.complete(
            messages=[UserMessage(text="台北市大安區")],
            tools=[_tool_definition()],
        )

        self.assertIsNone(result.reply)
        self.assertEqual(
            [
                ToolCall(
                    call_id="hf-call-1",
                    name="resolve_location",
                    arguments={
                        "county_name": "台北市",
                        "district_name": "大安區",
                    },
                )
            ],
            result.tool_calls,
        )

    async def test_prior_tool_call_and_result_are_preserved_for_next_step(self) -> None:
        chat_client = RecordingChatClient(
            {"choices": [{"message": {"content": "收到", "tool_calls": None}}]}
        )
        model = HuggingFaceModelClient(client=chat_client)

        await model.complete(
            messages=[
                UserMessage(text="台北市大安區"),
                AssistantToolCalls(
                    calls=[
                        ToolCall(
                            call_id="hf-call-1",
                            name="resolve_location",
                            arguments={
                                "county_name": "台北市",
                                "district_name": "大安區",
                            },
                        )
                    ]
                ),
                ToolResultMessage(
                    call_id="hf-call-1",
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

        messages = chat_client.requests[0]["messages"]
        self.assertEqual("assistant", messages[2]["role"])
        self.assertEqual("hf-call-1", messages[2]["tool_calls"][0]["id"])
        self.assertEqual("tool", messages[3]["role"])
        self.assertEqual("hf-call-1", messages[3]["tool_call_id"])
        self.assertIn("DEMO-63000030", messages[3]["content"])

    async def test_invalid_tool_arguments_are_rejected(self) -> None:
        chat_client = RecordingChatClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "hf-call-1",
                                    "function": {
                                        "name": "resolve_location",
                                        "arguments": "{not-json",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        model = HuggingFaceModelClient(client=chat_client)

        with self.assertRaisesRegex(
            HuggingFaceResponseError,
            "not valid JSON",
        ):
            await model.complete(
                messages=[UserMessage(text="台北市大安區")],
                tools=[_tool_definition()],
            )

    async def test_provider_error_is_replaced_with_safe_adapter_error(self) -> None:
        model = HuggingFaceModelClient(client=FailingChatClient())

        with self.assertRaisesRegex(
            HuggingFaceRequestError,
            "^Hugging Face inference request failed",
        ) as raised:
            await model.complete(
                messages=[UserMessage(text="水龍頭漏水")],
                tools=[_tool_definition()],
            )

        self.assertNotIn("sensitive details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
