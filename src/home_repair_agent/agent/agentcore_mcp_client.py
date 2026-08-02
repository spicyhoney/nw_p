from __future__ import annotations

import asyncio
import logging
import math
import os
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Literal, Self, cast
from urllib.parse import quote

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from home_repair_agent.agent.mcp_client import MCPToolClient
from home_repair_agent.agent.models import ToolDefinition, ToolExecutionResult

_AGENTCORE_REGION = "us-west-2"
_AGENTCORE_SERVICE = "bedrock-agentcore"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_SENSITIVE_TRANSPORT_LOGGERS = (
    "httpx",
    "httpcore",
    "mcp.client.streamable_http",
)

HttpClientFactory = Callable[..., AbstractAsyncContextManager[Any]]
TransportFactory = Callable[..., AbstractAsyncContextManager[tuple[Any, Any, Any]]]
ClientSessionFactory = Callable[..., AbstractAsyncContextManager[Any]]


class AgentCoreMCPError(RuntimeError):
    """Safe, payload-free error raised by the AgentCore MCP adapter."""


class AgentCoreMCPConfigurationError(AgentCoreMCPError):
    """Raised when controlled AgentCore settings are missing or invalid."""


class AgentCoreMCPSettings(BaseModel):
    """Validated settings for one AgentCore Remote MCP connection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    runtime_arn: SecretStr
    region: Literal["us-west-2"] = _AGENTCORE_REGION
    qualifier: str = Field(default="DEFAULT", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

    @field_validator("runtime_arn")
    @classmethod
    def validate_runtime_arn(cls, value: SecretStr) -> SecretStr:
        runtime_arn = value.get_secret_value()
        parts = runtime_arn.split(":", 5)
        if (
            len(parts) != 6
            or parts[0] != "arn"
            or parts[1] != "aws"
            or parts[2] != _AGENTCORE_SERVICE
            or parts[3] != _AGENTCORE_REGION
            or len(parts[4]) != 12
            or not parts[4].isdigit()
            or not parts[5].startswith("runtime/")
            or len(parts[5]) == len("runtime/")
        ):
            raise ValueError("AgentCore Runtime identifier is invalid")
        return value

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> AgentCoreMCPSettings:
        source = os.environ if environ is None else environ
        runtime_arn = source.get("AGENTCORE_RUNTIME_ARN", "").strip()
        if not runtime_arn:
            raise AgentCoreMCPConfigurationError("AGENTCORE_RUNTIME_ARN is required.")
        try:
            return cls(
                runtime_arn=SecretStr(runtime_arn),
                region=source.get("AGENTCORE_REGION", _AGENTCORE_REGION).strip(),
                qualifier=source.get("AGENTCORE_QUALIFIER", "DEFAULT").strip(),
            )
        except (TypeError, ValidationError, ValueError):
            raise AgentCoreMCPConfigurationError(
                "AgentCore Remote MCP configuration is invalid."
            ) from None


def _build_invocation_url(settings: AgentCoreMCPSettings) -> str:
    encoded_arn = quote(settings.runtime_arn.get_secret_value(), safe="")
    encoded_qualifier = quote(settings.qualifier, safe="")
    return (
        f"https://bedrock-agentcore.{settings.region}.amazonaws.com/"
        f"runtimes/{encoded_arn}/invocations?qualifier={encoded_qualifier}"
    )


class AgentCoreSigV4Auth(httpx.Auth):
    """Sign every request with current credentials from the boto3 provider chain."""

    requires_request_body = True

    def __init__(self, *, credential_session: Any, region: str) -> None:
        if region != _AGENTCORE_REGION:
            raise AgentCoreMCPConfigurationError("AgentCore Remote MCP configuration is invalid.")
        self._credential_session = credential_session
        self._region = region

    def validate_credentials(self) -> None:
        """Fail closed without blocking an async caller's event loop."""

        self._get_frozen_credentials()

    def _get_frozen_credentials(self) -> Any:
        try:
            credentials = self._credential_session.get_credentials()
            if credentials is None:
                raise AgentCoreMCPError("AWS credentials are unavailable or expired.")
            frozen = credentials.get_frozen_credentials()
            expiry_time = getattr(credentials, "_expiry_time", None)
            if isinstance(expiry_time, datetime):
                if expiry_time.tzinfo is None:
                    expiry_time = expiry_time.replace(tzinfo=UTC)
                if expiry_time <= datetime.now(UTC):
                    raise AgentCoreMCPError("AWS credentials are unavailable or expired.")
            if not getattr(frozen, "access_key", None) or not getattr(frozen, "secret_key", None):
                raise AgentCoreMCPError("AWS credentials are unavailable or expired.")
            return frozen
        except AgentCoreMCPError:
            raise
        except Exception:  # noqa: BLE001 - credential backends have no stable exception base.
            raise AgentCoreMCPError("AWS credentials are unavailable or expired.") from None

    def auth_flow(self, request: httpx.Request):
        try:
            credentials = self._get_frozen_credentials()
            self._sign_request(request, credentials)
        except AgentCoreMCPError:
            raise
        except Exception:  # noqa: BLE001 - signer details must not escape this boundary.
            raise AgentCoreMCPError("AWS request signing failed.") from None
        yield request

    async def async_auth_flow(self, request: httpx.Request):
        try:
            await request.aread()
            credentials = await asyncio.to_thread(self._get_frozen_credentials)
            self._sign_request(request, credentials)
        except AgentCoreMCPError:
            raise
        except Exception:  # noqa: BLE001 - signer details must not escape this boundary.
            raise AgentCoreMCPError("AWS request signing failed.") from None
        yield request

    def _sign_request(self, request: httpx.Request, credentials: Any) -> None:
        stale_headers = {
            "authorization",
            "x-amz-date",
            "x-amz-security-token",
        }
        headers = {
            key: value for key, value in request.headers.items() if key.lower() not in stale_headers
        }
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            data=request.content,
            headers=headers,
        )
        SigV4Auth(credentials, _AGENTCORE_SERVICE, self._region).add_auth(aws_request)
        for header in stale_headers:
            if header in request.headers:
                del request.headers[header]
        for key, value in aws_request.headers.items():
            request.headers[key] = value


