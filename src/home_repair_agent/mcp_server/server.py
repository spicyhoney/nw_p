from __future__ import annotations

import os
from datetime import datetime
from typing import Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.postgres_repository import PostgresReadRepository
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.mcp_server.models import (
    ConsultationFormToolResponse,
    ProviderMatchToolResponse,
    ResolveLocationToolResponse,
    SearchServicesToolResponse,
)

MCPTransport = Literal["stdio", "streamable-http"]
SUPPORTED_TRANSPORTS: tuple[MCPTransport, ...] = ("stdio", "streamable-http")
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp_server(
    read_services: ReadServiceLayer | None = None,
    *,
    database_url: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    """Build the MCP server, optionally injecting services for tests."""

    if read_services is None:
        resolved_database_url = database_url or os.getenv("DATABASE_URL")
        if not resolved_database_url:
            raise RuntimeError("DATABASE_URL is required when no ReadServiceLayer is injected.")
        read_services = ReadServiceLayer(PostgresReadRepository(resolved_database_url))

    mcp = FastMCP(
        name="home-repair-agent",
        instructions=(
            "Use these read-only tools to identify a supported repair service, "
            "resolve a Taiwan county and district, and obtain the consultation "
            "form or synthetic provider candidates. Never invent IDs when a "
            "tool returns ok=false or returns no candidates."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
    _register_read_tools(mcp, read_services)
    return mcp


def _register_read_tools(mcp: FastMCP, read_services: ReadServiceLayer) -> None:
    @mcp.tool(
        name="search_services",
        title="Search supported repair services",
        description=(
            "Search the curated service catalog using a user's problem "
            "description, such as '水龍頭漏水'. An empty query lists services. "
            "This tool never creates or changes data."
        ),
        annotations=READ_ONLY_ANNOTATIONS,
    )
    def search_services(
        query: str | None = None,
        limit: int = 10,
    ) -> SearchServicesToolResponse:
        try:
            result = read_services.search_services(query=query, limit=limit)
        except ServiceLayerError as error:
            return SearchServicesToolResponse.from_service_error(error)
        except Exception as error:
            raise _unavailable_tool_error() from error
        return SearchServicesToolResponse.success(result)

    @mcp.tool(
        name="resolve_location",
        title="Resolve a Taiwan administrative area",
        description=(
            "Resolve a county/city and district/township pair to one curated "
            "location ID. Both names are required. If the result is missing or "
            "ambiguous, do not guess; ask the user to clarify."
        ),
        annotations=READ_ONLY_ANNOTATIONS,
    )
    def resolve_location(
        county_name: str,
        district_name: str,
    ) -> ResolveLocationToolResponse:
        try:
            result = read_services.resolve_location(
                county_name=county_name,
                district_name=district_name,
            )
        except ServiceLayerError as error:
            return ResolveLocationToolResponse.from_service_error(error)
        except Exception as error:
            raise _unavailable_tool_error() from error
        return ResolveLocationToolResponse.success(result)

    @mcp.tool(
        name="get_consultation_form",
        title="Get the consultation form for a service",
        description=(
            "Return the latest unique consultation form, topics, and options "
            "for a service_id previously returned by search_services. Never "
            "invent a service_id or form field."
        ),
        annotations=READ_ONLY_ANNOTATIONS,
    )
    def get_consultation_form(
        service_id: int,
    ) -> ConsultationFormToolResponse:
        try:
            result = read_services.get_consultation_form(service_id=service_id)
        except ServiceLayerError as error:
            return ConsultationFormToolResponse.from_service_error(error)
        except Exception as error:
            raise _unavailable_tool_error() from error
        return ConsultationFormToolResponse.success(result)

    @mcp.tool(
        name="match_service_providers",
        title="Match available synthetic service providers",
        description=(
            "Return ranked synthetic provider candidates for a service_id and "
            "location_id previously returned by read tools. Optional preferred "
            "times must both include a timezone. An empty candidate list means "
            "no eligible provider; never invent one. This tool never reserves "
            "a slot or changes data."
        ),
        annotations=READ_ONLY_ANNOTATIONS,
    )
    def match_service_providers(
        service_id: int,
        location_id: str,
        preferred_start: datetime | None = None,
        preferred_end: datetime | None = None,
        limit: int = 3,
    ) -> ProviderMatchToolResponse:
        try:
            result = read_services.match_service_providers(
                service_id=service_id,
                location_id=location_id,
                preferred_start=preferred_start,
                preferred_end=preferred_end,
                limit=limit,
            )
        except ServiceLayerError as error:
            return ProviderMatchToolResponse.from_service_error(error)
        except Exception as error:
            raise _unavailable_tool_error() from error
        return ProviderMatchToolResponse.success(result)


def _unavailable_tool_error() -> ToolError:
    return ToolError("SERVICE_UNAVAILABLE: The data service is temporarily unavailable.")


def main() -> None:
    transport_value = os.getenv("MCP_TRANSPORT", "stdio")
    if transport_value not in SUPPORTED_TRANSPORTS:
        choices = ", ".join(SUPPORTED_TRANSPORTS)
        raise RuntimeError(f"MCP_TRANSPORT must be one of: {choices}")

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = _read_port(os.getenv("MCP_PORT", "8000"))
    server = create_mcp_server(host=host, port=port)
    server.run(transport=cast(MCPTransport, transport_value))


def _read_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise RuntimeError("MCP_PORT must be an integer.") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("MCP_PORT must be between 1 and 65535.")
    return port
