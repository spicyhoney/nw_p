from __future__ import annotations

from typing import Any

from home_repair_agent.backend.models import (
    ConsultationForm,
    FormOption,
    FormTopic,
    ResolvedLocation,
    ServiceSummary,
)


SEARCH_SERVICES_SQL = """
WITH scored AS (
    SELECT
        service_id,
        service_vendor_id,
        vendor_name,
        service_type,
        service_type_name,
        name,
        description,
        aliases,
        CASE
            WHEN %(query)s = '' THEN 0
            WHEN strpos(lower(%(query)s), lower(name)) > 0 THEN 100
            WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(aliases) AS alias(value)
                WHERE strpos(lower(%(query)s), lower(alias.value)) > 0
            ) THEN 90
            WHEN strpos(lower(name), lower(%(query)s)) > 0 THEN 80
            WHEN EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(aliases) AS alias(value)
                WHERE strpos(lower(alias.value), lower(%(query)s)) > 0
            ) THEN 70
            WHEN strpos(lower(service_type_name), lower(%(query)s)) > 0 THEN 60
            WHEN strpos(lower(search_text), lower(%(query)s)) > 0 THEN 50
            ELSE 0
        END AS match_score
    FROM agent.service_catalog
)
SELECT
    service_id,
    service_vendor_id,
    vendor_name,
    service_type,
    service_type_name,
    name,
    description,
    aliases
FROM scored
WHERE %(query)s = '' OR match_score > 0
ORDER BY match_score DESC, service_id
LIMIT %(limit)s
"""


FIND_LOCATIONS_SQL = """
SELECT
    location_id,
    county_name,
    district_name,
    full_name,
    postal_code
FROM agent.location_catalog
WHERE
    (
        replace(county_name, '台', '臺') = %(county_name)s
        OR regexp_replace(
            replace(county_name, '台', '臺'),
            '[縣市]$',
            ''
        ) = %(county_base)s
    )
    AND (
        replace(district_name, '台', '臺') = %(district_name)s
        OR regexp_replace(
            replace(district_name, '台', '臺'),
            '[區鄉鎮市]$',
            ''
        ) = %(district_base)s
    )
ORDER BY
    CASE
        WHEN replace(county_name, '台', '臺') = %(county_name)s THEN 0
        ELSE 1
    END,
    CASE
        WHEN replace(district_name, '台', '臺') = %(district_name)s THEN 0
        ELSE 1
    END,
    location_id
LIMIT 10
"""


LIST_CONSULTATION_FORMS_SQL = """
SELECT
    form.form_key,
    form.service_id,
    form.version,
    form.name AS form_name,
    form.description AS form_description,
    topic.topic_key,
    topic.input_type,
    topic.title AS topic_title,
    topic.is_required,
    topic.sort_order AS topic_sort_order,
    topic.config,
    option.option_key,
    option.value AS option_value,
    option.label AS option_label,
    option.sort_order AS option_sort_order
FROM agent.form_template AS form
LEFT JOIN agent.form_topic AS topic USING (form_key)
LEFT JOIN agent.form_option AS option
    ON option.form_key = topic.form_key
    AND option.topic_key = topic.topic_key
WHERE form.service_id = %(service_id)s
ORDER BY
    form.version DESC,
    form.form_key,
    topic.sort_order,
    topic.topic_key,
    option.sort_order,
    option.option_key
"""


class PostgresReadRepository:
    """Static, parameterized queries against Agent-safe PostgreSQL views."""

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise ValueError("database_url must be a non-empty string")
        self._database_url = database_url

    def search_services(self, *, query: str, limit: int) -> list[ServiceSummary]:
        rows = self._fetch_all(
            SEARCH_SERVICES_SQL,
            {"query": query, "limit": limit},
        )
        return [ServiceSummary.model_validate(row) for row in rows]

    def find_locations(
        self,
        *,
        county_name: str,
        county_base: str,
        district_name: str,
        district_base: str,
    ) -> list[ResolvedLocation]:
        rows = self._fetch_all(
            FIND_LOCATIONS_SQL,
            {
                "county_name": county_name,
                "county_base": county_base,
                "district_name": district_name,
                "district_base": district_base,
            },
        )
        return [ResolvedLocation.model_validate(row) for row in rows]

    def list_consultation_forms(
        self,
        *,
        service_id: int,
    ) -> list[ConsultationForm]:
        rows = self._fetch_all(
            LIST_CONSULTATION_FORMS_SQL,
            {"service_id": service_id},
        )
        return _assemble_forms(rows)

    def _fetch_all(
        self,
        statement: str,
        parameters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL read services require psycopg. "
                "Install the data dependencies with: pip install -e .[data]"
            ) from exc

        with psycopg.connect(
            self._database_url,
            row_factory=dict_row,
        ) as connection:
            return list(connection.execute(statement, parameters).fetchall())


def _assemble_forms(rows: list[dict[str, Any]]) -> list[ConsultationForm]:
    forms: dict[str, dict[str, Any]] = {}

    for row in rows:
        form = forms.setdefault(
            row["form_key"],
            {
                "form_key": row["form_key"],
                "service_id": row["service_id"],
                "version": row["version"],
                "name": row["form_name"],
                "description": row["form_description"],
                "topics": {},
            },
        )
        if row["topic_key"] is None:
            continue

        topics: dict[str, dict[str, Any]] = form["topics"]
        topic = topics.setdefault(
            row["topic_key"],
            {
                "topic_key": row["topic_key"],
                "input_type": row["input_type"],
                "title": row["topic_title"],
                "is_required": row["is_required"],
                "sort_order": row["topic_sort_order"],
                "config": row["config"],
                "options": {},
            },
        )
        if row["option_key"] is not None:
            topic["options"].setdefault(
                row["option_key"],
                FormOption(
                    option_key=row["option_key"],
                    value=row["option_value"],
                    label=row["option_label"],
                    sort_order=row["option_sort_order"],
                ),
            )

    assembled: list[ConsultationForm] = []
    for form in forms.values():
        topics = [
            FormTopic(
                topic_key=topic["topic_key"],
                input_type=topic["input_type"],
                title=topic["title"],
                is_required=topic["is_required"],
                sort_order=topic["sort_order"],
                config=topic["config"],
                options=list(topic["options"].values()),
            )
            for topic in form["topics"].values()
        ]
        assembled.append(
            ConsultationForm(
                form_key=form["form_key"],
                service_id=form["service_id"],
                version=form["version"],
                name=form["name"],
                description=form["description"],
                topics=topics,
            )
        )
    return assembled
