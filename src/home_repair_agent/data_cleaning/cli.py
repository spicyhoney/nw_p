from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from .pipeline import run_pipeline
from .postgres import load_pipeline_outputs

DATASET_DIRECTORY = "(統一資訊) 命題數據集 - 2026 雲湧智生：臺灣生成式 AI 應用黑客松競賽"


def build_parser(project_root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the reproducible B+ data-cleaning pipeline.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=project_root / DATASET_DIRECTORY,
        help="Organizer dataset directory.",
    )
    parser.add_argument(
        "--reference-path",
        type=Path,
        default=project_root / "data" / "reference" / "taiwan_admin_areas.json",
        help="Pinned NLSC administrative-area snapshot.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "data" / "processed",
    )
    parser.add_argument(
        "--quarantine-dir",
        type=Path,
        default=project_root / "data" / "quarantine",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=project_root / "reports" / "data_quality.md",
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=date(2026, 8, 1),
        help="Fixed YYYY-MM-DD date used by reproducible synthetic demo records.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Optional PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--skip-migration",
        action="store_true",
        help="Load data without applying the bundled PostgreSQL migration.",
    )
    return parser


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    args = build_parser(project_root).parse_args()
    result = run_pipeline(
        source_dir=args.source_dir.resolve(),
        output_dir=args.output_dir.resolve(),
        quarantine_dir=args.quarantine_dir.resolve(),
        report_path=args.report_path.resolve(),
        reference_path=args.reference_path.resolve(),
        reference_date=args.reference_date,
    )

    summary = result.summary
    print("B+ data cleaning completed.")
    print(
        "Locations: "
        f"{summary['location_summary']['canonical_locations']}; "
        f"orders: {summary['order_summary']['rows']}; "
        f"issues: {sum(summary['severity_counts'].values())}; "
        f"quarantined indexes: {summary['quarantine_records']}."
    )
    print(f"Report: {result.output_paths['report']}")

    if args.database_url:
        counts = load_pipeline_outputs(
            database_url=args.database_url,
            project_root=project_root,
            output_paths=result.output_paths,
            apply_migration=not args.skip_migration,
        )
        print(f"PostgreSQL load completed: {sum(counts.values())} rows processed.")
    else:
        print("PostgreSQL load skipped because DATABASE_URL was not set.")
    return 0
