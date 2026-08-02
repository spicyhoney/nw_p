from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from home_repair_agent.web.speech import HuggingFaceGradioSpeechToTextClient


class _TimedClient(httpx.AsyncClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.timings: list[dict[str, object]] = []

    async def post(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._timed_request("POST", url, *args, **kwargs)

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._timed_request("GET", url, *args, **kwargs)

    async def _timed_request(
        self,
        method: str,
        url: str,
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response:
        started = time.perf_counter()
        response = await super().request(method, url, *args, **kwargs)
        self.timings.append(
            {
                "method": method,
                "phase": _phase_for_url(url),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "status_code": response.status_code,
            }
        )
        return response


def _phase_for_url(url: str) -> str:
    if url.endswith("/upload"):
        return "upload"
    if "/event" in url or "/call/transcribe/" in url:
        return "queue_and_inference"
    return "enqueue"


def _content_type_for_path(path: Path) -> str:
    return {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }.get(path.suffix.lower(), "")


async def _run(args: argparse.Namespace) -> dict[str, object]:
    audio_path = Path(args.audio).resolve(strict=True)
    content_type = args.content_type or _content_type_for_path(audio_path)
    if not content_type:
        raise ValueError("--content-type is required for this audio extension")
    audio = audio_path.read_bytes()

    async with _TimedClient(
        base_url=args.space_url,
        timeout=args.timeout_seconds,
        follow_redirects=False,
    ) as http_client:
        client = HuggingFaceGradioSpeechToTextClient(
            base_url=args.space_url,
            timeout_seconds=args.timeout_seconds,
            client=http_client,
        )
        started = time.perf_counter()
        transcript = await client.transcribe(audio, content_type=content_type)
        total_ms = round((time.perf_counter() - started) * 1000)
        return {
            "model_id": transcript.model_id,
            "audio_bytes": len(audio),
            "transcript_characters": len(transcript.text),
            "total_ms": total_ms,
            "phases": http_client.timings,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure a synthetic/public HF ASR request without logging audio or text."
    )
    parser.add_argument("audio")
    parser.add_argument(
        "--content-type",
        choices=("audio/mp4", "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm"),
    )
    parser.add_argument(
        "--space-url",
        default="https://liaozike-breeze-asr-api.hf.space",
    )
    parser.add_argument("--timeout-seconds", type=int, default=120)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
