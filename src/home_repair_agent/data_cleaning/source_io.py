from __future__ import annotations

import csv
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ORDER_NUMERIC_COLUMNS = {
    "record_id",
    "service_vendor_id",
    "service_id",
    "deposit_amount",
    "original_amount",
    "discount_amount",
    "shipping_fee_amount",
    "final_amount",
    "refund_amount",
    "order_points",
    "used_points",
    "refund_points",
    "earn_points",
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def extract_json_documents(text: str) -> tuple[list[Any], list[str]]:
    """Read adjacent JSON documents while retaining non-JSON text as evidence."""
    decoder = json.JSONDecoder()
    documents: list[Any] = []
    interleaved_text: list[str] = []
    cursor = 0

    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text):
            break

        if text[cursor] not in "[{":
            candidates = [
                position
                for position in (text.find("{", cursor), text.find("[", cursor))
                if position >= 0
            ]
            next_document = min(candidates) if candidates else len(text)
            fragment = text[cursor:next_document].strip()
            if fragment:
                interleaved_text.append(fragment)
            cursor = next_document
            continue

        try:
            document, end = decoder.raw_decode(text, cursor)
        except json.JSONDecodeError:
            interleaved_text.append(text[cursor])
            cursor += 1
            continue

        documents.append(document)
        cursor = end

    return documents, interleaved_text


def load_fragmented_tables(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    documents, interleaved_text = extract_json_documents(read_text(path))
    tables: dict[str, list[dict[str, Any]]] = {}

    for document in documents:
        if not isinstance(document, dict):
            continue
        for name, rows in document.items():
            if isinstance(rows, list):
                tables[name] = rows

    return tables, interleaved_text


def load_json_table(path: Path, table_name: str) -> list[dict[str, Any]]:
    payload = json.loads(read_text(path))
    rows = payload.get(table_name)
    if not isinstance(rows, list):
        raise TypeError(f"{path.name} does not contain a list named {table_name}")
    return rows


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def values_semantically_equal(column: str, json_value: Any, csv_value: str) -> bool:
    if json_value is None and csv_value == "":
        return True

    if column in ORDER_NUMERIC_COLUMNS:
        try:
            return Decimal(str(json_value)) == Decimal(csv_value)
        except InvalidOperation:
            return False

    if column == "is_deleted":
        return str(json_value).lower() == csv_value.lower()

    if column in {"vendor_data", "order_items"}:
        return parse_json_value(json_value) == parse_json_value(csv_value)

    return str(json_value) == csv_value


def compare_order_sources(
    json_rows: list[dict[str, Any]],
    csv_rows: list[dict[str, str]],
) -> dict[str, Any]:
    csv_by_record_id = {row["record_id"]: row for row in csv_rows}
    json_ids = {str(row["record_id"]) for row in json_rows}
    csv_ids = set(csv_by_record_id)
    mismatches: dict[str, int] = {}

    for json_row in json_rows:
        csv_row = csv_by_record_id.get(str(json_row["record_id"]))
        if csv_row is None:
            continue
        for column, value in json_row.items():
            if not values_semantically_equal(column, value, csv_row.get(column, "")):
                mismatches[column] = mismatches.get(column, 0) + 1

    return {
        "json_rows": len(json_rows),
        "csv_rows": len(csv_rows),
        "same_record_ids": json_ids == csv_ids,
        "json_only_record_ids": sorted(json_ids - csv_ids),
        "csv_only_record_ids": sorted(csv_ids - json_ids),
        "semantic_mismatch_counts": dict(sorted(mismatches.items())),
        "semantically_identical": json_ids == csv_ids and not mismatches,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
