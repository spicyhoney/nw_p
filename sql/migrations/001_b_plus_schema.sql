BEGIN;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS demo;
CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS core.service_vendor (
    service_vendor_id integer PRIMARY KEY,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_type IN (
        'official_raw', 'official_repaired', 'external_reference',
        'curated_config', 'synthetic'
    )),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS core.service (
    service_id integer PRIMARY KEY,
    service_vendor_id integer NOT NULL
        REFERENCES core.service_vendor (service_vendor_id),
    service_type text NOT NULL,
    service_type_name text,
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    image_url text,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    aliases_source_type text NOT NULL DEFAULT 'curated_config',
    search_text text NOT NULL DEFAULT '',
    search_text_source_types jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(aliases) = 'array'),
    CHECK (aliases_source_type = 'curated_config'),
    CHECK (jsonb_typeof(search_text_source_types) = 'array'),
    CHECK (source_type IN (
        'official_raw', 'official_repaired', 'external_reference',
        'curated_config', 'synthetic'
    )),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS core.location (
    location_id text PRIMARY KEY,
    county_name text NOT NULL,
    district_name text NOT NULL,
    full_name text NOT NULL UNIQUE,
    postal_code text,
    organizer_county_code text,
    organizer_district_code text,
    nlsc_county_code text,
    nlsc_county_code01 text,
    nlsc_town_code text,
    nlsc_town_code01 text,
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_type IN (
        'official_raw', 'official_repaired', 'external_reference',
        'curated_config', 'synthetic'
    )),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS core.source_mapping (
    entity_type text NOT NULL,
    source_system text NOT NULL,
    source_id text NOT NULL,
    canonical_id text,
    candidate_canonical_id text,
    mapping_status text NOT NULL,
    mapping_method text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entity_type, source_system, source_id),
    CHECK (mapping_status IN ('verified', 'unresolved', 'rejected')),
    CHECK (NOT agent_eligible OR (
        mapping_status = 'verified' AND canonical_id IS NOT NULL
    ))
);

CREATE TABLE IF NOT EXISTS core.data_issue (
    issue_id text PRIMARY KEY,
    source_table text NOT NULL,
    source_record_id text NOT NULL,
    issue_code text NOT NULL,
    severity text NOT NULL,
    message text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (severity IN ('info', 'warning', 'error'))
);

CREATE TABLE IF NOT EXISTS core.form_template (
    form_key text PRIMARY KEY,
    service_id integer NOT NULL REFERENCES core.service (service_id),
    version integer NOT NULL CHECK (version > 0),
    name text NOT NULL,
    description text NOT NULL DEFAULT '',
    is_active boolean NOT NULL DEFAULT true,
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source_type IN ('curated_config', 'official_repaired')),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS core.form_topic (
    form_key text NOT NULL REFERENCES core.form_template (form_key),
    topic_key text NOT NULL,
    input_type text NOT NULL,
    title text NOT NULL,
    is_required boolean NOT NULL DEFAULT false,
    sort_order integer NOT NULL,
    config jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (form_key, topic_key),
    CHECK (sort_order > 0),
    CHECK (source_type IN ('curated_config', 'official_repaired')),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS core.form_option (
    option_key text PRIMARY KEY,
    form_key text NOT NULL,
    topic_key text NOT NULL,
    value text NOT NULL,
    label text NOT NULL,
    sort_order integer NOT NULL,
    source_type text NOT NULL,
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL,
    agent_eligible boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (form_key, topic_key)
        REFERENCES core.form_topic (form_key, topic_key),
    UNIQUE (form_key, topic_key, value),
    CHECK (sort_order > 0),
    CHECK (source_type IN ('curated_config', 'official_repaired')),
    CHECK (quality_status IN ('verified', 'review', 'quarantined')),
    CHECK (NOT agent_eligible OR quality_status = 'verified')
);

CREATE TABLE IF NOT EXISTS quarantine.source_record (
    source_table text NOT NULL,
    source_record_id text NOT NULL,
    issue_codes jsonb NOT NULL DEFAULT '[]'::jsonb,
    raw_preserved_in text NOT NULL,
    raw_payload_included boolean NOT NULL DEFAULT false,
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_table, source_record_id),
    CHECK (jsonb_typeof(issue_codes) = 'array'),
    CHECK (raw_payload_included = false)
);

