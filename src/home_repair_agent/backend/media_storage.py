"""Safe local storage for user-supplied repair photos.

This module deliberately owns files only.  Callers persist the returned relative
path with their case/session record; no binary image data belongs in a database.
"""

from __future__ import annotations

import os
import re
import stat
import warnings
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,119}$")
_MEDIA_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_MEDIA_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
_EXTENSION_CONTENT_TYPES = {
    extension: content_type for extension, content_type in _MEDIA_FORMATS.values()
}


class MediaStorageError(Exception):
    """A safe-to-expose storage failure.

    Messages intentionally contain neither uploaded bytes nor filesystem paths.
    """

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StoredMedia:
    """Database-safe reference to a normalized image object."""

    media_id: str
    relative_path: str
    content_type: str
    byte_size: int


@dataclass(frozen=True)
class MediaRead:
    content: bytes
    content_type: str


@dataclass(frozen=True)
class DeletionReceipt:
    """Handle for a staged deletion that may be committed or rolled back."""

    media: StoredMedia
    operation_id: str


class ObjectStorage(Protocol):
    """Minimal safe object operations used by a future object-store adapter."""

    def read_object(self, relative_path: str) -> bytes: ...

    def delete_object(self, relative_path: str) -> None: ...


class MediaStorage(ObjectStorage, Protocol):
    """Image-specific storage contract for session and case workflows."""

    def store_session_image(
        self,
        *,
        session_id: str,
        content: bytes,
        declared_content_type: str | None = None,
        original_filename: str | None = None,
    ) -> StoredMedia: ...

    def associate_with_case(self, *, media: StoredMedia, case_id: str) -> StoredMedia: ...

    def rollback_association(self, *, media: StoredMedia, session_id: str) -> StoredMedia: ...

    def read_image(self, media: StoredMedia) -> MediaRead: ...

    def stage_delete(self, *, media: StoredMedia) -> DeletionReceipt: ...

    def rollback_delete(self, receipt: DeletionReceipt) -> StoredMedia: ...

    def commit_delete(self, receipt: DeletionReceipt) -> None: ...

    def delete(self, *, media: StoredMedia) -> None: ...


def default_media_root() -> Path:
    """Return the configured media root without exposing it in errors or records."""

    configured_root = os.environ.get("MEDIA_ROOT")
    if configured_root:
        return Path(configured_root)
    return Path(__file__).resolve().parents[3] / "var" / "media"


