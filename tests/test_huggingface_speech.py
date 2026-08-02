from __future__ import annotations

import json
import unittest

import httpx

from home_repair_agent.web.speech import (
    DEFAULT_HF_ASR_MODEL_ID,
    DEFAULT_HF_ASR_SPACE_URL,
    MAX_SPEECH_UPLOAD_BYTES,
    HuggingFaceGradioSpeechToTextClient,
    SpeechToTextConfigurationError,
    SpeechToTextInputError,
    SpeechToTextRequestError,
    SpeechToTextResponseError,
    SpeechToTextTimeoutError,
)


def _webm_audio() -> bytes:
    return b"\x1a\x45\xdf\xa3" + b"synthetic-audio"


class HuggingFaceSpeechConfigurationTests(unittest.TestCase):
    def test_defaults_target_the_verified_breeze_space_contract(self) -> None:
        client = HuggingFaceGradioSpeechToTextClient.from_environment(environ={})

        self.assertEqual(DEFAULT_HF_ASR_MODEL_ID, client.model_id)
        self.assertEqual(DEFAULT_HF_ASR_SPACE_URL, client.base_url)

    def test_only_https_hf_space_origins_are_allowed(self) -> None:
        for unsafe_url in (
            "http://example.hf.space",
            "https://example.com",
            "https://user:secret@example.hf.space",
            "https://example.hf.space?token=secret",
        ):
            with (
                self.subTest(unsafe_url=unsafe_url),
                self.assertRaises(SpeechToTextConfigurationError),
            ):
                HuggingFaceGradioSpeechToTextClient(base_url=unsafe_url)

    def test_extra_inputs_must_be_a_small_scalar_json_object(self) -> None:
        for value in ("[]", "not-json", '{"nested":{"unsafe":true}}'):
            with (
                self.subTest(value=value),
                self.assertRaises(SpeechToTextConfigurationError),
            ):
                HuggingFaceGradioSpeechToTextClient.from_environment(
                    environ={"HF_ASR_EXTRA_INPUTS_JSON": value}
                )


class HuggingFaceSpeechClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_transcribes_gradio_event_without_forwarding_general_hf_token(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertNotIn("authorization", request.headers)
            if request.url.path == "/gradio_api/upload":
                self.assertIn("multipart/form-data", request.headers["content-type"])
                return httpx.Response(200, json=["/tmp/gradio/public-audio.webm"])
            if request.url.path == "/gradio_api/call/v2/transcribe":
                payload = json.loads(request.content)
                self.assertEqual(
                    "/tmp/gradio/public-audio.webm",
                    payload["audio"]["path"],
                )
                return httpx.Response(200, json={"event_id": "event-safe"})
            if request.url.path == "/gradio_api/call/transcribe/event-safe":
                return httpx.Response(
                    200,
                    text=(f"event: complete\ndata: {json.dumps(['臺北市大安區 水龍頭漏水'])}\n\n"),
                )
            raise AssertionError(f"unexpected path: {request.url.path}")

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=DEFAULT_HF_ASR_SPACE_URL,
        ) as http_client:
            client = HuggingFaceGradioSpeechToTextClient.from_environment(
                environ={"HF_TOKEN": "must-not-be-forwarded"},
                client=http_client,
            )
            transcript = await client.transcribe(
                _webm_audio(),
                content_type="audio/webm;codecs=opus",
            )

        self.assertEqual("臺北市大安區 水龍頭漏水", transcript.text)
        self.assertEqual(DEFAULT_HF_ASR_MODEL_ID, transcript.model_id)
        self.assertEqual(3, len(requests))

    async def test_rejects_unsupported_mime_mismatched_magic_and_oversize_audio(self) -> None:
        client = HuggingFaceGradioSpeechToTextClient()
        cases = (
            (_webm_audio(), "audio/aac"),
            (b"not-webm", "audio/webm"),
            (b"\x1a\x45\xdf\xa3" + b"x" * MAX_SPEECH_UPLOAD_BYTES, "audio/webm"),
        )
        for audio, content_type in cases:
            with (
                self.subTest(content_type=content_type, size=len(audio)),
                self.assertRaises(SpeechToTextInputError),
            ):
                await client.transcribe(audio, content_type=content_type)

    async def test_provider_failure_uses_a_redacted_error(self) -> None:
        provider_payload = "private-provider-payload"

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text=provider_payload)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=DEFAULT_HF_ASR_SPACE_URL,
        ) as http_client:
            client = HuggingFaceGradioSpeechToTextClient(client=http_client)
            with self.assertRaises(SpeechToTextRequestError) as raised:
                await client.transcribe(_webm_audio(), content_type="audio/webm")

        self.assertNotIn(provider_payload, str(raised.exception))

    async def test_timeout_is_explicit_and_never_returns_a_fallback_transcript(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("synthetic timeout", request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=DEFAULT_HF_ASR_SPACE_URL,
        ) as http_client:
            client = HuggingFaceGradioSpeechToTextClient(client=http_client)
            with self.assertRaises(SpeechToTextTimeoutError):
                await client.transcribe(_webm_audio(), content_type="audio/webm")

    async def test_incomplete_event_and_blank_transcript_are_rejected(self) -> None:
        completed_bodies = iter(
            (
                "event: heartbeat\ndata: null\n\n",
                f"event: complete\ndata: {json.dumps([json.dumps({'text': '   '})])}\n\n",
            )
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/gradio_api/upload":
                return httpx.Response(200, json=["/tmp/gradio/audio.webm"])
            if request.url.path == "/gradio_api/call/v2/transcribe":
                return httpx.Response(200, json={"event_id": "event-safe"})
            return httpx.Response(200, text=next(completed_bodies))

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=DEFAULT_HF_ASR_SPACE_URL,
        ) as http_client:
            client = HuggingFaceGradioSpeechToTextClient(client=http_client)
            for _ in range(2):
                with self.assertRaises(SpeechToTextResponseError):
                    await client.transcribe(_webm_audio(), content_type="audio/webm")


if __name__ == "__main__":
    unittest.main()