CREATE TABLE IF NOT EXISTS demo.provider (
    provider_id text PRIMARY KEY,
    display_name text NOT NULL,
    service_id integer NOT NULL REFERENCES core.service (service_id),
    rating numeric(2, 1) NOT NULL CHECK (rating BETWEEN 0 AND 5),
    completed_jobs integer NOT NULL CHECK (completed_jobs >= 0),
    base_inspection_fee numeric(12, 2) NOT NULL CHECK (base_inspection_fee >= 0),
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demo.provider_service_area (
    provider_id text NOT NULL REFERENCES demo.provider (provider_id),
    location_id text NOT NULL REFERENCES core.location (location_id),
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (provider_id, location_id)
);

CREATE TABLE IF NOT EXISTS demo.provider_availability (
    availability_id text PRIMARY KEY,
    provider_id text NOT NULL REFERENCES demo.provider (provider_id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    status text NOT NULL CHECK (status IN ('available', 'held', 'booked')),
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS demo.consultation_case (
    case_id text PRIMARY KEY,
    service_id integer NOT NULL REFERENCES core.service (service_id),
    form_key text NOT NULL REFERENCES core.form_template (form_key),
    location_id text NOT NULL REFERENCES core.location (location_id),
    problem_summary text NOT NULL,
    preferred_start timestamptz NOT NULL,
    preferred_end timestamptz NOT NULL,
    status text NOT NULL CHECK (
        status IN ('draft', 'submitted', 'matched', 'confirmed', 'cancelled')
    ),
    answers jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (preferred_end > preferred_start)
);

CREATE TABLE IF NOT EXISTS demo.match_result (
    match_id text PRIMARY KEY,
    case_id text NOT NULL REFERENCES demo.consultation_case (case_id),
    provider_id text NOT NULL REFERENCES demo.provider (provider_id),
    availability_id text NOT NULL
        REFERENCES demo.provider_availability (availability_id),
    score numeric(5, 4) NOT NULL CHECK (score BETWEEN 0 AND 1),
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL CHECK (status IN ('candidate', 'selected', 'rejected')),
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(reasons) = 'array')
);

CREATE TABLE IF NOT EXISTS demo.service_order (
    order_no text PRIMARY KEY,
    case_id text NOT NULL REFERENCES demo.consultation_case (case_id),
    match_id text NOT NULL REFERENCES demo.match_result (match_id),
    provider_id text NOT NULL REFERENCES demo.provider (provider_id),
    service_id integer NOT NULL REFERENCES core.service (service_id),
    order_type text NOT NULL,
    order_status text NOT NULL,
    scheduled_start timestamptz NOT NULL,
    scheduled_end timestamptz NOT NULL,
    deposit_amount numeric(12, 2) NOT NULL CHECK (deposit_amount >= 0),
    final_amount numeric(12, 2) NOT NULL CHECK (final_amount >= 0),
    currency char(3) NOT NULL DEFAULT 'TWD',
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (scheduled_end > scheduled_start)
);

CREATE TABLE IF NOT EXISTS demo.order_item (
    order_no text NOT NULL REFERENCES demo.service_order (order_no),
    item_no integer NOT NULL CHECK (item_no > 0),
    item_name text NOT NULL,
    quantity numeric(12, 2) NOT NULL CHECK (quantity > 0),
    unit_price numeric(12, 2) NOT NULL CHECK (unit_price >= 0),
    item_amount numeric(12, 2) NOT NULL CHECK (item_amount >= 0),
    source_type text NOT NULL CHECK (source_type = 'synthetic'),
    source_file text NOT NULL,
    source_record_id text NOT NULL,
    cleaning_rule text NOT NULL,
    quality_status text NOT NULL CHECK (quality_status = 'verified'),
    agent_eligible boolean NOT NULL CHECK (agent_eligible),
    loaded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (order_no, item_no)
);

CREATE INDEX IF NOT EXISTS service_search_text_idx
    ON core.service USING gin (to_tsvector('simple', search_text));
CREATE INDEX IF NOT EXISTS location_full_name_idx ON core.location (full_name);
CREATE INDEX IF NOT EXISTS data_issue_code_idx ON core.data_issue (issue_code);
CREATE INDEX IF NOT EXISTS availability_lookup_idx
    ON demo.provider_availability (provider_id, status, starts_at, ends_at);

CREATE OR REPLACE VIEW agent.service_catalog
WITH (security_barrier = true) AS
SELECT
    s.service_id,
    s.service_vendor_id,
    v.name AS vendor_name,
    s.service_type,
    s.service_type_name,
    s.name,
    s.description,
    s.aliases,
    s.aliases_source_type,
    s.search_text,
    s.search_text_source_types
FROM core.service AS s
JOIN core.service_vendor AS v
    ON v.service_vendor_id = s.service_vendor_id
WHERE
    s.quality_status = 'verified'
    AND s.agent_eligible
    AND v.quality_status = 'verified'
    AND v.agent_eligible;

CREATE OR REPLACE VIEW agent.location_catalog
WITH (security_barrier = true) AS
SELECT
    location_id,
    county_name,
    district_name,
    full_name,
    postal_code
FROM core.location
WHERE quality_status = 'verified' AND agent_eligible;

CREATE OR REPLACE VIEW agent.form_template
WITH (security_barrier = true) AS
SELECT form_key, service_id, version, name, description
FROM core.form_template
WHERE
    is_active
    AND quality_status = 'verified'
    AND agent_eligible;

CREATE OR REPLACE VIEW agent.form_topic
WITH (security_barrier = true) AS
SELECT
    topic.form_key,
    topic.topic_key,
    topic.input_type,
    topic.title,
    topic.is_required,
    topic.sort_order,
    topic.config
FROM core.form_topic AS topic
JOIN agent.form_template AS form USING (form_key)
WHERE topic.quality_status = 'verified' AND topic.agent_eligible;

CREATE OR REPLACE VIEW agent.form_option
WITH (security_barrier = true) AS
SELECT
    option.option_key,
    option.form_key,
    option.topic_key,
    option.value,
    option.label,
    option.sort_order
FROM core.form_option AS option
JOIN agent.form_topic AS topic
    ON topic.form_key = option.form_key
    AND topic.topic_key = option.topic_key
WHERE option.quality_status = 'verified' AND option.agent_eligible;

CREATE OR REPLACE VIEW agent.available_provider_slot
WITH (security_barrier = true) AS
SELECT
    provider.provider_id,
    provider.display_name,
    provider.service_id,
    provider.rating,
    provider.completed_jobs,
    provider.base_inspection_fee,
    area.location_id,
    location.full_name AS location_name,
    availability.availability_id,
    availability.starts_at,
    availability.ends_at
FROM demo.provider AS provider
JOIN demo.provider_service_area AS area USING (provider_id)
JOIN agent.location_catalog AS location USING (location_id)
JOIN demo.provider_availability AS availability USING (provider_id)
WHERE
    provider.agent_eligible
    AND area.agent_eligible
    AND availability.agent_eligible
    AND availability.status = 'available';

CREATE OR REPLACE VIEW agent.consultation_case
WITH (security_barrier = true) AS
SELECT
    case_id,
    service_id,
    form_key,
    location_id,
    problem_summary,
    preferred_start,
    preferred_end,
    status,
    answers
FROM demo.consultation_case
WHERE quality_status = 'verified' AND agent_eligible;

CREATE OR REPLACE VIEW agent.service_order
WITH (security_barrier = true) AS
SELECT
    order_no,
    case_id,
    provider_id,
    service_id,
    order_type,
    order_status,
    scheduled_start,
    scheduled_end,
    deposit_amount,
    final_amount,
    currency
FROM demo.service_order
WHERE quality_status = 'verified' AND agent_eligible;

COMMIT;
