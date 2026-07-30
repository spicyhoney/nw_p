from __future__ import annotations

import asyncio
import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

try:
    import psycopg
except ImportError:
    psycopg = None

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.backend.case_models import (
    CaseSubmissionCommand,
    ProviderDecisionCommand,
    SyntheticContact,
)
from home_repair_agent.backend.case_services import (
    CaseWorkflowConflictError,
    CaseWorkflowService,
)
from home_repair_agent.backend.postgres_case_repository import (
    PostgresCaseWorkflowRepository,
)
from home_repair_agent.data_cleaning.postgres import apply_migrations

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REFERENCE_TIME = datetime(2026, 7, 28, 12, tzinfo=TAIPEI_TIMEZONE)


class _FailingIdempotencyRepository(PostgresCaseWorkflowRepository):
    async def save_idempotency(self, record) -> None:
        del record
        raise RuntimeError("forced idempotency failure")


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "TEST_DATABASE_URL and psycopg are required for PostgreSQL integration tests.",
)
class PostgresCaseWorkflowRepositoryTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.applied_migrations = apply_migrations(
            database_url=DATABASE_URL,
            project_root=PROJECT_ROOT,
        )

    def setUp(self) -> None:
        self._clear_workflow_tables()

    def tearDown(self) -> None:
        self._clear_workflow_tables()

    def _clear_workflow_tables(self) -> None:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute(
                """
                TRUNCATE TABLE
                    workflow.idempotency_record,
                    workflow.case_audit_event,
                    workflow.service_order,
                    workflow.service_case
                """
            )

    def _service(
        self,
        repository: PostgresCaseWorkflowRepository | None = None,
    ) -> CaseWorkflowService:
        return CaseWorkflowService(
            repository or PostgresCaseWorkflowRepository(DATABASE_URL),
            now=lambda: REFERENCE_TIME,
        )

    def _submission(self) -> CaseSubmissionCommand:
        return CaseSubmissionCommand(
            session_id="postgres-session-001",
            service_id=17,
            service_name="水電修繕",
            form_key="repair_form_v1",
            location_id="ORG-63000030",
            location_name="臺北市大安區",
            problem_summary="水龍頭漏水，需要安排檢查。",
            answers={
                "issue_category": "leaking_faucet",
                "notes": "大約每分鐘滴水。",
            },
            preferred_start="2026-08-01T13:00:00+08:00",
            preferred_end="2026-08-01T17:00:00+08:00",
            provider_id="SYN-PROVIDER-001",
            provider_name="安心修繕 A 組",
            availability_id="SYN-SLOT-001",
            contact=SyntheticContact(
                name="林小安",
                mobile="0912-345-678",
                address="臺北市大安區 Demo 路 1 號",
            ),
            confirmed=True,
            idempotency_key="submit:postgres-session-001",
        )

    def _scalar(self, statement: str) -> object:
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(statement).fetchone()[0]

    async def test_migrations_and_case_state_survive_repository_recreation(self) -> None:
        self.assertEqual(
            ["001_b_plus_schema.sql", "002_case_workflow.sql"],
            self.applied_migrations,
        )
        submitted = await self._service().submit_case(self._submission())

        reloaded = await self._service().get_provider_case(
            provider_id="SYN-PROVIDER-001",
            case_id=submitted.case_id,
        )
        accepted = await self._service().decide_case(
            ProviderDecisionCommand(
                case_id=submitted.case_id,
                provider_id="SYN-PROVIDER-001",
                decision="accept",
                confirmed=True,
                idempotency_key=f"accept:{submitted.case_id}",
            )
        )
        consumer = await self._service().get_consumer_case("postgres-session-001")
        persisted = await self._service().get_provider_case(
            provider_id="SYN-PROVIDER-001",
            case_id=submitted.case_id,
        )

        self.assertEqual("masked", reloaded.contact.access)
        self.assertEqual("accepted", accepted.status)
        self.assertEqual("accepted", consumer.status)
        self.assertEqual(accepted.order_no, consumer.order_no)
        self.assertEqual(
            ["case_submitted", "provider_accepted", "contact_revealed"],
            [event.event_type for event in persisted.audit_events],
        )
        self.assertEqual(1, self._scalar("SELECT count(*) FROM workflow.service_order"))
        self.assertEqual(
            3,
            self._scalar("SELECT count(*) FROM workflow.case_audit_event"),
        )

    async def test_idempotency_survives_repository_recreation(self) -> None:
        first = await self._service().submit_case(self._submission())
        second = await self._service().submit_case(self._submission())

        self.assertEqual(first.case_id, second.case_id)
        self.assertEqual(1, self._scalar("SELECT count(*) FROM workflow.service_case"))
        self.assertEqual(
            1,
            self._scalar("SELECT count(*) FROM workflow.idempotency_record"),
        )

    async def test_async_repository_never_uses_sync_psycopg_connect(self) -> None:
        with patch.object(
            psycopg,
            "connect",
            side_effect=AssertionError("sync psycopg.connect reached async Web path"),
        ):
            submitted = await self._service().submit_case(self._submission())
            reloaded = await self._service().get_provider_case(
                provider_id="SYN-PROVIDER-001",
                case_id=submitted.case_id,
            )

        self.assertEqual("pending_provider", reloaded.status)

    async def test_case_and_audit_roll_back_when_idempotency_write_fails(self) -> None:
        service = self._service(
            _FailingIdempotencyRepository(DATABASE_URL),
        )

        with self.assertRaisesRegex(RuntimeError, "forced idempotency failure"):
            await service.submit_case(self._submission())

        self.assertEqual(0, self._scalar("SELECT count(*) FROM workflow.service_case"))
        self.assertEqual(
            0,
            self._scalar("SELECT count(*) FROM workflow.case_audit_event"),
        )

    async def test_database_rejects_accepted_case_without_order_number(self) -> None:
        submitted = await self._service().submit_case(self._submission())

        with (
            self.assertRaises(psycopg.errors.CheckViolation),
            psycopg.connect(DATABASE_URL) as connection,
        ):
            connection.execute(
                """
                UPDATE workflow.service_case
                SET status = 'accepted'
                WHERE case_id = %s
                """,
                (submitted.case_id,),
            )

        reloaded = await self._service().get_provider_case(
            provider_id="SYN-PROVIDER-001",
            case_id=submitted.case_id,
        )
        self.assertEqual("pending_provider", reloaded.status)

    async def test_separate_workers_allow_only_one_terminal_decision(self) -> None:
        submitted = await self._service().submit_case(self._submission())

        def decide(decision: str) -> object:
            service = self._service()
            return asyncio.run(
                service.decide_case(
                    ProviderDecisionCommand(
                        case_id=submitted.case_id,
                        provider_id="SYN-PROVIDER-001",
                        decision=decision,
                        confirmed=True,
                        idempotency_key=f"{decision}:{submitted.case_id}",
                    )
                )
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(decide, "accept"),
                executor.submit(decide, "reject"),
            ]

        results: list[object] = []
        for future in futures:
            try:
                results.append(future.result())
            except CaseWorkflowConflictError as error:
                results.append(error)

        successes = [
            result for result in results if not isinstance(result, CaseWorkflowConflictError)
        ]
        conflicts = [result for result in results if isinstance(result, CaseWorkflowConflictError)]
        self.assertEqual(1, len(successes))
        self.assertEqual(1, len(conflicts))
        self.assertEqual(
            int(successes[0].status == "accepted"),
            self._scalar("SELECT count(*) FROM workflow.service_order"),
        )


if __name__ == "__main__":
    unittest.main()
