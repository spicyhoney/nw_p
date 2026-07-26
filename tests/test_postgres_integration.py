from __future__ import annotations

import os
from pathlib import Path
import unittest

try:
    import psycopg
except ImportError:
    psycopg = None

from home_repair_agent.data_cleaning.postgres import load_pipeline_outputs


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("TEST_DATABASE_URL")

EXPECTED_TABLE_COUNTS = {
    "core.service_vendor": 6,
    "core.service": 8,
    "core.location": 368,
    "core.source_mapping": 24,
    "core.data_issue": 280,
    "core.form_template": 1,
    "core.form_topic": 8,
    "core.form_option": 14,
    "quarantine.source_record": 87,
    "demo.provider": 3,
    "demo.provider_service_area": 6,
    "demo.provider_availability": 3,
    "demo.consultation_case": 1,
    "demo.match_result": 1,
    "demo.service_order": 1,
    "demo.order_item": 1,
}

EXPECTED_AGENT_VIEW_COUNTS = {
    "agent.service_catalog": 8,
    "agent.location_catalog": 368,
    "agent.form_template": 1,
    "agent.form_topic": 8,
    "agent.form_option": 14,
    "agent.available_provider_slot": 6,
    "agent.consultation_case": 1,
    "agent.service_order": 1,
}


@unittest.skipUnless(
    DATABASE_URL and psycopg,
    "TEST_DATABASE_URL and psycopg are required for PostgreSQL integration tests.",
)
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output_paths = {
            "service_catalog": (
                PROJECT_ROOT / "data" / "processed" / "core_service_catalog.json"
            ),
            "locations": (
                PROJECT_ROOT / "data" / "processed" / "core_locations.json"
            ),
            "repair_form": (
                PROJECT_ROOT / "data" / "processed" / "curated_repair_form.json"
            ),
            "demo_seed": (
                PROJECT_ROOT / "data" / "processed" / "demo_seed.json"
            ),
            "source_mappings": (
                PROJECT_ROOT / "data" / "processed" / "source_mappings.json"
            ),
            "quality_summary": (
                PROJECT_ROOT
                / "data"
                / "processed"
                / "data_quality_summary.json"
            ),
            "historical_orders": (
                PROJECT_ROOT
                / "data"
                / "processed"
                / "_local_historical_orders_redacted.json"
            ),
            "quarantine": (
                PROJECT_ROOT
                / "data"
                / "quarantine"
                / "_local_quarantine_index.json"
            ),
            "report": PROJECT_ROOT / "reports" / "data_quality.md",
        }
        cls.loaded_counts = load_pipeline_outputs(
            database_url=DATABASE_URL,
            project_root=PROJECT_ROOT,
            output_paths=cls.output_paths,
            apply_migration=True,
        )

    def _scalar(self, statement: str) -> object:
        with psycopg.connect(DATABASE_URL) as connection:
            return connection.execute(statement).fetchone()[0]

    def _table_counts(self) -> dict[str, int]:
        return {
            table: int(self._scalar(f"SELECT count(*) FROM {table}"))
            for table in EXPECTED_TABLE_COUNTS
        }

    def _assert_database_rejects(
        self,
        statement: str,
        expected_error: type[Exception],
    ) -> None:
        with psycopg.connect(DATABASE_URL) as connection:
            with self.assertRaises(expected_error):
                connection.execute(statement)
            connection.rollback()

    def test_expected_rows_are_loaded(self) -> None:
        self.assertEqual(EXPECTED_TABLE_COUNTS, self._table_counts())
        self.assertEqual(sum(EXPECTED_TABLE_COUNTS.values()), 812)

    def test_agent_views_expose_only_expected_records(self) -> None:
        actual = {
            view: int(self._scalar(f"SELECT count(*) FROM {view}"))
            for view in EXPECTED_AGENT_VIEW_COUNTS
        }
        self.assertEqual(EXPECTED_AGENT_VIEW_COUNTS, actual)
        self.assertEqual(
            0,
            self._scalar(
                """
                SELECT count(*)
                FROM core.source_mapping
                WHERE mapping_status = 'unresolved' AND agent_eligible
                """
            ),
        )
        self.assertEqual(
            0,
            self._scalar(
                """
                SELECT count(*)
                FROM agent.service_catalog
                WHERE service_id IN (7, 18)
                """
            ),
        )

    def test_database_comments_are_queryable(self) -> None:
        self.assertTrue(
            self._scalar(
                "SELECT obj_description('core.service'::regclass, 'pg_class')"
            )
        )
        self.assertTrue(
            self._scalar(
                """
                SELECT col_description(
                    'core.source_mapping'::regclass,
                    (
                        SELECT attnum
                        FROM pg_attribute
                        WHERE
                            attrelid = 'core.source_mapping'::regclass
                            AND attname = 'candidate_canonical_id'
                    )
                )
                """
            )
        )
        self.assertTrue(
            self._scalar(
                """
                SELECT obj_description(
                    'agent.service_catalog'::regclass,
                    'pg_class'
                )
                """
            )
        )

    def test_constraints_reject_unsafe_changes(self) -> None:
        self._assert_database_rejects(
            """
            UPDATE core.location
            SET quality_status = 'review'
            WHERE location_id = (
                SELECT location_id FROM core.location WHERE agent_eligible LIMIT 1
            )
            """,
            psycopg.errors.CheckViolation,
        )
        self._assert_database_rejects(
            """
            UPDATE core.source_mapping
            SET mapping_status = 'unresolved'
            WHERE entity_type = 'service' AND source_id = '17'
            """,
            psycopg.errors.CheckViolation,
        )
        self._assert_database_rejects(
            """
            UPDATE quarantine.source_record
            SET raw_payload_included = true
            WHERE (source_table, source_record_id) = (
                SELECT source_table, source_record_id
                FROM quarantine.source_record
                LIMIT 1
            )
            """,
            psycopg.errors.CheckViolation,
        )
        self._assert_database_rejects(
            """
            UPDATE demo.provider
            SET service_id = 999999
            WHERE provider_id = 'SYN-PROVIDER-001'
            """,
            psycopg.errors.ForeignKeyViolation,
        )
        self._assert_database_rejects(
            """
            UPDATE demo.provider
            SET source_type = 'official_repaired'
            WHERE provider_id = 'SYN-PROVIDER-001'
            """,
            psycopg.errors.CheckViolation,
        )

    def test_migration_and_loader_are_idempotent(self) -> None:
        before = self._table_counts()
        loaded_again = load_pipeline_outputs(
            database_url=DATABASE_URL,
            project_root=PROJECT_ROOT,
            output_paths=self.output_paths,
            apply_migration=True,
        )
        after = self._table_counts()

        self.assertEqual(before, after)
        self.assertEqual(812, sum(loaded_again.values()))


if __name__ == "__main__":
    unittest.main()
