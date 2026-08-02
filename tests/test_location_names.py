from __future__ import annotations

import json
from pathlib import Path

from home_repair_agent.web.location_names import TAIWAN_DISTRICT_NAMES
from home_repair_agent.web.service import (
    _contains_location_description,
    _district_references,
)

REFERENCE_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "reference" / "taiwan_admin_areas.json"
)


def test_packaged_district_names_match_the_controlled_nlsc_snapshot() -> None:
    snapshot = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    expected = {item["district_name_raw"].replace("台", "臺") for item in snapshot["districts"]}

    assert TAIWAN_DISTRICT_NAMES == expected


def test_controlled_district_scan_does_not_match_an_admin_name_substring() -> None:
    text = "臺北市大安區集中區域的插座沒電"

    assert _district_references(text) == ("大安區",)
    assert not _contains_location_description("集中區域")
