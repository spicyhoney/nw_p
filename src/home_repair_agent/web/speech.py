"""Ephemeral speech-to-text adapter for the HF-only Web Demo voice input.

Audio is validated in memory, sent to a configured Hugging Face Gradio Space,
and discarded after transcription.  This module never creates a case, sends a
chat message, or falls back to another model provider.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

DEFAULT_HF_ASR_MODEL_ID = "MediaTek-Research/Breeze-ASR-26"
DEFAULT_HF_ASR_SPACE_URL = "https://liaozike-breeze-asr-api.hf.space"
DEFAULT_HF_ASR_API_NAME = "transcribe"
DEFAULT_HF_ASR_AUDIO_PARAMETER = "audio"
DEFAULT_HF_ASR_TIMEOUT_SECONDS = 90
DEFAULT_HF_ASR_EXTRA_INPUTS: dict[str, str | int | float | bool | None] = {}
MAX_SPEECH_UPLOAD_BYTES = 6 * 1024 * 1024
MAX_TRANSCRIPT_CHARACTERS = 1000
SUPPORTED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "audio/x-wav",
    }
)
_SAFE_API_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True, slots=True)
class Transcript:
    """Provider-neutral transcription returned to the browser for confirmation."""

    text: str
    model_id: str


class SpeechToTextPort(Protocol):
    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript: ...


class SpeechToTextError(RuntimeError):
    """Base error whose message excludes audio, transcript, and provider payloads."""


class SpeechToTextConfigurationError(SpeechToTextError):
    """The configured Hugging Face ASR endpoint is unsafe or incomplete."""


class SpeechToTextInputError(SpeechToTextError):
    """The caller supplied an unsupported or invalid audio payload."""


class SpeechToTextRequestError(SpeechToTextError):
    """The configured Hugging Face Space failed the request."""


class SpeechToTextTimeoutError(SpeechToTextRequestError):
    """The configured Hugging Face Space did not finish in time."""


class SpeechToTextResponseError(SpeechToTextError):
    """The provider response does not satisfy the transcript contract."""


class HuggingFaceGradioSpeechToTextClient:
    """Call a narrowly configured Gradio ASR endpoint without persisting audio."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_HF_ASR_SPACE_URL,
        api_name: str = DEFAULT_HF_ASR_API_NAME,
        audio_parameter: str = DEFAULT_HF_ASR_AUDIO_PARAMETER,
        model_id: str = DEFAULT_HF_ASR_MODEL_ID,
        timeout_seconds: int = DEFAULT_HF_ASR_TIMEOUT_SECONDS,
        extra_inputs: Mapping[str, str | int | float | bool | None] | None = None,
        token: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = _validate_space_url(base_url)
        self._api_name = _validate_identifier(api_name, name="api_name")
        self._audio_parameter = _validate_identifier(
            audio_parameter,
            name="audio_parameter",
        )
        self._model_id = model_id.strip()
        if not self._model_id:
            raise ValueError("model_id must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = timeout_seconds
        self._extra_inputs = _validate_extra_inputs(
            DEFAULT_HF_ASR_EXTRA_INPUTS if extra_inputs is None else extra_inputs
        )
        self._token = token.strip() if token else ""
        self._client = client

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def base_url(self) -> str:
        return self._base_url

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> HuggingFaceGradioSpeechToTextClient:
        environment = os.environ if environ is None else environ
        extra_inputs = _parse_extra_inputs(environment.get("HF_ASR_EXTRA_INPUTS_JSON"))
        return cls(
            base_url=environment.get("HF_ASR_SPACE_URL", DEFAULT_HF_ASR_SPACE_URL),
            api_name=environment.get("HF_ASR_API_NAME", DEFAULT_HF_ASR_API_NAME),
            audio_parameter=environment.get(
                "HF_ASR_AUDIO_PARAMETER",
                DEFAULT_HF_ASR_AUDIO_PARAMETER,
            ),
            model_id=environment.get("HF_ASR_MODEL_ID", DEFAULT_HF_ASR_MODEL_ID),
            timeout_seconds=_parse_positive_int(
                environment.get("HF_ASR_TIMEOUT_SECONDS"),
                name="HF_ASR_TIMEOUT_SECONDS",
                default=DEFAULT_HF_ASR_TIMEOUT_SECONDS,
            ),
            extra_inputs=extra_inputs,
            # Deliberately do not reuse HF_TOKEN: a community Space must never
            # receive the chat/VLM credential implicitly.
            token=environment.get("HF_ASR_TOKEN"),
            client=client,
        )

    async def transcribe(self, audio: bytes, *, content_type: str) -> Transcript:
        normalized_type = _validate_audio(audio, content_type)
        if self._client is not None:
            return await self._transcribe_with_client(
                self._client,
                audio=audio,
                content_type=normalized_type,
            )
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        ) as client:
            return await self._transcribe_with_client(
                client,
                audio=audio,
                content_type=normalized_type,
            )

    async def _transcribe_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        audio: bytes,
        content_type: str,
    ) -> Transcript:
        filename = _safe_audio_filename(content_type)
        upload = await _safe_request(
            client.post,
            "/gradio_api/upload",
            timeout_seconds=self._timeout_seconds,
            files={"files": (filename, audio, content_type)},
        )
        try:
            upload_payload = upload.json()
            remote_path = upload_payload[0]
        except (ValueError, TypeError, IndexError, KeyError) as error:
            raise SpeechToTextResponseError(
                "Hugging Face ASR upload returned an invalid response."
            ) from error
        if not isinstance(remote_path, str) or not remote_path.strip():
            raise SpeechToTextResponseError("Hugging Face ASR upload returned an invalid response.")

        request_payload = dict(self._extra_inputs)
        request_payload[self._audio_parameter] = {
            "path": remote_path,
            "meta": {"_type": "gradio.FileData"},
        }
        call = await _safe_request(
            client.post,
            f"/gradio_api/call/v2/{self._api_name}",
            timeout_seconds=self._timeout_seconds,
            json=request_payload,
        )
        try:
            event_id = call.json()["event_id"]
        except (ValueError, TypeError, KeyError) as error:
            raise SpeechToTextResponseError(
                "Hugging Face ASR did not return a valid event identifier."
            ) from error
        if not isinstance(event_id, str) or not event_id.strip():
            raise SpeechToTextResponseError(
                "Hugging Face ASR did not return a valid event identifier."
            )

        result = await _safe_request(
            client.get,
            f"/gradio_api/call/{self._api_name}/{event_id}",
            timeout_seconds=self._timeout_seconds,
        )
        text = _parse_gradio_transcript(result.text)
        return Transcript(text=text, model_id=self._model_id)


