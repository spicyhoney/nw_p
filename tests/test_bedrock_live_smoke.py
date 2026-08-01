from __future__ import annotations

import unittest

from home_repair_agent.agent.models import ToolCall
from scripts.bedrock_live_smoke import _validate_location_tool_calls


def _location_call(
    *,
    name: str = "resolve_location",
    arguments: dict[str, object] | None = None,
) -> ToolCall:
    return ToolCall(
        call_id="bedrock-call-1",
        name=name,
        arguments=(
            {"county_name": "台北市", "district_name": "大安區"} if arguments is None else arguments
        ),
    )


class BedrockLiveSmokeValidationTests(unittest.TestCase):
    def test_accepts_exact_resolve_location_call(self) -> None:
        tool_call = _location_call()

        self.assertEqual(tool_call, _validate_location_tool_calls([tool_call]))

    def test_rejects_missing_or_multiple_tool_calls(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            _validate_location_tool_calls([])
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            _validate_location_tool_calls([_location_call(), _location_call()])

    def test_rejects_unexpected_tool_name(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unexpected tool"):
            _validate_location_tool_calls([_location_call(name="search_services")])

    def test_rejects_unexpected_location_arguments(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unexpected.*arguments"):
            _validate_location_tool_calls(
                [
                    _location_call(
                        arguments={
                            "county_name": "台北市",
                            "district_name": "信義區",
                        }
                    )
                ]
            )


if __name__ == "__main__":
    unittest.main()
