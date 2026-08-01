from __future__ import annotations

import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "home_repair_agent" / "web" / "static"


class MediaFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        cls.app = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        cls.styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
        cls.provider = (STATIC_DIR / "provider.html").read_text(encoding="utf-8")
        cls.provider_js = (STATIC_DIR / "provider.js").read_text(encoding="utf-8")
        cls.provider_styles = (STATIC_DIR / "provider.css").read_text(encoding="utf-8")

    def test_consumer_image_controls_are_labeled_and_constrained(self) -> None:
        self.assertIn('id="media-file"', self.index)
        self.assertIn('accept="image/jpeg,image/png,image/webp"', self.index)
        self.assertIn('id="media-external-consent"', self.index)
        self.assertIn('id="media-status"', self.index)
        self.assertIn('role="status"', self.index)
        self.assertIn('aria-live="polite"', self.index)
        self.assertIn("MEDIA_MAX_BYTES = 8 * 1024 * 1024", self.app)
        self.assertIn("validateMediaFile", self.app)

    def test_upload_requires_huggingface_and_explicit_consent(self) -> None:
        self.assertIn("health.model_provider", self.app)
        self.assertIn('store.mediaProvider === "huggingface"', self.app)
        self.assertIn('bedrock: "Bedrock 模式"', self.app)
        self.assertIn("Mock／Bedrock／未設定", self.app)
        self.assertIn('body.append("external_processing_confirmed", "true")', self.app)
        self.assertIn('method: "POST", body', self.app)
        self.assertIn("new FormData()", self.app)
        self.assertIn("options.body instanceof FormData", self.app)
        self.assertIn("圖片不會上傳，也不會改用其他模式處理", self.app)

    def test_analysis_is_editable_and_explicitly_confirmed(self) -> None:
        for control in (
            "media-service-query",
            "media-problem-summary",
            "media-safety-warnings",
        ):
            self.assertIn(f'id="{control}"', self.index)
        self.assertIn("/confirm", self.app)
        self.assertIn("service_query", self.app)
        self.assertIn("problem_summary", self.app)
        self.assertIn("safety_warnings", self.app)
        self.assertIn("analysis.confirmed", self.app)

    def test_mobile_touch_targets_and_provider_image_contract_are_present(self) -> None:
        self.assertIn("min-height: 44px", self.styles)
        self.assertIn(".media-section", self.styles)
        self.assertIn('id="provider-image-section"', self.provider)
        self.assertIn("detail.has_image === true", self.provider_js)
        self.assertIn(
            "/api/provider/cases/${encodeURIComponent(expectedCaseId)}/image", self.provider_js
        )
        self.assertIn('"X-Demo-Provider-Id": expectedProviderId', self.provider_js)
        self.assertIn("URL.createObjectURL(await response.blob())", self.provider_js)
        self.assertIn(".provider-image-section img", self.provider_styles)
        self.assertIn("object-fit: contain", self.provider_styles)
        self.assertNotIn("image_path", self.provider_js)


if __name__ == "__main__":
    unittest.main()
