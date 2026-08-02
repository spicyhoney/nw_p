"""Production request pacing for shared model clients."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence

from home_repair_agent.agent.models import (
    ConversationMessage,
    ModelTurn,
    ToolDefinition,
)
from home_repair_agent.agent.ports import ModelClient

MINIMUM_BEDROCK_INTERVAL_SECONDS = 1.1


class PacedModelClient:
    """Keep shared model request starts at least the configured interval apart."""

    def __init__(
        self,
        delegate: ModelClient,
        *,
        minimum_interval_seconds: float = MINIMUM_BEDROCK_INTERVAL_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if minimum_interval_seconds < MINIMUM_BEDROCK_INTERVAL_SECONDS:
            raise ValueError(
                f"minimum_interval_seconds must be at least {MINIMUM_BEDROCK_INTERVAL_SECONDS}"
            )
        self._delegate = delegate
        self._minimum_interval_seconds = minimum_interval_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._request_started_at: list[float] = []

    @property
    def request_count(self) -> int:
        return len(self._request_started_at)

    @property
    def request_intervals_seconds(self) -> list[float]:
        return [
            later - earlier
            for earlier, later in zip(
                self._request_started_at,
                self._request_started_at[1:],
                strict=False,
            )
        ]

    async def complete(
        self,
        *,
        messages: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
    ) -> ModelTurn:
        async with self._lock:
            if self._request_started_at:
                elapsed = self._monotonic() - self._request_started_at[-1]
                wait_seconds = self._minimum_interval_seconds - elapsed
                if wait_seconds > 0:
                    await self._sleep(wait_seconds)
            self._request_started_at.append(self._monotonic())
            return await self._delegate.complete(messages=messages, tools=tools)
