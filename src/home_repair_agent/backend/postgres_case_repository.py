from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from home_repair_agent.backend.case_models import (
    CaseAuditEvent,
    IdempotencyRecord,
    SyntheticContact,
    WorkflowCase,
)
from home_repair_agent.backend.case_ports import CaseRepositoryConflictError

CASE_COLUMNS = """
    case_id,
    session_id,
    service_id,
    service_name,
    form_key,
    location_id,
    location_name,
    problem_summary,
    answers,
    preferred_start,
    preferred_end,
    provider_id,
    provider_name,
    availability_id,
    contact_name,
    contact_mobile,
    contact_address,
    status,
    order_no,
    source_type,
    created_at,
    updated_at,
    version
"""

SELECT_CASE_SQL = f"""
SELECT {CASE_COLUMNS}
FROM workflow.service_case
WHERE case_id = %(case_id)s
"""

LIST_SESSION_CASES_SQL = f"""
SELECT {CASE_COLUMNS}
FROM workflow.service_case
WHERE session_id = %(session_id)s
ORDER BY created_at, case_id
"""

LIST_PROVIDER_CASES_SQL = f"""
SELECT {CASE_COLUMNS}
FROM workflow.service_case
WHERE provider_id = %(provider_id)s
ORDER BY created_at, case_id
"""

INSERT_CASE_SQL = """
INSERT INTO workflow.service_case (
    case_id,
    session_id,
    service_id,
    service_name,
    form_key,
    location_id,
    location_name,
    problem_summary,
    answers,
    preferred_start,
    preferred_end,
    provider_id,
    provider_name,
    availability_id,
    contact_name,
    contact_mobile,
    contact_address,
    status,
    order_no,
    source_type,
    created_at,
    updated_at,
    version
) VALUES (
    %(case_id)s,
    %(session_id)s,
    %(service_id)s,
    %(service_name)s,
    %(form_key)s,
    %(location_id)s,
    %(location_name)s,
    %(problem_summary)s,
    %(answers)s::jsonb,
    %(preferred_start)s,
    %(preferred_end)s,
    %(provider_id)s,
    %(provider_name)s,
    %(availability_id)s,
    %(contact_name)s,
    %(contact_mobile)s,
    %(contact_address)s,
    %(status)s,
    %(order_no)s,
    %(source_type)s,
    %(created_at)s,
    %(updated_at)s,
    %(version)s
)
RETURNING case_id
"""

UPDATE_CASE_SQL = """
UPDATE workflow.service_case
SET
    status = %(status)s,
    order_no = %(order_no)s,
    updated_at = %(updated_at)s,
    version = %(version)s
WHERE
    case_id = %(case_id)s
    AND version = %(expected_version)s
RETURNING case_id
"""

SELECT_AUDIT_SQL = """
SELECT
    event_id,
    event_type,
    actor_type,
    actor_id,
    message,
    created_at
FROM workflow.case_audit_event
WHERE case_id = %(case_id)s
ORDER BY sequence_no, event_id
"""

INSERT_AUDIT_SQL = """
INSERT INTO workflow.case_audit_event (
    event_id,
    case_id,
    sequence_no,
    event_type,
    actor_type,
    actor_id,
    message,
    created_at
) VALUES (
    %(event_id)s,
    %(case_id)s,
    %(sequence_no)s,
    %(event_type)s,
    %(actor_type)s,
    %(actor_id)s,
    %(message)s,
    %(created_at)s
)
ON CONFLICT (event_id) DO NOTHING
"""

INSERT_ORDER_SQL = """
INSERT INTO workflow.service_order (
    order_no,
    case_id,
    provider_id,
    service_id,
    scheduled_start,
    scheduled_end,
    order_status,
    source_type,
    created_at
) VALUES (
    %(order_no)s,
    %(case_id)s,
    %(provider_id)s,
    %(service_id)s,
    %(scheduled_start)s,
    %(scheduled_end)s,
    'confirmed',
    %(source_type)s,
    %(created_at)s
)
"""

