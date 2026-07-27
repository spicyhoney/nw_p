from __future__ import annotations

import unittest
from datetime import datetime

from home_repair_agent.agent.demo import (
    TAIPEI_TIMEZONE,
    DemoReadRepository,
    _resolve_model_client,
    run_demo,
)
from home_repair_agent.agent.huggingface_model import (
    HuggingFaceConfigurationError,
)
from home_repair_agent.agent.mock_model import RuleBasedRepairMockModel
from home_repair_agent.backend.services import ReadServiceLayer


class DemoRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.services = ReadServiceLayer(DemoReadRepository())

    def test_demo_data_is_filtered_instead_of_returned_for_every_input(self) -> None:
        supported = self.services.search_services("水龍頭漏水")
        unsupported = self.services.search_services("幫我遛狗")

        self.assertEqual(1, supported.count)
        self.assertEqual(0, unsupported.count)

    def test_demo_location_supports_taipei_daan(self) -> None:
        location = self.services.resolve_location(
            county_name="台北市",
            district_name="大安區",
        )

        self.assertEqual("臺北市大安區", location.full_name)

    def test_demo_matching_returns_labeled_synthetic_candidates(self) -> None:
        result = self.services.match_service_providers(
            service_id=17,
            location_id="DEMO-63000030",
        )

        self.assertEqual(2, result.count)
        self.assertEqual("synthetic", result.data_source)
        self.assertTrue(
            all(candidate.source_type == "synthetic" for candidate in result.candidates)
        )

    def test_demo_slots_move_to_the_next_future_saturday(self) -> None:
        reference_time = datetime(2026, 8, 1, 18, 30, tzinfo=TAIPEI_TIMEZONE)
        repository = DemoReadRepository(reference_time=reference_time)

        slots = repository.list_available_provider_slots(
            service_id=17,
            location_id="DEMO-63000030",
            preferred_start=None,
            preferred_end=None,
            candidate_limit=3,
        )

        self.assertEqual(2, len(slots))
        self.assertEqual(datetime(2026, 8, 8, 13, tzinfo=TAIPEI_TIMEZONE), slots[0].starts_at)
        self.assertTrue(all(slot.starts_at > reference_time for slot in slots))

    def test_demo_reference_time_requires_timezone(self) -> None:
        naive_reference = datetime(2026, 8, 1, 12)  # noqa: DTZ001

        with self.assertRaisesRegex(ValueError, "reference_time must include a timezone"):
            DemoReadRepository(reference_time=naive_reference)


class ScriptedDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_demo_runs_the_real_four_tool_loop(self) -> None:
        output: list[str] = []

        conversation = await run_demo(
            scripted=True,
            output_func=output.append,
        )

        transcript = "\n".join(output)
        self.assertIn("[MCP] search_services", transcript)
        self.assertIn("[MCP] resolve_location", transcript)
        self.assertIn("[MCP] get_consultation_form", transcript)
        self.assertIn("[MCP] match_service_providers", transcript)
        self.assertIn("synthetic 師傅候選", transcript)
        self.assertIn("安心修繕 A 組", transcript)
        self.assertIn("沒有保留時段或建立案件", transcript)
        self.assertGreaterEqual(len(conversation.messages), 3)


class DemoModelRoutingTests(unittest.TestCase):
    def test_mock_is_the_explicit_default_without_credentials(self) -> None:
        model, label = _resolve_model_client("mock", environ={})

        self.assertIsInstance(model, RuleBasedRepairMockModel)
        self.assertIn("Mock Model", label)

    def test_huggingface_mode_does_not_silently_fall_back(self) -> None:
        with self.assertRaisesRegex(
            HuggingFaceConfigurationError,
            "HF_TOKEN is required",
        ):
            _resolve_model_client("huggingface", environ={})


if __name__ == "__main__":
    unittest.main()
