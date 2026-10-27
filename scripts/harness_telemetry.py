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
from contextlib import contextmanager
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
_PR_ID = re.compile(r"(?:PR[0-9]{1,8}|(?:BT|SIG)-[0-9]{2}|HARNESS(?:-[A-Z0-9]{1,16}){1,5})\Z")
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


def _ensure_directory(path: Path, *, create: bool) -> Path:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            return path
        try:
            path.mkdir(mode=0o700)
            info = path.lstat()
        except FileExistsError:
            info = path.lstat()
        except OSError as exc:
            raise _error("telemetry metadata directory cannot be created safely") from exc
    except OSError as exc:
        raise _error("telemetry metadata directory cannot be inspected safely") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise _error("telemetry metadata path is not a real directory")
    try:
        canonical = path.resolve(strict=True)
    except OSError as exc:
        raise _error("telemetry metadata directory cannot be canonicalized") from exc
    if canonical != path:
        raise _error("telemetry metadata directory is not canonical")
    return path


def _metadata_directory(repo: Path, *, create: bool) -> Path:
    common = _common_directory(repo)
    common = _ensure_directory(common, create=False)
    metadata = common / "codex-harness"
    return _ensure_directory(metadata, create=create)


def _runtime_directory(repo: Path, *, create: bool = False) -> Path:
    metadata = _metadata_directory(repo, create=create)
    runtime = metadata / "runtime"
    return _ensure_directory(runtime, create=create)


def telemetry_path(repo: Path, *, schema_version: int = 1) -> Path:
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise _error("unsupported telemetry schema version")
    metadata = _metadata_directory(repo, create=False)
    filename = "telemetry.jsonl" if schema_version == 1 else "telemetry-v2.jsonl"
    return metadata / filename


def _regular_file_info(path: Path) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _error("telemetry stream cannot be inspected safely") from exc
    if not stat.S_ISREG(info.st_mode):
        raise _error("telemetry stream is not a regular file")
    return info


def _read_stream(path: Path, schema_version: int) -> tuple[list[dict], int]:
    observations = _observations_module()
    info = _regular_file_info(path)
    if info is None:
        return [], 0
    raw = observations._safe_read(path, max_bytes=MAX_FILE_BYTES)
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
    path = telemetry_path(repo, schema_version=schema_version)
    rows, _ = _read_stream(path, schema_version)
    if schema_version == 2:
        _validate_v2_series(rows)
    return rows


@contextmanager
def _stream_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    lock_fd = None
    lock_info = None
    while lock_fd is None:
        try:
            lock_fd = os.open(lock_path, flags, 0o600)
            lock_info = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_info.st_mode):
                os.close(lock_fd)
                lock_fd = None
                raise _error("telemetry append lock is unsafe")
        except FileExistsError:
            existing = _regular_file_info(lock_path)
            if existing is None:
                continue
            if time.monotonic() >= deadline:
                raise _error("telemetry append lock is contended") from None
            time.sleep(0.005)
        except OSError as exc:
            raise _error("telemetry append lock cannot be acquired safely") from exc
    try:
        yield
    finally:
        os.close(lock_fd)
        try:
            current = lock_path.lstat()
            if (
                lock_info is not None
                and current.st_dev == lock_info.st_dev
                and current.st_ino == lock_info.st_ino
                and stat.S_ISREG(current.st_mode)
            ):
                lock_path.unlink()
        except OSError:
            pass


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


def _append_locked(path: Path, payload: dict, schema_version: int) -> None:
    rows, expected_size = _read_stream(path, schema_version)
    if len(rows) >= MAX_JSONL_RECORDS:
        raise _error("telemetry record count exceeds the reviewed limit")
    encoded = _encode_record(payload)
    if expected_size + len(encoded) > MAX_FILE_BYTES:
        raise _error("telemetry file size exceeds the reviewed limit")
    if schema_version == 2:
        _validate_v2_series([*rows, payload])

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise _error("telemetry stream cannot be opened safely") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != expected_size:
            raise _error("telemetry stream changed during append")
        written = 0
        while written < len(encoded):
            try:
                count = os.write(fd, encoded[written:])
            except OSError as exc:
                raise _error("telemetry append did not complete") from exc
            if count <= 0:
                raise _error("telemetry append did not complete")
            written += count
    finally:
        os.close(fd)


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

    metadata = _metadata_directory(repo, create=True)
    path = metadata / ("telemetry-v2.jsonl" if schema_version == 2 else "telemetry.jsonl")
    with _stream_lock(path):
        _append_locked(path, validated, schema_version)
    return path


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
