from __future__ import annotations

import unittest
from enum import Enum

from pydantic import ValidationError

from home_repair_agent.backend.repair_conversation import (
    RepairBranch,
    RepairRoutingResult,
    RoutingConfidence,
    route_repair_branch,
)


class RepairConversationRoutingTests(unittest.TestCase):
    def test_routes_all_five_closed_world_branches(self) -> None:
        cases = [
            (
                "廚房的水龍頭漏水",
                RepairBranch.FAUCET_LEAK,
                RoutingConfidence.HIGH,
            ),
            (
                "馬桶沖水後一直有異音",
                RepairBranch.TOILET_ISSUE,
                RoutingConfidence.HIGH,
            ),
            (
                "牆內水管好像破裂了",
                RepairBranch.PIPE_ISSUE,
                RoutingConfidence.HIGH,
            ),
            (
                "房間插座沒有反應",
                RepairBranch.ELECTRICAL_ISSUE,
                RoutingConfidence.HIGH,
            ),
            (
                "家裡有其他水電狀況，但我還說不清楚",
                RepairBranch.OTHER,
                RoutingConfidence.LOW,
            ),
        ]

        for message, expected_branch, expected_confidence in cases:
            with self.subTest(message=message):
                result = route_repair_branch(message)

                self.assertEqual(expected_branch, result.branch)
                self.assertEqual(expected_confidence, result.confidence)
                self.assertFalse(result.unsupported)
                self.assertFalse(result.multiple_requests)
                self.assertEqual([], result.alternatives)
                self.assertIsNotNone(result.clarification_question)
                self.assertIn("確認", result.clarification_question or "")

    def test_medium_confidence_uses_a_declared_alias(self) -> None:
        result = route_repair_branch("洗手間的便器有問題")

        self.assertEqual(RepairBranch.TOILET_ISSUE, result.branch)
        self.assertEqual(RoutingConfidence.MEDIUM, result.confidence)

    def test_multiple_requests_require_selecting_one_branch(self) -> None:
        result = route_repair_branch("水龍頭漏水，另外插座還會冒火花")

        self.assertIsNone(result.branch)
        self.assertEqual(RoutingConfidence.MEDIUM, result.confidence)
        self.assertEqual(
            [RepairBranch.FAUCET_LEAK, RepairBranch.ELECTRICAL_ISSUE],
            result.alternatives,
        )
        self.assertTrue(result.multiple_requests)
        self.assertFalse(result.unsupported)
        self.assertIn("請先選擇一項", result.clarification_question or "")
        self.assertIsNotNone(result.safety_message)
        self.assertNotIn("已派單", result.safety_message or "")

    def test_unknown_water_electrical_request_stays_in_other_and_asks(self) -> None:
        result = route_repair_branch("住家有水電問題，但不知道是哪個設備")

        self.assertEqual(RepairBranch.OTHER, result.branch)
        self.assertEqual(RoutingConfidence.LOW, result.confidence)
        self.assertFalse(result.unsupported)
        self.assertEqual([], result.alternatives)
        self.assertIn("完整描述", result.clarification_question or "")

    def test_clearly_unsupported_request_is_not_forced_into_a_branch(self) -> None:
        result = route_repair_branch("我想預約居家清潔和餐點外送")

        self.assertIsNone(result.branch)
        self.assertEqual(RoutingConfidence.LOW, result.confidence)
        self.assertTrue(result.unsupported)
        self.assertFalse(result.multiple_requests)
        self.assertEqual([], result.alternatives)
        self.assertIn("只支援居家水電修繕", result.clarification_question or "")

    def test_major_water_leak_returns_a_conservative_safety_message(self) -> None:
        result = route_repair_branch("水管破裂，現在大量漏水")

        self.assertEqual(RepairBranch.PIPE_ISSUE, result.branch)
        self.assertIsNotNone(result.safety_message)
        self.assertIn("不要冒險", result.safety_message or "")
        self.assertNotIn("診斷", result.safety_message or "")
        self.assertNotIn("保證", result.safety_message or "")

    def test_enum_values_and_result_contract_are_allowlisted(self) -> None:
        self.assertTrue(issubclass(RepairBranch, str))
        self.assertTrue(issubclass(RepairBranch, Enum))
        self.assertEqual(
            {
                "faucet_leak",
                "toilet_issue",
                "pipe_issue",
                "electrical_issue",
                "other",
            },
            {branch.value for branch in RepairBranch},
        )
        self.assertEqual(
            {"high", "medium", "low"},
            {confidence.value for confidence in RoutingConfidence},
        )

        messages = (
            "水龍頭漏水",
            "馬桶壞了",
            "水管漏水",
            "電線冒火花",
            "其他水電問題",
            "請幫我訂餐",
        )
        for message in messages:
            with self.subTest(message=message):
                result = route_repair_branch(message)
                if result.branch is not None:
                    self.assertIn(result.branch, set(RepairBranch))
                self.assertTrue(all(branch in set(RepairBranch) for branch in result.alternatives))

        with self.assertRaises(ValidationError):
            RepairRoutingResult.model_validate({"branch": "roof_issue", "confidence": "high"})
        with self.assertRaises(ValidationError):
            RepairRoutingResult.model_validate({"confidence": "high", "unexpected": "value"})


if __name__ == "__main__":
    unittest.main()
