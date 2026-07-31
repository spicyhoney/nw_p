from __future__ import annotations

import os
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from home_repair_agent.backend.media_storage import (
    MAX_UPLOAD_BYTES,
    LocalMediaStorage,
    MediaStorageError,
    default_media_root,
)


def _image_bytes(image_format: str, *, exif: object | None = None) -> bytes:
    output = BytesIO()
    image = Image.new("RGB", (12, 8), color=(23, 91, 157))
    options: dict[str, object] = {}
    if exif is not None:
        options["exif"] = exif
    image.save(output, format=image_format, **options)
    return output.getvalue()


class LocalMediaStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "media"
        self.storage = LocalMediaStorage(self.root)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_media_root_defaults_to_repo_runtime_directory_and_can_be_overridden(self) -> None:
        expected_default = Path(__file__).resolve().parents[1] / "var" / "media"
        with patch.dict(os.environ, {"MEDIA_ROOT": ""}):
            self.assertEqual(expected_default, default_media_root())
        with patch.dict(os.environ, {"MEDIA_ROOT": str(self.root)}):
            self.assertEqual(self.root, default_media_root())

    def test_accepts_and_normalizes_each_allowed_decoded_format(self) -> None:
        expected = {
            "JPEG": ("jpg", "image/jpeg"),
            "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp"),
        }

        for image_format, (extension, content_type) in expected.items():
            with self.subTest(image_format=image_format):
                stored = self.storage.store_session_image(
                    session_id="session-001",
                    content=_image_bytes(image_format),
                )
                read = self.storage.read_image(stored)

                self.assertRegex(stored.media_id, r"^[a-f0-9]{32}$")
                self.assertEqual(
                    f"sessions/session-001/{stored.media_id}.{extension}",
                    stored.relative_path,
                )
                self.assertEqual(content_type, stored.content_type)
                self.assertEqual(content_type, read.content_type)
                with Image.open(BytesIO(read.content)) as result:
                    self.assertEqual(image_format, result.format)

    def test_client_mime_and_filename_cannot_choose_the_stored_format(self) -> None:
        stored = self.storage.store_session_image(
            session_id="session-001",
            content=_image_bytes("PNG"),
            declared_content_type="image/jpeg",
            original_filename="not-really-a-jpeg.jpg",
        )

        self.assertEqual("image/png", stored.content_type)
        self.assertTrue(stored.relative_path.endswith(".png"))

    def test_rejects_oversized_and_corrupt_content_without_writing_a_file(self) -> None:
        oversized = b"x" * (MAX_UPLOAD_BYTES + 1)
        for content, code in ((oversized, "MEDIA_TOO_LARGE"), (b"not an image", "INVALID_IMAGE")):
            with self.subTest(code=code):
                with self.assertRaises(MediaStorageError) as context:
                    self.storage.store_session_image(session_id="session-001", content=content)
                self.assertEqual(code, context.exception.code)
        self.assertFalse((self.root / "sessions").exists())

    def test_traversal_and_symlink_paths_are_rejected_without_exposing_paths(self) -> None:
        with self.assertRaises(MediaStorageError) as traversal:
            self.storage.store_session_image(
                session_id="../outside",
                content=_image_bytes("PNG"),
            )
        self.assertEqual("INVALID_MEDIA_OWNER", traversal.exception.code)
        self.assertNotIn(str(self.root), traversal.exception.message)

        with self.assertRaises(MediaStorageError) as object_traversal:
            self.storage.read_object("../outside/image.png")
        self.assertEqual("INVALID_MEDIA_PATH", object_traversal.exception.code)
        self.assertNotIn(str(self.root), object_traversal.exception.message)

        external = Path(self.temporary_directory.name) / "outside"
        external.mkdir()
        sessions = self.root / "sessions"
        try:
            sessions.symlink_to(external, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks are unavailable: {error}")
        with self.assertRaises(MediaStorageError) as symlink:
            self.storage.store_session_image(
                session_id="session-001",
                content=_image_bytes("PNG"),
            )
        self.assertEqual("UNSAFE_MEDIA_PATH", symlink.exception.code)
        self.assertFalse(any(external.iterdir()))

    def test_reencoding_strips_exif_metadata(self) -> None:
        exif = Image.Exif()
        exif[270] = "Sensitive metadata"
        original = _image_bytes("JPEG", exif=exif)
        with Image.open(BytesIO(original)) as uploaded:
            self.assertTrue(uploaded.getexif())

        stored = self.storage.store_session_image(session_id="session-001", content=original)
        result = self.storage.read_image(stored)

        with Image.open(BytesIO(result.content)) as normalized:
            self.assertEqual({}, dict(normalized.getexif()))
            self.assertNotIn("exif", normalized.info)

    def test_association_rollback_and_staged_deletion_cleanup(self) -> None:
        stored = self.storage.store_session_image(
            session_id="session-001",
            content=_image_bytes("WEBP"),
        )
        associated = self.storage.associate_with_case(media=stored, case_id="SYN-CASE-001")

        self.assertTrue(associated.relative_path.startswith("cases/SYN-CASE-001/"))
        with self.assertRaises(MediaStorageError) as missing_source:
            self.storage.read_image(stored)
        self.assertEqual("MEDIA_NOT_FOUND", missing_source.exception.code)

        restored = self.storage.rollback_association(media=associated, session_id="session-001")
        receipt = self.storage.stage_delete(media=restored)
        self.assertFalse((self.root / restored.relative_path).exists())

        self.storage.rollback_delete(receipt)
        self.assertTrue(self.storage.read_image(restored).content)
        receipt = self.storage.stage_delete(media=restored)
        self.storage.commit_delete(receipt)
        with self.assertRaises(MediaStorageError) as deleted:
            self.storage.read_image(restored)
        self.assertEqual("MEDIA_NOT_FOUND", deleted.exception.code)
        self.assertFalse((self.root / ".deletions").exists())


if __name__ == "__main__":
    unittest.main()
