#!/usr/bin/env python3
"""Cooperative, repository-global lease and durable structural evidence for one writer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATE_DIRECTORY = "codex-writer-lease"
ACTIVE_NAME = "active.json"
EVENTS_NAME = "events"
ARCHIVE_NAME = "archive"
MAX_EVENT_COUNT = 512
MAX_RECORD_BYTES = 4_096
MAX_EVIDENCE_BYTES = 262_144
MAX_DIRECTORY_ENTRIES = (MAX_EVENT_COUNT * 2) + 2
ZERO_DIGEST = "0" * 64

_WRITER_ROLES = frozenset(
    {"normal_implementer", "high_implementer", "critical_implementer"}
)
_CHECKPOINTS = frozenset(
    {"writer_start", "before_red", "before_green", "before_commit", "before_push"}
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_PR_ID = re.compile(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_IDENTITY_FIELDS = (
    "pr_id",
    "base_sha",
    "writer_role",
    "owner_ref",
    "session_ref",
    "lease_id",
)
_ACTIVE_FIELDS = frozenset({"schema_version", *_IDENTITY_FIELDS})
_EVENT_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "sequence",
        "previous_event_digest",
        *_IDENTITY_FIELDS,
    }
)
_EVIDENCE_FIELDS = frozenset({"schema_version", "events", *_IDENTITY_FIELDS})


class WriterLeaseError(RuntimeError):
    """A generic fail-closed lease error that never reflects caller-controlled values."""

    def __init__(self) -> None:
        super().__init__("writer lease operation failed")


class _LeaseArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "writer lease operation failed\n")


def _fail() -> None:
    raise WriterLeaseError()


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic, newline-free, ASCII JSON bytes."""
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail()


def evidence_digest(raw: bytes) -> str:
    if type(raw) is not bytes or len(raw) > MAX_EVIDENCE_BYTES:
        _fail()
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _decode_json(raw: bytes, maximum: int) -> object:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        _fail()
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, WriterLeaseError):
        _fail()
    if canonical_json_bytes(value) != raw:
        _fail()
    return value


def _is_ascii(value: str) -> bool:
    return value.isascii()


def _validate_identity_values(
    *,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
    lease_id: str | None = None,
) -> dict[str, str]:
    values = (pr_id, base_sha, writer_role, owner_ref, session_ref)
    if any(type(value) is not str or not _is_ascii(value) for value in values):
        _fail()
    if len(pr_id) > 64 or _PR_ID.fullmatch(pr_id) is None:
        _fail()
    if _HEX40.fullmatch(base_sha) is None:
        _fail()
    if writer_role not in _WRITER_ROLES:
        _fail()
    if _HEX64.fullmatch(owner_ref) is None or _HEX64.fullmatch(session_ref) is None:
        _fail()
    result = {
        "pr_id": pr_id,
        "base_sha": base_sha,
        "writer_role": writer_role,
        "owner_ref": owner_ref,
        "session_ref": session_ref,
    }
    if lease_id is not None:
        if type(lease_id) is not str or _HEX64.fullmatch(lease_id) is None:
            _fail()
        result["lease_id"] = lease_id
    return result


def _validate_identity_record(record: object) -> dict[str, Any]:
    if type(record) is not dict or set(record) != _ACTIVE_FIELDS:
        _fail()
    if type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION:
        _fail()
    _validate_identity_values(
        pr_id=record["pr_id"],
        base_sha=record["base_sha"],
        writer_role=record["writer_role"],
        owner_ref=record["owner_ref"],
        session_ref=record["session_ref"],
        lease_id=record["lease_id"],
    )
    return record


def _identity_matches(record: dict[str, Any], expected: dict[str, str]) -> bool:
    return all(record.get(field) == value for field, value in expected.items())


def _validate_label(value: str) -> None:
    if type(value) is not str or not value.isascii() or _LABEL.fullmatch(value) is None:
        _fail()


