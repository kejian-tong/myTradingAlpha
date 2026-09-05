"""Create-only local raw capture storage for PIT-01."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import StableId

from .capture import CapturedPayload
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_SHA256_PREFIX = "sha256:"
_MANIFEST_ENVELOPE_KEYS = frozenset({"manifest", "manifest_checksum"})
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


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


@dataclass(frozen=True)
class _WriteDirectories:
    root: int
    objects: int
    sha256: int
    manifests: int
    locks: int


@dataclass(frozen=True)
class _ReadDirectories:
    root: int
    objects: int
    sha256: int
    manifests: int


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
        configured = Path(root)
        self._configured_root = Path(os.path.abspath(os.fspath(configured)))
        try:
            self._physical_root = self._configured_root.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RawStoreCorruptionError("cannot resolve the configured raw-store root") from exc
        self._operation_lock = threading.RLock()
        self._identity_lock = threading.Lock()
        self._directory_identities: dict[str, tuple[int, int]] = {}

    def put(self, captured: CapturedPayload) -> None:
        """Create a manifest and raw object, or accept an identical prior write."""

        manifest_id = self._validated_key_from_capture(captured)
        normalized = self._revalidate_capture(captured)
        manifest_bytes = self._manifest_envelope_bytes(normalized.manifest)
        object_name = self._object_name(normalized.manifest.checksum)
        manifest_name = self._manifest_name(manifest_id)

        # The file-lock context depends on the verified directory descriptor yielded here.
        with self._operation_lock, self._write_directories() as directories:  # noqa: SIM117
            with self._manifest_lock(directories.locks, manifest_id):
                if self._entry_exists(directories.manifests, manifest_name):
                    existing = self._read_captured_from_directories(
                        directories.manifests,
                        directories.sha256,
                        manifest_id,
                    )
                    if existing == normalized:
                        return
                    raise RawStoreConflictError(
                        f"manifest_id already stores different content: {manifest_id}"
                    )

                if self._entry_exists(directories.sha256, object_name):
                    existing_object = self._read_regular_file(
                        directories.sha256,
                        object_name,
                        missing_error=RawStoreCorruptionError,
                        missing_message="manifest references a missing raw object",
                    )
                    if existing_object != normalized.raw_bytes or _sha256(existing_object) != (
                        normalized.manifest.checksum
                    ):
                        raise RawStoreCorruptionError(
                            "content-addressed object does not match its checksum name"
                        )
                else:
                    published = self._publish_no_clobber(
                        directories.sha256,
                        object_name,
                        normalized.raw_bytes,
                    )
                    if not published:
                        existing_object = self._read_regular_file(
                            directories.sha256,
                            object_name,
                            missing_error=RawStoreCorruptionError,
                            missing_message="raw object disappeared during publication",
                        )
                        if existing_object != normalized.raw_bytes:
                            raise RawStoreCorruptionError(
                                "competing object publication produced different bytes"
                            )

                if not self._publish_no_clobber(
                    directories.manifests,
                    manifest_name,
                    manifest_bytes,
                ):
                    existing = self._read_captured_from_directories(
                        directories.manifests,
                        directories.sha256,
                        manifest_id,
                    )
                    if existing == normalized:
                        return
                    raise RawStoreConflictError(
                        f"manifest_id was concurrently claimed: {manifest_id}"
                    )

    def get(self, manifest_id: str) -> CapturedPayload:
        """Load a capture only after revalidating every persisted boundary."""

        validated_id = self._validate_key(manifest_id)
        with self._operation_lock, self._read_directories() as directories:
            return self._read_captured_from_directories(
                directories.manifests,
                directories.sha256,
                validated_id,
            )

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

    @staticmethod
    def _manifest_name(manifest_id: str) -> str:
        return f"{manifest_id}.json"

    @staticmethod
    def _object_name(checksum: str) -> str:
        if not checksum.startswith(_SHA256_PREFIX):
            raise RawStoreCorruptionError("manifest checksum uses an unsupported algorithm")
        digest = checksum.removeprefix(_SHA256_PREFIX)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RawStoreCorruptionError("manifest checksum is not canonical SHA-256")
        return digest

    @staticmethod
    def _manifest_envelope_bytes(manifest: SourceManifest) -> bytes:
        manifest_value = manifest.model_dump(mode="json")
        manifest_bytes = _canonical_json(manifest_value)
        envelope = {
            "manifest": manifest_value,
            "manifest_checksum": _sha256(manifest_bytes),
        }
        return _canonical_json(envelope)

    def _read_captured_from_directories(
        self,
        manifests_fd: int,
        sha256_fd: int,
        manifest_id: str,
    ) -> CapturedPayload:
        manifest_bytes = self._read_regular_file(
            manifests_fd,
            self._manifest_name(manifest_id),
            missing_error=RawStoreNotFoundError,
            missing_message=f"manifest not found: {manifest_id}",
        )
        manifest = self._decode_manifest(manifest_bytes, manifest_id)
        raw_bytes = self._read_regular_file(
            sha256_fd,
            self._object_name(manifest.checksum),
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
            UnicodeDecodeError, json.JSONDecodeError, TypeError, ValidationError, ValueError,
            RecursionError,
        ) as exc:
            raise RawStoreCorruptionError("manifest failed integrity validation") from exc

    @contextmanager
    def _write_directories(self) -> Iterator[_WriteDirectories]:
        self._assert_configured_target()
        descriptors: list[int] = []
        try:
            root = self._open_physical_root(create=True, missing_error=RawStoreCorruptionError)
            descriptors.append(root)
            self._verify_directory_identity("root", root)
            objects = self._open_child_directory(root, "objects", create=True)
            descriptors.append(objects)
            self._verify_directory_identity("objects", objects)
            sha256 = self._open_child_directory(objects, "sha256", create=True)
            descriptors.append(sha256)
            self._verify_directory_identity("objects/sha256", sha256)
            manifests = self._open_child_directory(root, "manifests", create=True)
            descriptors.append(manifests)
            self._verify_directory_identity("manifests", manifests)
            locks = self._open_child_directory(root, "locks", create=True)
            descriptors.append(locks)
            self._verify_directory_identity("locks", locks)
            directories = _WriteDirectories(root, objects, sha256, manifests, locks)
            yield directories
            self._verify_write_bindings(directories)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            self._assert_configured_target()

    @contextmanager
    def _read_directories(self) -> Iterator[_ReadDirectories]:
        self._assert_configured_target()
        descriptors: list[int] = []
        try:
            root = self._open_physical_root(create=False, missing_error=RawStoreNotFoundError)
            descriptors.append(root)
            self._verify_directory_identity("root", root)
            manifests = self._open_child_directory(
                root,
                "manifests",
                create=False,
                missing_error=RawStoreNotFoundError,
            )
            descriptors.append(manifests)
            self._verify_directory_identity("manifests", manifests)
            objects = self._open_child_directory(root, "objects", create=False)
            descriptors.append(objects)
            self._verify_directory_identity("objects", objects)
            sha256 = self._open_child_directory(objects, "sha256", create=False)
            descriptors.append(sha256)
            self._verify_directory_identity("objects/sha256", sha256)
            directories = _ReadDirectories(root, objects, sha256, manifests)
            yield directories
            self._verify_read_bindings(directories)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            self._assert_configured_target()

    def _assert_configured_target(self) -> None:
        try:
            current_target = self._configured_root.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise RawStoreCorruptionError("configured raw-store root no longer resolves") from exc
        if current_target != self._physical_root:
            raise RawStoreCorruptionError("configured raw-store root was retargeted")

    def _open_physical_root(
        self,
        *,
        create: bool,
        missing_error: type[RawStoreError],
    ) -> int:
        try:
            descriptor = os.open(self._physical_root.anchor, _DIRECTORY_OPEN_FLAGS)
        except OSError as exc:
            raise RawStoreCorruptionError("cannot open filesystem anchor") from exc
        try:
            for component in self._physical_root.parts[1:]:
                next_descriptor = self._open_child_directory(
                    descriptor,
                    component,
                    create=create,
                    missing_error=missing_error,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    @staticmethod
    def _open_child_directory(
        parent_fd: int,
        name: str,
        *,
        create: bool,
        missing_error: type[RawStoreError] = RawStoreCorruptionError,
    ) -> int:
        try:
            return os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError as exc:
            if not create:
                raise missing_error(f"required store directory is missing: {name}") from exc
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            except OSError as mkdir_error:
                raise RawStoreCorruptionError(
                    f"cannot create required store directory: {name}"
                ) from mkdir_error
            try:
                return os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
            except OSError as open_error:
                raise RawStoreCorruptionError(
                    f"created store path is not a safe directory: {name}"
                ) from open_error
        except OSError as exc:
            raise RawStoreCorruptionError(f"store path is not a safe directory: {name}") from exc

    def _verify_directory_identity(self, name: str, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise RawStoreCorruptionError(f"store path is not a directory: {name}")
        identity = (opened.st_dev, opened.st_ino)
        with self._identity_lock:
            expected = self._directory_identities.setdefault(name, identity)
        if expected != identity:
            raise RawStoreCorruptionError(f"store directory was replaced: {name}")

    def _verify_write_bindings(self, directories: _WriteDirectories) -> None:
        self._verify_current_root_binding(directories.root)
        self._verify_child_directory_binding(directories.root, "objects", directories.objects)
        self._verify_child_directory_binding(directories.objects, "sha256", directories.sha256)
        self._verify_child_directory_binding(directories.root, "manifests", directories.manifests)
        self._verify_child_directory_binding(directories.root, "locks", directories.locks)

    def _verify_read_bindings(self, directories: _ReadDirectories) -> None:
        self._verify_current_root_binding(directories.root)
        self._verify_child_directory_binding(directories.root, "objects", directories.objects)
        self._verify_child_directory_binding(directories.objects, "sha256", directories.sha256)
        self._verify_child_directory_binding(directories.root, "manifests", directories.manifests)

    def _verify_current_root_binding(self, operation_root_fd: int) -> None:
        current_root_fd = self._open_physical_root(
            create=False,
            missing_error=RawStoreCorruptionError,
        )
        try:
            self._assert_same_directory(
                os.fstat(operation_root_fd),
                os.fstat(current_root_fd),
                "root",
            )
        finally:
            os.close(current_root_fd)

    @classmethod
    def _verify_child_directory_binding(
        cls,
        parent_fd: int,
        name: str,
        opened_child_fd: int,
    ) -> None:
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise RawStoreCorruptionError(f"store directory binding disappeared: {name}") from exc
        except OSError as exc:
            raise RawStoreCorruptionError(f"cannot verify store directory binding: {name}") from exc
        cls._assert_same_directory(os.fstat(opened_child_fd), current, name)

    @staticmethod
    def _assert_same_directory(first: os.stat_result, second: os.stat_result, name: str) -> None:
        if (
            not stat.S_ISDIR(first.st_mode)
            or not stat.S_ISDIR(second.st_mode)
            or first.st_dev != second.st_dev
            or first.st_ino != second.st_ino
        ):
            raise RawStoreCorruptionError(f"store directory binding changed: {name}")

    @contextmanager
    def _manifest_lock(self, locks_fd: int, manifest_id: str) -> Iterator[None]:
        lock_name = f"{manifest_id}.lock"
        descriptor = self._open_manifest_lock(locks_fd, lock_name)
        try:
            self._verify_regular_file_binding(locks_fd, lock_name, descriptor)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._verify_regular_file_binding(locks_fd, lock_name, descriptor)
            yield
        finally:
            try:
                self._verify_regular_file_binding(locks_fd, lock_name, descriptor)
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    @classmethod
    def _open_manifest_lock(cls, locks_fd: int, lock_name: str) -> int:
        common_flags = (
            os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        for _attempt in range(100):
            try:
                descriptor = os.open(
                    lock_name,
                    common_flags | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=locks_fd,
                )
            except FileExistsError:
                try:
                    descriptor = os.open(lock_name, common_flags, dir_fd=locks_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise RawStoreCorruptionError(
                        "manifest lock is not a safe regular file"
                    ) from exc
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RawStoreCorruptionError(
                    "manifest lock cannot be exclusively created"
                ) from exc

            try:
                cls._verify_regular_file_binding(locks_fd, lock_name, descriptor)
            except Exception:
                os.close(descriptor)
                raise
            return descriptor
        raise RawStoreCorruptionError("manifest lock remained unavailable during creation")

    @staticmethod
    def _verify_regular_file_binding(parent_fd: int, name: str, opened_fd: int) -> None:
        try:
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise RawStoreCorruptionError(f"store file binding disappeared: {name}") from exc
        except OSError as exc:
            raise RawStoreCorruptionError(f"cannot verify store file binding: {name}") from exc
        opened = os.fstat(opened_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_dev != current.st_dev
            or opened.st_ino != current.st_ino
        ):
            raise RawStoreCorruptionError(f"store file binding changed: {name}")

    @staticmethod
    def _entry_exists(directory_fd: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RawStoreCorruptionError(f"cannot inspect store entry: {name}") from exc
        return True

    @staticmethod
    def _publish_no_clobber(directory_fd: int, name: str, value: bytes) -> bool:
        temporary_name: str | None = None
        descriptor: int | None = None
        for _attempt in range(100):
            candidate = f".{name}.{secrets.token_hex(12)}.tmp"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                continue
            except OSError as exc:
                raise RawStoreCorruptionError("cannot create atomic temporary entry") from exc
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise RawStoreCorruptionError("cannot allocate a unique atomic temporary entry")

        try:
            remaining = memoryview(value)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise RawStoreCorruptionError("short write while publishing store entry")
                remaining = remaining[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                return False
            except OSError as exc:
                raise RawStoreCorruptionError("cannot publish atomic store entry") from exc
            os.fsync(directory_fd)
            return True
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise RawStoreCorruptionError("cannot remove atomic temporary entry") from exc

    @staticmethod
    def _read_regular_file(
        directory_fd: int,
        name: str,
        *,
        missing_error: type[RawStoreError],
        missing_message: str,
    ) -> bytes:
        try:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise missing_error(missing_message) from exc
        except OSError as exc:
            raise RawStoreCorruptionError(f"cannot inspect store entry: {name}") from exc
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise RawStoreCorruptionError(f"store entry is not a regular file: {name}")

        try:
            descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_fd)
        except FileNotFoundError as exc:
            raise missing_error(missing_message) from exc
        except OSError as exc:
            raise RawStoreCorruptionError(f"store entry became unsafe while opening: {name}") from exc

        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
            ):
                raise RawStoreCorruptionError(f"store entry changed while opening: {name}")
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