class _SensitiveEndpointLogFilter(logging.Filter):
    """Redact the Runtime identifier from dependency log records."""

    def __init__(self, settings: AgentCoreMCPSettings) -> None:
        super().__init__()
        runtime_arn = settings.runtime_arn.get_secret_value()
        arn_parts = runtime_arn.split(":", 5)
        resource = arn_parts[5]
        self._tokens = tuple(
            sorted(
                {
                    runtime_arn,
                    quote(runtime_arn, safe=""),
                    arn_parts[4],
                    resource,
                    resource.removeprefix("runtime/"),
                },
                key=len,
                reverse=True,
            )
        )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._redact(value) for key, value in record.args.items()}
        return True

    def _redact(self, value: object) -> object:
        text = value if isinstance(value, str) else str(value)
        redacted = text
        for token in self._tokens:
            redacted = redacted.replace(token, "[REDACTED]")
        return redacted if redacted != text else value


def _install_sensitive_log_filter(
    stack: AsyncExitStack,
    settings: AgentCoreMCPSettings,
) -> None:
    log_filter = _SensitiveEndpointLogFilter(settings)
    for logger_name in _SENSITIVE_TRANSPORT_LOGGERS:
        logger = logging.getLogger(logger_name)
        logger.addFilter(log_filter)
        stack.callback(logger.removeFilter, log_filter)


