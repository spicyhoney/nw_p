from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from html import unescape
from pathlib import Path
from typing import Any

from .demo import build_curated_repair_form, build_demo_seed
from .reference import load_admin_reference, merge_locations
from .source_io import (
    compare_order_sources,
    load_csv_rows,
    load_fragmented_tables,
    load_json_table,
    parse_json_value,
    sha256_file,
    write_json,
)

MASTER_FILE = "相關主檔設定.json"
COUNTY_FILE = "縣市區域範例資料.json"
CONSULTATION_FILE = "諮詢單相關範例資料.json"
ORDER_JSON_FILE = "order_record範例資料.json"
ORDER_CSV_FILE = "order_record範例資料.csv"

REQUIRED_SOURCE_FILES = (
    MASTER_FILE,
    COUNTY_FILE,
    CONSULTATION_FILE,
    ORDER_JSON_FILE,
    ORDER_CSV_FILE,
)

SOURCE_TYPES = {
    "official_raw",
    "official_repaired",
    "external_reference",
    "curated_config",
    "synthetic",
}

ALLOWED_ORDER_STATUSES = {
    "01": {"11", "12", "13", "14", "15", "80", "90", "98", "99"},
    "02": {"01", "02", "03", "04", "70", "80", "90", "99"},
    "03": {"01", "02", "03", "04", "80", "90", "99"},
    "04": {"01", "02", "03", "04", "80", "90", "99"},
    "05": {"01", "02", "03", "04", "80", "90", "99"},
    "06": {"01", "02", "03", "04", "80", "90", "99"},
}

SERVICE_ALIASES = {
    1: ["洗衣機", "洗衣機異味", "洗衣機清潔"],
    2: ["冷氣", "空調", "冷氣不冷", "冷氣清洗"],
    3: ["寄件", "包裹", "宅配", "到府收件"],
    4: ["居家清潔", "打掃", "廚房清潔", "浴室清潔"],
    5: ["家事服務", "計時清潔", "掃地", "拖地"],
    9: ["餐廳", "訂位", "訂桌"],
    16: ["外送", "餐點", "美食"],
    17: ["水電", "修繕", "水龍頭漏水", "馬桶不通", "水管堵塞", "插座"],
}

SAFE_ORDER_COLUMNS = (
    "record_id",
    "order_no",
    "service_vendor_id",
    "service_id",
    "platform_code",
    "order_type",
    "order_status",
    "order_time",
    "deposit_time",
    "confirm_time",
    "service_time",
    "complete_time",
    "cancel_time",
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
    "point_status",
    "point_grant_time",
    "quote_approved_time",
    "quote_no",
    "comment_status",
    "is_deleted",
    "cre_time",
    "upd_time",
)


