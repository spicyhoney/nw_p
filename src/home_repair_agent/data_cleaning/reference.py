from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unicodedata
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from typing import Any

from .source_io import write_json


NLSC_COUNTY_URL = "https://api.nlsc.gov.tw/other/ListCounty"
NLSC_TOWN_URL = "https://api.nlsc.gov.tw/other/ListTown1/{county_code}"
NLSC_DATASET_URL = "https://data.gov.tw/dataset/102011"
OPEN_DATA_LICENSE_URL = "https://data.gov.tw/license"


def normalize_admin_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().replace("臺", "台")


def _fetch_xml(url: str, timeout: int = 30) -> ET.Element:
    request = Request(
        url,
        headers={"User-Agent": "home-repair-agent-data-pipeline/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    return ET.fromstring(body)


def fetch_nlsc_admin_areas() -> dict[str, Any]:
    county_root = _fetch_xml(NLSC_COUNTY_URL)
    counties: list[dict[str, str]] = []
    districts: list[dict[str, str]] = []

    for county_item in county_root.findall("countyItem"):
        county_code = county_item.findtext("countycode", "").strip()
        county_name_raw = county_item.findtext("countyname", "").strip()
        county_code01 = county_item.findtext("countycode01", "").strip()
        if not county_code or not county_name_raw:
            continue

        county = {
            "nlsc_county_code": county_code,
            "nlsc_county_code01": county_code01,
            "county_name": normalize_admin_name(county_name_raw),
            "county_name_raw": county_name_raw,
        }
        counties.append(county)

        town_root = _fetch_xml(NLSC_TOWN_URL.format(county_code=county_code))
        for town_item in town_root.findall("townItem"):
            town_code = town_item.findtext("towncode", "").strip()
            town_code01 = town_item.findtext("towncode01", "").strip()
            town_name_raw = town_item.findtext("townname", "").strip()
            if not town_code or not town_name_raw:
                continue
            districts.append(
                {
                    **county,
                    "nlsc_town_code": town_code,
                    "nlsc_town_code01": town_code01,
                    "district_name": normalize_admin_name(town_name_raw),
                    "district_name_raw": town_name_raw,
                }
            )

    counties.sort(key=lambda item: item["nlsc_county_code"])
    districts.sort(
        key=lambda item: (
            item["nlsc_county_code"],
            item["nlsc_town_code"],
        )
    )

    return {
        "metadata": {
            "source_type": "external_reference",
            "provider": "內政部國土測繪中心",
            "dataset": "代碼服務－鄉鎮市區清單（戶政）",
            "dataset_url": NLSC_DATASET_URL,
            "county_api_url": NLSC_COUNTY_URL,
            "town_api_url_template": NLSC_TOWN_URL,
            "license": "政府資料開放授權條款第1版",
            "license_url": OPEN_DATA_LICENSE_URL,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
        "counties": counties,
        "districts": districts,
    }


def fetch_and_save_nlsc_admin_areas(output_path: Path) -> dict[str, Any]:
    payload = fetch_nlsc_admin_areas()
    write_json(output_path, payload)
    return payload


def load_admin_reference(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def merge_locations(
    organizer_counties: list[dict[str, Any]],
    organizer_districts: list[dict[str, Any]],
    external_reference: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    issues: list[dict[str, Any]] = []
    county_by_code = {row["code"]: row for row in organizer_counties}
    external_by_name = {
        (
            normalize_admin_name(row["county_name"]),
            normalize_admin_name(row["district_name"]),
        ): row
        for row in external_reference["districts"]
    }
    matched_external_keys: set[tuple[str, str]] = set()
    locations: list[dict[str, Any]] = []

    for row in organizer_districts:
        county = county_by_code.get(row["county_code"])
        if county is None:
            issues.append(
                {
                    "issue_code": "ORPHAN_DISTRICT_COUNTY",
                    "severity": "error",
                    "source_record_id": row["code"],
                    "message": "行政區引用不存在的縣市代碼",
                }
            )
            continue

        county_name = normalize_admin_name(county["name"])
        district_name = normalize_admin_name(row["name"])
        key = (county_name, district_name)
        external = external_by_name.get(key)
        if external:
            matched_external_keys.add(key)
        else:
            issues.append(
                {
                    "issue_code": "NO_EXTERNAL_LOCATION_MATCH",
                    "severity": "warning",
                    "source_record_id": f"{row['county_code']}:{row['code']}",
                    "message": f"找不到外部行政區對照：{county_name}{district_name}",
                }
            )

        locations.append(
            {
                "location_id": f"ORG-{row['county_code']}-{row['code']}",
                "county_name": county_name,
                "district_name": district_name,
                "full_name": f"{county_name}{district_name}",
                "postal_code": str(row.get("zip") or "") or None,
                "organizer_county_code": row["county_code"],
                "organizer_district_code": row["code"],
                "nlsc_county_code": external.get("nlsc_county_code") if external else None,
                "nlsc_county_code01": (
                    external.get("nlsc_county_code01") if external else None
                ),
                "nlsc_town_code": external.get("nlsc_town_code") if external else None,
                "nlsc_town_code01": external.get("nlsc_town_code01") if external else None,
                "source_type": "official_repaired",
                "source_file": "縣市區域範例資料.json",
                "source_record_id": f"district:{row['county_code']}:{row['code']}",
                "quality_status": "verified" if external else "review",
                "agent_eligible": external is not None,
                "cleaning_rule": "derive_full_name_and_crosswalk_nlsc",
            }
        )

    for key, external in external_by_name.items():
        if key in matched_external_keys:
            continue
        locations.append(
            {
                "location_id": f"NLSC-{external['nlsc_town_code']}",
                "county_name": normalize_admin_name(external["county_name"]),
                "district_name": normalize_admin_name(external["district_name"]),
                "full_name": (
                    f"{normalize_admin_name(external['county_name'])}"
                    f"{normalize_admin_name(external['district_name'])}"
                ),
                "postal_code": None,
                "organizer_county_code": None,
                "organizer_district_code": None,
                "nlsc_county_code": external["nlsc_county_code"],
                "nlsc_county_code01": external["nlsc_county_code01"],
                "nlsc_town_code": external["nlsc_town_code"],
                "nlsc_town_code01": external["nlsc_town_code01"],
                "source_type": "external_reference",
                "source_file": "data/reference/taiwan_admin_areas.json",
                "source_record_id": f"town:{external['nlsc_town_code']}",
                "quality_status": "verified",
                "agent_eligible": True,
                "cleaning_rule": "add_missing_location_from_nlsc",
            }
        )

    locations.sort(key=lambda item: (item["county_name"], item["district_name"]))
    summary = {
        "organizer_counties": len(organizer_counties),
        "organizer_districts": len(organizer_districts),
        "external_counties": len(external_reference["counties"]),
        "external_districts": len(external_reference["districts"]),
        "matched_organizer_districts": len(matched_external_keys),
        "external_only_districts": len(external_by_name) - len(matched_external_keys),
        "canonical_locations": len(locations),
    }
    return locations, issues, summary
