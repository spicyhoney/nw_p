from __future__ import annotations

from typing import Protocol

from home_repair_agent.backend.models import (
    ConsultationForm,
    ResolvedLocation,
    ServiceSummary,
)


class ReadRepository(Protocol):
    """Data-access contract used by the read-only Service Layer."""

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        ...

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        ...

    def list_consultation_forms(self, *, service_id: int) -> list[ConsultationForm]:
        ...
