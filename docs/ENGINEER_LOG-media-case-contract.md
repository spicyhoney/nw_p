# MEDIA-001 case media contract

Date: 2026-07-31

## Scope

Added the case-workflow persistence contract for an optional uploaded image and
its structured VLM analysis. Media file creation, cleanup, and serving remain
outside this change so the Web/storage owner can coordinate their transaction.

## Contract

- `image_path: str | None` is a server-relative, forward-slash path. Empty,
  absolute, Windows-drive, backslash, `.` and `..` segments are rejected by
  `CaseSubmissionCommand` and `WorkflowCase`.
- `image_analysis: CaseImageAnalysis | None` retains `service_query`,
  `problem_summary`, `safety_warnings`, `confidence`, `uncertain`,
  `confirmed`, and `correction`; it is not folded into `problem_summary`.
- Consumer and provider case views expose both optional fields. Existing
  image-free cases continue to produce `null` values.
- The submission fingerprint includes these fields, so the existing
  idempotency rule also covers image metadata.

## PostgreSQL

`003_case_media_contract.sql` adds nullable `image_path text` and
`image_analysis jsonb` to `workflow.service_case`. Database constraints reject
absolute/traversal/backslash paths and require the persisted analysis object to
contain the seven contract keys with the expected JSON types and a confidence
between zero and one. The repository selects, inserts, updates, and rehydrates
both fields, so a fresh repository instance reads them back after restart.

## Verification

```
.\.venv\Scripts\python.exe -m pytest -q tests/test_case_workflow.py tests/test_postgres_case_repository.py
# 12 passed, 6 skipped, 7 subtests passed

.\.venv\Scripts\python.exe -m ruff check src\home_repair_agent\backend\case_models.py src\home_repair_agent\backend\case_services.py src\home_repair_agent\backend\postgres_case_repository.py tests\test_case_workflow.py tests\test_postgres_case_repository.py
# All checks passed
```

The PostgreSQL tests remain skipped without `TEST_DATABASE_URL`; when supplied,
the repository recreation test verifies image-path and analysis rehydration.

The complete suite was also run: `121 passed, 17 skipped, 1 failed`. The only
failure is outside this contract scope in
`tests/test_media_storage.py::LocalMediaStorageTests::test_reencoding_strips_exif_metadata`,
where the fixture's source JPEG already reports an empty EXIF object before the
storage implementation is invoked.
