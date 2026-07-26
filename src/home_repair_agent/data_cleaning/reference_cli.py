from __future__ import annotations

import argparse
from pathlib import Path

from .reference import fetch_and_save_nlsc_admin_areas


def main() -> int:
    project_root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(
        description="Fetch and pin the official NLSC county and district reference."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root / "data" / "reference" / "taiwan_admin_areas.json",
    )
    args = parser.parse_args()
    payload = fetch_and_save_nlsc_admin_areas(args.output.resolve())
    print(
        f"Saved {len(payload['counties'])} counties and "
        f"{len(payload['districts'])} districts to {args.output.resolve()}."
    )
    return 0
