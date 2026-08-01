from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "home_repair_agent" / "web" / "static"
CHECKLIST_CONCURRENCY_TEST = Path(__file__).with_name("test_checklist_concurrency.js")


class ConsumerAccessibilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        cls.javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    def test_checklist_uses_native_labeled_checked_controls(self) -> None:
        self.assertIn('id="checklist-list"', self.html)
        self.assertIn('id="checklist-feedback"', self.html)
        self.assertIn('aria-describedby="checklist-help"', self.html)
        self.assertIn('input.type = "checkbox"', self.javascript)
        self.assertIn("input.checked = item.checked", self.javascript)
        self.assertIn("label.htmlFor = input.id", self.javascript)
        self.assertIn('event.key === "Enter"', self.javascript)
        self.assertIn('"PUT"', self.javascript)

    def test_status_and_error_regions_are_announced(self) -> None:
        self.assertIn('id="app-status"', self.html)
        self.assertIn('id="dispatch-status"', self.html)
        self.assertIn('role="status"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="alert"', self.html)
        self.assertIn('aria-live="assertive"', self.html)
        self.assertIn('document.body.setAttribute("aria-busy"', self.javascript)

    def test_keyboard_focus_touch_targets_and_reduced_motion_are_preserved(self) -> None:
        self.assertIn("--focus: #005fcc", self.css)
        self.assertIn("outline: 3px solid var(--focus)", self.css)
        self.assertIn("min-height: 44px", self.css)
        self.assertIn("min-height: 48px", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("scroll-behavior: auto !important", self.css)

    def test_mobile_view_controls_expose_their_target_and_state(self) -> None:
        self.assertIn('aria-controls="progress-pane"', self.html)
        self.assertIn('aria-controls="conversation-pane"', self.html)
        self.assertIn('aria-controls="candidates-pane"', self.html)
        self.assertIn('aria-pressed="true"', self.html)
        self.assertIn('button.setAttribute("aria-pressed", "true")', self.javascript)
        self.assertIn("100dvh", self.css)

    def test_conversation_uses_one_scroll_region_and_reachable_composer(self) -> None:
        self.assertIn('id="conversation-scroll-region"', self.html)
        self.assertIn('aria-label="對話內容與諮詢資訊"', self.html)
        self.assertRegex(
            self.html,
            re.compile(
                r'id="conversation-scroll-region".*id="message-list"'
                r'.*id="summary-section".*</div>\s*<form\s+id="message-form"',
                re.DOTALL,
            ),
        )

        conversation_rule = re.search(r"\.conversation-pane\s*\{([^}]+)\}", self.css)
        scroll_rule = re.search(r"\.conversation-scroll-region\s*\{([^}]+)\}", self.css)
        message_rule = re.search(r"\.message-list\s*\{([^}]+)\}", self.css)
        form_rule = re.search(r"\.consultation-form-section\s*\{([^}]+)\}", self.css)
        self.assertIsNotNone(conversation_rule)
        self.assertIsNotNone(scroll_rule)
        self.assertIsNotNone(message_rule)
        self.assertIsNotNone(form_rule)
        self.assertIn(
            "grid-template-rows: auto minmax(0, 1fr) auto",
            conversation_rule.group(1),
        )
        self.assertIn("overflow-y: auto", scroll_rule.group(1))
        self.assertNotIn("overflow-y", message_rule.group(1))
        self.assertNotIn("overflow-y", form_rule.group(1))
        self.assertNotIn("max-height", form_rule.group(1))
        self.assertIn("scrollRegion.scrollTo", self.javascript)
        self.assertNotIn("lastElementChild?.scrollIntoView", self.javascript)
        self.assertNotIn(
            "elements.messageList.scrollTop = elements.messageList.scrollHeight",
            self.javascript,
        )

    def test_out_of_order_checklist_responses_do_not_replace_newer_state(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required for the browser-state regression test")

        result = subprocess.run(
            [node, str(CHECKLIST_CONCURRENCY_TEST)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("checklist concurrency regression: passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