def _validate_event(record: object) -> dict[str, Any]:
    if type(record) is not dict:
        _fail()
    event_type = record.get("event_type")
    expected_fields = set(_EVENT_BASE_FIELDS)
    if event_type == "verify":
        expected_fields.update({"checkpoint", "phase"})
    elif event_type not in {"acquire", "release"}:
        _fail()
    if set(record) != expected_fields:
        _fail()
    if type(record["schema_version"]) is not int or record["schema_version"] != SCHEMA_VERSION:
        _fail()
    if type(record["sequence"]) is not int or record["sequence"] < 0:
        _fail()
    if type(record["previous_event_digest"]) is not str or _HEX64.fullmatch(
        record["previous_event_digest"]
    ) is None:
        _fail()
    _validate_identity_values(
        pr_id=record["pr_id"],
        base_sha=record["base_sha"],
        writer_role=record["writer_role"],
        owner_ref=record["owner_ref"],
        session_ref=record["session_ref"],
        lease_id=record["lease_id"],
    )
    if event_type == "verify":
        if record["checkpoint"] not in _CHECKPOINTS:
            _fail()
        _validate_label(record["phase"])
    return record


def _safe_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _git(repo_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(repo_root), *arguments],
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError):
        _fail()
    if result.returncode != 0 or len(result.stdout) > 4_096:
        _fail()
    try:
        output = result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError:
        _fail()
    if not output or "\n" in output or "\x00" in output:
        _fail()
    return output


def _validate_platform() -> None:
    if sys.platform not in {"darwin", "linux"}:
        _fail()


def _owned_directory(path: Path, *, exact_mode: int | None = None) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        _fail()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        _fail()
    mode = stat.S_IMODE(metadata.st_mode)
    if exact_mode is not None:
        if mode != exact_mode:
            _fail()
    elif mode & (stat.S_IWGRP | stat.S_IWOTH):
        _fail()


def _owned_file_descriptor(fd: int, mode: int) -> None:
    try:
        metadata = os.fstat(fd)
    except OSError:
        _fail()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != mode
    ):
        _fail()


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        metadata = os.fstat(fd)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise OSError
        return fd
    except OSError:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)
        _fail()


def _fsync_directory(path: Path) -> None:
    fd = _open_directory(path)
    try:
        os.fsync(fd)
    except OSError:
        _fail()
    finally:
        os.close(fd)


def _ensure_directory(path: Path, parent: Path) -> None:
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError:
        _fail()
    else:
        _fsync_directory(parent)
    _owned_directory(path, exact_mode=0o700)


def _path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        _fail()
    return True


def _state_paths(
    repo_root: Path | str, *, create: bool
) -> tuple[Path, Path, Path, Path]:
    _validate_platform()
    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        _fail()
    _owned_directory(root)
    common_text = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common_input = Path(common_text)
    if not common_input.is_absolute():
        _fail()
    try:
        common = common_input.resolve(strict=True)
    except OSError:
        _fail()
    if common != common_input:
        _fail()
    _owned_directory(common)
    state = common / STATE_DIRECTORY
    events = state / EVENTS_NAME
    archive = state / ARCHIVE_NAME
    if create:
        state_existed = _path_exists(state)
        _ensure_directory(state, common)
        if state_existed and not _path_exists(events):
            _fail()
        _ensure_directory(events, state)
    elif _path_exists(state):
        _owned_directory(state, exact_mode=0o700)
        if _path_exists(events):
            _owned_directory(events, exact_mode=0o700)
    return common, state, events, archive


def _verify_base_commit(repo_root: Path, base_sha: str) -> None:
    if _git(repo_root, "cat-file", "-t", base_sha) != "commit":
        _fail()


def _create_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _exclusive_write(path: Path, raw: bytes) -> None:
    if type(raw) is not bytes or not raw or len(raw) > MAX_RECORD_BYTES:
        _fail()
    fd: int | None = None
    try:
        fd = os.open(path, _create_flags(), 0o600)
        _owned_file_descriptor(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if type(written) is not int or written <= 0:
                raise OSError
            offset += written
        os.fsync(fd)
        parent_fd = _open_directory(path.parent)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except (OSError, WriterLeaseError):
        if fd is not None:
            try:
                os.ftruncate(fd, 0)
                os.fsync(fd)
            except OSError:
                pass
        _fail()
    finally:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)


def _read_regular(path: Path, maximum: int = MAX_RECORD_BYTES) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        _owned_file_descriptor(fd, 0o600)
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 4_096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not raw or len(raw) > maximum:
            _fail()
        return raw
    except (OSError, WriterLeaseError):
        _fail()
    finally:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)


