from __future__ import annotations

from typing import Protocol

from home_repair_agent.backend.case_models import (
    IdempotencyRecord,
    WorkflowCase,
)


class CaseWorkflowRepository(Protocol):
    """Persistence contract for the confirmed dispatch workflow."""

    def get_case(self, case_id: str) -> WorkflowCase | None: ...

    def list_cases_for_session(self, session_id: str) -> list[WorkflowCase]:
        """Return cases in creation order, oldest first."""
        ...

    def list_cases_for_provider(self, provider_id: str) -> list[WorkflowCase]: ...

    def save_case(self, case: WorkflowCase) -> None: ...

    def get_idempotency(self, key: str) -> IdempotencyRecord | None: ...

    def save_idempotency(self, record: IdempotencyRecord) -> None: ...