async def _safe_request(
    request_method: Callable[..., Awaitable[httpx.Response]],
    path: str,
    *,
    timeout_seconds: int,
    **kwargs: object,
) -> httpx.Response:
    try:
        response = await request_method(path, **kwargs)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as error:
        raise SpeechToTextTimeoutError("Hugging Face ASR request timed out.") from error
    except httpx.HTTPError as error:
        raise SpeechToTextRequestError("Hugging Face ASR request failed.") from error
    except TimeoutError as error:
        raise SpeechToTextTimeoutError("Hugging Face ASR request timed out.") from error


def _validate_audio(audio: bytes, content_type: str) -> str:
    if not isinstance(audio, bytes) or not audio:
        raise SpeechToTextInputError("A non-empty audio recording is required.")
    if len(audio) > MAX_SPEECH_UPLOAD_BYTES:
        raise SpeechToTextInputError("Audio recording exceeds the 6 MiB limit.")
    normalized_type = content_type.partition(";")[0].strip().lower()
    if normalized_type not in SUPPORTED_AUDIO_MIME_TYPES:
        raise SpeechToTextInputError("Unsupported audio MIME type.")
    if not _matches_audio_signature(audio, normalized_type):
        raise SpeechToTextInputError("Audio content does not match its declared format.")
    return normalized_type


