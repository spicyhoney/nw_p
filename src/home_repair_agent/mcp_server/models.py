from __future__ import annotations

from typing import Any, Generic, Self, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

from home_repair_agent.backend.errors import ServiceLayerError
from home_repair_agent.backend.models import (
    ConsultationForm,
    ResolvedLocation,
    ServiceSearchResult,
)

DataT = TypeVar("DataT")


class MCPModel(BaseModel):
    """Strict JSON model used at the MCP adapter boundary."""

    model_config = ConfigDict(extra="forbid")


class ToolErrorPayload(MCPModel):
    code: str
    message: str
    details: dict[str, Any]


class ToolResponse(MCPModel, Generic[DataT]):
    """Recoverable domain result returned as structured MCP content."""

    ok: bool
    data: DataT | None = None
    error: ToolErrorPayload | None = None

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("successful responses require data and no error")
        if not self.ok and (self.data is not None or self.error is None):
            raise ValueError("failed responses require an error and no data")
        return self

    @classmethod
    def success(cls, data: DataT) -> Self:
        return cls(ok=True, data=data)

    @classmethod
    def from_service_error(cls, error: ServiceLayerError) -> Self:
        return cls(
            ok=False,
            error=ToolErrorPayload(
                code=error.code,
                message=error.message,
                details=error.details,
            ),
        )


class SearchServicesToolResponse(ToolResponse[ServiceSearchResult]):
    pass


class ResolveLocationToolResponse(ToolResponse[ResolvedLocation]):
    pass


class ConsultationFormToolResponse(ToolResponse[ConsultationForm]):
    pass
