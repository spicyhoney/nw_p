# MEDIA-001 integration record

Date: 2026-07-31

## Outcome

Integrated the VLM, local media storage and case-persistence subtasks into the
FastAPI consumer/provider workflow. After independent review and successful
verification, the user authorized a direct `main` push without a PR; the
completed feature was therefore removed from `TASKS.md` and retained in the
implementation index and this record.

## Confirmed flow

1. `WEB_MODEL_PROVIDER=huggingface` and valid HF configuration are required;
   Mock and provider errors do not fallback.
2. A user explicitly consents, then uploads one actual JPEG/PNG/WebP up to
   8 MiB. Pillow normalizes it, strips metadata and stores a server-generated
   relative key under `MEDIA_ROOT`.
3. The VLM returns a Traditional-Chinese suggestion only. Until the user edits
   and confirms it, messages, form submission, matching and dispatch cannot use
   the result.
4. Confirmation calls the existing read-only `search_services` Tool and only
   applies a unique catalog result. The LLM never supplies a canonical service
   ID or performs a write.
5. Dispatch persists the relative path and confirmed structured analysis.
   Browser JSON exposes `has_image`, never `image_path`.
6. The assigned provider can fetch pending/accepted images with the Demo
   provider header; rejected, unassigned and missing images return 404.

The stored key remains in the session layout after dispatch. This avoids a
filesystem move after the database transaction has committed; reset/removal is
already prohibited after a case exists. A future object-storage adapter may
promote the key inside a coordinated transaction.

## Review corrections made during integration

- Replaced direct provider `<img src>` loading with an authorized fetch plus a
  short-lived object URL, because an image element cannot attach the provider
  identity header.
- Excluded server paths from API serialization and hid derived image analysis
  after provider rejection.
- Required persisted path and confirmed analysis to exist as a pair in Pydantic
  and PostgreSQL constraints.
- Added rollback-aware cleanup for replacement, removal, reset and VLM failure.
- Added provider preview sizing and cache-version bumps after responsive browser
  inspection.

## Verification

```text
pytest: 134 passed, 18 skipped, 52 subtests passed
affected Python Ruff: pass
compileall: pass
app.js / provider.js node --check: pass
git diff --check: pass
browser: 1280x720 and 390x844, no horizontal overflow or console error
live HF VLM: pass with a synthetic image, Qwen/Qwen3-VL-30B-A3B-Instruct,
             provider=novita and provider=auto
```

The 18 skips include PostgreSQL integration because this machine has no
`TEST_DATABASE_URL`; CI must apply and verify migration 003. Full-repository
Ruff still reports 16 pre-existing `data_cleaning` findings outside this task;
all changed Python files pass. The live smoke used only an in-memory synthetic
image and did not record the token, image payload or provider request ID. The
previous Qwen 2.5 VL default was unavailable to this account's enabled providers,
so the verified Qwen 3 VL model became the project default. Provider availability
can change; deployment should repeat the same synthetic smoke.