def _bounded_names(directory: Path) -> list[str]:
    names: list[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > MAX_DIRECTORY_ENTRIES:
                    _fail()
    except (OSError, WriterLeaseError):
        _fail()
    return sorted(names)


def _scan_events(events: Path) -> list[tuple[dict[str, Any], bytes]]:
    _owned_directory(events, exact_mode=0o700)
    names = _bounded_names(events)
    if len(names) % 2:
        _fail()
    count = len(names) // 2
    if count > MAX_EVENT_COUNT:
        _fail()
    expected_names = sorted(
        name
        for sequence in range(count)
        for name in (f"{sequence:08d}.json", f"{sequence:08d}.commit")
    )
    if names != expected_names:
        _fail()
    result: list[tuple[dict[str, Any], bytes]] = []
    previous = ZERO_DIGEST
    identity: dict[str, str] | None = None
    for sequence in range(count):
        raw = _read_regular(events / f"{sequence:08d}.json")
        marker = _read_regular(events / f"{sequence:08d}.commit", 64)
        digest = hashlib.sha256(raw).hexdigest()
        if marker != digest.encode("ascii"):
            _fail()
        event = _validate_event(_decode_json(raw, MAX_RECORD_BYTES))
        if event["sequence"] != sequence or event["previous_event_digest"] != previous:
            _fail()
        event_identity = {field: event[field] for field in _IDENTITY_FIELDS}
        if identity is None:
            identity = event_identity
            if event["event_type"] != "acquire":
                _fail()
        elif event_identity != identity or event["event_type"] == "acquire":
            _fail()
        if result and result[-1][0]["event_type"] == "release":
            _fail()
        previous = digest
        result.append((event, raw))
    return result


def _append_event(events: Path, event: dict[str, Any]) -> dict[str, Any]:
    chain = _scan_events(events)
    sequence = len(chain)
    if sequence >= MAX_EVENT_COUNT:
        _fail()
    event = dict(event)
    event["sequence"] = sequence
    event["previous_event_digest"] = (
        hashlib.sha256(chain[-1][1]).hexdigest() if chain else ZERO_DIGEST
    )
    validated = _validate_event(event)
    raw = canonical_json_bytes(validated)
    _exclusive_write(events / f"{sequence:08d}.json", raw)
    _exclusive_write(
        events / f"{sequence:08d}.commit", hashlib.sha256(raw).hexdigest().encode("ascii")
    )
    return validated


def _archive_completed_lane(state: Path, events: Path) -> None:
    chain = _scan_events(events)
    if not chain:
        return
    if chain[-1][0]["event_type"] != "release":
        _fail()
    lease_id = chain[0][0]["lease_id"]
    archive = state / ARCHIVE_NAME
    _ensure_directory(archive, state)
    destination = archive / lease_id
    try:
        os.mkdir(destination, 0o700)
        _fsync_directory(archive)
        _owned_directory(destination, exact_mode=0o700)
        for name in _bounded_names(events):
            os.rename(events / name, destination / name)
        _fsync_directory(destination)
        _fsync_directory(events)
        _fsync_directory(state)
    except (OSError, WriterLeaseError):
        _fail()
    if _bounded_names(events):
        _fail()


def _record(identity: dict[str, str]) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **identity}


def _event(event_type: str, identity: dict[str, str], **detail: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": event_type,
        **identity,
        **detail,
        "sequence": 0,
        "previous_event_digest": ZERO_DIGEST,
    }


def inspect(*, repo_root: Path | str) -> dict[str, Any]:
    _common, state, events, _archive = _state_paths(repo_root, create=False)
    if not _path_exists(state):
        return {"status": "inactive"}
    if not _path_exists(events):
        return {"status": "blocked"}
    active_path = events.parent / ACTIVE_NAME
    try:
        active_exists = active_path.exists() or active_path.is_symlink()
        chain = _scan_events(events)
        if not active_exists:
            if not chain:
                return {"status": "inactive"}
            if chain[-1][0]["event_type"] == "release":
                return {"status": "released", "lease_id": chain[0][0]["lease_id"]}
            return {"status": "blocked"}
        active = _validate_identity_record(_decode_json(_read_regular(active_path), MAX_RECORD_BYTES))
        identity = {field: active[field] for field in _IDENTITY_FIELDS}
        if (
            not chain
            or not all(_identity_matches(event, identity) for event, _raw in chain)
            or chain[-1][0]["event_type"] == "release"
        ):
            return {"status": "blocked"}
        return {"status": "active", "active": active}
    except WriterLeaseError:
        return {"status": "blocked"}


