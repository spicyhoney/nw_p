from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def apply_migrations(
    *,
    database_url: str,
    project_root: Path,
) -> list[str]:
    """Apply every bundled SQL migration in filename order."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL migrations require psycopg. "
            "Install the data dependencies with: pip install -e .[data]"
        ) from exc

    with psycopg.connect(database_url) as connection, connection.cursor() as cursor:
        return _apply_migrations(cursor, project_root=project_root)


def _apply_migrations(cursor: Any, *, project_root: Path) -> list[str]:
    migration_dir = project_root / "sql" / "migrations"
    migration_paths = sorted(migration_dir.glob("*.sql"))
    if not migration_paths:
        raise RuntimeError(f"No SQL migrations found in {migration_dir}")

    for migration_path in migration_paths:
        cursor.execute(migration_path.read_text(encoding="utf-8"))
    return [migration_path.name for migration_path in migration_paths]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _execute_many(cursor: Any, statement: str, rows: list[dict[str, Any]]) -> int:
    if rows:
        cursor.executemany(statement, rows)
    return len(rows)


def load_pipeline_outputs(
    *,
    database_url: str,
    project_root: Path,
    output_paths: dict[str, Path],
    apply_migration: bool = True,
) -> dict[str, int]:
    """Load B+ outputs into PostgreSQL without exposing raw source payloads."""
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL loader requires psycopg. "
            "Install the data dependencies with: pip install -e .[data]"
        ) from exc

    service_catalog = _read_json(output_paths["service_catalog"])
    locations = _read_json(output_paths["locations"])["locations"]
    repair_form = _read_json(output_paths["repair_form"])
    demo_seed = _read_json(output_paths["demo_seed"])
    mappings = _read_json(output_paths["source_mappings"])["mappings"]
    quality_summary = _read_json(output_paths["quality_summary"])
    quarantine = _read_json(output_paths["quarantine"])["records"]

    counts: dict[str, int] = {}
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            if apply_migration:
                _apply_migrations(cursor, project_root=project_root)

            counts["core.service_vendor"] = _execute_many(
                cursor,
                """
                INSERT INTO core.service_vendor (
                    service_vendor_id, name, description, source_type, source_file,
                    source_record_id, cleaning_rule, quality_status, agent_eligible
                ) VALUES (
                    %(service_vendor_id)s, %(name)s, %(description)s, %(source_type)s,
                    %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
                    %(quality_status)s, %(agent_eligible)s
                )
                ON CONFLICT (service_vendor_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                service_catalog["vendors"],
            )
            service_rows = [
                {
                    **row,
                    "aliases_json": json.dumps(row["aliases"], ensure_ascii=False),
                    "search_text_source_types_json": json.dumps(
                        row["search_text_source_types"], ensure_ascii=False
                    ),
                }
                for row in service_catalog["services"]
            ]
            counts["core.service"] = _execute_many(
                cursor,
                """
                INSERT INTO core.service (
                    service_id, service_vendor_id, service_type, service_type_name,
                    name, description, image_url, aliases, aliases_source_type,
                    search_text, search_text_source_types, source_type, source_file,
                    source_record_id, cleaning_rule, quality_status, agent_eligible
                ) VALUES (
                    %(service_id)s, %(service_vendor_id)s, %(service_type)s,
                    %(service_type_name)s, %(name)s, %(description)s, %(image_url)s,
                    %(aliases_json)s::jsonb, %(aliases_source_type)s, %(search_text)s,
                    %(search_text_source_types_json)s::jsonb, %(source_type)s,
                    %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
                    %(quality_status)s, %(agent_eligible)s
                )
                ON CONFLICT (service_id) DO UPDATE SET
                    service_vendor_id = EXCLUDED.service_vendor_id,
                    service_type = EXCLUDED.service_type,
                    service_type_name = EXCLUDED.service_type_name,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    image_url = EXCLUDED.image_url,
                    aliases = EXCLUDED.aliases,
                    aliases_source_type = EXCLUDED.aliases_source_type,
                    search_text = EXCLUDED.search_text,
                    search_text_source_types = EXCLUDED.search_text_source_types,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                service_rows,
            )
            counts["core.location"] = _execute_many(
                cursor,
                """
                INSERT INTO core.location (
                    location_id, county_name, district_name, full_name, postal_code,
                    organizer_county_code, organizer_district_code, nlsc_county_code,
                    nlsc_county_code01, nlsc_town_code, nlsc_town_code01, source_type,
                    source_file, source_record_id, cleaning_rule, quality_status,
                    agent_eligible
                ) VALUES (
                    %(location_id)s, %(county_name)s, %(district_name)s, %(full_name)s,
                    %(postal_code)s, %(organizer_county_code)s,
                    %(organizer_district_code)s, %(nlsc_county_code)s,
                    %(nlsc_county_code01)s, %(nlsc_town_code)s,
                    %(nlsc_town_code01)s, %(source_type)s, %(source_file)s,
                    %(source_record_id)s, %(cleaning_rule)s, %(quality_status)s,
                    %(agent_eligible)s
                )
                ON CONFLICT (location_id) DO UPDATE SET
                    county_name = EXCLUDED.county_name,
                    district_name = EXCLUDED.district_name,
                    full_name = EXCLUDED.full_name,
                    postal_code = EXCLUDED.postal_code,
                    organizer_county_code = EXCLUDED.organizer_county_code,
                    organizer_district_code = EXCLUDED.organizer_district_code,
                    nlsc_county_code = EXCLUDED.nlsc_county_code,
                    nlsc_county_code01 = EXCLUDED.nlsc_county_code01,
                    nlsc_town_code = EXCLUDED.nlsc_town_code,
                    nlsc_town_code01 = EXCLUDED.nlsc_town_code01,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                locations,
            )

            mapping_rows = [
                {**row, "evidence_json": json.dumps(row["evidence"], ensure_ascii=False)}
                for row in mappings
            ]
            counts["core.source_mapping"] = _execute_many(
                cursor,
                """
                INSERT INTO core.source_mapping (
                    entity_type, source_system, source_id, canonical_id,
                    candidate_canonical_id, mapping_status, mapping_method, evidence,
                    agent_eligible
                ) VALUES (
                    %(entity_type)s, %(source_system)s, %(source_id)s, %(canonical_id)s,
                    %(candidate_canonical_id)s, %(mapping_status)s, %(mapping_method)s,
                    %(evidence_json)s::jsonb, %(agent_eligible)s
                )
                ON CONFLICT (entity_type, source_system, source_id) DO UPDATE SET
                    canonical_id = EXCLUDED.canonical_id,
                    candidate_canonical_id = EXCLUDED.candidate_canonical_id,
                    mapping_status = EXCLUDED.mapping_status,
                    mapping_method = EXCLUDED.mapping_method,
                    evidence = EXCLUDED.evidence,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                mapping_rows,
            )

            form = repair_form["form"]
            counts["core.form_template"] = _execute_many(
                cursor,
                """
                INSERT INTO core.form_template (
                    form_key, service_id, version, name, description, is_active,
                    source_type, source_file, source_record_id, cleaning_rule,
                    quality_status, agent_eligible
                ) VALUES (
                    %(form_key)s, %(service_id)s, %(version)s, %(name)s,
                    %(description)s, %(is_active)s, %(source_type)s,
                    %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
                    %(quality_status)s, %(agent_eligible)s
                )
                ON CONFLICT (form_key) DO UPDATE SET
                    service_id = EXCLUDED.service_id,
                    version = EXCLUDED.version,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    is_active = EXCLUDED.is_active,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                [form],
            )
            topic_rows = [
                {**row, "config_json": json.dumps(row["config"], ensure_ascii=False)}
                for row in repair_form["topics"]
            ]
            counts["core.form_topic"] = _execute_many(
                cursor,
                """
                INSERT INTO core.form_topic (
                    form_key, topic_key, input_type, title, is_required, sort_order,
                    config, source_type, source_file, source_record_id, cleaning_rule,
                    quality_status, agent_eligible
                ) VALUES (
                    %(form_key)s, %(topic_key)s, %(input_type)s, %(title)s,
                    %(is_required)s, %(sort_order)s, %(config_json)s::jsonb,
                    %(source_type)s, %(source_file)s, %(source_record_id)s,
                    %(cleaning_rule)s, %(quality_status)s, %(agent_eligible)s
                )
                ON CONFLICT (form_key, topic_key) DO UPDATE SET
                    input_type = EXCLUDED.input_type,
                    title = EXCLUDED.title,
                    is_required = EXCLUDED.is_required,
                    sort_order = EXCLUDED.sort_order,
                    config = EXCLUDED.config,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                topic_rows,
            )
            counts["core.form_option"] = _execute_many(
                cursor,
                """
                INSERT INTO core.form_option (
                    option_key, form_key, topic_key, value, label, sort_order,
                    source_type, source_file, source_record_id, cleaning_rule,
                    quality_status, agent_eligible
                ) VALUES (
                    %(option_key)s, %(form_key)s, %(topic_key)s, %(value)s, %(label)s,
                    %(sort_order)s, %(source_type)s, %(source_file)s,
                    %(source_record_id)s, %(cleaning_rule)s, %(quality_status)s,
                    %(agent_eligible)s
                )
                ON CONFLICT (option_key) DO UPDATE SET
                    form_key = EXCLUDED.form_key,
                    topic_key = EXCLUDED.topic_key,
                    value = EXCLUDED.value,
                    label = EXCLUDED.label,
                    sort_order = EXCLUDED.sort_order,
                    source_type = EXCLUDED.source_type,
                    source_file = EXCLUDED.source_file,
                    source_record_id = EXCLUDED.source_record_id,
                    cleaning_rule = EXCLUDED.cleaning_rule,
                    quality_status = EXCLUDED.quality_status,
                    agent_eligible = EXCLUDED.agent_eligible
                """,
                repair_form["options"],
            )

            issue_rows = [
                {**row, "details_json": json.dumps(row["details"], ensure_ascii=False)}
                for row in quality_summary["issues"]
            ]
            counts["core.data_issue"] = _execute_many(
                cursor,
                """
                INSERT INTO core.data_issue (
                    issue_id, source_table, source_record_id, issue_code, severity,
                    message, details
                ) VALUES (
                    %(issue_id)s, %(source_table)s, %(source_record_id)s,
                    %(issue_code)s, %(severity)s, %(message)s,
                    %(details_json)s::jsonb
                )
                ON CONFLICT (issue_id) DO UPDATE SET
                    source_table = EXCLUDED.source_table,
                    source_record_id = EXCLUDED.source_record_id,
                    issue_code = EXCLUDED.issue_code,
                    severity = EXCLUDED.severity,
                    message = EXCLUDED.message,
                    details = EXCLUDED.details
                """,
                issue_rows,
            )
            quarantine_rows = [
                {
                    **row,
                    "issue_codes_json": json.dumps(row.get("issue_codes", []), ensure_ascii=False),
                }
                for row in quarantine
            ]
            counts["quarantine.source_record"] = _execute_many(
                cursor,
                """
                INSERT INTO quarantine.source_record (
                    source_table, source_record_id, issue_codes, raw_preserved_in,
                    raw_payload_included
                ) VALUES (
                    %(source_table)s, %(source_record_id)s, %(issue_codes_json)s::jsonb,
                    %(raw_preserved_in)s, %(raw_payload_included)s
                )
                ON CONFLICT (source_table, source_record_id) DO UPDATE SET
                    issue_codes = EXCLUDED.issue_codes,
                    raw_preserved_in = EXCLUDED.raw_preserved_in,
                    raw_payload_included = EXCLUDED.raw_payload_included
                """,
                quarantine_rows,
            )

            counts.update(_load_demo_rows(cursor, demo_seed))
        connection.commit()

    return counts


def _load_demo_rows(cursor: Any, demo_seed: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    counts["demo.provider"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.provider (
            provider_id, display_name, service_id, rating, completed_jobs,
            base_inspection_fee, source_type, source_file, source_record_id,
            cleaning_rule, quality_status, agent_eligible
        ) VALUES (
            %(provider_id)s, %(display_name)s, %(service_id)s, %(rating)s,
            %(completed_jobs)s, %(base_inspection_fee)s, %(source_type)s,
            %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
            %(quality_status)s, %(agent_eligible)s
        )
        ON CONFLICT (provider_id) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            service_id = EXCLUDED.service_id,
            rating = EXCLUDED.rating,
            completed_jobs = EXCLUDED.completed_jobs,
            base_inspection_fee = EXCLUDED.base_inspection_fee,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        demo_seed["providers"],
    )
    counts["demo.provider_service_area"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.provider_service_area (
            provider_id, location_id, source_type, source_file, source_record_id,
            cleaning_rule, quality_status, agent_eligible
        ) VALUES (
            %(provider_id)s, %(location_id)s, %(source_type)s, %(source_file)s,
            %(source_record_id)s, %(cleaning_rule)s, %(quality_status)s,
            %(agent_eligible)s
        )
        ON CONFLICT (provider_id, location_id) DO UPDATE SET
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        demo_seed["provider_service_areas"],
    )
    counts["demo.provider_availability"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.provider_availability (
            availability_id, provider_id, starts_at, ends_at, status, source_type,
            source_file, source_record_id, cleaning_rule, quality_status,
            agent_eligible
        ) VALUES (
            %(availability_id)s, %(provider_id)s, %(starts_at)s, %(ends_at)s,
            %(status)s, %(source_type)s, %(source_file)s, %(source_record_id)s,
            %(cleaning_rule)s, %(quality_status)s, %(agent_eligible)s
        )
        ON CONFLICT (availability_id) DO UPDATE SET
            provider_id = EXCLUDED.provider_id,
            starts_at = EXCLUDED.starts_at,
            ends_at = EXCLUDED.ends_at,
            status = EXCLUDED.status,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        demo_seed["provider_availability"],
    )
    case_rows = [
        {**row, "answers_json": json.dumps(row["answers"], ensure_ascii=False)}
        for row in demo_seed["consultation_cases"]
    ]
    counts["demo.consultation_case"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.consultation_case (
            case_id, service_id, form_key, location_id, problem_summary,
            preferred_start, preferred_end, status, answers, source_type,
            source_file, source_record_id, cleaning_rule, quality_status,
            agent_eligible
        ) VALUES (
            %(case_id)s, %(service_id)s, %(form_key)s, %(location_id)s,
            %(problem_summary)s, %(preferred_start)s, %(preferred_end)s, %(status)s,
            %(answers_json)s::jsonb, %(source_type)s, %(source_file)s,
            %(source_record_id)s, %(cleaning_rule)s, %(quality_status)s,
            %(agent_eligible)s
        )
        ON CONFLICT (case_id) DO UPDATE SET
            service_id = EXCLUDED.service_id,
            form_key = EXCLUDED.form_key,
            location_id = EXCLUDED.location_id,
            problem_summary = EXCLUDED.problem_summary,
            preferred_start = EXCLUDED.preferred_start,
            preferred_end = EXCLUDED.preferred_end,
            status = EXCLUDED.status,
            answers = EXCLUDED.answers,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        case_rows,
    )
    match_rows = [
        {**row, "reasons_json": json.dumps(row["reasons"], ensure_ascii=False)}
        for row in demo_seed["match_results"]
    ]
    counts["demo.match_result"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.match_result (
            match_id, case_id, provider_id, availability_id, score, reasons, status,
            source_type, source_file, source_record_id, cleaning_rule,
            quality_status, agent_eligible
        ) VALUES (
            %(match_id)s, %(case_id)s, %(provider_id)s, %(availability_id)s,
            %(score)s, %(reasons_json)s::jsonb, %(status)s, %(source_type)s,
            %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
            %(quality_status)s, %(agent_eligible)s
        )
        ON CONFLICT (match_id) DO UPDATE SET
            case_id = EXCLUDED.case_id,
            provider_id = EXCLUDED.provider_id,
            availability_id = EXCLUDED.availability_id,
            score = EXCLUDED.score,
            reasons = EXCLUDED.reasons,
            status = EXCLUDED.status,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        match_rows,
    )
    counts["demo.service_order"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.service_order (
            order_no, case_id, match_id, provider_id, service_id, order_type,
            order_status, scheduled_start, scheduled_end, deposit_amount,
            final_amount, currency, source_type, source_file, source_record_id,
            cleaning_rule, quality_status, agent_eligible
        ) VALUES (
            %(order_no)s, %(case_id)s, %(match_id)s, %(provider_id)s, %(service_id)s,
            %(order_type)s, %(order_status)s, %(scheduled_start)s, %(scheduled_end)s,
            %(deposit_amount)s, %(final_amount)s, %(currency)s, %(source_type)s,
            %(source_file)s, %(source_record_id)s, %(cleaning_rule)s,
            %(quality_status)s, %(agent_eligible)s
        )
        ON CONFLICT (order_no) DO UPDATE SET
            case_id = EXCLUDED.case_id,
            match_id = EXCLUDED.match_id,
            provider_id = EXCLUDED.provider_id,
            service_id = EXCLUDED.service_id,
            order_type = EXCLUDED.order_type,
            order_status = EXCLUDED.order_status,
            scheduled_start = EXCLUDED.scheduled_start,
            scheduled_end = EXCLUDED.scheduled_end,
            deposit_amount = EXCLUDED.deposit_amount,
            final_amount = EXCLUDED.final_amount,
            currency = EXCLUDED.currency,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        demo_seed["orders"],
    )
    counts["demo.order_item"] = _execute_many(
        cursor,
        """
        INSERT INTO demo.order_item (
            order_no, item_no, item_name, quantity, unit_price, item_amount,
            source_type, source_file, source_record_id, cleaning_rule,
            quality_status, agent_eligible
        ) VALUES (
            %(order_no)s, %(item_no)s, %(item_name)s, %(quantity)s, %(unit_price)s,
            %(item_amount)s, %(source_type)s, %(source_file)s,
            %(source_record_id)s, %(cleaning_rule)s, %(quality_status)s,
            %(agent_eligible)s
        )
        ON CONFLICT (order_no, item_no) DO UPDATE SET
            item_name = EXCLUDED.item_name,
            quantity = EXCLUDED.quantity,
            unit_price = EXCLUDED.unit_price,
            item_amount = EXCLUDED.item_amount,
            source_type = EXCLUDED.source_type,
            source_file = EXCLUDED.source_file,
            source_record_id = EXCLUDED.source_record_id,
            cleaning_rule = EXCLUDED.cleaning_rule,
            quality_status = EXCLUDED.quality_status,
            agent_eligible = EXCLUDED.agent_eligible
        """,
        demo_seed["order_items"],
    )
    return counts
