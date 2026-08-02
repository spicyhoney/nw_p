"""Hugging Face hosted vision-language adapter for repair-photo suggestions.

This module deliberately only produces a validated suggestion.  It does not
query services, create cases, or dispatch providers; those actions require
separate service-layer validation and an explicit user confirmation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
from collections.abc import Mapping
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_HF_VL_MODEL_ID = "Qwen/Qwen3-VL-30B-A3B-Instruct"
DEFAULT_HF_VL_PROVIDER = "auto"
DEFAULT_HF_VL_MAX_TOKENS = 512
DEFAULT_HF_VL_TIMEOUT_SECONDS = 60
SUPPORTED_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})

VISION_ANALYSIS_SYSTEM_PROMPT = """\
You analyze a home-repair photo only as a preliminary suggestion. Return exactly
one JSON object matching the supplied schema. Do not invent a service_id, create
a case, dispatch a provider, claim certainty, or treat the result as a user
confirmation. Mention immediate hazards in safety_warnings and set uncertain
when the photo alone is insufficient or ambiguous. Write service_query,
problem_summary and safety_warnings in Traditional Chinese for a Taiwan service
catalog.
"""


class HuggingFaceVisionChatClient(Protocol):
    """Small synchronous surface provided by huggingface_hub.InferenceClient."""

    def chat_completion(self, **kwargs: Any) -> object: ...


class HuggingFaceVisionError(RuntimeError):
    """Base error whose message excludes image data and provider payloads."""


class HuggingFaceVisionConfigurationError(HuggingFaceVisionError):
    """The vision adapter is not configured for a hosted request."""


class HuggingFaceVisionInputError(HuggingFaceVisionError):
    """The caller supplied an image this adapter cannot send to the model."""


class HuggingFaceVisionRequestError(HuggingFaceVisionError):
    """The hosted inference provider rejected or failed the request."""


class HuggingFaceVisionTimeoutError(HuggingFaceVisionRequestError):
    """The hosted inference request timed out."""


class HuggingFaceVisionResponseError(HuggingFaceVisionError):
    """The hosted response cannot satisfy the image-analysis contract."""


class VisionAnalysisResult(BaseModel):
    """Strict, suggestion-only result returned by a vision-language model."""

    model_config = ConfigDict(extra="forbid", strict=True)

    service_query: str = Field(min_length=1, max_length=300)
    problem_summary: str = Field(min_length=1, max_length=1200)
    safety_warnings: list[str] = Field(max_length=10)
    confidence: float = Field(ge=0, le=1)
    uncertain: bool

    @field_validator("service_query", "problem_summary")
    @classmethod
    def _non_blank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("safety_warnings")
    @classmethod
    def _valid_warnings(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("safety warnings must not be blank")
            normalized.append(cleaned)
        return normalized

    @field_validator("confidence")
    @classmethod
    def _finite_confidence(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value


class HuggingFaceVisionClient:
    """Translate verified image bytes into an HF VLM chat-completion request."""

    def __init__(
        self,
        *,
        client: HuggingFaceVisionChatClient,
        model_id: str = DEFAULT_HF_VL_MODEL_ID,
        provider: str = DEFAULT_HF_VL_PROVIDER,
        max_tokens: int = DEFAULT_HF_VL_MAX_TOKENS,
        timeout_seconds: int = DEFAULT_HF_VL_TIMEOUT_SECONDS,
    ) -> None:
        normalized_model_id = model_id.strip()
        normalized_provider = provider.strip()
        if not normalized_model_id:
            raise ValueError("model_id must not be empty")
        if not normalized_provider:
            raise ValueError("provider must not be empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._client = client
        self._model_id = normalized_model_id
        self._provider = normalized_provider
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def timeout_seconds(self) -> int:
        return self._timeout_seconds

    @classmethod
    def from_environment(
        cls,
        *,
        client: HuggingFaceVisionChatClient | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> HuggingFaceVisionClient:
        environment = os.environ if environ is None else environ
        token = environment.get("HF_TOKEN", "").strip()
        if not token:
            raise HuggingFaceVisionConfigurationError(
                "HF_TOKEN is required for Hugging Face vision model mode."
            )

        model_id = environment.get("HF_VL_MODEL_ID", DEFAULT_HF_VL_MODEL_ID).strip()
        provider = environment.get("HF_VL_PROVIDER", DEFAULT_HF_VL_PROVIDER).strip()
        if not model_id:
            raise HuggingFaceVisionConfigurationError("HF_VL_MODEL_ID must not be empty.")
        if not provider:
            raise HuggingFaceVisionConfigurationError("HF_VL_PROVIDER must not be empty.")
        max_tokens = _parse_positive_int(
            environment.get("HF_VL_MAX_TOKENS"),
            name="HF_VL_MAX_TOKENS",
            default=DEFAULT_HF_VL_MAX_TOKENS,
        )
        timeout_seconds = _parse_positive_int(
            environment.get("HF_VL_TIMEOUT_SECONDS"),
            name="HF_VL_TIMEOUT_SECONDS",
            default=DEFAULT_HF_VL_TIMEOUT_SECONDS,
        )
        resolved_client = client or _create_inference_client(
            token=token,
            provider=provider,
            timeout_seconds=timeout_seconds,
        )
        return cls(
            client=resolved_client,
            model_id=model_id,
            provider=provider,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )

    async def analyze(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        context: str | None = None,
    ) -> VisionAnalysisResult:
        """Return a structured suggestion for bytes already verified by media intake."""
        request = self._build_request(
            image_bytes=image_bytes,
            mime_type=mime_type,
            context=context,
        )
        try:
            response = await asyncio.to_thread(self._client.chat_completion, **request)
        except TimeoutError as error:
            raise HuggingFaceVisionTimeoutError(
                "Hugging Face vision inference timed out."
            ) from error
        except Exception as error:
            raise HuggingFaceVisionRequestError(
                "Hugging Face vision inference request failed."
            ) from error
        return _parse_analysis_response(response)

    def _build_request(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        context: str | None,
    ) -> dict[str, Any]:
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise HuggingFaceVisionInputError("A non-empty verified image is required.")
        normalized_mime_type = mime_type.strip().lower()
        if normalized_mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            raise HuggingFaceVisionInputError(
                "Unsupported image MIME type for Hugging Face vision analysis."
            )
        if context is not None and not isinstance(context, str):
            raise HuggingFaceVisionInputError("Image analysis context must be text.")

        image_url = _to_data_url(image_bytes, normalized_mime_type)
        return {
            "model": self._model_id,
            "messages": [
                {"role": "system", "content": VISION_ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _analysis_prompt(context)},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "max_tokens": self._max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "repair_image_analysis",
                    "strict": True,
                    "schema": VisionAnalysisResult.model_json_schema(),
                },
            },
        }


def _analysis_prompt(context: str | None) -> str:
    prompt = (
        "Analyze this repair photo. Return only the requested JSON object with a "
        "broad service_query, a concise problem_summary, safety_warnings, confidence, "
        "and uncertain. Use Traditional Chinese for all user-facing text. This is a "
        "suggestion pending user confirmation."
    )
    if context and context.strip():
        return f"{prompt}\nUser-provided context: {context.strip()}"
    return prompt


def _to_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _create_inference_client(
    *,
    token: str,
    provider: str,
    timeout_seconds: int,
) -> HuggingFaceVisionChatClient:
    try:
        from huggingface_hub import InferenceClient
    except ImportError as error:
        raise HuggingFaceVisionConfigurationError(
            'huggingface_hub is required; install the project with the "app" extra.'
        ) from error

    try:
        return cast(
            HuggingFaceVisionChatClient,
            InferenceClient(
                api_key=token,
                provider=provider,
                timeout=timeout_seconds,
            ),
        )
    except Exception as error:
        raise HuggingFaceVisionConfigurationError(
            "Could not create the Hugging Face vision inference client."
        ) from error


def _parse_positive_int(
    raw_value: str | None,
    *,
    name: str,
    default: int,
) -> int:
    if raw_value is None or not raw_value.strip():
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise HuggingFaceVisionConfigurationError(f"{name} must be a positive integer.") from error
    if parsed <= 0:
        raise HuggingFaceVisionConfigurationError(f"{name} must be a positive integer.")
    return parsed


def _parse_analysis_response(response: object) -> VisionAnalysisResult:
    choices = _field(response, "choices")
    if not isinstance(choices, list) or not choices:
        raise HuggingFaceVisionResponseError(
            "Hugging Face vision response is missing completion choices."
        )
    message = _field(choices[0], "message")
    content = _field(message, "content")
    if not isinstance(content, str) or not content.strip():
        raise HuggingFaceVisionResponseError(
            "Hugging Face vision response is missing structured analysis content."
        )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise HuggingFaceVisionResponseError(
            "Hugging Face vision response is not valid analysis JSON."
        ) from error
    if not isinstance(payload, dict):
        raise HuggingFaceVisionResponseError("Hugging Face vision analysis must be a JSON object.")
    try:
        return VisionAnalysisResult.model_validate(payload)
    except ValidationError as error:
        raise HuggingFaceVisionResponseError(
            "Hugging Face vision response does not match the analysis schema."
        ) from error


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
