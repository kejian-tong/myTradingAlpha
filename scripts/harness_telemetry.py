"""Record and summarize bounded Codex harness observations outside the Git worktree.

Legacy lifecycle rows remain in ``telemetry.jsonl``. Explicit token observations
use ``telemetry-v2.jsonl`` and are never folded into legacy token totals.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import stat
import subprocess
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path

MAX_RECORD_BYTES = 16_384
MAX_FILE_BYTES = 16_777_216
MAX_JSONL_RECORDS = 10_000
MAX_SIGNED_INT = 2**63 - 1
MAX_LABEL_BYTES = 128
_LOCK_TIMEOUT_SECONDS = 1.0

_ALLOWED_EVENTS = {
    "agent_spawn",
    "agent_stop",
    "phase_complete",
    "review_result",
    "head_invalidated",
    "ci_rerun",
    "context_compaction",
}
_ALLOWED_PHASES = {
    "preflight", "jit", "red", "green", "refactor", "review", "repair", "merge_gate"
}
_ALLOWED_COMPACTION_TRIGGERS = {"manual", "auto"}
ALLOWED_ROLES = frozenset(
    {
        "master",
        "normal_implementer",
        "high_implementer",
        "critical_implementer",
        "reviewer_high",
        "reviewer_xhigh",
        "code_explorer",
        "test_auditor",
        "boundary_reviewer",
        "external_spec_researcher",
        "astra_canary",
    }
)
ALLOWED_MODELS = frozenset(
    {
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-6-astra",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "gpt-5.6-luna",
    }
)
ALLOWED_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_PR_ID = re.compile(
    r"(?:PR[0-9]{1,8}|(?:FND|PIT|SIG|BT|RSK|EXC|EXP|OMS|FWD|LIVE)-[0-9]{2}"
    r"|HARNESS(?:-[A-Z0-9]{1,16}){1,5})\Z"
)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_LEGACY_FIELDS = {
    "event", "phase", "pr_id", "role", "model", "effort", "head_sha", "trigger",
    "active_agents", "review_round", "blocking_findings", "duration_ms",
    "input_tokens", "cached_input_tokens", "output_tokens", "observed_at_ms",
}
_LEGACY_COUNT_FIELDS = (
    "active_agents", "review_round", "blocking_findings", "duration_ms",
    "input_tokens", "cached_input_tokens", "output_tokens", "observed_at_ms",
)
_V2_FIELDS = {
    "schema_version", "event", "observed_at_ms", "usage", "role", "model", "effort",
    "head_sha", "pr_ref",
}
_V2_REQUIRED = {"schema_version", "event", "observed_at_ms", "usage"}
_OUTER_IDENTITY_FIELDS = ("role", "model", "effort", "head_sha", "pr_ref")


def _observations_module():
    path = Path(__file__).resolve().with_name("harness_observations.py")
    spec = importlib.util.spec_from_file_location("codex_harness_observations", path)
    if spec is None or spec.loader is None:
        raise OSError("cannot load harness observations module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _error(message: str) -> ValueError:
    return ValueError(message)


def _safe_keys(record: object, allowed: set[str], required: set[str], *, label: str) -> set[str]:
    if type(record) is not dict:
        raise _error(f"{label} must be a built-in dictionary")
    keys = []
    for key in dict.keys(record):
        if type(key) is not str:
            raise _error(f"{label} fields must be built-in strings")
        keys.append(key)
    key_set = set(keys)
    if not required <= key_set:
        raise _error(f"{label} fields differ from the reviewed schema")
    if not key_set <= allowed:
        raise _error("unknown telemetry fields")
    return key_set


def _label(value: object, field: str) -> str:
    if type(value) is not str or not value or len(value) > MAX_LABEL_BYTES:
        raise _error(f"{field} must be a reviewed label")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _error(f"{field} must be a reviewed label") from exc
    if len(encoded) > MAX_LABEL_BYTES or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise _error(f"{field} must be a reviewed label")
    return value


def _timestamp(value: object) -> int:
    if type(value) is not int or not 0 <= value <= MAX_SIGNED_INT:
        raise _error("observed_at_ms must be a non-negative signed 64-bit integer")
    return value


def _validate(record: dict) -> dict:
    """Validate a legacy lifecycle row and return a detached built-in dictionary."""
    keys = _safe_keys(record, _LEGACY_FIELDS, {"event"}, label="telemetry record")
    event = record["event"]
    if type(event) is not str or event not in _ALLOWED_EVENTS:
        raise _error("unsupported telemetry event")
    if "phase" in keys and (
        type(record["phase"]) is not str or record["phase"] not in _ALLOWED_PHASES
    ):
        raise _error("unsupported telemetry phase")
    if "trigger" in keys and (
        event != "context_compaction"
        or type(record["trigger"]) is not str
        or record["trigger"] not in _ALLOWED_COMPACTION_TRIGGERS
    ):
        raise _error("invalid compaction trigger")
    for key in _LEGACY_COUNT_FIELDS:
        if key in keys:
            value = record[key]
            if type(value) is not int or not 0 <= value <= MAX_SIGNED_INT:
                raise _error(f"{key} must be a non-negative integer in signed 64-bit range")
    if "pr_id" in keys:
        pr_id = _label(record["pr_id"], "pr_id")
        if _PR_ID.fullmatch(pr_id) is None:
            raise _error("pr_id must use a reviewed roadmap or harness identifier")
    for key, allowed_values in (
        ("role", ALLOWED_ROLES),
        ("model", ALLOWED_MODELS),
        ("effort", ALLOWED_EFFORTS),
    ):
        if key in keys and _label(record[key], key) not in allowed_values:
            raise _error(f"unsupported telemetry {key}")
    if "head_sha" in keys:
        head_sha = _label(record["head_sha"], "head_sha")
        if _HEX40.fullmatch(head_sha) is None:
            raise _error("head_sha must be lowercase hexadecimal")
    if "observed_at_ms" in keys:
        _timestamp(record["observed_at_ms"])
    return {key: record[key] for key in keys}


def _validate_v2(record: object, *, timestamp_required: bool = True) -> dict:
    observations = _observations_module()
    keys = _safe_keys(
        record,
        _V2_FIELDS,
        _V2_REQUIRED if timestamp_required else _V2_REQUIRED - {"observed_at_ms"},
        label="usage observation",
    )
    assert type(record) is dict
    if type(record.get("schema_version")) is not int or record["schema_version"] != 2:
        raise _error("unsupported telemetry schema version")
    if type(record.get("event")) is not str or record["event"] != "usage_observation":
        raise _error("unsupported telemetry event")
    result = {"schema_version": 2, "event": "usage_observation"}
    if "observed_at_ms" in keys:
        result["observed_at_ms"] = _timestamp(record["observed_at_ms"])
    result["usage"] = observations.validate_usage(record["usage"])
    for key, allowed_values in (
        ("role", ALLOWED_ROLES),
        ("model", ALLOWED_MODELS),
        ("effort", ALLOWED_EFFORTS),
    ):
        if key in keys:
            value = _label(record[key], key)
            if value not in allowed_values:
                raise _error(f"unsupported telemetry {key}")
            result[key] = value
    if "head_sha" in keys:
        value = _label(record["head_sha"], "head_sha")
        if _HEX40.fullmatch(value) is None:
            raise _error("head_sha must be lowercase hexadecimal")
        result["head_sha"] = value
    if "pr_ref" in keys:
        value = _label(record["pr_ref"], "pr_ref")
        if _HEX64.fullmatch(value) is None:
            raise _error("pr_ref must be a pseudonymous lowercase SHA-256 reference")
        result["pr_ref"] = value
    return result


def _clean_git_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }


def _common_directory(repo: Path) -> Path:
    try:
        repo_path = repo.resolve(strict=True)
        raw = subprocess.check_output(
            ["git", "-C", str(repo_path), "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
            env=_clean_git_environment(),
        ).strip()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise _error("repository Git metadata cannot be resolved safely") from exc
    common = Path(raw)
    if not common.is_absolute():
        common = repo_path / common
    try:
        info = common.lstat()
    except OSError as exc:
        raise _error("Git common directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise _error("Git common directory is not a real directory")
    try:
        return common.resolve(strict=True)
    except OSError as exc:
        raise _error("Git common directory cannot be canonicalized") from exc


def _require_storage() -> None:
    """Fail before mutation when descriptor-relative confinement is unavailable."""
    flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if (
        os.name != "posix"
        or any(not getattr(os, flag, 0) for flag in flags)
        or not {os.open, os.stat, os.mkdir, os.unlink, os.rmdir} <= os.supports_dir_fd
        or os.scandir not in os.supports_fd
        or os.stat not in os.supports_follow_symlinks
    ):
        raise _error("secure telemetry storage is unsupported on this platform")


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


class _Directory:
    """An opened directory whose verified ancestor descriptors remain alive."""

    def __init__(self, fd: int, path: Path, parent: _Directory | None = None):
        self.fd = fd
        self.path = path
        self.parent = parent
        self.info = os.fstat(fd)

    def verify(self) -> None:
        current = os.fstat(self.fd)
        if not stat.S_ISDIR(current.st_mode) or not _same_inode(current, self.info):
            raise _error("telemetry directory changed during access")
        if self.parent is not None:
            self.parent.verify()
            entry = os.stat(self.path.name, dir_fd=self.parent.fd, follow_symlinks=False)
            if not stat.S_ISDIR(entry.st_mode) or not _same_inode(entry, self.info):
                raise _error("telemetry directory changed during access")

    def entry_info(
        self, name: str, *, directory: bool = False, mutable: bool = False
    ) -> os.stat_result | None:
        self.verify()
        try:
            info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            self.verify()
            return None
        self.verify()
        if directory:
            if not stat.S_ISDIR(info.st_mode):
                raise _error("telemetry metadata path is not a real directory")
        elif not stat.S_ISREG(info.st_mode):
            raise _error("telemetry entry is not a regular file")
        elif mutable and info.st_nlink != 1:
            raise _error("multiply linked telemetry evidence cannot be modified")
        return info

    def verify_file(
        self, name: str, expected: os.stat_result, *, fd: int | None = None,
        mutable: bool = False, expected_size: int | None = None,
    ) -> None:
        current = self.entry_info(name, mutable=mutable)
        if current is None or not _same_inode(current, expected):
            raise _error("telemetry file changed during access")
        opened = current if fd is None else os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_inode(opened, expected)
            or (mutable and opened.st_nlink != 1)
            or (expected_size is not None and (
                current.st_size != expected_size or opened.st_size != expected_size
            ))
        ):
            raise _error("telemetry file changed during access")

    def unlink_file(self, name: str, expected: os.stat_result) -> None:
        self.verify_file(name, expected, mutable=True, expected_size=expected.st_size)
        os.unlink(name, dir_fd=self.fd)

    def remove(self) -> None:
        self.verify()
        if self.parent is None:
            raise _error("telemetry root cannot be removed")
        os.rmdir(self.path.name, dir_fd=self.parent.fd)


@contextmanager
def _child_directory(
    parent: _Directory, name: str, *, create: bool = False
) -> Iterator[_Directory | None]:
    expected = parent.entry_info(name, directory=True)
    if expected is None:
        if not create:
            yield None
            return
        parent.verify()
        with suppress(FileExistsError):
            os.mkdir(name, mode=0o700, dir_fd=parent.fd)
        expected = parent.entry_info(name, directory=True)
        if expected is None:
            raise _error("telemetry directory changed during creation")
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent.fd)
    try:
        child = _Directory(fd, parent.path / name, parent)
        if not _same_inode(child.info, expected):
            raise _error("telemetry directory changed during open")
        child.verify()
        yield child
    finally:
        os.close(fd)


@contextmanager
def _directory_path(path: Path) -> Iterator[_Directory]:
    """Open each canonical ancestor relative to its retained parent, starting at root."""
    with ExitStack() as stack:
        fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, fd)
        directory = _Directory(fd, Path(path.anchor))
        for name in path.parts[1:]:
            child = stack.enter_context(_child_directory(directory, name))
            if child is None:
                raise _error("Git common directory is unavailable")
            directory = child
        yield directory


@contextmanager
def _metadata_handle(repo: Path, *, create: bool = False) -> Iterator[_Directory | None]:
    _require_storage()
    try:
        with (
            _directory_path(_common_directory(repo)) as common,
            _child_directory(common, "codex-harness", create=create) as metadata,
        ):
            yield metadata
    except OSError as exc:
        raise _error("telemetry storage cannot be accessed safely") from exc


def telemetry_path(repo: Path, *, schema_version: int = 1) -> Path:
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise _error("unsupported telemetry schema version")
    _require_storage()
    common = _common_directory(repo)
    try:
        with _directory_path(common) as parent, _child_directory(parent, "codex-harness"):
            filename = "telemetry.jsonl" if schema_version == 1 else "telemetry-v2.jsonl"
            return common / "codex-harness" / filename
    except OSError as exc:
        raise _error("telemetry storage cannot be accessed safely") from exc


@contextmanager
def _regular_handle(
    directory: _Directory, name: str, *, write: bool = False, create: bool = False,
    mutable: bool = False, exclusive: bool = False,
) -> Iterator[int | None]:
    mutable = mutable or write
    expected = directory.entry_info(name, mutable=mutable)
    if expected is None and not create:
        yield None
        return
    if expected is not None and exclusive:
        raise FileExistsError("telemetry entry already exists")
    flags = (os.O_RDWR | os.O_APPEND) if write else os.O_RDONLY
    flags |= os.O_NOFOLLOW | os.O_NONBLOCK
    if expected is None:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(name, flags, 0o600, dir_fd=directory.fd)
    try:
        info = os.fstat(fd)
        if expected is None:
            expected = info
        directory.verify_file(
            name, expected, fd=fd, mutable=mutable, expected_size=expected.st_size,
        )
        yield fd
    finally:
        os.close(fd)


def _read_fd(fd: int, *, max_bytes: int) -> bytes:
    if os.fstat(fd).st_size > max_bytes:
        raise _error("JSONL file size exceeds the reviewed limit")
    chunks = []
    total = 0
    while True:
        chunk = os.read(fd, min(65_536, max_bytes + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise _error("JSONL file size exceeds the reviewed limit")


def _read_stream(
    directory: _Directory, name: str, fd: int, schema_version: int, *, mutable: bool = False
) -> tuple[list[dict], int]:
    observations = _observations_module()
    info = os.fstat(fd)
    raw = _read_fd(fd, max_bytes=MAX_FILE_BYTES)
    directory.verify_file(name, info, fd=fd, mutable=mutable, expected_size=len(raw))
    if raw and not raw.endswith(b"\n"):
        raise _error("telemetry stream has an incomplete tail")
    rows = []
    offset = 0
    line_number = 0
    while offset < len(raw):
        newline = raw.find(b"\n", offset)
        if newline < 0:
            break
        line = raw[offset:newline]
        offset = newline + 1
        line_number += 1
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line.strip():
            continue
        if len(line) > MAX_RECORD_BYTES:
            raise _error("telemetry record exceeds the reviewed byte limit")
        try:
            decoded = observations.decode_json(line, max_bytes=MAX_RECORD_BYTES)
            row = _validate_v2(decoded) if schema_version == 2 else _validate(decoded)
        except (TypeError, ValueError) as exc:
            raise _error(f"invalid telemetry record on line {line_number}") from exc
        rows.append(row)
        if len(rows) > MAX_JSONL_RECORDS:
            raise _error("telemetry record count exceeds the reviewed limit")
    return rows, len(raw)


def _outer_identity(record: dict) -> tuple[object, ...]:
    return tuple(record.get(key) for key in _OUTER_IDENTITY_FIELDS)


def _v2_record_identity(record: dict) -> tuple[object, ...]:
    usage = record["usage"]
    return (
        usage["source_kind"],
        usage["usage_scope"],
        usage["aggregation_scope"],
        *_outer_identity(record),
    )


def _v2_record_content(record: dict) -> tuple[object, ...]:
    usage = record["usage"]
    return (*_v2_record_identity(record), *(usage[key] for key in usage))


def _validate_v2_series(rows: list[dict]) -> None:
    identities: dict[str, tuple[object, ...]] = {}
    contents: dict[tuple[str, int], tuple[object, ...]] = {}
    for row in rows:
        usage = row["usage"]
        ref = usage["observation_ref"]
        identity = _v2_record_identity(row)
        prior_identity = identities.get(ref)
        if prior_identity is not None and prior_identity != identity:
            raise _error("usage observation identity cannot be rebound")
        identities[ref] = identity
        revision_key = (ref, usage["revision"])
        content = _v2_record_content(row)
        prior_content = contents.get(revision_key)
        if prior_content is not None and prior_content != content:
            raise _error("conflicting usage observation revision")
        contents[revision_key] = content


def load(repo: Path, *, schema_version: int = 1) -> list[dict]:
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise _error("unsupported telemetry schema version")
    name = "telemetry.jsonl" if schema_version == 1 else "telemetry-v2.jsonl"
    with _metadata_handle(repo) as metadata:
        if metadata is None:
            return []
        with _regular_handle(metadata, name) as fd:
            if fd is None:
                return []
            rows, _ = _read_stream(metadata, name, fd, schema_version)
            if schema_version == 2:
                _validate_v2_series(rows)
            return rows


@contextmanager
def _entry_lock(directory: _Directory, name: str) -> Iterator[None]:
    """Serialize cooperating transactions; never recover or remove an existing lock."""
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    lock_fd = None
    lock_info = None
    acquired = False
    while lock_fd is None:
        if time.monotonic() >= deadline:
            raise _error("telemetry lock is contended")
        directory.verify()
        try:
            lock_fd = os.open(name, flags, 0o600, dir_fd=directory.fd)
        except FileExistsError:
            directory.entry_info(name, mutable=True)
            if time.monotonic() >= deadline:
                raise _error("telemetry lock is contended") from None
            time.sleep(0.005)
    try:
        lock_info = os.fstat(lock_fd)
        directory.verify_file(name, lock_info, fd=lock_fd, mutable=True, expected_size=0)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                directory.verify_file(name, lock_info, fd=lock_fd, mutable=True, expected_size=0)
                directory.unlink_file(name, lock_info)
        except (OSError, ValueError):
            # Preserve a replaced/unsafe lock instead of deleting unverified evidence.
            pass
        finally:
            os.close(lock_fd)


def _encode_record(record: dict) -> bytes:
    try:
        encoded = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _error("telemetry record cannot be encoded safely") from exc
    if len(encoded) - 1 > MAX_RECORD_BYTES:
        raise _error("telemetry record exceeds the reviewed byte limit")
    return encoded


def _append_locked(
    directory: _Directory, name: str, payload: dict, schema_version: int
) -> None:
    # The same opened regular inode supplies the validated prefix and receives the append.
    with _regular_handle(directory, name, write=True, create=True) as fd:
        assert fd is not None
        rows, expected_size = _read_stream(directory, name, fd, schema_version, mutable=True)
        if len(rows) >= MAX_JSONL_RECORDS:
            raise _error("telemetry record count exceeds the reviewed limit")
        encoded = _encode_record(payload)
        if expected_size + len(encoded) > MAX_FILE_BYTES:
            raise _error("telemetry file size exceeds the reviewed limit")
        if schema_version == 2:
            _validate_v2_series([*rows, payload])
        info = os.fstat(fd)
        written = 0
        while written < len(encoded):
            directory.verify_file(
                name, info, fd=fd, mutable=True, expected_size=expected_size + written,
            )
            try:
                count = os.write(fd, encoded[written:])
            except OSError as exc:
                raise _error("telemetry append did not complete") from exc
            if count <= 0:
                raise _error("telemetry append did not complete")
            written += count
        directory.verify_file(
            name, info, fd=fd, mutable=True, expected_size=expected_size + written,
        )


def record(repo: Path, payload: dict) -> Path:
    if type(payload) is not dict:
        raise _error("telemetry record must be a built-in dictionary")
    keys = []
    for key in dict.keys(payload):
        if type(key) is not str:
            raise _error("telemetry record fields must be built-in strings")
        keys.append(key)
    versioned = "schema_version" in set(keys)
    schema_version = 2 if versioned else 1
    if schema_version == 2:
        validated = _validate_v2(payload, timestamp_required=False)
    else:
        validated = _validate(payload)
    if "observed_at_ms" not in validated:
        validated["observed_at_ms"] = time.time_ns() // 1_000_000
    validated = _validate_v2(validated) if schema_version == 2 else _validate(validated)

    name = "telemetry-v2.jsonl" if schema_version == 2 else "telemetry.jsonl"
    with _metadata_handle(repo, create=True) as metadata:
        assert metadata is not None
        with _entry_lock(metadata, f".{name}.lock"):
            _append_locked(metadata, name, validated, schema_version)
        return metadata.path / name


def summarize(repo: Path) -> dict:
    legacy_rows = load(repo)
    usage_rows = load(repo, schema_version=2)
    peak_agents = max((row.get("active_agents", 0) for row in legacy_rows), default=0)
    durations = [row["duration_ms"] for row in legacy_rows if "duration_ms" in row]
    token_rows = [
        row
        for row in legacy_rows
        if any(key in row for key in ("input_tokens", "cached_input_tokens", "output_tokens"))
    ]
    legacy_complete = None
    if token_rows:
        legacy_complete = all(
            all(key in row for key in ("input_tokens", "cached_input_tokens", "output_tokens"))
            for row in token_rows
        )
    observations = _observations_module()
    return {
        "records": len(legacy_rows),
        "events": dict(Counter(row["event"] for row in legacy_rows)),
        "roles": dict(Counter(row["role"] for row in legacy_rows if "role" in row)),
        "compaction_triggers": dict(
            Counter(row["trigger"] for row in legacy_rows if "trigger" in row)
        ),
        "peak_active_agents": peak_agents,
        "duration_ms_total": sum(durations),
        "review_round_max": max((row.get("review_round", 0) for row in legacy_rows), default=0),
        "blocking_findings_total": sum(row.get("blocking_findings", 0) for row in legacy_rows),
        "token_observation_records": len(token_rows),
        "input_tokens_observed": sum(row.get("input_tokens", 0) for row in token_rows),
        "cached_input_tokens_observed": sum(
            row.get("cached_input_tokens", 0) for row in token_rows
        ),
        "output_tokens_observed": sum(row.get("output_tokens", 0) for row in token_rows),
        "legacy_token_accounting_complete": legacy_complete,
        "usage_v2_records": len(usage_rows),
        "usage_v2": observations.summarize_usage([row["usage"] for row in usage_rows])
        if usage_rows
        else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "summary", "path"))
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", help="JSON object for the record action")
    args = parser.parse_args()
    try:
        if args.action == "path":
            print(telemetry_path(args.repo))
        elif args.action == "summary":
            print(json.dumps(summarize(args.repo), indent=2, sort_keys=True))
        else:
            if args.json is None:
                parser.error("--json is required for record")
            payload = _observations_module().decode_json(args.json)
            if type(payload) is not dict:
                parser.error("--json must decode to an object")
            print(record(args.repo, payload))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