def acquire(
    *,
    repo_root: Path | str,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
) -> dict[str, Any]:
    supplied = _validate_identity_values(
        pr_id=pr_id,
        base_sha=base_sha,
        writer_role=writer_role,
        owner_ref=owner_ref,
        session_ref=session_ref,
    )
    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, TypeError, ValueError):
        _fail()
    _verify_base_commit(root, base_sha)
    _common, state, events, _archive = _state_paths(root, create=True)
    lease_id = secrets.token_hex(32)
    identity = {**supplied, "lease_id": lease_id}
    active_path = state / ACTIVE_NAME
    _exclusive_write(active_path, canonical_json_bytes(_record(identity)))
    try:
        _archive_completed_lane(state, events)
        _append_event(events, _event("acquire", identity))
    except WriterLeaseError:
        _fail()
    return _record(identity)


def _active_identity(
    *,
    repo_root: Path | str,
    lease_id: str,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
) -> tuple[Path, dict[str, str], list[tuple[dict[str, Any], bytes]]]:
    expected = _validate_identity_values(
        pr_id=pr_id,
        base_sha=base_sha,
        writer_role=writer_role,
        owner_ref=owner_ref,
        session_ref=session_ref,
        lease_id=lease_id,
    )
    _common, state, events, _archive = _state_paths(repo_root, create=False)
    active = _validate_identity_record(
        _decode_json(_read_regular(state / ACTIVE_NAME), MAX_RECORD_BYTES)
    )
    if not _identity_matches(active, expected):
        _fail()
    chain = _scan_events(events)
    if (
        not chain
        or not all(_identity_matches(event, expected) for event, _raw in chain)
        or chain[-1][0]["event_type"] == "release"
    ):
        _fail()
    return events, expected, chain


def verify(
    *,
    repo_root: Path | str,
    lease_id: str,
    checkpoint: str,
    phase: str,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
) -> dict[str, Any]:
    if checkpoint not in _CHECKPOINTS:
        _fail()
    _validate_label(phase)
    events, identity, chain = _active_identity(
        repo_root=repo_root,
        lease_id=lease_id,
        pr_id=pr_id,
        base_sha=base_sha,
        writer_role=writer_role,
        owner_ref=owner_ref,
        session_ref=session_ref,
    )
    last = chain[-1][0]
    if (
        last["event_type"] == "verify"
        and last["checkpoint"] == checkpoint
        and last["phase"] == phase
    ):
        return last
    return _append_event(events, _event("verify", identity, checkpoint=checkpoint, phase=phase))


def release(
    *,
    repo_root: Path | str,
    lease_id: str,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
) -> dict[str, Any]:
    events, identity, _chain = _active_identity(
        repo_root=repo_root,
        lease_id=lease_id,
        pr_id=pr_id,
        base_sha=base_sha,
        writer_role=writer_role,
        owner_ref=owner_ref,
        session_ref=session_ref,
    )
    released = _append_event(events, _event("release", identity))
    active_path = events.parent / ACTIVE_NAME
    try:
        os.unlink(active_path)
        _fsync_directory(events.parent)
    except (OSError, WriterLeaseError):
        _fail()
    return released


def _find_evidence_lane(state: Path, events: Path, lease_id: str) -> Path:
    chain = _scan_events(events)
    if chain and chain[0][0]["lease_id"] == lease_id:
        return events
    archive = state / ARCHIVE_NAME
    if not archive.exists():
        _fail()
    _owned_directory(archive, exact_mode=0o700)
    lane = archive / lease_id
    _owned_directory(lane, exact_mode=0o700)
    return lane


