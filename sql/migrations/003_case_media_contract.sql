BEGIN;

ALTER TABLE workflow.service_case
    ADD COLUMN IF NOT EXISTS image_path text,
    ADD COLUMN IF NOT EXISTS image_analysis jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'workflow_case_image_path_relative'
          AND conrelid = 'workflow.service_case'::regclass
    ) THEN
        ALTER TABLE workflow.service_case
            ADD CONSTRAINT workflow_case_image_path_relative
            CHECK (
                image_path IS NULL
                OR (
                    image_path <> ''
                    AND image_path !~ '(^/|^[A-Za-z]:|(^|/)\.\.(/|$))'
                    AND position(chr(92) IN image_path) = 0
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'workflow_case_image_analysis_shape'
          AND conrelid = 'workflow.service_case'::regclass
    ) THEN
        ALTER TABLE workflow.service_case
            ADD CONSTRAINT workflow_case_image_analysis_shape
            CHECK (
                (image_path IS NULL AND image_analysis IS NULL)
                OR (
                    image_path IS NOT NULL
                    AND image_analysis IS NOT NULL
                    AND jsonb_typeof(image_analysis) = 'object'
                    AND image_analysis ?& ARRAY[
                        'service_query',
                        'problem_summary',
                        'safety_warnings',
                        'confidence',
                        'uncertain',
                        'confirmed',
                        'correction'
                    ]
                    AND jsonb_typeof(image_analysis -> 'service_query') = 'string'
                    AND jsonb_typeof(image_analysis -> 'problem_summary') = 'string'
                    AND jsonb_typeof(image_analysis -> 'safety_warnings') = 'array'
                    AND jsonb_typeof(image_analysis -> 'confidence') = 'number'
                    AND (image_analysis ->> 'confidence')::numeric BETWEEN 0 AND 1
                    AND jsonb_typeof(image_analysis -> 'uncertain') = 'boolean'
                    AND jsonb_typeof(image_analysis -> 'confirmed') = 'boolean'
                    AND (image_analysis ->> 'confirmed')::boolean IS TRUE
                    AND jsonb_typeof(image_analysis -> 'correction') IN ('string', 'null')
                )
            );
    END IF;
END $$;

COMMENT ON COLUMN workflow.service_case.image_path IS
    'Optional server-relative media path only; absolute and traversal paths are rejected.';
COMMENT ON COLUMN workflow.service_case.image_analysis IS
    'Optional structured VLM result: service query, summary, warnings, confidence, uncertainty, confirmation, and correction.';

COMMIT;
