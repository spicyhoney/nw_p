from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "home_repair_agent" / "web" / "static"
STALE_REFRESH_TEST = Path(__file__).with_name("test_media_stale_refresh.js")


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
        self.assertIn('id="image-mode-button"', self.index)
        self.assertIn('aria-controls="media-section"', self.index)
        self.assertIn('aria-label="開啟圖片上傳與分析"', self.index)
        self.assertIn('id="media-file"', self.index)
        self.assertIn('accept="image/jpeg,image/png,image/webp"', self.index)
        self.assertIn('id="media-external-consent"', self.index)
        self.assertIn('id="media-status"', self.index)
        self.assertIn('role="status"', self.index)
        self.assertIn('aria-live="polite"', self.index)
        self.assertIn("MEDIA_MAX_BYTES = 8 * 1024 * 1024", self.app)
        self.assertIn("validateMediaFile", self.app)
        self.assertIn("function openImageMode()", self.app)
        self.assertIn("store.mediaModeExpanded = true", self.app)
        self.assertNotIn("請先確認水電修繕分支，再上傳圖片", self.app)

    def test_upload_uses_independent_hf_media_capability_and_explicit_consent(self) -> None:
        self.assertIn("health.media_provider", self.app)
        self.assertNotIn("health.model_provider", self.app)
        self.assertNotIn(
            "store.mediaProvider = store.session.provider.key",
            self.app,
        )
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
        self.assertIn("analysis_revision: media.analysis.analysis_revision", self.app)
        self.assertIn("analysis?.confirmed", self.app)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for DOM behavior checks")
    def test_media_confirmation_refresh_and_flow_lock_use_real_dom_behavior(self) -> None:
        result = subprocess.run(
            ["node", str(STALE_REFRESH_TEST)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("media stale refresh DOM regression: passed", result.stdout)
        self.assertIn("media flow lock DOM regression: passed", result.stdout)

    def test_confirmed_analysis_has_a_safe_summary_and_explicit_reedit_path(self) -> None:
        for control in (
            "media-confirmed-card",
            "media-confirmed-preview",
            "media-confirmed-service",
            "media-confirmed-summary",
            "media-edit-toggle",
            "media-confirmed-remove",
        ):
            self.assertIn(f'id="{control}"', self.index)
        self.assertIn('aria-controls="media-analysis-form"', self.index)
        self.assertIn("elements.mediaConfirmedService.textContent", self.app)
        self.assertIn("elements.mediaConfirmedSummary.textContent", self.app)
        self.assertIn("store.mediaEditorExpanded", self.app)
        self.assertNotIn("innerHTML", self.app)

    def test_media_refresh_preserves_an_unchanged_form_draft(self) -> None:
        self.assertIn("consultationFormSignature", self.app)
        self.assertIn("formVersion: form.version", self.app)
        self.assertIn("if (signature !== store.formSignature)", self.app)
        self.assertIn("elements.formFields.replaceChildren", self.app)
        self.assertIn(
            "revealConversationSection(elements.formSection, elements.formTitle)", self.app
        )

    def test_session_reset_clears_unsubmitted_local_media_state(self) -> None:
        self.assertIn("resetTransientConversationUi", self.app)
        self.assertIn("clearPreviewObjectUrl();", self.app)
        self.assertIn("store.mediaModeExpanded = false", self.app)
        self.assertIn('elements.mediaFile.value = ""', self.app)
        self.assertIn("elements.mediaConsent.checked = false", self.app)
        self.assertIn('elements.mediaPreview?.removeAttribute("src")', self.app)

    def test_media_transitions_move_focus_to_the_next_available_control(self) -> None:
        self.assertIn(
            "elements.mediaAnalysisForm,\n        elements.mediaServiceQuery,",
            self.app,
        )
        self.assertIn(
            "revealConversationSection(elements.routingSection, elements.routingTitle)",
            self.app,
        )
        self.assertIn(
            "revealConversationSection(elements.mediaSection, elements.mediaFile)",
            self.app,
        )

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
