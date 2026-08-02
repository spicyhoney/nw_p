from __future__ import annotations

import json
import unittest
from datetime import datetime
from pathlib import Path

from home_repair_agent.agent.demo import TAIPEI_TIMEZONE, DemoReadRepository
from home_repair_agent.backend.services import ReadServiceLayer
from home_repair_agent.data_cleaning.demo import build_curated_repair_form

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_FORM_PATH = PROJECT_ROOT / "data" / "processed" / "curated_repair_form.json"
ISSUE_CATEGORIES = [
    "faucet_leak",
    "toilet_issue",
    "pipe_issue",
    "electrical_issue",
    "other",
]
WATER_SHUTOFF_CATEGORIES = [
    "faucet_leak",
    "toilet_issue",
    "pipe_issue",
]


class RepairFormConfigurationTests(unittest.TestCase):
    def test_builder_matches_versioned_processed_artifact(self) -> None:
        processed = json.loads(PROCESSED_FORM_PATH.read_text(encoding="utf-8"))

        self.assertEqual(processed, build_curated_repair_form())

    def test_demo_repository_uses_all_controlled_repair_branches(self) -> None:
        repository = DemoReadRepository(reference_time=datetime(2026, 8, 1, tzinfo=TAIPEI_TIMEZONE))

        forms = repository.list_consultation_forms(service_id=17)

        self.assertEqual(1, len(forms))
        form = forms[0]
        self.assertEqual("repair_form_v1", form.form_key)
        self.assertEqual(17, form.service_id)
        self.assertEqual(1, form.version)

        topics = {topic.topic_key: topic for topic in form.topics}
        self.assertEqual(
            ISSUE_CATEGORIES,
            [option.value for option in topics["issue_category"].options],
        )
        applicability = topics["water_shutoff"].config["applicable_issue_categories"]
        self.assertEqual(WATER_SHUTOFF_CATEGORIES, applicability)
        self.assertNotIn("electrical_issue", applicability)
        self.assertNotIn("other", applicability)

    def test_demo_repository_recognizes_controlled_electrical_terms(self) -> None:
        services = ReadServiceLayer(DemoReadRepository())

        for term in ("插座", "電路", "電線", "冒火花"):
            with self.subTest(term=term):
                self.assertEqual(1, services.search_services(term).count)


if __name__ == "__main__":
    unittest.main()