def export_evidence(
    *,
    repo_root: Path | str,
    lease_id: str,
    pr_id: str,
    base_sha: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
) -> bytes:
    identity = _validate_identity_values(
        pr_id=pr_id,
        base_sha=base_sha,
        writer_role=writer_role,
        owner_ref=owner_ref,
        session_ref=session_ref,
        lease_id=lease_id,
    )
    _common, state, events, _archive = _state_paths(repo_root, create=False)
    lane = _find_evidence_lane(state, events, lease_id)
    chain = _scan_events(lane)
    if (
        not chain
        or chain[-1][0]["event_type"] != "release"
        or not all(_identity_matches(event, identity) for event, _raw in chain)
    ):
        _fail()
    raw = canonical_json_bytes(
        {"schema_version": SCHEMA_VERSION, **identity, "events": [event for event, _ in chain]}
    )
    if len(raw) > MAX_EVIDENCE_BYTES:
        _fail()
    validate_evidence(raw)
    return raw


def validate_evidence(raw: bytes) -> dict[str, Any]:
    value = _decode_json(raw, MAX_EVIDENCE_BYTES)
    if type(value) is not dict or set(value) != _EVIDENCE_FIELDS:
        _fail()
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        _fail()
    identity = _validate_identity_values(
        pr_id=value["pr_id"],
        base_sha=value["base_sha"],
        writer_role=value["writer_role"],
        owner_ref=value["owner_ref"],
        session_ref=value["session_ref"],
        lease_id=value["lease_id"],
    )
    events_value = value["events"]
    if type(events_value) is not list or not events_value or len(events_value) > MAX_EVENT_COUNT:
        _fail()
    previous = ZERO_DIGEST
    events: list[dict[str, Any]] = []
    for sequence, candidate in enumerate(events_value):
        event = _validate_event(candidate)
        if (
            event["sequence"] != sequence
            or event["previous_event_digest"] != previous
            or not _identity_matches(event, identity)
            or (sequence == 0 and event["event_type"] != "acquire")
            or (sequence > 0 and event["event_type"] == "acquire")
            or (events and events[-1]["event_type"] == "release")
        ):
            _fail()
        previous = hashlib.sha256(canonical_json_bytes(event)).hexdigest()
        events.append(event)
    if events[-1]["event_type"] != "release":
        _fail()
    return value


def _identity_arguments(parser: argparse.ArgumentParser, *, include_lease: bool) -> None:
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--pr-id", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--writer-role", required=True, choices=sorted(_WRITER_ROLES))
    parser.add_argument("--owner-ref", required=True)
    parser.add_argument("--session-ref", required=True)
    if include_lease:
        parser.add_argument("--lease-id", required=True)


def _print_json(value: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(value) + b"\n")


def _read_bounded_input(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(path, flags)
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_size > maximum
        ):
            raise OSError
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 4_096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not raw or len(raw) > maximum:
            raise OSError
        return raw
    except OSError:
        _fail()
    finally:
        if fd is not None:
            with suppress(OSError):
                os.close(fd)


def main(argv: Iterable[str] | None = None) -> int:
    parser = _LeaseArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    acquire_parser = commands.add_parser("acquire")
    _identity_arguments(acquire_parser, include_lease=False)
    verify_parser = commands.add_parser("verify")
    _identity_arguments(verify_parser, include_lease=True)
    verify_parser.add_argument("--checkpoint", required=True, choices=sorted(_CHECKPOINTS))
    verify_parser.add_argument("--phase", required=True)
    release_parser = commands.add_parser("release")
    _identity_arguments(release_parser, include_lease=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--repo-root", required=True, type=Path)
    export_parser = commands.add_parser("export")
    _identity_arguments(export_parser, include_lease=True)
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("evidence", type=Path)
    args = vars(parser.parse_args(list(argv) if argv is not None else None))
    action = args.pop("action")
    try:
        if action == "acquire":
            _print_json(acquire(**args))
        elif action == "verify":
            _print_json(verify(**args))
        elif action == "release":
            _print_json(release(**args))
        elif action == "inspect":
            _print_json(inspect(**args))
        elif action == "export":
            sys.stdout.buffer.write(export_evidence(**args) + b"\n")
        else:
            raw = _read_bounded_input(args["evidence"], MAX_EVIDENCE_BYTES)
            _print_json(validate_evidence(raw))
    except (OSError, WriterLeaseError):
        print("writer lease operation failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
