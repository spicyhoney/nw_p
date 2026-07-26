from __future__ import annotations

import unittest

from home_repair_agent.agent.demo import DemoReadRepository, run_demo
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


class ScriptedDemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_demo_runs_the_real_three_tool_loop(self) -> None:
        output: list[str] = []

        conversation = await run_demo(
            scripted=True,
            output_func=output.append,
        )

        transcript = "\n".join(output)
        self.assertIn("[MCP] search_services", transcript)
        self.assertIn("[MCP] resolve_location", transcript)
        self.assertIn("[MCP] get_consultation_form", transcript)
        self.assertIn("必要資訊已收集完成", transcript)
        self.assertIn("沒有寫入資料庫或建立案件", transcript)
        self.assertGreaterEqual(len(conversation.messages), 3)


if __name__ == "__main__":
    unittest.main()
