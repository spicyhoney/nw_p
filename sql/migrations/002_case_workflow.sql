BEGIN;

CREATE SCHEMA IF NOT EXISTS workflow;

COMMENT ON SCHEMA workflow IS
    '消費者確認派單後的案件、訂單、冪等與稽核寫入資料；不直接暴露給 Agent。';

CREATE TABLE IF NOT EXISTS workflow.service_case (
    case_id text PRIMARY KEY,
    session_id text NOT NULL,
    service_id integer NOT NULL CHECK (service_id > 0),
    service_name text NOT NULL,
    form_key text NOT NULL,
    location_id text NOT NULL,
    location_name text NOT NULL,
    problem_summary text NOT NULL,
    answers jsonb NOT NULL DEFAULT '{}'::jsonb,
    preferred_start timestamptz NOT NULL,
    preferred_end timestamptz NOT NULL,
    provider_id text NOT NULL,
    provider_name text NOT NULL,
    availability_id text NOT NULL,
    contact_name text NOT NULL,
    contact_mobile text NOT NULL,
    contact_address text NOT NULL,
    status text NOT NULL,
    order_no text UNIQUE,
    source_type text NOT NULL DEFAULT 'synthetic',
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    version integer NOT NULL,
    CONSTRAINT workflow_case_answers_object
        CHECK (jsonb_typeof(answers) = 'object'),
    CONSTRAINT workflow_case_time_order
        CHECK (preferred_end > preferred_start),
    CONSTRAINT workflow_case_time_limit
        CHECK (preferred_end <= preferred_start + interval '12 hours'),
    CONSTRAINT workflow_case_status
        CHECK (status IN ('pending_provider', 'accepted', 'rejected')),
    CONSTRAINT workflow_case_order_state
        CHECK (
            (status = 'accepted' AND order_no IS NOT NULL)
            OR
            (status IN ('pending_provider', 'rejected') AND order_no IS NULL)
        ),
    CONSTRAINT workflow_case_source
        CHECK (source_type = 'synthetic'),
    CONSTRAINT workflow_case_timestamps
        CHECK (updated_at >= created_at),
    CONSTRAINT workflow_case_version
        CHECK (version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS workflow_one_active_case_per_session_idx
    ON workflow.service_case (session_id)
    WHERE status IN ('pending_provider', 'accepted');

CREATE INDEX IF NOT EXISTS workflow_case_session_created_idx
    ON workflow.service_case (session_id, created_at, case_id);

CREATE INDEX IF NOT EXISTS workflow_case_provider_updated_idx
    ON workflow.service_case (provider_id, updated_at DESC, case_id);

CREATE TABLE IF NOT EXISTS workflow.service_order (
    order_no text PRIMARY KEY,
    case_id text NOT NULL UNIQUE
        REFERENCES workflow.service_case (case_id) ON DELETE RESTRICT,
    provider_id text NOT NULL,
    service_id integer NOT NULL CHECK (service_id > 0),
    scheduled_start timestamptz NOT NULL,
    scheduled_end timestamptz NOT NULL,
    order_status text NOT NULL DEFAULT 'confirmed',
    source_type text NOT NULL DEFAULT 'synthetic',
    created_at timestamptz NOT NULL,
    CONSTRAINT workflow_order_time_order
        CHECK (scheduled_end > scheduled_start),
    CONSTRAINT workflow_order_status
        CHECK (order_status = 'confirmed'),
    CONSTRAINT workflow_order_source
        CHECK (source_type = 'synthetic')
);

CREATE TABLE IF NOT EXISTS workflow.case_audit_event (
    event_id text PRIMARY KEY,
    case_id text NOT NULL
        REFERENCES workflow.service_case (case_id) ON DELETE RESTRICT,
    sequence_no integer NOT NULL,
    event_type text NOT NULL,
    actor_type text NOT NULL,
    actor_id text NOT NULL,
    message text NOT NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT workflow_audit_case_sequence
        UNIQUE (case_id, sequence_no),
    CONSTRAINT workflow_audit_sequence_positive
        CHECK (sequence_no > 0),
    CONSTRAINT workflow_audit_event_type
        CHECK (
            event_type IN (
                'case_submitted',
                'provider_accepted',
                'provider_rejected',
                'contact_revealed'
            )
        ),
    CONSTRAINT workflow_audit_actor_type
        CHECK (actor_type IN ('consumer', 'provider', 'system'))
);

CREATE INDEX IF NOT EXISTS workflow_audit_case_sequence_idx
    ON workflow.case_audit_event (case_id, sequence_no);

CREATE TABLE IF NOT EXISTS workflow.idempotency_record (
    idempotency_key text PRIMARY KEY,
    operation text NOT NULL,
    fingerprint text NOT NULL,
    case_id text NOT NULL
        REFERENCES workflow.service_case (case_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT workflow_idempotency_key_length
        CHECK (char_length(idempotency_key) BETWEEN 8 AND 128),
    CONSTRAINT workflow_idempotency_fingerprint
        CHECK (fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS workflow_idempotency_case_idx
    ON workflow.idempotency_record (case_id);

COMMENT ON TABLE workflow.service_case IS
    '已由消費者確認的通用服務案件；服務、表單、地點與廠商名稱保存建立當下快照。';
COMMENT ON COLUMN workflow.service_case.answers IS
    '依 form topic key 保存的結構化回答；不得放入未經同意的正式個資。';
COMMENT ON COLUMN workflow.service_case.status IS
    'pending_provider、accepted 或 rejected；合法轉換由 CaseWorkflowService 控制。';
COMMENT ON COLUMN workflow.service_case.version IS
    '供 optimistic concurrency control 使用；每次狀態更新必須增加一。';
COMMENT ON TABLE workflow.service_order IS
    '廠商接受案件後建立的 synthetic Demo 訂單；一個案件最多一張訂單。';
COMMENT ON TABLE workflow.case_audit_event IS
    '不可由 Agent 任意改寫的派單、接單、拒絕與聯絡資料揭露稽核事件。';
COMMENT ON TABLE workflow.idempotency_record IS
    '保存寫入命令結果，避免重複派單或重複建立訂單。';

COMMIT;
