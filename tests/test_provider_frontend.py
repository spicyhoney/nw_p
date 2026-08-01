from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "home_repair_agent" / "web" / "static"


class ProviderFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (STATIC_DIR / "provider.html").read_text(encoding="utf-8")
        cls.styles = (STATIC_DIR / "provider.css").read_text(encoding="utf-8")
        cls.javascript = (STATIC_DIR / "provider.js").read_text(encoding="utf-8")

    def test_workspace_uses_natural_page_scroll_and_reflows_before_two_columns_cramp(self) -> None:
        self.assertIn("overflow-y: auto", self.styles)
        self.assertIn("min-height: 100dvh", self.styles)
        self.assertIn("@media (max-width: 1100px)", self.styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", self.styles)
        self.assertNotIn("min-height: calc(100vh - 154px)", self.styles)
        self.assertNotIn("overflow-x: auto", self.styles)
        self.assertNotIn("zoom:", self.styles)
        self.assertNotIn("transform: scale", self.styles)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend behavior checks")
    def test_answer_metadata_hides_duplicate_and_unknown_internal_values(self) -> None:
        answers = {
            "issue_category": "leaking_faucet",
            "issue_description": "<img src=x onerror=alert(1)>",
            "preferred_time": "2026-08-01T13:00:00+08:00 / 2026-08-01T17:00:00+08:00",
            "urgency": "urgent",
            "unknown_internal_key": "internal-value",
        }
        script = f"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync({json.dumps(str(STATIC_DIR / "provider.js"))}, "utf8");
const context = {{ document: {{ addEventListener() {{}} }} }};
vm.createContext(context);
vm.runInContext(source, context);
const result = vm.runInContext(
  `providerAnswerEntries(${{JSON.stringify({json.dumps(answers)})}})`,
  context,
);
process.stdout.write(JSON.stringify(result));
"""
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            encoding="utf-8",
        )
        result = json.loads(completed.stdout)

        self.assertEqual(
            [
                ["問題類型", "水龍頭漏水"],
                ["問題描述", "<img src=x onerror=alert(1)>"],
                ["緊急程度", "緊急"],
            ],
            result,
        )
        self.assertNotIn("innerHTML", self.javascript)

    def test_time_window_is_rendered_in_taipei_and_not_as_a_generic_answer(self) -> None:
        self.assertIn('timeZone: "Asia/Taipei"', self.javascript)
        self.assertIn('"preferred_time",', self.javascript)
        self.assertIn("formatProviderWindow(", self.javascript)
        self.assertIn("希望時段", self.html)


if __name__ == "__main__":
    unittest.main()
