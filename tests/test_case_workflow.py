from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE
from home_repair_agent.backend.case_models import (
    CaseSubmissionCommand,
    ProviderDecisionCommand,
    SyntheticContact,
)
from home_repair_agent.backend.case_services import (
    CaseWorkflowConflictError,
    CaseWorkflowInputError,
    CaseWorkflowNotFoundError,
    CaseWorkflowService,
)
from home_repair_agent.web.demo_case_repository import DemoCaseWorkflowRepository


class CaseWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 28, 12, tzinfo=TAIPEI_TIMEZONE)
        self.service = CaseWorkflowService(
            DemoCaseWorkflowRepository(),
            now=lambda: self.now,
        )

    def submission(
        self,
        *,
        provider_id: str = "SYN-PROVIDER-001",
        confirmed: bool = True,
        idempotency_key: str = "submit:session-001:provider-001",
        preferred_start: str = "2026-08-01T13:00:00+08:00",
        preferred_end: str = "2026-08-01T17:00:00+08:00",
    ) -> CaseSubmissionCommand:
        return CaseSubmissionCommand(
            session_id="session-001",
            service_id=17,
            service_name="水電修繕",
            form_key="demo_repair_form_v1",
            location_id="DEMO-63000030",
            location_name="臺北市大安區",
            problem_summary="水龍頭漏水｜大約每分鐘滴水。",
            answers={
                "issue_category": "leaking_faucet",
                "notes": "大約每分鐘滴水。",
            },
            preferred_start=preferred_start,
            preferred_end=preferred_end,
            provider_id=provider_id,
            provider_name=(
                "安心修繕 A 組" if provider_id == "SYN-PROVIDER-001" else "城市水電 B 組"
            ),
            availability_id=(
                "SYN-SLOT-001" if provider_id == "SYN-PROVIDER-001" else "SYN-SLOT-002"
            ),
            contact=SyntheticContact(
                name="林小安",
                mobile="0912-345-678",
                address="臺北市大安區 Demo 路 1 號",
            ),
            confirmed=confirmed,
            idempotency_key=idempotency_key,
        )

    async def test_submission_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(CaseWorkflowInputError) as context:
            await self.service.submit_case(self.submission(confirmed=False))

        self.assertEqual("CONFIRMATION_REQUIRED", context.exception.code)

    async def test_submission_rejects_window_expired_after_matching(self) -> None:
        command = self.submission()
        self.now = datetime(2026, 8, 1, 13, 30, tzinfo=TAIPEI_TIMEZONE)

        with self.assertRaises(CaseWorkflowInputError) as context:
            await self.service.submit_case(command)

        self.assertEqual("INVALID_TIME_WINDOW", context.exception.code)
        self.assertIsNone(await self.service.get_consumer_case("session-001"))

    async def test_submission_rechecks_the_complete_time_window_policy(self) -> None:
        valid = self.submission()
        invalid_commands = {
            "timezone": valid.model_copy(
                update={
                    "preferred_start": valid.preferred_start.astimezone(UTC),
                    "preferred_end": valid.preferred_end.astimezone(UTC),
                }
            ),
            "ordering": valid.model_copy(update={"preferred_end": valid.preferred_start}),
            "duration": valid.model_copy(
                update={"preferred_end": valid.preferred_start + timedelta(hours=13)}
            ),
        }

        for label, command in invalid_commands.items():
            with self.subTest(label=label):
                with self.assertRaises(CaseWorkflowInputError) as context:
                    await self.service.submit_case(command)
                self.assertEqual("INVALID_TIME_WINDOW", context.exception.code)

    async def test_submission_is_idempotent_for_the_same_payload(self) -> None:
        first = await self.service.submit_case(self.submission())
        second = await self.service.submit_case(self.submission())

        self.assertEqual(first.case_id, second.case_id)
        self.assertEqual("pending_provider", second.status)

    async def test_reused_idempotency_key_rejects_a_different_payload(self) -> None:
        await self.service.submit_case(self.submission())

        with self.assertRaises(CaseWorkflowConflictError) as context:
            await self.service.submit_case(self.submission(provider_id="SYN-PROVIDER-002"))

        self.assertEqual("IDEMPOTENCY_KEY_REUSED", context.exception.code)

    async def test_pending_case_exposes_only_masked_contact_to_assigned_provider(
        self,
    ) -> None:
        submitted = await self.service.submit_case(self.submission())
        detail = await self.service.get_provider_case(
            provider_id="SYN-PROVIDER-001",
            case_id=submitted.case_id,
        )

        self.assertEqual("masked", detail.contact.access)
        self.assertEqual("林○安", detail.contact.name)
        self.assertEqual("0912***678", detail.contact.mobile)
        self.assertNotIn("Demo 路", detail.contact.address)

        with self.assertRaises(CaseWorkflowNotFoundError):
            await self.service.get_provider_case(
                provider_id="SYN-PROVIDER-002",
                case_id=submitted.case_id,
            )

    async def test_accept_reveals_synthetic_contact_and_creates_order(self) -> None:
        submitted = await self.service.submit_case(self.submission())
        accepted = await self.service.decide_case(
            ProviderDecisionCommand(
                case_id=submitted.case_id,
                provider_id="SYN-PROVIDER-001",
                decision="accept",
                confirmed=True,
                idempotency_key=f"accept:{submitted.case_id}",
            )
        )

        self.assertEqual("accepted", accepted.status)
        self.assertTrue(accepted.order_no.startswith("SYN-ORDER-"))
        self.assertEqual("full", accepted.contact.access)
        self.assertEqual("0912-345-678", accepted.contact.mobile)
        self.assertEqual(
            [
                "case_submitted",
                "provider_accepted",
                "contact_revealed",
            ],
            [event.event_type for event in accepted.audit_events],
        )

        consumer = await self.service.get_consumer_case("session-001")
        self.assertIsNotNone(consumer)
        self.assertEqual("accepted", consumer.status)
        self.assertEqual(accepted.order_no, consumer.order_no)
        self.assertFalse(consumer.can_dispatch_again)

    async def test_provider_decision_requires_confirmation_and_is_idempotent(
        self,
    ) -> None:
        submitted = await self.service.submit_case(self.submission())
        command = ProviderDecisionCommand(
            case_id=submitted.case_id,
            provider_id="SYN-PROVIDER-001",
            decision="accept",
            confirmed=True,
            idempotency_key=f"accept:{submitted.case_id}",
        )

        with self.assertRaises(CaseWorkflowInputError) as context:
            await self.service.decide_case(command.model_copy(update={"confirmed": False}))

        first = await self.service.decide_case(command)
        second = await self.service.decide_case(command)

        self.assertEqual("CONFIRMATION_REQUIRED", context.exception.code)
        self.assertEqual(first.order_no, second.order_no)
        self.assertEqual(3, len(second.audit_events))

    async def test_reject_never_reveals_contact_and_allows_next_provider(self) -> None:
        submitted = await self.service.submit_case(self.submission())
        rejected = await self.service.decide_case(
            ProviderDecisionCommand(
                case_id=submitted.case_id,
                provider_id="SYN-PROVIDER-001",
                decision="reject",
                confirmed=True,
                idempotency_key=f"reject:{submitted.case_id}",
            )
        )

        self.assertEqual("rejected", rejected.status)
        self.assertEqual("unavailable", rejected.contact.access)
        self.assertIsNone(rejected.contact.mobile)

        next_case = await self.service.submit_case(
            self.submission(
                provider_id="SYN-PROVIDER-002",
                idempotency_key="submit:session-001:provider-002",
            )
        )
        self.assertEqual("pending_provider", next_case.status)
        self.assertEqual(
            ["SYN-PROVIDER-001"],
            next_case.rejected_provider_ids,
        )

    async def test_atomic_decision_allows_only_one_terminal_transition(self) -> None:
        submitted = await self.service.submit_case(self.submission())

        async def decide(action: str) -> object:
            return await self.service.decide_case(
                ProviderDecisionCommand(
                    case_id=submitted.case_id,
                    provider_id="SYN-PROVIDER-001",
                    decision=action,
                    confirmed=True,
                    idempotency_key=f"{action}:{submitted.case_id}",
                )
            )

        results = await asyncio.gather(
            decide("accept"),
            decide("reject"),
            return_exceptions=True,
        )

        successes = [result for result in results if not isinstance(result, Exception)]
        conflicts = [result for result in results if isinstance(result, CaseWorkflowConflictError)]
        self.assertEqual(1, len(successes))
        self.assertEqual(1, len(conflicts))


if __name__ == "__main__":
    unittest.main()
