from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from home_repair_agent.backend.case_models import (
    CaseAuditEvent,
    CaseAuditView,
    CaseStatus,
    CaseSubmissionCommand,
    ConsumerCaseView,
    IdempotencyRecord,
    ProviderCaseDetail,
    ProviderCaseSummary,
    ProviderContactView,
    ProviderDecisionCommand,
    WorkflowCase,
    validate_case_time_window,
)
from home_repair_agent.backend.case_ports import CaseWorkflowRepository

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
ACTIVE_CASE_STATUSES = frozenset({"pending_provider", "accepted"})
AUDIT_LABELS = {
    "case_submitted": "消費者已確認派單",
    "provider_accepted": "廠商已接單",
    "provider_rejected": "廠商已拒絕案件",
    "contact_revealed": "接單後已授權揭露 synthetic 聯絡資料",
}


class CaseWorkflowError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or {}


class CaseWorkflowInputError(CaseWorkflowError):
    pass


class CaseWorkflowConflictError(CaseWorkflowError):
    pass


class CaseWorkflowNotFoundError(CaseWorkflowError):
    def __init__(self) -> None:
        super().__init__(
            code="CASE_NOT_FOUND",
            message="找不到這個案件，或目前廠商沒有查看權限。",
        )


class CaseWorkflowService:
    """Confirmed, idempotent and auditable case-dispatch business rules."""

    def __init__(
        self,
        repository: CaseWorkflowRepository,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._now = now
        self._lock = asyncio.Lock()

    async def submit_case(self, command: CaseSubmissionCommand) -> ConsumerCaseView:
        _require_confirmation(command.confirmed, operation="派單")
        key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = _fingerprint(
            "submit_case",
            command.model_dump(
                mode="json",
                exclude={"confirmed", "idempotency_key"},
            ),
        )

        async with self._lock:
            existing = self._idempotent_case(
                key=key,
                operation="submit_case",
                fingerprint=fingerprint,
            )
            if existing is not None:
                return self._consumer_view(existing)

            created_at = self._now()
            _validate_submission_window(command, now=created_at)
            previous_cases = self._repository.list_cases_for_session(command.session_id)
            active = next(
                (case for case in previous_cases if case.status in ACTIVE_CASE_STATUSES),
                None,
            )
            if active is not None:
                raise CaseWorkflowConflictError(
                    code="ACTIVE_CASE_EXISTS",
                    message="這次諮詢已有等待中或已接單的案件，不能重複派單。",
                )
            if any(
                case.provider_id == command.provider_id and case.status == "rejected"
                for case in previous_cases
            ):
                raise CaseWorkflowConflictError(
                    code="PROVIDER_ALREADY_REJECTED",
                    message="這位廠商已拒絕此案件，不能再次派送同一份需求。",
                )

            case_id = f"SYN-CASE-{uuid4().hex[:12].upper()}"
            case = WorkflowCase(
                case_id=case_id,
                session_id=command.session_id,
                service_id=command.service_id,
                service_name=command.service_name,
                form_key=command.form_key,
                location_id=command.location_id,
                location_name=command.location_name,
                problem_summary=command.problem_summary,
                answers=command.answers,
                preferred_start=command.preferred_start,
                preferred_end=command.preferred_end,
                provider_id=command.provider_id,
                provider_name=command.provider_name,
                availability_id=command.availability_id,
                contact=command.contact,
                status="pending_provider",
                created_at=created_at,
                updated_at=created_at,
                version=1,
                audit_events=[
                    _audit_event(
                        event_type="case_submitted",
                        actor_type="consumer",
                        actor_id=command.session_id,
                        created_at=created_at,
                    )
                ],
            )
            self._repository.save_case(case)
            self._repository.save_idempotency(
                IdempotencyRecord(
                    key=key,
                    operation="submit_case",
                    fingerprint=fingerprint,
                    case_id=case.case_id,
                )
            )
            return self._consumer_view(case)

    async def get_consumer_case(self, session_id: str) -> ConsumerCaseView | None:
        async with self._lock:
            cases = self._repository.list_cases_for_session(session_id)
            if not cases:
                return None
            return self._consumer_view(_latest_case(cases), all_cases=cases)

    async def has_session_cases(self, session_id: str) -> bool:
        async with self._lock:
            return bool(self._repository.list_cases_for_session(session_id))

    async def list_provider_cases(
        self,
        *,
        provider_id: str,
        status: CaseStatus | None = None,
    ) -> list[ProviderCaseSummary]:
        async with self._lock:
            cases = self._repository.list_cases_for_provider(provider_id)
            if status is not None:
                cases = [case for case in cases if case.status == status]
            cases.sort(key=lambda case: (case.updated_at, case.case_id), reverse=True)
            return [self._provider_summary(case) for case in cases]

    async def get_provider_case(
        self,
        *,
        provider_id: str,
        case_id: str,
    ) -> ProviderCaseDetail:
        async with self._lock:
            case = self._authorized_case(provider_id=provider_id, case_id=case_id)
            return self._provider_detail(case)

    async def decide_case(
        self,
        command: ProviderDecisionCommand,
    ) -> ProviderCaseDetail:
        operation = f"provider_{command.decision}"
        _require_confirmation(command.confirmed, operation="案件狀態變更")
        key = _validate_idempotency_key(command.idempotency_key)
        fingerprint = _fingerprint(
            operation,
            command.model_dump(
                mode="json",
                exclude={"confirmed", "idempotency_key"},
            ),
        )

        async with self._lock:
            existing = self._idempotent_case(
                key=key,
                operation=operation,
                fingerprint=fingerprint,
            )
            if existing is not None:
                if existing.provider_id != command.provider_id:
                    raise CaseWorkflowNotFoundError()
                return self._provider_detail(existing)

            case = self._authorized_case(
                provider_id=command.provider_id,
                case_id=command.case_id,
            )
            if case.status != "pending_provider":
                raise CaseWorkflowConflictError(
                    code="INVALID_CASE_TRANSITION",
                    message="案件已不在待接單狀態，不能重複變更。",
                )

            changed_at = self._now()
            events = list(case.audit_events)
            if command.decision == "accept":
                case.status = "accepted"
                case.order_no = f"SYN-ORDER-{uuid4().hex[:10].upper()}"
                events.extend(
                    [
                        _audit_event(
                            event_type="provider_accepted",
                            actor_type="provider",
                            actor_id=command.provider_id,
                            created_at=changed_at,
                        ),
                        _audit_event(
                            event_type="contact_revealed",
                            actor_type="system",
                            actor_id="case-workflow",
                            created_at=changed_at,
                        ),
                    ]
                )
            else:
                case.status = "rejected"
                events.append(
                    _audit_event(
                        event_type="provider_rejected",
                        actor_type="provider",
                        actor_id=command.provider_id,
                        created_at=changed_at,
                    )
                )

            case.audit_events = events
            case.updated_at = changed_at
            case.version += 1
            self._repository.save_case(case)
            self._repository.save_idempotency(
                IdempotencyRecord(
                    key=key,
                    operation=operation,
                    fingerprint=fingerprint,
                    case_id=case.case_id,
                )
            )
            return self._provider_detail(case)

    def _authorized_case(self, *, provider_id: str, case_id: str) -> WorkflowCase:
        case = self._repository.get_case(case_id)
        if case is None or case.provider_id != provider_id:
            raise CaseWorkflowNotFoundError()
        return case

    def _idempotent_case(
        self,
        *,
        key: str,
        operation: str,
        fingerprint: str,
    ) -> WorkflowCase | None:
        record = self._repository.get_idempotency(key)
        if record is None:
            return None
        if record.operation != operation or record.fingerprint != fingerprint:
            raise CaseWorkflowConflictError(
                code="IDEMPOTENCY_KEY_REUSED",
                message="同一個冪等鍵已用於不同操作，已拒絕寫入。",
            )
        case = self._repository.get_case(record.case_id)
        if case is None:
            raise CaseWorkflowConflictError(
                code="IDEMPOTENCY_RESULT_MISSING",
                message="找不到先前寫入結果，已停止重試。",
            )
        return case

    def _consumer_view(
        self,
        case: WorkflowCase,
        *,
        all_cases: list[WorkflowCase] | None = None,
    ) -> ConsumerCaseView:
        cases = (
            all_cases
            if all_cases is not None
            else self._repository.list_cases_for_session(case.session_id)
        )
        rejected_provider_ids = sorted(
            {item.provider_id for item in cases if item.status == "rejected"}
        )
        return ConsumerCaseView(
            case_id=case.case_id,
            provider_id=case.provider_id,
            provider_name=case.provider_name,
            status=case.status,
            order_no=case.order_no,
            preferred_start=case.preferred_start,
            preferred_end=case.preferred_end,
            rejected_provider_ids=rejected_provider_ids,
            can_dispatch_again=case.status == "rejected",
        )

    def _provider_summary(self, case: WorkflowCase) -> ProviderCaseSummary:
        return ProviderCaseSummary(
            case_id=case.case_id,
            status=case.status,
            service_name=case.service_name,
            location_name=case.location_name,
            problem_summary=case.problem_summary,
            preferred_start=case.preferred_start,
            preferred_end=case.preferred_end,
            contact_name_masked=_mask_name(case.contact.name),
            order_no=case.order_no,
            created_at=case.created_at,
            updated_at=case.updated_at,
        )

    def _provider_detail(self, case: WorkflowCase) -> ProviderCaseDetail:
        return ProviderCaseDetail(
            case_id=case.case_id,
            status=case.status,
            service_name=case.service_name,
            location_name=case.location_name,
            problem_summary=case.problem_summary,
            answers=case.answers,
            preferred_start=case.preferred_start,
            preferred_end=case.preferred_end,
            contact=_contact_view(case),
            order_no=case.order_no,
            created_at=case.created_at,
            updated_at=case.updated_at,
            audit_events=[
                CaseAuditView(
                    event_type=event.event_type,
                    label=AUDIT_LABELS[event.event_type],
                    created_at=event.created_at,
                )
                for event in case.audit_events
            ],
        )


def _require_confirmation(value: bool, *, operation: str) -> None:
    if value is not True:
        raise CaseWorkflowInputError(
            code="CONFIRMATION_REQUIRED",
            message=f"{operation}需要使用者明確確認。",
            fields={"confirmed": "請先確認本次操作。"},
        )


def _validate_submission_window(
    command: CaseSubmissionCommand,
    *,
    now: datetime,
) -> None:
    try:
        validate_case_time_window(
            preferred_start=command.preferred_start,
            preferred_end=command.preferred_end,
        )
    except ValueError as error:
        raise CaseWorkflowInputError(
            code="INVALID_TIME_WINDOW",
            message=str(error),
            fields={"preferred_time": "請重新選擇有效的服務時段。"},
        ) from error
    if now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeError("CaseWorkflowService now() must return an aware datetime")
    if command.preferred_start <= now:
        raise CaseWorkflowInputError(
            code="INVALID_TIME_WINDOW",
            message="希望服務時間已過期，請重新選擇未來的服務時段。",
            fields={"preferred_time": "請重新選擇未來的服務時段。"},
        )


def _validate_idempotency_key(value: str) -> str:
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise CaseWorkflowInputError(
            code="INVALID_IDEMPOTENCY_KEY",
            message="冪等鍵格式不合法。",
            fields={
                "idempotency_key": (
                    "需為 8 至 128 字元，且只能包含英數、句點、底線、冒號與連字號。"
                )
            },
        )
    return value


def _fingerprint(operation: str, payload: dict[str, object]) -> str:
    serialized = json.dumps(
        {"operation": operation, "payload": payload},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _audit_event(
    *,
    event_type: str,
    actor_type: str,
    actor_id: str,
    created_at: datetime,
) -> CaseAuditEvent:
    return CaseAuditEvent(
        event_id=f"AUD-{uuid4().hex[:12].upper()}",
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        message=AUDIT_LABELS[event_type],
        created_at=created_at,
    )


def _latest_case(cases: list[WorkflowCase]) -> WorkflowCase:
    return cases[-1]


def _contact_view(case: WorkflowCase) -> ProviderContactView:
    if case.status == "accepted":
        return ProviderContactView(
            access="full",
            name=case.contact.name,
            mobile=case.contact.mobile,
            address=case.contact.address,
        )
    if case.status == "pending_provider":
        return ProviderContactView(
            access="masked",
            name=_mask_name(case.contact.name),
            mobile=_mask_mobile(case.contact.mobile),
            address=f"{case.location_name}（詳細地址接單後顯示）",
        )
    return ProviderContactView(access="unavailable")


def _mask_name(value: str) -> str:
    if len(value) <= 1:
        return "○"
    if len(value) == 2:
        return f"{value[0]}○"
    return f"{value[0]}○{value[-1]}"


def _mask_mobile(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 7:
        return "***"
    return f"{digits[:4]}***{digits[-3:]}"
