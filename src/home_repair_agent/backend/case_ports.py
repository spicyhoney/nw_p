from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol

from home_repair_agent.backend.case_models import (
    IdempotencyRecord,
    WorkflowCase,
)


class CaseRepositoryConflictError(Exception):
    """A persistence conflict that the Service Layer should expose as HTTP 409."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CaseWorkflowRepository(Protocol):
    """Persistence contract for the confirmed dispatch workflow."""

    def transaction(self) -> AbstractAsyncContextManager[None]:
        """Keep all reads and writes in one atomic repository transaction."""
        ...

    def lock_idempotency_key(self, key: str) -> None:
        """Serialize commands that use the same idempotency key."""
        ...

    def lock_session(self, session_id: str) -> None:
        """Serialize case creation for the same consumer session."""
        ...

    def get_case(
        self,
        case_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowCase | None: ...

    def list_cases_for_session(self, session_id: str) -> list[WorkflowCase]:
        """Return cases in creation order, oldest first."""
        ...

    def list_cases_for_provider(self, provider_id: str) -> list[WorkflowCase]: ...

    def save_case(self, case: WorkflowCase) -> None: ...

    def get_idempotency(self, key: str) -> IdempotencyRecord | None: ...

    def save_idempotency(self, record: IdempotencyRecord) -> None: ...
