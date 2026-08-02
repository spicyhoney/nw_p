from __future__ import annotations

import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "home_repair_agent" / "web" / "static"


class VoiceFrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        cls.javascript = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
        cls.css = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")

    def test_voice_button_has_external_processing_and_confirmation_disclosure(self) -> None:
        self.assertIn('id="voice-button"', self.html)
        self.assertIn('id="voice-disclosure"', self.html)
        self.assertIn('aria-describedby="voice-disclosure"', self.html)
        self.assertIn("外部 Hugging Face Space", self.html)
        self.assertIn("辨識文字必須由你確認後再送出", self.html)
        self.assertIn('id="voice-status" role="status" aria-live="polite"', self.html)

    def test_voice_input_is_hf_only_and_never_auto_submits(self) -> None:
        self.assertIn("isHuggingFaceMediaAvailable()", self.javascript)
        self.assertIn("elements.voiceButton.hidden = !available", self.javascript)
        self.assertIn(
            'body.append("external_processing_confirmed", "true")',
            self.javascript,
        )
        self.assertIn("elements.messageInput.value = combined", self.javascript)
        self.assertIn("文字已填入但尚未送出", self.javascript)
        complete_voice = self.javascript.split("async function completeVoiceCapture(capture)", 1)[
            1
        ].split("function cancelVoiceCapture()", 1)[0]
        self.assertNotIn("requestSubmit", complete_voice)
        self.assertNotIn("handleMessageSubmit", complete_voice)

    def test_recording_is_bounded_cancelable_and_not_persisted_in_browser_storage(self) -> None:
        self.assertIn("VOICE_MAX_BYTES = 6 * 1024 * 1024", self.javascript)
        self.assertIn("VOICE_MAX_DURATION_MS = 30 * 1000", self.javascript)
        self.assertIn("cancelVoiceCapture", self.javascript)
        self.assertIn("stream.getTracks().forEach((track) => track.stop())", self.javascript)
        self.assertNotIn("localStorage", self.javascript)
        self.assertNotIn("sessionStorage", self.javascript)

    def test_slow_public_space_has_honest_elapsed_progress_without_provider_fallback(self) -> None:
        self.assertIn("VOICE_PROGRESS_INTERVAL_MS = 15 * 1000", self.javascript)
        self.assertIn('VOICE_EXPECTED_WAIT_SECONDS = "45–60"', self.javascript)
        self.assertIn("startVoiceProgress();", self.javascript)
        self.assertIn("已等待 ${elapsedSeconds} 秒", self.javascript)
        self.assertIn("可按「取消」後改用文字", self.javascript)
        self.assertIn("new AbortController()", self.javascript)
        self.assertIn("cancelVoiceTranscription();", self.javascript)
        self.assertIn("signal: abortController.signal", self.javascript)
        self.assertIn('error?.name === "AbortError"', self.javascript)
        self.assertIn("stopVoiceProgress();", self.javascript)
        self.assertNotIn("fallbackVoice", self.javascript)

    def test_voice_button_preserves_reachable_composer_layout(self) -> None:
        self.assertIn(".message-composer--voice", self.css)
        self.assertIn("64px minmax(0, 1fr) 48px", self.css)
        self.assertIn("height: 48px", self.css)
        self.assertIn("max-height: clamp(48px, 18dvh, 128px)", self.css)


if __name__ == "__main__":
    unittest.main()
