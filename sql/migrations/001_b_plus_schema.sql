BEGIN;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS quarantine;
CREATE SCHEMA IF NOT EXISTS demo;
CREATE SCHEMA IF NOT EXISTS agent;

COMMENT ON SCHEMA core IS
    '通過 B+ 清洗規則的服務、行政區、表單、來源映射與品質問題。';
COMMENT ON SCHEMA quarantine IS
    '無法確認或不符合規則的來源紀錄索引；不得供 Agent 使用。';
COMMENT ON SCHEMA demo IS
    '為 MVP 展示建立且明確標記為 synthetic 的師傅、時段、案件與訂單。';
COMMENT ON SCHEMA agent IS
    '只暴露 quality_status=verified 且 agent_eligible=true 資料的安全讀取介面。';

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

COMMENT ON TABLE core.service_vendor IS
    '主辦方服務供應商主檔經格式與文字正規化後的可信版本。';
COMMENT ON COLUMN core.service_vendor.service_vendor_id IS
    '沿用主辦方主檔的服務供應商 ID，不為缺漏供應商自行造號。';
COMMENT ON COLUMN core.service_vendor.source_type IS
    '紀錄的主要來源類型；本表預期為 official_repaired。';
COMMENT ON COLUMN core.service_vendor.quality_status IS
    '品質狀態：verified、review 或 quarantined。';
COMMENT ON COLUMN core.service_vendor.agent_eligible IS
    '是否允許出現在 agent schema；為 true 時品質必須是 verified。';

COMMENT ON TABLE core.service IS
    '服務主檔；service_id=17 是本專案水電修繕 MVP 的正式服務錨點。';
COMMENT ON COLUMN core.service.service_id IS
    '主辦方服務 ID；7 與 18 等不存在於本表的 ID 不會被猜測補入。';
COMMENT ON COLUMN core.service.aliases IS
    '團隊整理的搜尋別名，只協助查找，不改變正式服務名稱或 ID。';
COMMENT ON COLUMN core.service.aliases_source_type IS
    'aliases 的來源固定為 curated_config，避免被誤認為主辦方欄位。';
COMMENT ON COLUMN core.service.search_text IS
    '由正式名稱、描述與團隊別名組成，供受控服務搜尋使用。';
COMMENT ON COLUMN core.service.search_text_source_types IS
    'search_text 各組成部分的來源類型清單。';
COMMENT ON COLUMN core.service.agent_eligible IS
    '是否允許 Agent 搜尋；資料庫 constraint 會阻止未驗證資料設為 true。';

COMMENT ON TABLE core.location IS
    '主辦方行政區與國土測繪中心參考快照合併後的 368 筆標準行政區。';
COMMENT ON COLUMN core.location.location_id IS
    'ORG- 前綴代表主辦方資料可對照；NLSC- 前綴代表由官方外部參考補齊。';
COMMENT ON COLUMN core.location.full_name IS
    '正規化後的縣市加行政區名稱，例如台北市大安區。';
COMMENT ON COLUMN core.location.organizer_district_code IS
    '主辦方行政區代碼；外部補齊資料可能為 NULL。';
COMMENT ON COLUMN core.location.nlsc_town_code IS
    '內政部國土測繪中心鄉鎮市區代碼。';
COMMENT ON COLUMN core.location.agent_eligible IS
    '只有完成外部對照或來自可信外部參考的行政區才可供 Agent 使用。';

COMMENT ON TABLE core.source_mapping IS
    '來源 ID 到正式 ID 的映射決策；未確認資料保留 unresolved。';
COMMENT ON COLUMN core.source_mapping.canonical_id IS
    '已由證據確認的正式 ID；unresolved 紀錄必須保持 NULL。';
COMMENT ON COLUMN core.source_mapping.candidate_canonical_id IS
    '僅供人工調查的候選 ID，不代表已完成映射，Agent 不得採用。';
COMMENT ON COLUMN core.source_mapping.mapping_status IS
    'verified、unresolved 或 rejected。';
COMMENT ON COLUMN core.source_mapping.mapping_method IS
    '作出映射判斷的方法，例如 same_id_in_master 或 semantic_hint_only。';
COMMENT ON COLUMN core.source_mapping.evidence IS
    '支持或限制映射判斷的結構化證據與備註。';
COMMENT ON COLUMN core.source_mapping.agent_eligible IS
    '只有 verified 且 canonical_id 非 NULL 的映射才能為 true。';

