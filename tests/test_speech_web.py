from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from home_repair_agent.web.app import create_app
from home_repair_agent.web.speech import (
    DEFAULT_HF_ASR_MODEL_ID,
    SpeechToTextRequestError,
    Transcript,
)


class _FakeSpeechClient:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript:
        self.calls.append((audio, content_type))
        if self.failure is not None:
            raise self.failure
        return Transcript(
            text="臺北市大安區水龍頭漏水",
            model_id=DEFAULT_HF_ASR_MODEL_ID,
        )


@contextmanager
def _huggingface_test_client(speech_client: _FakeSpeechClient):
    with (
        patch.dict(
            "os.environ",
            {"WEB_MODEL_PROVIDER": "huggingface", "HF_TOKEN": "test-only-token"},
            clear=False,
        ),
        patch(
            "home_repair_agent.web.app._resolve_model_client",
            return_value=(Mock(), "Hugging Face test double"),
        ),
        patch(
            "home_repair_agent.web.app.HuggingFaceVisionClient.from_environment",
            return_value=Mock(),
        ),
        TestClient(create_app(speech_to_text_client=speech_client)) as client,
    ):
        yield client


class SpeechWebTests(unittest.TestCase):
    def test_hf_mode_transcribes_ephemeral_audio_for_user_confirmation(self) -> None:
        speech = _FakeSpeechClient()
        with _huggingface_test_client(speech) as client:
            session = client.post("/api/sessions").json()
            response = client.post(
                f"/api/sessions/{session['session_id']}/speech/transcribe",
                files={"file": ("voice.webm", b"synthetic-webm", "audio/webm")},
                data={"external_processing_confirmed": "true"},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {
                "text": "臺北市大安區水龍頭漏水",
                "model_id": DEFAULT_HF_ASR_MODEL_ID,
                "provider": "huggingface_space",
                "needs_user_confirmation": True,
            },
            response.json(),
        )
        self.assertEqual([(b"synthetic-webm", "audio/webm")], speech.calls)
        self.assertNotIn("test-only-token", response.text)

    def test_explicit_external_processing_consent_is_required(self) -> None:
        speech = _FakeSpeechClient()
        with _huggingface_test_client(speech) as client:
            session = client.post("/api/sessions").json()
            response = client.post(
                f"/api/sessions/{session['session_id']}/speech/transcribe",
                files={"file": ("voice.webm", b"synthetic-webm", "audio/webm")},
                data={"external_processing_confirmed": "false"},
            )

        self.assertEqual(422, response.status_code)
        self.assertEqual("VOICE_EXTERNAL_CONSENT_REQUIRED", response.json()["error"]["code"])
        self.assertEqual([], speech.calls)

    def test_mock_mode_rejects_voice_even_when_a_fake_client_is_injected(self) -> None:
        speech = _FakeSpeechClient()
        with TestClient(create_app(speech_to_text_client=speech)) as client:
            session = client.post("/api/sessions").json()
            response = client.post(
                f"/api/sessions/{session['session_id']}/speech/transcribe",
                files={"file": ("voice.webm", b"synthetic-webm", "audio/webm")},
                data={"external_processing_confirmed": "true"},
            )

        self.assertEqual(409, response.status_code)
        self.assertEqual("VOICE_INPUT_UNAVAILABLE", response.json()["error"]["code"])
        self.assertIn("不會改用 Mock", response.json()["error"]["message"])
        self.assertEqual([], speech.calls)

    def test_upstream_failure_is_redacted_and_has_no_mock_fallback(self) -> None:
        secret_marker = "provider-private-payload"
        speech = _FakeSpeechClient(failure=SpeechToTextRequestError(secret_marker))
        with _huggingface_test_client(speech) as client:
            session = client.post("/api/sessions").json()
            response = client.post(
                f"/api/sessions/{session['session_id']}/speech/transcribe",
                files={"file": ("voice.webm", b"synthetic-webm", "audio/webm")},
                data={"external_processing_confirmed": "true"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("VOICE_TRANSCRIPTION_FAILED", response.json()["error"]["code"])
        self.assertIn("沒有改用 Mock", response.json()["error"]["message"])
        self.assertNotIn(secret_marker, response.text)
        self.assertNotIn("synthetic-webm", response.text)


if __name__ == "__main__":
    unittest.main()
