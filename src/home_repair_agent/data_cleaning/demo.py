from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any


TAIPEI_TIMEZONE = timezone(timedelta(hours=8))


def _curated_provenance(source_record_id: str) -> dict[str, Any]:
    return {
        "source_type": "curated_config",
        "source_file": "src/home_repair_agent/data_cleaning/demo.py",
        "source_record_id": source_record_id,
        "cleaning_rule": "define_versioned_water_repair_form",
        "quality_status": "verified",
        "agent_eligible": True,
    }


def _synthetic_provenance(source_record_id: str) -> dict[str, Any]:
    return {
        "source_type": "synthetic",
        "source_file": "src/home_repair_agent/data_cleaning/demo.py",
        "source_record_id": source_record_id,
        "cleaning_rule": "generate_deterministic_demo_seed",
        "quality_status": "verified",
        "agent_eligible": True,
    }


def build_curated_repair_form() -> dict[str, Any]:
    form = {
        "form_key": "repair_form_v1",
        "service_id": 17,
        "version": 1,
        "name": "居家水電修繕諮詢單",
        "description": "蒐集水電問題、服務地點、照片與可服務時間。",
        "is_active": True,
        **_curated_provenance("form:repair_form_v1"),
    }
    topics = [
        {
            "topic_key": "issue_category",
            "input_type": "single_select",
            "title": "需要處理的問題",
            "is_required": True,
            "sort_order": 1,
            "config": {},
        },
        {
            "topic_key": "issue_description",
            "input_type": "long_text",
            "title": "請描述目前的狀況",
            "is_required": True,
            "sort_order": 2,
            "config": {"max_length": 1000},
        },
        {
            "topic_key": "service_location",
            "input_type": "location",
            "title": "服務地點",
            "is_required": True,
            "sort_order": 3,
            "config": {},
        },
        {
            "topic_key": "water_shutoff",
            "input_type": "single_select",
            "title": "目前是否可以關閉水源",
            "is_required": True,
            "sort_order": 4,
            "config": {},
        },
        {
            "topic_key": "preferred_date",
            "input_type": "date",
            "title": "希望服務日期",
            "is_required": True,
            "sort_order": 5,
            "config": {"minimum_offset_days": 1, "maximum_offset_days": 30},
        },
        {
            "topic_key": "preferred_time",
            "input_type": "single_select",
            "title": "希望服務時段",
            "is_required": True,
            "sort_order": 6,
            "config": {},
        },
        {
            "topic_key": "photos",
            "input_type": "media",
            "title": "現場照片",
            "is_required": False,
            "sort_order": 7,
            "config": {"minimum": 0, "maximum": 5},
        },
        {
            "topic_key": "contact_method",
            "input_type": "single_select",
            "title": "偏好的聯絡方式",
            "is_required": True,
            "sort_order": 8,
            "config": {},
        },
    ]
    options = [
        ("issue_category", "faucet_leak", "水龍頭漏水", 1),
        ("issue_category", "toilet_issue", "馬桶堵塞或無法沖水", 2),
        ("issue_category", "pipe_issue", "水管漏水或堵塞", 3),
        ("issue_category", "electrical_issue", "插座、燈具或電路問題", 4),
        ("issue_category", "other", "其他水電問題", 5),
        ("water_shutoff", "yes", "可以", 1),
        ("water_shutoff", "no", "不可以", 2),
        ("water_shutoff", "unknown", "不確定", 3),
        ("preferred_time", "morning", "上午", 1),
        ("preferred_time", "afternoon", "下午", 2),
        ("preferred_time", "evening", "晚上", 3),
        ("contact_method", "app", "App 訊息", 1),
        ("contact_method", "phone", "電話", 2),
        ("contact_method", "email", "Email", 3),
    ]
    return {
        "form": form,
        "topics": [
            {
                **topic,
                "form_key": form["form_key"],
                **_curated_provenance(f"topic:{topic['topic_key']}"),
            }
            for topic in topics
        ],
        "options": [
            {
                "option_key": f"{topic_key}:{option_key}",
                "form_key": form["form_key"],
                "topic_key": topic_key,
                "value": option_key,
                "label": label,
                "sort_order": sort_order,
                **_curated_provenance(f"option:{topic_key}:{option_key}"),
            }
            for topic_key, option_key, label, sort_order in options
        ],
    }


def _location_id(locations: list[dict[str, Any]], full_name: str) -> str:
    for location in locations:
        if location["full_name"] == full_name:
            return location["location_id"]
    raise ValueError(f"Demo location is unavailable: {full_name}")


def _iso_at(day: date, hour: int) -> str:
    return datetime.combine(day, time(hour=hour), tzinfo=TAIPEI_TIMEZONE).isoformat()