@dataclass
class IssueCollector:
    issues: list[dict[str, Any]] = field(default_factory=list)
    _next_id: int = 1

    def add(
        self,
        *,
        source_table: str,
        source_record_id: str,
        issue_code: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issue = {
            "issue_id": f"ISSUE-{self._next_id:05d}",
            "source_table": source_table,
            "source_record_id": str(source_record_id),
            "issue_code": issue_code,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
        self._next_id += 1
        self.issues.append(issue)
        return issue


@dataclass(frozen=True)
class PipelineResult:
    summary: dict[str, Any]
    output_paths: dict[str, Path]


def _clean_html_text(value: Any) -> str:
    if value is None:
        return ""
    text = unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = "".join(character for character in text if character >= " " or character in "\n\t")
    return re.sub(r"\s+", " ", text).strip()


def _parse_service_type_legend(interleaved_text: list[str]) -> dict[str, str]:
    legend: dict[str, str] = {}
    for fragment in interleaved_text:
        if not fragment.startswith("type:"):
            continue
        content = fragment.removeprefix("type:").strip()
        matches = list(re.finditer(r"(\d+)\s+", content))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            legend[match.group(1)] = content[match.end() : end].strip()
    return legend


def _provenance(
    *,
    source_type: str,
    source_file: str,
    source_record_id: str,
    cleaning_rule: str,
    quality_status: str,
    agent_eligible: bool,
) -> dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Unsupported source_type: {source_type}")
    if agent_eligible and quality_status != "verified":
        raise ValueError("Only verified records can be agent eligible")
    return {
        "source_type": source_type,
        "source_file": source_file,
        "source_record_id": source_record_id,
        "cleaning_rule": cleaning_rule,
        "quality_status": quality_status,
        "agent_eligible": agent_eligible,
    }


def _clean_service_catalog(
    tables: dict[str, list[dict[str, Any]]],
    interleaved_text: list[str],
    issues: IssueCollector,
) -> dict[str, Any]:
    vendors = tables["cms_homepage_service_vendor"]
    services = tables["cms_homepage_service"]
    vendor_ids = {row["id"] for row in vendors}
    legend = _parse_service_type_legend(interleaved_text)

    cleaned_vendors = [
        {
            "service_vendor_id": row["id"],
            "name": _clean_html_text(row["name"]),
            "description": _clean_html_text(row.get("description")),
            **_provenance(
                source_type="official_repaired",
                source_file=MASTER_FILE,
                source_record_id=f"vendor:{row['id']}",
                cleaning_rule="split_json_documents_and_normalize_text",
                quality_status="verified",
                agent_eligible=True,
            ),
        }
        for row in vendors
    ]

    cleaned_services: list[dict[str, Any]] = []
    image_counts = Counter(row.get("img_url") for row in services if row.get("img_url"))
    for row in services:
        service_id = row["id"]
        if row["service_vendor_id"] not in vendor_ids:
            issues.add(
                source_table="cms_homepage_service",
                source_record_id=str(service_id),
                issue_code="ORPHAN_SERVICE_VENDOR",
                severity="error",
                message="服務引用不存在的服務供應商",
                details={"service_vendor_id": row["service_vendor_id"]},
            )

        description = _clean_html_text(row.get("description"))
        if not description:
            issues.add(
                source_table="cms_homepage_service",
                source_record_id=str(service_id),
                issue_code="MISSING_SERVICE_DESCRIPTION",
                severity="warning",
                message="服務描述為空，搜尋只能使用名稱與人工整理的別名",
            )

        image_url = row.get("img_url")
        if image_url and image_counts[image_url] > 1:
            issues.add(
                source_table="cms_homepage_service",
                source_record_id=str(service_id),
                issue_code="REUSED_PLACEHOLDER_IMAGE",
                severity="warning",
                message="多個服務共用相同圖片網址",
            )

        aliases = SERVICE_ALIASES.get(service_id, [])
        name = _clean_html_text(row["name"])
        cleaned_services.append(
            {
                "service_id": service_id,
                "service_vendor_id": row["service_vendor_id"],
                "service_type": str(row["type"]).zfill(2),
                "service_type_name": legend.get(str(row["type"])),
                "name": name,
                "description": description,
                "image_url": image_url,
                "aliases": aliases,
                "aliases_source_type": "curated_config",
                "search_text": " ".join([name, description, *aliases]).strip(),
                "search_text_source_types": [
                    "official_repaired",
                    "curated_config",
                ],
                **_provenance(
                    source_type="official_repaired",
                    source_file=MASTER_FILE,
                    source_record_id=f"service:{service_id}",
                    cleaning_rule=(
                        "split_json_documents_normalize_text_and_add_curated_search_aliases"
                    ),
                    quality_status=(
                        "verified" if row["service_vendor_id"] in vendor_ids else "quarantined"
                    ),
                    agent_eligible=row["service_vendor_id"] in vendor_ids,
                ),
            }
        )

    return {
        "service_type_legend": dict(sorted(legend.items(), key=lambda item: int(item[0]))),
        "vendors": cleaned_vendors,
        "services": cleaned_services,
    }


def _feedback_references(
    feedback_rows: list[dict[str, Any]],
) -> tuple[set[int], set[int], bool]:
    topic_ids: set[int] = set()
    option_ids: set[int] = set()
    contains_plaintext_pii = False
    pii_pattern = re.compile(r"(09\d{8}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")

    for row in feedback_rows:
        content = parse_json_value(row.get("feedback_content"))
        if not isinstance(content, dict):
            continue
        serialized = json.dumps(content, ensure_ascii=False)
        contains_plaintext_pii = contains_plaintext_pii or bool(pii_pattern.search(serialized))
        for answer in content.get("data", []):
            topic_id = answer.get("topicId")
            if isinstance(topic_id, int):
                topic_ids.add(topic_id)
            for answer_item in answer.get("answerList", []):
                answer_id = answer_item.get("answerId")
                if isinstance(answer_id, int):
                    option_ids.add(answer_id)

    return topic_ids, option_ids, contains_plaintext_pii


def _audit_consultation(
    tables: dict[str, list[dict[str, Any]]],
    known_service_ids: set[int],
    issues: IssueCollector,
) -> list[dict[str, Any]]:
    forms = tables.get("pms_form", [])
    groups = tables.get("pms_form_group", [])
    topics = tables.get("pms_form_topic", [])
    media = tables.get("pms_topic_media", [])
    options = tables.get("pms_topic_option", [])
    relations = tables.get("pms_topic_county_district_relation", [])
    feedback = tables.get("pms_form_feedback", [])

    form_ids = {row["id"] for row in forms}
    group_ids = {row["id"] for row in groups}
    topic_ids = {row["id"] for row in topics}
    option_ids = {row["id"] for row in options}
    quarantine_reasons: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

    for form in forms:
        record_id = str(form["id"])
        if form.get("is_enable") != "1" or form.get("is_deleted") != "0":
            issue = issues.add(
                source_table="pms_form",
                source_record_id=record_id,
                issue_code="FORM_DISABLED_OR_DELETED",
                severity="error",
                message="唯一表單已停用或刪除，不能作為 Agent 正式表單",
            )
            quarantine_reasons[("pms_form", record_id)].add(issue["issue_code"])

    for topic in topics:
        record_id = str(topic["id"])
        if topic["form_id"] not in form_ids:
            issue = issues.add(
                source_table="pms_form_topic",
                source_record_id=record_id,
                issue_code="ORPHAN_TOPIC_FORM",
                severity="error",
                message="題目引用不存在的表單",
            )
            quarantine_reasons[("pms_form_topic", record_id)].add(issue["issue_code"])
        if topic["form_group_id"] not in group_ids:
            issue = issues.add(
                source_table="pms_form_topic",
                source_record_id=record_id,
                issue_code="ORPHAN_TOPIC_GROUP",
                severity="error",
                message="題目引用不存在的題組",
                details={"form_group_id": topic["form_group_id"]},
            )
            quarantine_reasons[("pms_form_topic", record_id)].add(issue["issue_code"])

    sort_counts = Counter((row["form_id"], row["sort"]) for row in topics)
    for (form_id, sort_order), count in sort_counts.items():
        if count > 1:
            issues.add(
                source_table="pms_form_topic",
                source_record_id=f"form:{form_id}:sort:{sort_order}",
                issue_code="DUPLICATE_TOPIC_SORT",
                severity="warning",
                message="同一表單有重複的題目排序",
                details={"count": count},
            )

    for row in media:
        record_id = str(row["id"])
        if row["topic_id"] not in topic_ids:
            issue = issues.add(
                source_table="pms_topic_media",
                source_record_id=record_id,
                issue_code="ORPHAN_MEDIA_TOPIC",
                severity="error",
                message="圖片引用不存在的題目",
                details={"topic_id": row["topic_id"]},
            )
            quarantine_reasons[("pms_topic_media", record_id)].add(issue["issue_code"])

    for row in options:
        record_id = str(row["id"])
        if row["topic_id"] not in topic_ids:
            issue = issues.add(
                source_table="pms_topic_option",
                source_record_id=record_id,
                issue_code="ORPHAN_OPTION_TOPIC",
                severity="error",
                message="選項引用不存在的題目",
                details={"topic_id": row["topic_id"]},
            )
            quarantine_reasons[("pms_topic_option", record_id)].add(issue["issue_code"])

    for row in relations:
        record_id = (
            f"{row['form_id']}:{row['topic_id']}:{row['county_code']}:{row['district_code']}"
        )
        if row["topic_id"] not in topic_ids:
            issue = issues.add(
                source_table="pms_topic_county_district_relation",
                source_record_id=record_id,
                issue_code="ORPHAN_RELATION_TOPIC",
                severity="error",
                message="地區關聯引用不存在的題目",
            )
            quarantine_reasons[("pms_topic_county_district_relation", record_id)].add(
                issue["issue_code"]
            )

    feedback_topic_ids, feedback_option_ids, contains_plaintext_pii = _feedback_references(feedback)
    missing_feedback_topics = sorted(feedback_topic_ids - topic_ids)
    missing_feedback_options = sorted(feedback_option_ids - option_ids)

    for row in feedback:
        record_id = str(row["feedback_no"])
        if row["service_id"] not in known_service_ids:
            issue = issues.add(
                source_table="pms_form_feedback",
                source_record_id=record_id,
                issue_code="ORPHAN_FEEDBACK_SERVICE",
                severity="error",
                message="諮詢回饋引用不存在的服務",
                details={"service_id": row["service_id"]},
            )
            quarantine_reasons[("pms_form_feedback", record_id)].add(issue["issue_code"])
        if missing_feedback_topics:
            issue = issues.add(
                source_table="pms_form_feedback",
                source_record_id=record_id,
                issue_code="MISSING_FEEDBACK_TOPICS",
                severity="error",
                message="回饋內容引用範例資料未提供的題目",
                details={"topic_ids": missing_feedback_topics},
            )
            quarantine_reasons[("pms_form_feedback", record_id)].add(issue["issue_code"])
        if missing_feedback_options:
            issue = issues.add(
                source_table="pms_form_feedback",
                source_record_id=record_id,
                issue_code="MISSING_FEEDBACK_OPTIONS",
                severity="error",
                message="回饋內容引用範例資料未提供的選項",
                details={"option_ids": missing_feedback_options},
            )
            quarantine_reasons[("pms_form_feedback", record_id)].add(issue["issue_code"])
        if contains_plaintext_pii:
            issue = issues.add(
                source_table="pms_form_feedback",
                source_record_id=record_id,
                issue_code="PLAINTEXT_PII_IN_FEEDBACK_JSON",
                severity="error",
                message="feedback_content 含明文電話或 Email，不得提供給 Agent",
            )
            quarantine_reasons[("pms_form_feedback", record_id)].add(issue["issue_code"])

    # The supplied consultation package is one internally inconsistent test snapshot.
    for table_name, rows in tables.items():
        for index, row in enumerate(rows):
            composite_parts = (
                row.get("form_id"),
                row.get("topic_id"),
                row.get("county_code"),
                row.get("district_code"),
            )
            composite_id = (
                ":".join(str(value) for value in composite_parts)
                if any(value is not None for value in composite_parts)
                else None
            )
            record_id = str(row.get("id") or row.get("feedback_no") or composite_id or index)
            quarantine_reasons[(table_name, record_id)].add("UNUSABLE_TEST_CONSULTATION_SNAPSHOT")

    return [
        {
            "source_table": table_name,
            "source_record_id": record_id,
            "issue_codes": sorted(reason_codes),
            "raw_preserved_in": CONSULTATION_FILE,
            "raw_payload_included": False,
        }
        for (table_name, record_id), reason_codes in sorted(quarantine_reasons.items())
    ]


def _safe_order_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "item_index": index,
            "item_name": str(item),
            "quantity": None,
            "unit_price": None,
            "item_amount": None,
            "unit": None,
            "attributes": [],
        }

    def first(*keys: str) -> Any:
        for key in keys:
            if key in item and item[key] is not None:
                return item[key]
        return None

    attributes = first("attribute", "attributes")
    if not isinstance(attributes, list):
        attributes = [attributes] if isinstance(attributes, (str, int, float)) else []

    return {
        "item_index": index,
        "item_name": first("itemName", "name", "goods_name", "product_name", "title"),
        "quantity": first("quantity", "qty", "count"),
        "unit_price": first("unitPrice", "unit_price", "price"),
        "item_amount": first("itemAmount", "item_amount", "amount", "total"),
        "unit": first("unit"),
        "attributes": [str(value) for value in attributes],
    }


def normalize_order_items(value: Any) -> tuple[list[dict[str, Any]], str]:
    parsed = parse_json_value(value)
    shape = "missing"
    raw_items: list[Any] = []

    if isinstance(parsed, list):
        shape = "list"
        raw_items = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("orderItems"), list):
        shape = "object_orderItems"
        raw_items = parsed["orderItems"]
    elif isinstance(parsed, dict) and isinstance(parsed.get("goods"), list):
        shape = "object_goods"
        raw_items = parsed["goods"]
    elif isinstance(parsed, dict) and isinstance(parsed.get("goods"), dict):
        shape = "object_single_goods"
        raw_items = [parsed["goods"]]
    elif parsed is not None:
        shape = type(parsed).__name__

    return [_safe_order_item(item, index) for index, item in enumerate(raw_items, 1)], shape


