from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from home_repair_agent.data_cleaning.demo import build_demo_seed
from home_repair_agent.data_cleaning.pipeline import (
    _build_source_mappings,
    normalize_order_items,
    run_pipeline,
)
from home_repair_agent.data_cleaning.reference import merge_locations
from home_repair_agent.data_cleaning.source_io import extract_json_documents


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PROJECT_ROOT / (
    "(統一資訊) 命題數據集 - 2026 雲湧智生："
    "臺灣生成式 AI 應用黑客松競賽"
)
REFERENCE_PATH = (
    PROJECT_ROOT / "data" / "reference" / "taiwan_admin_areas.json"
)


class SourceParsingTests(unittest.TestCase):
    def test_extracts_adjacent_json_and_retains_interleaved_legend(self) -> None:
        text = '{"first": [{"id": 1}]}\ntype: 1 service\n{"second": []}'

        documents, evidence = extract_json_documents(text)

        self.assertEqual(2, len(documents))
        self.assertEqual([{"id": 1}], documents[0]["first"])
        self.assertEqual(["type: 1 service"], evidence)

    def test_normalizes_all_supported_order_item_shapes(self) -> None:
        cases = [
            ([{"name": "A", "price": 100}], "list"),
            ({"orderItems": [{"name": "B"}]}, "object_orderItems"),
            ({"goods": [{"name": "C"}]}, "object_goods"),
            ({"goods": {"name": "D"}}, "object_single_goods"),
        ]

        for payload, expected_shape in cases:
            with self.subTest(shape=expected_shape):
                items, shape = normalize_order_items(payload)
                self.assertEqual(expected_shape, shape)
                self.assertEqual(1, len(items))


class PolicyTests(unittest.TestCase):
    def test_unresolved_service_seven_is_not_remapped(self) -> None:
        mappings = _build_source_mappings(
            known_service_ids={17},
            known_vendor_ids={1},
            consultation_tables={"pms_form_feedback": [{"service_id": 7}]},
            order_rows=[],
        )
        mapping = next(
            row
            for row in mappings
            if row["entity_type"] == "service" and row["source_id"] == "7"
        )

        self.assertEqual("unresolved", mapping["mapping_status"])
        self.assertIsNone(mapping["canonical_id"])
        self.assertEqual("17", mapping["candidate_canonical_id"])
        self.assertFalse(mapping["agent_eligible"])

    def test_unmatched_organizer_location_is_not_agent_eligible(self) -> None:
        locations, issues, _ = merge_locations(
            organizer_counties=[{"code": "A", "name": "測試市"}],
            organizer_districts=[
                {"county_code": "A", "code": "001", "name": "未知區", "zip": "000"}
            ],
            external_reference={"counties": [], "districts": []},
        )

        self.assertEqual("review", locations[0]["quality_status"])
        self.assertFalse(locations[0]["agent_eligible"])
        self.assertEqual("NO_EXTERNAL_LOCATION_MATCH", issues[0]["issue_code"])

    def test_demo_chain_is_synthetic_and_uses_verified_service(self) -> None:
        locations = [
            {"location_id": "D", "full_name": "台北市大安區"},
            {"location_id": "X", "full_name": "台北市信義區"},
            {"location_id": "Z", "full_name": "台北市中正區"},
        ]

        seed = build_demo_seed(locations, date(2026, 8, 1))

        record_groups = (
            "providers",
            "provider_service_areas",
            "provider_availability",
            "consultation_cases",
            "match_results",
            "orders",
            "order_items",
        )
        for group in record_groups:
            for record in seed[group]:
                self.assertEqual("synthetic", record["source_type"])
                self.assertEqual("verified", record["quality_status"])
                self.assertTrue(record["agent_eligible"])
                self.assertTrue(record["source_file"])
                self.assertTrue(record["source_record_id"])
                self.assertTrue(record["cleaning_rule"])
        self.assertEqual(17, seed["consultation_cases"][0]["service_id"])
        self.assertEqual(17, seed["orders"][0]["service_id"])


class PipelineIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        SOURCE_DIR.exists() and REFERENCE_PATH.exists(),
        "Local organizer dataset and pinned NLSC reference are required.",
    )
    def test_pipeline_produces_agent_safe_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            result = run_pipeline(
                source_dir=SOURCE_DIR,
                output_dir=temporary / "processed",
                quarantine_dir=temporary / "quarantine",
                report_path=temporary / "data_quality.md",
                reference_path=REFERENCE_PATH,
                reference_date=date(2026, 8, 1),
            )

            self.assertTrue(
                result.summary["order_source_comparison"]["semantically_identical"]
            )
            self.assertGreater(result.summary["unresolved_mappings"], 0)
            service_catalog = json.loads(
                result.output_paths["service_catalog"].read_text(encoding="utf-8")
            )
            locations = json.loads(
                result.output_paths["locations"].read_text(encoding="utf-8")
            )["locations"]
            all_agent_records = [
                *service_catalog["vendors"],
                *service_catalog["services"],
                *locations,
            ]
            for record in all_agent_records:
                if record["agent_eligible"]:
                    self.assertEqual("verified", record["quality_status"])

            safe_orders = result.output_paths["historical_orders"].read_text(
                encoding="utf-8"
            )
            self.assertNotIn("member_phone", safe_orders)
            self.assertNotIn("member_email", safe_orders)
            self.assertNotIn("member_name", safe_orders)


if __name__ == "__main__":
    unittest.main()