def _matches_audio_signature(audio: bytes, content_type: str) -> bool:
    if content_type in {"audio/wav", "audio/x-wav"}:
        return len(audio) >= 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    if content_type == "audio/webm":
        return audio.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/ogg":
        return audio.startswith(b"OggS")
    if content_type == "audio/mp4":
        return len(audio) >= 12 and audio[4:8] == b"ftyp"
    if content_type == "audio/mpeg":
        return audio.startswith(b"ID3") or (
            len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0
        )
    return False


def _safe_audio_filename(content_type: str) -> str:
    extension = {
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/x-wav": "wav",
    }[content_type]
    return f"voice-input.{extension}"


def _parse_gradio_transcript(body: str) -> str:
    completed_data: str | None = None
    current_event = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            current_event = line.partition(":")[2].strip()
        elif line.startswith("data:") and current_event == "complete":
            completed_data = line.partition(":")[2].strip()
        elif current_event == "error":
            raise SpeechToTextRequestError("Hugging Face ASR request failed.")
    if completed_data is None:
        raise SpeechToTextResponseError("Hugging Face ASR did not return a completed transcript.")
    try:
        outer = json.loads(completed_data)
        first = outer[0]
        if isinstance(first, str):
            try:
                parsed = json.loads(first)
            except json.JSONDecodeError:
                parsed = first
        else:
            parsed = first
        transcript = parsed["text"] if isinstance(parsed, dict) else parsed
    except (json.JSONDecodeError, TypeError, IndexError, KeyError) as error:
        raise SpeechToTextResponseError(
            "Hugging Face ASR returned an invalid transcript."
        ) from error
    if not isinstance(transcript, str):
        raise SpeechToTextResponseError("Hugging Face ASR returned an invalid transcript.")
    normalized = " ".join(_CONTROL_CHARACTERS.sub(" ", transcript).split())
    if not normalized:
        raise SpeechToTextResponseError("Hugging Face ASR returned an empty transcript.")
    if len(normalized) > MAX_TRANSCRIPT_CHARACTERS:
        raise SpeechToTextResponseError("Hugging Face ASR transcript is too long.")
    return normalized


def _validate_space_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".hf.space")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SpeechToTextConfigurationError("HF_ASR_SPACE_URL must be an HTTPS hf.space origin.")
    return normalized


def _validate_identifier(value: str, *, name: str) -> str:
    normalized = value.strip().strip("/")
    if not _SAFE_API_NAME.fullmatch(normalized):
        raise SpeechToTextConfigurationError(f"{name} contains unsupported characters.")
    return normalized


def _validate_extra_inputs(
    values: Mapping[str, str | int | float | bool | None],
) -> dict[str, str | int | float | bool | None]:
    if len(values) > 10:
        raise SpeechToTextConfigurationError("HF ASR extra inputs exceed the limit.")
    normalized: dict[str, str | int | float | bool | None] = {}
    for key, value in values.items():
        safe_key = _validate_identifier(key, name="HF ASR extra input name")
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise SpeechToTextConfigurationError(
                "HF ASR extra inputs must contain scalar JSON values."
            )
        normalized[safe_key] = value
    return normalized


def _parse_extra_inputs(value: str | None) -> dict[str, str | int | float | bool | None]:
    if value is None or not value.strip():
        return dict(DEFAULT_HF_ASR_EXTRA_INPUTS)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise SpeechToTextConfigurationError(
            "HF_ASR_EXTRA_INPUTS_JSON must be a JSON object."
        ) from error
    if not isinstance(parsed, dict):
        raise SpeechToTextConfigurationError("HF_ASR_EXTRA_INPUTS_JSON must be a JSON object.")
    return _validate_extra_inputs(parsed)


def _parse_positive_int(value: str | None, *, name: str, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise SpeechToTextConfigurationError(f"{name} must be a positive integer.") from error
    if parsed <= 0:
        raise SpeechToTextConfigurationError(f"{name} must be a positive integer.")
    return parsed