SELECT_IDEMPOTENCY_SQL = """
SELECT
    idempotency_key,
    operation,
    fingerprint,
    case_id
FROM workflow.idempotency_record
WHERE idempotency_key = %(key)s
"""

INSERT_IDEMPOTENCY_SQL = """
INSERT INTO workflow.idempotency_record (
    idempotency_key,
    operation,
    fingerprint,
    case_id
) VALUES (
    %(key)s,
    %(operation)s,
    %(fingerprint)s,
    %(case_id)s
)
"""

ADVISORY_LOCK_SQL = """
SELECT pg_advisory_xact_lock(hashtextextended(%(lock_key)s, 0))
"""


class PostgresCaseWorkflowRepository:
    """Transactional PostgreSQL persistence for confirmed case workflows."""

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("database_url must be a non-empty string")
        self._database_url = database_url
        self._active_connection: ContextVar[Any | None] = ContextVar(
            f"case_workflow_connection_{id(self)}",
            default=None,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        existing = self._active_connection.get()
        if existing is not None:
            yield
            return

        psycopg, dict_row = _load_psycopg()
        connection = await psycopg.AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        )
        token = self._active_connection.set(connection)
        try:
            async with connection.transaction():
                yield
        finally:
            self._active_connection.reset(token)
            await connection.close()

    async def lock_idempotency_key(self, key: str) -> None:
        await self._lock(f"idempotency:{key}")

    async def lock_session(self, session_id: str) -> None:
        await self._lock(f"session:{session_id}")

    async def get_case(
        self,
        case_id: str,
        *,
        for_update: bool = False,
    ) -> WorkflowCase | None:
        if for_update and self._active_connection.get() is None:
            raise RuntimeError("for_update reads require an active transaction")
        statement = SELECT_CASE_SQL
        if for_update:
            statement += "\nFOR UPDATE"
        async with self._connection() as connection:
            cursor = await connection.execute(statement, {"case_id": case_id})
            row = await cursor.fetchone()
            return await self._assemble_case(connection, row) if row is not None else None

    async def list_cases_for_session(self, session_id: str) -> list[WorkflowCase]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                LIST_SESSION_CASES_SQL,
                {"session_id": session_id},
            )
            rows = await cursor.fetchall()
            return [await self._assemble_case(connection, row) for row in rows]

    async def list_cases_for_provider(self, provider_id: str) -> list[WorkflowCase]:
        async with self._connection() as connection:
            cursor = await connection.execute(
                LIST_PROVIDER_CASES_SQL,
                {"provider_id": provider_id},
            )
            rows = await cursor.fetchall()
            return [await self._assemble_case(connection, row) for row in rows]

    async def save_case(self, case: WorkflowCase) -> None:
        connection = self._require_transaction()
        parameters = _case_parameters(case)
        psycopg, _dict_row = _load_psycopg()
        try:
            if case.version == 1:
                cursor = await connection.execute(INSERT_CASE_SQL, parameters)
            else:
                cursor = await connection.execute(
                    UPDATE_CASE_SQL,
                    {
                        **parameters,
                        "expected_version": case.version - 1,
                    },
                )
            saved = await cursor.fetchone()
            if saved is None:
                raise CaseRepositoryConflictError(
                    code="CONCURRENT_CASE_UPDATE",
                    message="案件已被其他操作更新，請重新讀取最新狀態。",
                )

            if case.order_no is not None:
                await connection.execute(
                    INSERT_ORDER_SQL,
                    {
                        "order_no": case.order_no,
                        "case_id": case.case_id,
                        "provider_id": case.provider_id,
                        "service_id": case.service_id,
                        "scheduled_start": case.preferred_start,
                        "scheduled_end": case.preferred_end,
                        "source_type": case.source_type,
                        "created_at": case.updated_at,
                    },
                )

            for sequence_no, event in enumerate(case.audit_events, start=1):
                await connection.execute(
                    INSERT_AUDIT_SQL,
                    {
                        **event.model_dump(),
                        "case_id": case.case_id,
                        "sequence_no": sequence_no,
                    },
                )
        except psycopg.errors.UniqueViolation as error:
            raise _write_conflict(error) from error

    async def get_idempotency(self, key: str) -> IdempotencyRecord | None:
        async with self._connection() as connection:
            cursor = await connection.execute(
                SELECT_IDEMPOTENCY_SQL,
                {"key": key},
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["idempotency_key"],
            operation=row["operation"],
            fingerprint=row["fingerprint"],
            case_id=row["case_id"],
        )

    async def save_idempotency(self, record: IdempotencyRecord) -> None:
        connection = self._require_transaction()
        psycopg, _dict_row = _load_psycopg()
        try:
            await connection.execute(
                INSERT_IDEMPOTENCY_SQL,
                record.model_dump(),
            )
        except psycopg.errors.UniqueViolation as error:
            raise _write_conflict(error) from error

    async def _lock(self, lock_key: str) -> None:
        connection = self._require_transaction()
        await connection.execute(ADVISORY_LOCK_SQL, {"lock_key": lock_key})

    def _require_transaction(self) -> Any:
        connection = self._active_connection.get()
        if connection is None:
            raise RuntimeError("case workflow writes require an active transaction")
        return connection

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        existing = self._active_connection.get()
        if existing is not None:
            yield existing
            return

        psycopg, dict_row = _load_psycopg()
        connection = await psycopg.AsyncConnection.connect(
            self._database_url,
            row_factory=dict_row,
        )
        try:
            yield connection
        finally:
            await connection.close()

    async def _assemble_case(
        self,
        connection: Any,
        row: dict[str, Any],
    ) -> WorkflowCase:
        cursor = await connection.execute(
            SELECT_AUDIT_SQL,
            {"case_id": row["case_id"]},
        )
        audit_rows = await cursor.fetchall()
        return WorkflowCase(
            case_id=row["case_id"],
            session_id=row["session_id"],
            service_id=row["service_id"],
            service_name=row["service_name"],
            form_key=row["form_key"],
            location_id=row["location_id"],
            location_name=row["location_name"],
            problem_summary=row["problem_summary"],
            answers=row["answers"],
            preferred_start=row["preferred_start"],
            preferred_end=row["preferred_end"],
            provider_id=row["provider_id"],
            provider_name=row["provider_name"],
            availability_id=row["availability_id"],
            contact=SyntheticContact(
                name=row["contact_name"],
                mobile=row["contact_mobile"],
                address=row["contact_address"],
                source_type=row["source_type"],
            ),
            status=row["status"],
            order_no=row["order_no"],
            source_type=row["source_type"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=row["version"],
            audit_events=[CaseAuditEvent.model_validate(event) for event in audit_rows],
        )


def _case_parameters(case: WorkflowCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "service_id": case.service_id,
        "service_name": case.service_name,
        "form_key": case.form_key,
        "location_id": case.location_id,
        "location_name": case.location_name,
        "problem_summary": case.problem_summary,
        "answers": json.dumps(case.answers, ensure_ascii=False),
        "preferred_start": case.preferred_start,
        "preferred_end": case.preferred_end,
        "provider_id": case.provider_id,
        "provider_name": case.provider_name,
        "availability_id": case.availability_id,
        "contact_name": case.contact.name,
        "contact_mobile": case.contact.mobile,
        "contact_address": case.contact.address,
        "status": case.status,
        "order_no": case.order_no,
        "source_type": case.source_type,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "version": case.version,
    }


def _write_conflict(error: Exception) -> CaseRepositoryConflictError:
    constraint_name = getattr(getattr(error, "diag", None), "constraint_name", None)
    if constraint_name == "workflow_one_active_case_per_session_idx":
        return CaseRepositoryConflictError(
            code="ACTIVE_CASE_EXISTS",
            message="此需求已有等待回覆或已接單案件，請先確認目前案件。",
        )
    return CaseRepositoryConflictError(
        code="CASE_WRITE_CONFLICT",
        message="案件資料與另一個操作衝突，請重新讀取後再試。",
    )


def _load_psycopg() -> tuple[Any, Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL case persistence requires psycopg. "
            "Install the data dependencies with: pip install -e .[data]"
        ) from error
    return psycopg, dict_row