COMMENT ON TABLE core.data_issue IS
    '清洗管線發現的格式、關聯、狀態、個資與資料品質問題。';
COMMENT ON COLUMN core.data_issue.issue_code IS
    '可供統計與測試使用的穩定問題代碼。';
COMMENT ON COLUMN core.data_issue.severity IS
    '問題嚴重度：info、warning 或 error。';
COMMENT ON COLUMN core.data_issue.details IS
    '不含原始個資 payload 的結構化問題細節。';

COMMENT ON TABLE core.form_template IS
    '團隊為 service_id=17 設計並版本化的水電修繕諮詢表單。';
COMMENT ON COLUMN core.form_template.form_key IS
    '穩定表單鍵；版本更新時不可覆蓋既有語意。';
COMMENT ON COLUMN core.form_template.source_type IS
    '本專案表單為 curated_config，不冒充主辦方原始表單。';
COMMENT ON TABLE core.form_topic IS
    '諮詢表單題目、輸入型別、必填規則與排序。';
COMMENT ON COLUMN core.form_topic.config IS
    '題型特定限制，例如長度、日期範圍或媒體數量。';
COMMENT ON TABLE core.form_option IS
    '單選或多選題可接受的穩定值與使用者顯示文字。';
COMMENT ON COLUMN core.form_option.value IS
    '程式與 Agent 應保存的穩定選項值，不是顯示文字。';

COMMENT ON TABLE quarantine.source_record IS
    '問題來源紀錄的安全索引，只指向原始檔，不複製原始 payload。';
COMMENT ON COLUMN quarantine.source_record.issue_codes IS
    '使此來源紀錄進入隔離區的問題代碼清單。';
COMMENT ON COLUMN quarantine.source_record.raw_preserved_in IS
    '原始紀錄仍保存在哪個本機主辦方檔案。';
COMMENT ON COLUMN quarantine.source_record.raw_payload_included IS
    '固定為 false，確保隔離資料庫不複製可能含個資的 payload。';

COMMENT ON TABLE demo.provider IS
    'synthetic 水電服務師傅資料，只用於 MVP 媒合展示。';
COMMENT ON COLUMN demo.provider.provider_id IS
    'SYN- 前綴的模擬師傅 ID，不能與真實服務商混用。';
COMMENT ON TABLE demo.provider_service_area IS
    'synthetic 師傅可服務行政區。';
COMMENT ON TABLE demo.provider_availability IS
    'synthetic 師傅可預約時段。';
COMMENT ON COLUMN demo.provider_availability.status IS
    '時段狀態：available、held 或 booked。';
COMMENT ON TABLE demo.consultation_case IS
    'synthetic 使用者諮詢案件，串接表單、服務、地點與期望時段。';
COMMENT ON COLUMN demo.consultation_case.answers IS
    '依 form_topic/topic_key 儲存的結構化 Demo 回答。';
COMMENT ON TABLE demo.match_result IS
    'synthetic 案件與師傅的媒合結果及可解釋原因。';
COMMENT ON COLUMN demo.match_result.score IS
    '0 到 1 的 Demo 媒合分數，不是由主辦方模型產生。';
COMMENT ON TABLE demo.service_order IS
    '使用者確認媒合後建立的 synthetic Demo 訂單。';
COMMENT ON COLUMN demo.service_order.order_no IS
    'SYN- 前綴的 Demo 訂單編號，不與 99 筆歷史範例混用。';
COMMENT ON TABLE demo.order_item IS
    'synthetic Demo 訂單的明細項目。';

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

COMMENT ON VIEW agent.service_catalog IS
    'Agent 可搜尋的已驗證服務與供應商，不包含 unresolved 服務。';
COMMENT ON VIEW agent.location_catalog IS
    'Agent 可查詢的已驗證行政區清單。';
COMMENT ON VIEW agent.form_template IS
    'Agent 可使用的啟用中、已驗證表單版本。';
COMMENT ON VIEW agent.form_topic IS
    'Agent 可追問的已驗證表單題目。';
COMMENT ON VIEW agent.form_option IS
    'Agent 可接受與回傳的已驗證表單選項。';
COMMENT ON VIEW agent.available_provider_slot IS
    '依服務區域與 available 狀態提供的 synthetic Demo 師傅時段。';
COMMENT ON VIEW agent.consultation_case IS
    'Agent 可查詢的 synthetic Demo 諮詢案件。';
COMMENT ON VIEW agent.service_order IS
    'Agent 可查詢的 synthetic Demo 訂單狀態，不含歷史範例訂單。';

COMMIT;