class LocalMediaStorage:
    """Local filesystem implementation of :class:`MediaStorage`.

    Uploaded content is decoded, normalized and re-encoded before it reaches the
    filesystem.  The decoded format, rather than a client MIME type or filename,
    determines the generated extension and content type.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        configured_root = Path(root) if root is not None else default_media_root()
        self._root = self._initialize_root(configured_root)

    def store_session_image(
        self,
        *,
        session_id: str,
        content: bytes,
        declared_content_type: str | None = None,
        original_filename: str | None = None,
    ) -> StoredMedia:
        """Validate and normalize an image into ``sessions/{session}/{id}.{ext}``.

        Client MIME and filename values are accepted only for adapter compatibility;
        they never influence validation, format selection or the destination path.
        """

        del declared_content_type, original_filename
        self._validate_identifier(session_id, label="session")
        normalized, extension, content_type = self._normalize_image(content)
        media_id = uuid4().hex
        relative_path = f"sessions/{session_id}/{media_id}.{extension}"
        self._write_new(relative_path, normalized)
        return StoredMedia(
            media_id=media_id,
            relative_path=relative_path,
            content_type=content_type,
            byte_size=len(normalized),
        )

    def associate_with_case(self, *, media: StoredMedia, case_id: str) -> StoredMedia:
        """Atomically move one session image into the case-owned layout."""

        self._validate_identifier(case_id, label="case")
        source = self._validate_media(media, expected_kind="sessions")
        extension = source.suffix.lstrip(".")
        destination_relative = f"cases/{case_id}/{media.media_id}.{extension}"
        self._move(source, self._safe_path(destination_relative))
        return replace(media, relative_path=destination_relative)

    def rollback_association(self, *, media: StoredMedia, session_id: str) -> StoredMedia:
        """Move a case image back to a session after a failed case transaction."""

        self._validate_identifier(session_id, label="session")
        source = self._validate_media(media, expected_kind="cases")
        extension = source.suffix.lstrip(".")
        destination_relative = f"sessions/{session_id}/{media.media_id}.{extension}"
        self._move(source, self._safe_path(destination_relative))
        return replace(media, relative_path=destination_relative)

    def read_image(self, media: StoredMedia) -> MediaRead:
        path = self._validate_media(media)
        extension = path.suffix.lstrip(".")
        return MediaRead(
            content=self._read(path),
            content_type=_EXTENSION_CONTENT_TYPES[extension],
        )

    def read_object(self, relative_path: str) -> bytes:
        """Read only a generated session/case media key, never an arbitrary path."""

        return self._read(self._safe_path(relative_path))

    def delete_object(self, relative_path: str) -> None:
        """Permanently remove only a generated session/case media key."""

        self._delete_path(self._safe_path(relative_path))

    def delete(self, *, media: StoredMedia) -> None:
        """Permanently delete a media object when rollback is not required."""

        self._delete_path(self._validate_media(media))

    def stage_delete(self, *, media: StoredMedia) -> DeletionReceipt:
        """Move an object into private staging so a surrounding transaction can roll back."""

        source = self._validate_media(media)
        operation_id = uuid4().hex
        staged_relative = f".deletions/{operation_id}/{source.name}"
        self._move(source, self._safe_path(staged_relative, allow_staging=True))
        return DeletionReceipt(media=media, operation_id=operation_id)

    def rollback_delete(self, receipt: DeletionReceipt) -> StoredMedia:
        """Restore an object previously passed to :meth:`stage_delete`."""

        original = self._validate_media(receipt.media)
        staged = self._staged_path(receipt)
        if original.exists():
            raise MediaStorageError(
                code="MEDIA_ROLLBACK_CONFLICT",
                message="The media object cannot be restored safely.",
            )
        self._move(staged, original)
        self._remove_empty_parents(staged.parent)
        return receipt.media

    def commit_delete(self, receipt: DeletionReceipt) -> None:
        """Finalize a staged deletion after the surrounding transaction commits."""

        self._delete_path(self._staged_path(receipt), allow_staging=True)

    def _normalize_image(self, content: bytes) -> tuple[bytes, str, str]:
        if not isinstance(content, bytes):
            raise MediaStorageError(
                code="INVALID_MEDIA_CONTENT",
                message="Image content must be binary data.",
            )
        if not content:
            raise MediaStorageError(code="INVALID_IMAGE", message="Image data is invalid.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise MediaStorageError(
                code="MEDIA_TOO_LARGE",
                message="Image files must not exceed 8 MB.",
            )

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as uploaded:
                    image_format = uploaded.format
                    if image_format not in _MEDIA_FORMATS:
                        raise MediaStorageError(
                            code="UNSUPPORTED_IMAGE_TYPE",
                            message="Only JPEG, PNG, and WebP images are allowed.",
                        )
                    uploaded.load()
                    normalized = self._copy_without_metadata(uploaded)
        except MediaStorageError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise MediaStorageError(
                code="INVALID_IMAGE",
                message="Image data is invalid.",
            ) from None
        except (UnidentifiedImageError, OSError, ValueError):
            raise MediaStorageError(
                code="INVALID_IMAGE",
                message="Image data is invalid.",
            ) from None

        extension, content_type = _MEDIA_FORMATS[image_format]
        output = BytesIO()
        try:
            save_options: dict[str, object] = {}
            if image_format == "JPEG":
                save_options.update(quality=90, optimize=True)
            normalized.save(output, format=image_format, **save_options)
        except OSError:
            raise MediaStorageError(
                code="IMAGE_NORMALIZATION_FAILED",
                message="Image data could not be normalized.",
            ) from None
        normalized_content = output.getvalue()
        if len(normalized_content) > MAX_UPLOAD_BYTES:
            raise MediaStorageError(
                code="MEDIA_TOO_LARGE",
                message="Image files must not exceed 8 MB.",
            )
        return normalized_content, extension, content_type

    @staticmethod
    def _copy_without_metadata(uploaded: Image.Image) -> Image.Image:
        has_alpha = uploaded.mode in {"RGBA", "LA"} or "transparency" in uploaded.info
        if uploaded.format == "JPEG":
            mode = "RGB"
        else:
            mode = "RGBA" if has_alpha else "RGB"
        clean = Image.new(mode, uploaded.size)
        clean.paste(uploaded.convert(mode))
        return clean

    def _validate_media(self, media: StoredMedia, *, expected_kind: str | None = None) -> Path:
        if not isinstance(media, StoredMedia) or not _MEDIA_ID_PATTERN.fullmatch(media.media_id):
            raise MediaStorageError(
                code="INVALID_MEDIA_REFERENCE", message="Media reference is invalid."
            )
        path = self._safe_path(media.relative_path)
        parts = PurePosixPath(media.relative_path).parts
        if expected_kind is not None and parts[0] != expected_kind:
            raise MediaStorageError(
                code="INVALID_MEDIA_REFERENCE", message="Media reference is invalid."
            )
        expected_name = f"{media.media_id}{path.suffix}"
        if path.name != expected_name:
            raise MediaStorageError(
                code="INVALID_MEDIA_REFERENCE", message="Media reference is invalid."
            )
        return path

    def _safe_path(self, relative_path: str, *, allow_staging: bool = False) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")
        if "\\" in relative_path or relative_path.startswith(("/", "~")):
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")

        parts = path.parts
        if len(parts) != 3:
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")
        if parts[0] in {"sessions", "cases"}:
            self._validate_identifier(parts[1], label="owner")
            self._validate_media_filename(parts[2])
        elif allow_staging and parts[0] == ".deletions":
            if not _MEDIA_ID_PATTERN.fullmatch(parts[1]):
                raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")
            self._validate_media_filename(parts[2])
        else:
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")

        candidate = self._root.joinpath(*parts)
        self._assert_no_symlink(candidate, include_target=True)
        return candidate

    def _staged_path(self, receipt: DeletionReceipt) -> Path:
        if not isinstance(receipt, DeletionReceipt) or not _MEDIA_ID_PATTERN.fullmatch(
            receipt.operation_id
        ):
            raise MediaStorageError(
                code="INVALID_DELETE_RECEIPT", message="Deletion receipt is invalid."
            )
        filename = PurePosixPath(receipt.media.relative_path).name
        return self._safe_path(
            f".deletions/{receipt.operation_id}/{filename}",
            allow_staging=True,
        )

    @staticmethod
    def _validate_identifier(value: str, *, label: str) -> None:
        if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
            raise MediaStorageError(
                code="INVALID_MEDIA_OWNER",
                message=f"The {label} identifier is invalid.",
            )

    @staticmethod
    def _validate_media_filename(filename: str) -> None:
        media_id, separator, extension = filename.partition(".")
        if (
            not separator
            or not _MEDIA_ID_PATTERN.fullmatch(media_id)
            or extension not in _EXTENSION_CONTENT_TYPES
        ):
            raise MediaStorageError(code="INVALID_MEDIA_PATH", message="Media path is invalid.")

    @staticmethod
    def _initialize_root(configured_root: Path) -> Path:
        root = configured_root.expanduser().absolute()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_UNAVAILABLE",
                message="Media storage is unavailable.",
            ) from None
        if root.is_symlink():
            raise MediaStorageError(
                code="MEDIA_STORAGE_UNAVAILABLE",
                message="Media storage is unavailable.",
            )
        return root.resolve(strict=True)

    def _assert_no_symlink(self, path: Path, *, include_target: bool) -> None:
        try:
            relative = path.relative_to(self._root)
        except ValueError:
            raise MediaStorageError(
                code="INVALID_MEDIA_PATH", message="Media path is invalid."
            ) from None

        current = self._root
        parts = relative.parts if include_target else relative.parts[:-1]
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise MediaStorageError(code="UNSAFE_MEDIA_PATH", message="Media path is unsafe.")

    def _write_new(self, relative_path: str, content: bytes) -> None:
        destination = self._safe_path(relative_path)
        self._prepare_parent(destination)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(destination, flags, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
        except FileExistsError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_CONFLICT",
                message="Media storage could not allocate an image.",
            ) from None
        except OSError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_UNAVAILABLE",
                message="Media storage is unavailable.",
            ) from None

    def _read(self, path: Path) -> bytes:
        self._assert_no_symlink(path, include_target=True)
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, "rb") as source:
                return source.read()
        except OSError:
            raise MediaStorageError(
                code="MEDIA_NOT_FOUND", message="Media was not found."
            ) from None

    def _move(self, source: Path, destination: Path) -> None:
        self._assert_no_symlink(source, include_target=True)
        self._prepare_parent(destination)
        try:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError
            if not stat.S_ISREG(source.lstat().st_mode):
                raise OSError
            os.replace(source, destination)
        except FileExistsError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_CONFLICT",
                message="Media storage could not move the image safely.",
            ) from None
        except OSError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_UNAVAILABLE",
                message="Media storage is unavailable.",
            ) from None

    def _delete_path(self, path: Path, *, allow_staging: bool = False) -> None:
        self._safe_path(
            path.relative_to(self._root).as_posix(),
            allow_staging=allow_staging,
        )
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise OSError
            path.unlink()
        except OSError:
            raise MediaStorageError(
                code="MEDIA_NOT_FOUND", message="Media was not found."
            ) from None
        self._remove_empty_parents(path.parent)

    def _prepare_parent(self, path: Path) -> None:
        self._assert_no_symlink(path, include_target=False)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise MediaStorageError(
                code="MEDIA_STORAGE_UNAVAILABLE",
                message="Media storage is unavailable.",
            ) from None
        self._assert_no_symlink(path, include_target=False)

    def _remove_empty_parents(self, start: Path) -> None:
        current = start
        while current != self._root:
            try:
                current.rmdir()
            except OSError:
                return
            current = current.parent
