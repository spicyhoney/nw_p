from __future__ import annotations

from home_repair_agent.backend.case_models import (
    IdempotencyRecord,
    WorkflowCase,
)


class DemoCaseWorkflowRepository:
    """Process-local storage used only by the synthetic provider workflow demo."""

    def __init__(self) -> None:
        self._cases: dict[str, WorkflowCase] = {}
        self._idempotency: dict[str, IdempotencyRecord] = {}

    def get_case(self, case_id: str) -> WorkflowCase | None:
        case = self._cases.get(case_id)
        return case.model_copy(deep=True) if case is not None else None

    def list_cases_for_session(self, session_id: str) -> list[WorkflowCase]:
        return [
            case.model_copy(deep=True)
            for case in self._cases.values()
            if case.session_id == session_id
        ]

    def list_cases_for_provider(self, provider_id: str) -> list[WorkflowCase]:
        return [
            case.model_copy(deep=True)
            for case in self._cases.values()
            if case.provider_id == provider_id
        ]

    def save_case(self, case: WorkflowCase) -> None:
        self._cases[case.case_id] = case.model_copy(deep=True)

    def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        record = self._idempotency.get(key)
        return record.model_copy(deep=True) if record is not None else None

    def save_idempotency(self, record: IdempotencyRecord) -> None:
        self._idempotency[record.key] = record.model_copy(deep=True)
