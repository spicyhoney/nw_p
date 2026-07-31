from __future__ import annotations

import base64
import json
import unittest
from typing import Any

from home_repair_agent.agent.huggingface_vision import (
    DEFAULT_HF_VL_MODEL_ID,
    HuggingFaceVisionClient,
    HuggingFaceVisionConfigurationError,
    HuggingFaceVisionInputError,
    HuggingFaceVisionRequestError,
    HuggingFaceVisionResponseError,
    HuggingFaceVisionTimeoutError,
)


class RecordingVisionClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[dict[str, Any]] = []

    def chat_completion(self, **kwargs: Any) -> object:
        self.requests.append(kwargs)
        return self.response


class FailingVisionClient:
    def chat_completion(self, **kwargs: Any) -> object:
        del kwargs
        raise RuntimeError("provider response with sensitive details")


class TimeoutVisionClient:
    def chat_completion(self, **kwargs: Any) -> object:
        del kwargs
        raise TimeoutError("provider timeout details")


def _response(payload: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


def _analysis_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "service_query": "plumbing leak repair",
        "problem_summary": "A pipe joint appears to be leaking.",
        "safety_warnings": ["Turn off the nearby water supply if safe."],
        "confidence": 0.82,
        "uncertain": False,
    }
    payload.update(overrides)
    return payload


class HuggingFaceVisionConfigurationTests(unittest.TestCase):
    def test_from_environment_requires_token_without_fallback(self) -> None:
        with self.assertRaisesRegex(HuggingFaceVisionConfigurationError, "HF_TOKEN is required"):
            HuggingFaceVisionClient.from_environment(environ={})

    def test_environment_configures_dedicated_vision_model(self) -> None:
        model = HuggingFaceVisionClient.from_environment(
            client=RecordingVisionClient(_response(_analysis_payload())),
            environ={
                "HF_TOKEN": "test-only-token",
                "HF_VL_MODEL_ID": "org/vision-model",
                "HF_VL_PROVIDER": "test-provider",
                "HF_VL_MAX_TOKENS": "321",
                "HF_VL_TIMEOUT_SECONDS": "42",
            },
        )

        self.assertEqual("org/vision-model", model.model_id)
        self.assertEqual("test-provider", model.provider)
        self.assertEqual(42, model.timeout_seconds)
        self.assertNotIn("test-only-token", repr(model))

    def test_default_vision_model_is_configurable(self) -> None:
        model = HuggingFaceVisionClient.from_environment(
            client=RecordingVisionClient(_response(_analysis_payload())),
            environ={"HF_TOKEN": "test-only-token"},
        )

        self.assertEqual(DEFAULT_HF_VL_MODEL_ID, model.model_id)

    def test_empty_vision_model_is_a_configuration_error(self) -> None:
        with self.assertRaisesRegex(
            HuggingFaceVisionConfigurationError, "HF_VL_MODEL_ID must not be empty"
        ):
            HuggingFaceVisionClient.from_environment(
                client=RecordingVisionClient(_response(_analysis_payload())),
                environ={"HF_TOKEN": "test-only-token", "HF_VL_MODEL_ID": " "},
            )


class HuggingFaceVisionClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_multimodal_payload_and_normal_analysis(self) -> None:
        chat_client = RecordingVisionClient(_response(_analysis_payload()))
        model = HuggingFaceVisionClient(
            client=chat_client,
            model_id="org/vision-model",
            provider="test-provider",
        )
        image_bytes = b"synthetic-png-bytes"

        result = await model.analyze(
            image_bytes=image_bytes,
            mime_type="image/png",
            context="Water drips below the kitchen sink.",
        )

        self.assertEqual("plumbing leak repair", result.service_query)
        self.assertFalse(result.uncertain)
        request = chat_client.requests[0]
        self.assertEqual("org/vision-model", request["model"])
        self.assertEqual("json_schema", request["response_format"]["type"])
        user_content = request["messages"][1]["content"]
        self.assertEqual("text", user_content[0]["type"])
        self.assertIn("Water drips", user_content[0]["text"])
        self.assertEqual("image_url", user_content[1]["type"])
        self.assertEqual(
            "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii"),
            user_content[1]["image_url"]["url"],
        )

    async def test_low_confidence_uncertain_result_is_preserved(self) -> None:
        model = HuggingFaceVisionClient(
            client=RecordingVisionClient(
                _response(_analysis_payload(confidence=0.21, uncertain=True, safety_warnings=[]))
            )
        )

        result = await model.analyze(image_bytes=b"synthetic", mime_type="image/jpeg")

        self.assertEqual(0.21, result.confidence)
        self.assertTrue(result.uncertain)
        self.assertEqual([], result.safety_warnings)

    async def test_unsupported_mime_is_rejected_before_provider_call(self) -> None:
        chat_client = RecordingVisionClient(_response(_analysis_payload()))
        model = HuggingFaceVisionClient(client=chat_client)

        with self.assertRaisesRegex(HuggingFaceVisionInputError, "Unsupported image MIME type"):
            await model.analyze(image_bytes=b"not-a-pdf", mime_type="application/pdf")

        self.assertEqual([], chat_client.requests)

    async def test_invalid_or_unsafe_response_schema_is_rejected(self) -> None:
        chat_client = RecordingVisionClient(
            _response(_analysis_payload(service_id="invented-service-id"))
        )
        model = HuggingFaceVisionClient(client=chat_client)

        with self.assertRaisesRegex(HuggingFaceVisionResponseError, "does not match"):
            await model.analyze(image_bytes=b"synthetic", mime_type="image/webp")

    async def test_non_json_response_is_rejected(self) -> None:
        model = HuggingFaceVisionClient(
            client=RecordingVisionClient({"choices": [{"message": {"content": "not-json"}}]})
        )

        with self.assertRaisesRegex(HuggingFaceVisionResponseError, "not valid analysis JSON"):
            await model.analyze(image_bytes=b"synthetic", mime_type="image/jpeg")

    async def test_provider_error_is_masked_without_fallback(self) -> None:
        model = HuggingFaceVisionClient(client=FailingVisionClient())

        with self.assertRaisesRegex(
            HuggingFaceVisionRequestError, "^Hugging Face vision inference request failed"
        ) as raised:
            await model.analyze(image_bytes=b"synthetic", mime_type="image/jpeg")

        self.assertNotIn("sensitive details", str(raised.exception))

    async def test_timeout_is_explicit_and_masked(self) -> None:
        model = HuggingFaceVisionClient(client=TimeoutVisionClient())

        with self.assertRaisesRegex(
            HuggingFaceVisionTimeoutError, "^Hugging Face vision inference timed out"
        ) as raised:
            await model.analyze(image_bytes=b"synthetic", mime_type="image/jpeg")

        self.assertNotIn("provider timeout details", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
