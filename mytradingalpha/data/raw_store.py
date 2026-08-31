"""Create-only local raw capture storage for PIT-01."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import StableId

from .capture import CapturedPayload
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_SHA256_PREFIX = "sha256:"
_MANIFEST_ENVELOPE_KEYS = frozenset({"manifest", "manifest_checksum"})


class RawStoreError(Exception):
    """Base class for typed raw-store failures."""


class RawStoreConflictError(RawStoreError):
    """A manifest ID already identifies different immutable content."""


class RawStoreCorruptionError(RawStoreError):
    """A stored entry is malformed, unsafe, or fails integrity validation."""


class RawStoreNotFoundError(RawStoreError):
    """A requested manifest does not exist."""


class RawStoreInvalidKeyError(RawStoreError):
    """A manifest key is invalid or could escape the store root."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return f"{_SHA256_PREFIX}{hashlib.sha256(value).hexdigest()}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


class RawStore:
    """Local immutable manifests plus checksum-addressed arbitrary raw bytes."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def _objects_dir(self) -> Path:
        return self._root / "objects" / "sha256"

    @property
    def _manifests_dir(self) -> Path:
        return self._root / "manifests"

    @property
    def _locks_dir(self) -> Path:
        return self._root / "locks"

    def put(self, captured: CapturedPayload) -> None:
        """Create a manifest and raw object, or accept an identical prior write."""

        manifest_id = self._validated_key_from_capture(captured)
        normalized = self._revalidate_capture(captured)
        self._ensure_storage_directories()

        manifest_bytes = self._manifest_envelope_bytes(normalized.manifest)
        manifest_path = self._manifest_path(manifest_id)
        object_path = self._object_path(normalized.manifest.checksum)

        with self._manifest_lock(manifest_id):
            if self._entry_exists(manifest_path):
                existing = self._read_captured(manifest_id)
                if existing == normalized:
                    return
                raise RawStoreConflictError(
                    f"manifest_id already stores different content: {manifest_id}"
                )

            if self._entry_exists(object_path):
                existing_object = self._read_regular_file(
                    object_path,
                    missing_error=RawStoreCorruptionError,
                    missing_message="manifest references a missing raw object",
                )
                if existing_object != normalized.raw_bytes or _sha256(existing_object) != (
                    normalized.manifest.checksum
                ):
                    raise RawStoreCorruptionError(
                        "content-addressed object does not match its checksum path"
                    )
            else:
                published = self._publish_no_clobber(object_path, normalized.raw_bytes)
                if not published:
                    existing_object = self._read_regular_file(
                        object_path,
                        missing_error=RawStoreCorruptionError,
                        missing_message="raw object disappeared during publication",
                    )
                    if existing_object != normalized.raw_bytes:
                        raise RawStoreCorruptionError(
                            "competing object publication produced different bytes"
                        )

            if not self._publish_no_clobber(manifest_path, manifest_bytes):
                existing = self._read_captured(manifest_id)
                if existing == normalized:
                    return
                raise RawStoreConflictError(f"manifest_id was concurrently claimed: {manifest_id}")

    def get(self, manifest_id: str) -> CapturedPayload:
        """Load a capture only after revalidating every persisted boundary."""

        validated_id = self._validate_key(manifest_id)
        return self._read_captured(validated_id)

    def _validated_key_from_capture(self, captured: CapturedPayload) -> str:
        try:
            manifest_id = captured.manifest.manifest_id
        except (AttributeError, TypeError) as exc:
            raise RawStoreCorruptionError("put requires a CapturedPayload") from exc
        return self._validate_key(manifest_id)

    @staticmethod
    def _validate_key(value: object) -> str:
        try:
            validated = _STABLE_ID_ADAPTER.validate_python(value)
        except ValidationError as exc:
            raise RawStoreInvalidKeyError("invalid manifest_id") from exc
        if Path(validated).name != validated or validated in {".", ".."}:
            raise RawStoreInvalidKeyError("manifest_id cannot contain path traversal")
        return validated

    @staticmethod
    def _revalidate_capture(captured: CapturedPayload) -> CapturedPayload:
        try:
            serialized = captured.model_dump(mode="python")
            return CapturedPayload.model_validate(serialized)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise RawStoreCorruptionError("captured payload failed boundary validation") from exc

    def _manifest_path(self, manifest_id: str) -> Path:
        return self._manifests_dir / f"{manifest_id}.json"

    def _object_path(self, checksum: str) -> Path:
        if not checksum.startswith(_SHA256_PREFIX):
            raise RawStoreCorruptionError("manifest checksum uses an unsupported algorithm")
        digest = checksum.removeprefix(_SHA256_PREFIX)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RawStoreCorruptionError("manifest checksum is not canonical SHA-256")
        return self._objects_dir / digest

    @staticmethod
    def _manifest_envelope_bytes(manifest: SourceManifest) -> bytes:
        manifest_value = manifest.model_dump(mode="json")
        manifest_bytes = _canonical_json(manifest_value)
        envelope = {
            "manifest": manifest_value,
            "manifest_checksum": _sha256(manifest_bytes),
        }
        return _canonical_json(envelope)

    def _read_captured(self, manifest_id: str) -> CapturedPayload:
        self._require_read_directories()
        manifest_bytes = self._read_regular_file(
            self._manifest_path(manifest_id),
            missing_error=RawStoreNotFoundError,
            missing_message=f"manifest not found: {manifest_id}",
        )
        manifest = self._decode_manifest(manifest_bytes, manifest_id)
        self._require_directory(self._root / "objects")
        self._require_directory(self._objects_dir)
        raw_bytes = self._read_regular_file(
            self._object_path(manifest.checksum),
            missing_error=RawStoreCorruptionError,
            missing_message="manifest references a missing raw object",
        )
        if _sha256(raw_bytes) != manifest.checksum:
            raise RawStoreCorruptionError("raw object checksum mismatch")
        try:
            return CapturedPayload(manifest=manifest, raw_bytes=raw_bytes)
        except (TypeError, ValidationError, ValueError) as exc:
            raise RawStoreCorruptionError("stored payload failed contract validation") from exc

    @staticmethod
    def _decode_manifest(value: bytes, requested_id: str) -> SourceManifest:
        try:
            envelope = json.loads(value, object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(envelope, dict) or frozenset(envelope) != _MANIFEST_ENVELOPE_KEYS:
                raise ValueError("invalid manifest envelope fields")
            manifest_value = envelope["manifest"]
            manifest_checksum = envelope["manifest_checksum"]
            if not isinstance(manifest_value, dict) or not isinstance(manifest_checksum, str):
                raise ValueError("invalid manifest envelope types")
            if _sha256(_canonical_json(manifest_value)) != manifest_checksum:
                raise ValueError("manifest envelope checksum mismatch")
            manifest = SourceManifest.model_validate(manifest_value)
            if manifest.manifest_id != requested_id:
                raise ValueError("manifest ID does not match its store key")
            return manifest
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValidationError,
            ValueError,
        ) as exc:
            raise RawStoreCorruptionError("manifest failed integrity validation") from exc

    def _ensure_storage_directories(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._require_directory(self._root)
        for directory in (
            self._root / "objects",
            self._objects_dir,
            self._manifests_dir,
            self._locks_dir,
        ):
            directory.mkdir(exist_ok=True)
            self._require_directory(directory)

    def _require_read_directories(self) -> None:
        if not self._entry_exists(self._root) or not self._entry_exists(self._manifests_dir):
            raise RawStoreNotFoundError("raw store or manifest directory does not exist")
        self._require_directory(self._root)
        self._require_directory(self._manifests_dir)

    @staticmethod
    def _require_directory(path: Path) -> None:
        try:
            entry = path.lstat()
        except FileNotFoundError as exc:
            raise RawStoreCorruptionError(
                f"required store directory is missing: {path.name}"
            ) from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise RawStoreCorruptionError(f"store path is not a safe directory: {path.name}")

    @staticmethod
    def _entry_exists(path: Path) -> bool:
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        return True

    @contextmanager
    def _manifest_lock(self, manifest_id: str) -> Iterator[None]:
        lock_path = self._locks_dir / f"{manifest_id}.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                raise RawStoreCorruptionError("manifest lock is not a regular file") from exc
            raise
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RawStoreCorruptionError("manifest lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    @staticmethod
    def _publish_no_clobber(path: Path, value: bytes) -> bool:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, path)
            except FileExistsError:
                return False
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            return True
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _read_regular_file(
        path: Path,
        *,
        missing_error: type[RawStoreError],
        missing_message: str,
    ) -> bytes:
        try:
            before = path.lstat()
        except FileNotFoundError as exc:
            raise missing_error(missing_message) from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise RawStoreCorruptionError(f"store entry is not a regular file: {path.name}")

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            raise missing_error(missing_message) from exc
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.EISDIR}:
                raise RawStoreCorruptionError(
                    f"store entry became unsafe while opening: {path.name}"
                ) from exc
            raise

        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
            ):
                raise RawStoreCorruptionError(f"store entry changed while opening: {path.name}")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)


__all__ = [
    "RawStore",
    "RawStoreConflictError",
    "RawStoreCorruptionError",
    "RawStoreError",
    "RawStoreInvalidKeyError",
    "RawStoreNotFoundError",
]
