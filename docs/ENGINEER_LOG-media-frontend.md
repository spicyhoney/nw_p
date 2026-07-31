# MEDIA-001 Frontend implementation log

Date: 2026-07-31

- Added a consumer image panel for one JPEG, PNG, or WebP image up to 8 MB, including local preview and removal.
- Image upload is enabled only when `/api/health` reports `model_provider: "huggingface"`. Mock or unknown mode is visibly unavailable and does not fall back to another processing path.
- The upload uses multipart `FormData` with `file` and `external_processing_confirmed=true`; the shared request helper deliberately omits the JSON content type for `FormData`.
- Suggestions remain editable and are sent only through the explicit image confirmation endpoint. The UI displays confidence and uncertainty without treating either as user confirmation.
- Provider detail consumes `has_image` only and uses the case image route; it never accepts or renders a storage `image_path`.
- Added static frontend contract tests for these controls and API integration seams.