def _record_order_issue(
    issues: IssueCollector,
    record_id: str,
    error_codes: set[str],
    warning_codes: set[str],
    code: str,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    issues.add(
        source_table="mms_order_record",
        source_record_id=record_id,
        issue_code=code,
        severity=severity,
        message=message,
        details=details,
    )
    (error_codes if severity == "error" else warning_codes).add(code)


def _clean_orders(
    order_rows: list[dict[str, Any]],
    known_service_ids: set[int],
    known_vendor_ids: set[int],
    issues: IssueCollector,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    cleaned: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    shape_counts: Counter[str] = Counter()
    duplicate_record_ids = {
        record_id
        for record_id, count in Counter(row["record_id"] for row in order_rows).items()
        if count > 1
    }
    duplicate_order_keys = {
        key
        for key, count in Counter(
            (row["order_no"], row["service_id"]) for row in order_rows
        ).items()
        if count > 1
    }

    for row in order_rows:
        record_id = str(row["record_id"])
        error_codes: set[str] = set()
        warning_codes: set[str] = set()
        add_issue = partial(
            _record_order_issue,
            issues,
            record_id,
            error_codes,
            warning_codes,
        )

        if row["record_id"] in duplicate_record_ids:
            add_issue("DUPLICATE_ORDER_RECORD_ID", "error", "訂單 record_id 重複")
        if (row["order_no"], row["service_id"]) in duplicate_order_keys:
            add_issue(
                "DUPLICATE_ORDER_NO_SERVICE",
                "error",
                "訂單編號與服務 ID 組合重複",
            )
        if row["service_id"] not in known_service_ids:
            add_issue(
                "ORPHAN_ORDER_SERVICE",
                "error",
                "訂單引用不存在的服務",
                {"service_id": row["service_id"]},
            )
        if row["service_vendor_id"] not in known_vendor_ids:
            add_issue(
                "ORPHAN_ORDER_VENDOR",
                "error",
                "訂單引用不存在的服務供應商",
                {"service_vendor_id": row["service_vendor_id"]},
            )

        order_type = row["order_type"]
        order_status = row["order_status"]
        allowed_statuses = ALLOWED_ORDER_STATUSES.get(order_type)
        if allowed_statuses is None:
            add_issue(
                "UNDEFINED_ORDER_TYPE",
                "error",
                "訂單類型未出現在 schema 定義",
                {"order_type": order_type},
            )
        elif order_status not in allowed_statuses:
            add_issue(
                "INVALID_ORDER_TYPE_STATUS",
                "error",
                "訂單狀態不適用於此訂單類型",
                {"order_type": order_type, "order_status": order_status},
            )

        if order_status in {"70", "80"} and not row.get("complete_time"):
            add_issue(
                "COMPLETED_WITHOUT_COMPLETE_TIME",
                "error",
                "完成狀態缺少完成時間",
            )
        if order_status == "90" and not row.get("cancel_time"):
            add_issue(
                "CANCELLED_WITHOUT_CANCEL_TIME",
                "error",
                "取消狀態缺少取消時間",
            )
        if order_status in {"98", "99"} and float(row.get("refund_amount") or 0) == 0:
            add_issue(
                "REFUND_STATUS_WITH_ZERO_AMOUNT",
                "warning",
                "退款狀態的退款金額為零，需業務規則確認",
            )

        pii_fields = ("member_name", "member_phone", "member_email")
        if any("\ufffd" in str(row.get(field) or "") for field in pii_fields):
            add_issue(
                "CORRUPTED_ENCRYPTED_PII",
                "warning",
                "密文匯出後包含替代字元，清洗輸出已移除",
            )

        normalized_items, item_shape = normalize_order_items(row.get("order_items"))
        shape_counts[item_shape] += 1
        safe_row = {column: row.get(column) for column in SAFE_ORDER_COLUMNS}
        safe_row.update(
            {
                "order_items": normalized_items,
                "original_order_items_shape": item_shape,
                "vendor_data_redacted": row.get("vendor_data") is not None,
                "pii_redacted": True,
                "source_type": "official_repaired",
                "source_file": ORDER_JSON_FILE,
                "source_record_id": f"order:{record_id}",
                "cleaning_rule": (
                    "select_json_source_redact_pii_normalize_order_items_validate_state"
                ),
                "quality_status": (
                    "quarantined" if error_codes else "review" if warning_codes else "verified"
                ),
                # Historical examples have no authenticated user/case link.
                "agent_eligible": False,
                "issue_codes": sorted(error_codes | warning_codes),
            }
        )
        cleaned.append(safe_row)

        if error_codes:
            quarantine.append(
                {
                    "source_table": "mms_order_record",
                    "source_record_id": record_id,
                    "issue_codes": sorted(error_codes),
                    "raw_preserved_in": ORDER_JSON_FILE,
                    "raw_payload_included": False,
                }
            )

    summary = {
        "rows": len(order_rows),
        "verified": sum(row["quality_status"] == "verified" for row in cleaned),
        "review": sum(row["quality_status"] == "review" for row in cleaned),
        "quarantined": sum(row["quality_status"] == "quarantined" for row in cleaned),
        "agent_eligible": sum(bool(row["agent_eligible"]) for row in cleaned),
        **{f"shape_{key}": value for key, value in sorted(shape_counts.items())},
    }
    return cleaned, quarantine, summary


def _build_source_mappings(
    known_service_ids: set[int],
    known_vendor_ids: set[int],
    consultation_tables: dict[str, list[dict[str, Any]]],
    order_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    observed_service_ids = {
        row["service_id"] for row in consultation_tables.get("pms_form_feedback", [])
    } | {row["service_id"] for row in order_rows}
    observed_vendor_ids = {row["service_vendor_id"] for row in order_rows}
    observed_order_types = {row["order_type"] for row in order_rows}
    mappings: list[dict[str, Any]] = []

    for service_id in sorted(known_service_ids | observed_service_ids):
        verified = service_id in known_service_ids
        mappings.append(
            {
                "entity_type": "service",
                "source_system": "organizer_dataset",
                "source_id": str(service_id),
                "canonical_id": str(service_id) if verified else None,
                "candidate_canonical_id": "17" if service_id == 7 else None,
                "mapping_status": "verified" if verified else "unresolved",
                "mapping_method": (
                    "same_id_in_master"
                    if verified
                    else "semantic_hint_only"
                    if service_id == 7
                    else "no_evidence"
                ),
                "evidence": (
                    {"note": "回饋內容為馬桶問題，但不足以證明 7 等於 17"}
                    if service_id == 7
                    else {}
                ),
                "agent_eligible": verified,
            }
        )

    for vendor_id in sorted(known_vendor_ids | observed_vendor_ids):
        verified = vendor_id in known_vendor_ids
        mappings.append(
            {
                "entity_type": "service_vendor",
                "source_system": "organizer_dataset",
                "source_id": str(vendor_id),
                "canonical_id": str(vendor_id) if verified else None,
                "candidate_canonical_id": None,
                "mapping_status": "verified" if verified else "unresolved",
                "mapping_method": "same_id_in_master" if verified else "no_evidence",
                "evidence": {},
                "agent_eligible": verified,
            }
        )

    for order_type in sorted(set(ALLOWED_ORDER_STATUSES) | observed_order_types):
        verified = order_type in ALLOWED_ORDER_STATUSES
        mappings.append(
            {
                "entity_type": "order_type",
                "source_system": "organizer_dataset",
                "source_id": order_type,
                "canonical_id": order_type if verified else None,
                "candidate_canonical_id": None,
                "mapping_status": "verified" if verified else "unresolved",
                "mapping_method": "documented_in_schema" if verified else "not_documented",
                "evidence": {},
                "agent_eligible": verified,
            }
        )

    return mappings


def _render_report(
    *,
    generated_at: str,
    source_manifest: list[dict[str, Any]],
    table_counts: dict[str, int],
    source_comparison: dict[str, Any],
    location_summary: dict[str, int],
    order_summary: dict[str, int],
    issues: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
) -> str:
    issue_code_counts = Counter(issue["issue_code"] for issue in issues)
    severity_counts = Counter(issue["severity"] for issue in issues)
    unresolved = [mapping for mapping in mappings if mapping["mapping_status"] == "unresolved"]

    lines = [
        "# B+ 資料品質報告",
        "",
        f"產生時間：`{generated_at}`",
        "",
        "## 結論",
        "",
        "- 原始檔保持不變。",
        "- 訂單 JSON 與 CSV 經語意比較後只選 JSON 作為權威來源。",
        "- 無法確認的服務、供應商與訂單類型保留原值並隔離。",
        "- 官方 `service_id=17` 為水電修繕 MVP 的可信主軸。",
        "- 水電表單標記為 `curated_config`；師傅、時段、案件與訂單標記為 `synthetic`。",
        "- 歷史訂單已去除會員識別與密文，不提供給 Agent。",
        "",
        "## 原始檔",
        "",
        "| 檔案 | SHA-256 |",
        "|---|---|",
    ]
    lines.extend(f"| `{item['file']}` | `{item['sha256']}` |" for item in source_manifest)
    lines.extend(
        [
            "",
            "## 資料表筆數",
            "",
            "| 資料表 | 筆數 |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| `{name}` | {count} |" for name, count in sorted(table_counts.items()))
    lines.extend(
        [
            "",
            "## 訂單雙來源驗證",
            "",
            f"- JSON：{source_comparison['json_rows']} 筆",
            f"- CSV：{source_comparison['csv_rows']} 筆",
            f"- Record IDs 相同：{source_comparison['same_record_ids']}",
            f"- 欄位語意一致：{source_comparison['semantically_identical']}",
            "",
            "## 行政區整合",
            "",
        ]
    )
    lines.extend(f"- `{name}`：{value}" for name, value in location_summary.items())
    lines.extend(
        [
            "",
            (
                "外部參考來源：[內政部國土測繪中心行政區 API]"
                "(https://data.gov.tw/dataset/102011)，資料標記為 `external_reference`。"
            ),
            "",
            "## 歷史訂單處理",
            "",
        ]
    )
    lines.extend(f"- `{name}`：{value}" for name, value in order_summary.items())
    lines.extend(
        [
            "",
            "## 品質問題",
            "",
            f"- Error：{severity_counts.get('error', 0)}",
            f"- Warning：{severity_counts.get('warning', 0)}",
            "",
            "| 問題代碼 | 筆數 |",
            "|---|---:|",
        ]
    )
    lines.extend(f"| `{code}` | {count} |" for code, count in sorted(issue_code_counts.items()))
    lines.extend(
        [
            "",
            "## 無法確認的代碼",
            "",
            "| 類型 | 來源 ID | 候選 ID | 狀態 | 處理 |",
            "|---|---|---|---|---|",
        ]
    )
    lines.extend(
        (
            f"| {row['entity_type']} | `{row['source_id']}` | "
            f"`{row['candidate_canonical_id'] or ''}` | {row['mapping_status']} | "
            "保留原值、隔離、不供 Agent 使用 |"
        )
        for row in unresolved
    )
    lines.extend(
        [
            "",
            "## Agent 資料閘門",
            "",
            (
                "只有 `quality_status=verified` 且 `agent_eligible=true` 的資料可進入 "
                "`agent` schema views。`quarantine`、歷史個資與 unresolved mapping 不會被暴露。"
            ),
        ]
    )
    return "\n".join(lines)


def run_pipeline(
    *,
    source_dir: Path,
    output_dir: Path,
    quarantine_dir: Path,
    report_path: Path,
    reference_path: Path,
    reference_date: date,
) -> PipelineResult:
    missing_files = [
        filename for filename in REQUIRED_SOURCE_FILES if not (source_dir / filename).exists()
    ]
    if missing_files:
        raise FileNotFoundError(f"Missing source files: {', '.join(missing_files)}")
    if not reference_path.exists():
        raise FileNotFoundError(
            f"Missing external reference snapshot: {reference_path}. "
            "Run scripts/fetch_admin_reference.py first."
        )

    issues = IssueCollector()
    master_tables, master_junk = load_fragmented_tables(source_dir / MASTER_FILE)
    county_tables, county_junk = load_fragmented_tables(source_dir / COUNTY_FILE)
    consultation_tables, consultation_junk = load_fragmented_tables(source_dir / CONSULTATION_FILE)
    order_rows = load_json_table(source_dir / ORDER_JSON_FILE, "mms_order_record")
    order_csv_rows = load_csv_rows(source_dir / ORDER_CSV_FILE)
    external_reference = load_admin_reference(reference_path)

    for filename, junk in (
        (MASTER_FILE, master_junk),
        (COUNTY_FILE, county_junk),
        (CONSULTATION_FILE, consultation_junk),
    ):
        if junk:
            issues.add(
                source_table="source_file",
                source_record_id=filename,
                issue_code="FRAGMENTED_JSON_DOCUMENT",
                severity="warning",
                message="檔案不是單一 JSON document，已使用可追蹤解析規則拆分",
                details={"interleaved_text_blocks": len(junk)},
            )

    service_catalog = _clean_service_catalog(master_tables, master_junk, issues)
    known_service_ids = {row["service_id"] for row in service_catalog["services"]}
    known_vendor_ids = {row["service_vendor_id"] for row in service_catalog["vendors"]}

    locations, location_issues, location_summary = merge_locations(
        county_tables["sys_county"],
        county_tables["sys_district"],
        external_reference,
    )
    for location_issue in location_issues:
        issues.add(
            source_table="sys_district",
            source_record_id=location_issue["source_record_id"],
            issue_code=location_issue["issue_code"],
            severity=location_issue["severity"],
            message=location_issue["message"],
        )

    consultation_quarantine = _audit_consultation(
        consultation_tables,
        known_service_ids,
        issues,
    )
    source_comparison = compare_order_sources(order_rows, order_csv_rows)
    if not source_comparison["semantically_identical"]:
        issues.add(
            source_table="mms_order_record",
            source_record_id="JSON-vs-CSV",
            issue_code="ORDER_SOURCE_MISMATCH",
            severity="error",
            message="訂單 JSON 與 CSV 不一致，無法自動選定權威來源",
            details=source_comparison,
        )

    cleaned_orders, order_quarantine, order_summary = _clean_orders(
        order_rows,
        known_service_ids,
        known_vendor_ids,
        issues,
    )
    mappings = _build_source_mappings(
        known_service_ids,
        known_vendor_ids,
        consultation_tables,
        order_rows,
    )
    curated_form = build_curated_repair_form()
    demo_seed = build_demo_seed(locations, reference_date)

    table_counts: dict[str, int] = {}
    for table_group in (master_tables, county_tables, consultation_tables):
        table_counts.update({name: len(rows) for name, rows in table_group.items()})
    table_counts["mms_order_record"] = len(order_rows)

    source_manifest = [
        {
            "file": filename,
            "sha256": sha256_file(source_dir / filename),
        }
        for filename in REQUIRED_SOURCE_FILES
    ]
    generated_at = datetime.now(UTC).isoformat()
    full_quarantine = consultation_quarantine + order_quarantine
    issue_counts = Counter(issue["issue_code"] for issue in issues.issues)
    severity_counts = Counter(issue["severity"] for issue in issues.issues)

    summary = {
        "pipeline": "b_plus",
        "generated_at": generated_at,
        "reference_date": reference_date.isoformat(),
        "source_manifest": source_manifest,
        "table_counts": dict(sorted(table_counts.items())),
        "order_source_comparison": source_comparison,
        "location_summary": location_summary,
        "order_summary": order_summary,
        "issue_counts": dict(sorted(issue_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "issues": issues.issues,
        "quarantine_records": len(full_quarantine),
        "source_mappings": len(mappings),
        "unresolved_mappings": sum(row["mapping_status"] == "unresolved" for row in mappings),
    }

    output_paths = {
        "service_catalog": output_dir / "core_service_catalog.json",
        "locations": output_dir / "core_locations.json",
        "repair_form": output_dir / "curated_repair_form.json",
        "demo_seed": output_dir / "demo_seed.json",
        "source_mappings": output_dir / "source_mappings.json",
        "quality_summary": output_dir / "data_quality_summary.json",
        "historical_orders": output_dir / "_local_historical_orders_redacted.json",
        "quarantine": quarantine_dir / "_local_quarantine_index.json",
        "report": report_path,
    }
    write_json(output_paths["service_catalog"], service_catalog)
    write_json(output_paths["locations"], {"locations": locations})
    write_json(output_paths["repair_form"], curated_form)
    write_json(output_paths["demo_seed"], demo_seed)
    write_json(output_paths["source_mappings"], {"mappings": mappings})
    write_json(output_paths["quality_summary"], summary)
    write_json(output_paths["historical_orders"], {"orders": cleaned_orders})
    write_json(output_paths["quarantine"], {"records": full_quarantine})
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(
            generated_at=generated_at,
            source_manifest=source_manifest,
            table_counts=table_counts,
            source_comparison=source_comparison,
            location_summary=location_summary,
            order_summary=order_summary,
            issues=issues.issues,
            mappings=mappings,
        )
        + "\n",
        encoding="utf-8",
    )

    return PipelineResult(summary=summary, output_paths=output_paths)