def build_demo_seed(
    locations: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, Any]:
    daan = _location_id(locations, "台北市大安區")
    xinyi = _location_id(locations, "台北市信義區")
    zhongzheng = _location_id(locations, "台北市中正區")
    demo_day = reference_date

    providers = [
        {
            "provider_id": "SYN-PROVIDER-001",
            "display_name": "安心修繕 A 組",
            "service_id": 17,
            "rating": 4.8,
            "completed_jobs": 128,
            "base_inspection_fee": 300,
        },
        {
            "provider_id": "SYN-PROVIDER-002",
            "display_name": "城市水電 B 組",
            "service_id": 17,
            "rating": 4.6,
            "completed_jobs": 86,
            "base_inspection_fee": 250,
        },
        {
            "provider_id": "SYN-PROVIDER-003",
            "display_name": "即刻修繕 C 組",
            "service_id": 17,
            "rating": 4.7,
            "completed_jobs": 64,
            "base_inspection_fee": 350,
        },
    ]
    providers = [
        {
            **provider,
            **_synthetic_provenance(f"provider:{provider['provider_id']}"),
        }
        for provider in providers
    ]

    service_areas = [
        {"provider_id": "SYN-PROVIDER-001", "location_id": daan},
        {"provider_id": "SYN-PROVIDER-001", "location_id": xinyi},
        {"provider_id": "SYN-PROVIDER-002", "location_id": daan},
        {"provider_id": "SYN-PROVIDER-002", "location_id": zhongzheng},
        {"provider_id": "SYN-PROVIDER-003", "location_id": xinyi},
        {"provider_id": "SYN-PROVIDER-003", "location_id": zhongzheng},
    ]
    availability = [
        {
            "availability_id": "SYN-SLOT-001",
            "provider_id": "SYN-PROVIDER-001",
            "starts_at": _iso_at(demo_day, 13),
            "ends_at": _iso_at(demo_day, 17),
            "status": "available",
        },
        {
            "availability_id": "SYN-SLOT-002",
            "provider_id": "SYN-PROVIDER-002",
            "starts_at": _iso_at(demo_day, 9),
            "ends_at": _iso_at(demo_day, 12),
            "status": "available",
        },
        {
            "availability_id": "SYN-SLOT-003",
            "provider_id": "SYN-PROVIDER-003",
            "starts_at": _iso_at(demo_day, 14),
            "ends_at": _iso_at(demo_day, 18),
            "status": "available",
        },
    ]

    consultation_case = {
        "case_id": "SYN-CASE-001",
        "service_id": 17,
        "form_key": "repair_form_v1",
        "location_id": daan,
        "problem_summary": "廚房水龍頭持續漏水",
        "preferred_start": _iso_at(demo_day, 13),
        "preferred_end": _iso_at(demo_day, 17),
        "status": "matched",
        "answers": {
            "issue_category": "faucet_leak",
            "issue_description": "廚房水龍頭關閉後仍持續滴水。",
            "water_shutoff": "yes",
            "preferred_time": "afternoon",
            "contact_method": "app",
            "photos": [],
        },
        **_synthetic_provenance("case:SYN-CASE-001"),
    }
    match_result = {
        "match_id": "SYN-MATCH-001",
        "case_id": consultation_case["case_id"],
        "provider_id": "SYN-PROVIDER-001",
        "availability_id": "SYN-SLOT-001",
        "score": 0.96,
        "reasons": ["服務項目符合", "可服務大安區", "週六下午有空"],
        "status": "selected",
        **_synthetic_provenance("match:SYN-MATCH-001"),
    }
    order = {
        "order_no": "SYN-ORDER-001",
        "case_id": consultation_case["case_id"],
        "match_id": match_result["match_id"],
        "provider_id": match_result["provider_id"],
        "service_id": 17,
        "order_type": "01",
        "order_status": "11",
        "scheduled_start": _iso_at(demo_day, 13),
        "scheduled_end": _iso_at(demo_day, 17),
        "deposit_amount": 300,
        "final_amount": 300,
        "currency": "TWD",
        **_synthetic_provenance("order:SYN-ORDER-001"),
    }
    order_items = [
        {
            "order_no": order["order_no"],
            "item_no": 1,
            "item_name": "現場勘驗費",
            "quantity": 1,
            "unit_price": 300,
            "item_amount": 300,
            **_synthetic_provenance("order-item:SYN-ORDER-001:1"),
        }
    ]

    return {
        "reference_date": reference_date.isoformat(),
        "providers": providers,
        "provider_service_areas": [
            {
                **item,
                **_synthetic_provenance(
                    f"provider-area:{item['provider_id']}:{item['location_id']}"
                ),
            }
            for item in service_areas
        ],
        "provider_availability": [
            {
                **item,
                **_synthetic_provenance(
                    f"availability:{item['availability_id']}"
                ),
            }
            for item in availability
        ],
        "consultation_cases": [consultation_case],
        "match_results": [match_result],
        "orders": [order],
        "order_items": order_items,
    }