class AgentCoreMCPToolClient:
    """ToolClient adapter owning one initialized AgentCore MCP session."""

    def __init__(
        self,
        settings: AgentCoreMCPSettings,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        boto3_session: Any | None = None,
        http_client_factory: HttpClientFactory | None = None,
        transport_factory: TransportFactory | None = None,
        client_session_factory: ClientSessionFactory | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise AgentCoreMCPConfigurationError("AgentCore Remote MCP timeout is invalid.")
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._boto3_session = (
            boto3.Session(region_name=settings.region) if boto3_session is None else boto3_session
        )
        self._http_client_factory = http_client_factory or httpx.AsyncClient
        self._transport_factory = transport_factory or streamable_http_client
        self._client_session_factory = client_session_factory or ClientSession
        self._stack: AsyncExitStack | None = None
        self._delegate: MCPToolClient | None = None

    async def __aenter__(self) -> Self:
        if self._stack is not None:
            raise AgentCoreMCPError("AgentCore Remote MCP client is already connected.")

        stack = AsyncExitStack()
        try:
            _install_sensitive_log_filter(stack, self._settings)
            auth = AgentCoreSigV4Auth(
                credential_session=self._boto3_session,
                region=self._settings.region,
            )
            await asyncio.to_thread(auth.validate_credentials)
            http_client = await stack.enter_async_context(
                self._http_client_factory(
                    auth=auth,
                    timeout=httpx.Timeout(self._timeout_seconds),
                )
            )
            streams = await stack.enter_async_context(
                self._transport_factory(
                    _build_invocation_url(self._settings),
                    http_client=http_client,
                )
            )
            read_stream, write_stream, _ = streams
            mcp_session = await stack.enter_async_context(
                self._client_session_factory(read_stream, write_stream)
            )
            await mcp_session.initialize()
        except asyncio.CancelledError:
            await _close_quietly(stack)
            raise
        except AgentCoreMCPError:
            await _close_quietly(stack)
            raise
        except Exception:  # noqa: BLE001 - transport and MCP errors are intentionally masked.
            await _close_quietly(stack)
            raise AgentCoreMCPError("AgentCore Remote MCP initialization failed.") from None

        self._delegate = MCPToolClient(cast(ClientSession, mcp_session))
        self._stack = stack
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        stack = self._stack
        self._delegate = None
        self._stack = None
        if stack is None:
            return False
        try:
            await stack.aclose()
        except Exception:  # noqa: BLE001 - context-manager backends vary by SDK version.
            if exc_type is None:
                raise AgentCoreMCPError("AgentCore Remote MCP session close failed.") from None
        return False

    async def list_tools(self) -> list[ToolDefinition]:
        delegate = self._connected_delegate()
        try:
            return await delegate.list_tools()
        except Exception:  # noqa: BLE001 - remote payloads must not enter exceptions.
            raise AgentCoreMCPError("AgentCore Remote MCP tool listing failed.") from None

    async def call_tool(
        self,
        *,
        name: str,
        arguments: dict[str, object],
    ) -> ToolExecutionResult:
        delegate = self._connected_delegate()
        try:
            return await delegate.call_tool(name=name, arguments=arguments)
        except Exception:  # noqa: BLE001 - remote payloads must not enter exceptions.
            raise AgentCoreMCPError("AgentCore Remote MCP tool call failed.") from None

    def _connected_delegate(self) -> MCPToolClient:
        if self._delegate is None:
            raise AgentCoreMCPError("AgentCore Remote MCP client is not connected.")
        return self._delegate


async def _close_quietly(stack: AsyncExitStack) -> None:
    try:
        await stack.aclose()
    except Exception:  # noqa: BLE001 - preserve the original safe initialization error.
        return


def create_agentcore_mcp_tool_client(
    *,
    settings: AgentCoreMCPSettings | None = None,
    environ: Mapping[str, str] | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> AgentCoreMCPToolClient:
    """Create a fail-closed client; use the result as an async context manager."""

    if settings is not None and environ is not None:
        raise AgentCoreMCPConfigurationError("Pass settings or environment values, not both.")
    resolved_settings = settings or AgentCoreMCPSettings.from_env(environ)
    return AgentCoreMCPToolClient(
        resolved_settings,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "AgentCoreMCPConfigurationError",
    "AgentCoreMCPError",
    "AgentCoreMCPSettings",
    "AgentCoreMCPToolClient",
    "AgentCoreSigV4Auth",
    "create_agentcore_mcp_tool_client",
]
