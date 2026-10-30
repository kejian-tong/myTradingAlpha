#!/usr/bin/env python3
"""Collect, execute, and verify the fixed two-runner CI test partition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

MAX_REFERENCE_BYTES = 2_000_000
MAX_RECEIPT_BYTES = 8_000_000
MAX_COLLECTION_SECONDS = 1_800
MAX_EXECUTION_SECONDS = 18_000
MAX_NODE_COUNT = 50_000
MAX_NODEID_CHARS = 262_144
MAX_STRING_CHARS = 512
FIXED_ERROR = "CI partition operation failed\n"
UV_VERSION = "0.13.5"
BINDING_FIELDS = (
    "source_sha",
    "checkout_sha",
    "tree_sha",
    "lock_sha256",
    "workflow_run_id",
    "workflow_run_attempt",
    "runner_os",
    "runner_image_os",
    "runner_image_version",
    "python_version",
    "uv_version",
)
MANIFEST_FIELDS = set(BINDING_FIELDS) | {
    "schema_version",
    "nodeids",
    "collection_order",
}
RECEIPT_FIELDS = set(BINDING_FIELDS) | {
    "schema_version",
    "shard",
    "elapsed_ms",
    "pytest_exit_code",
    "completed",
    "nodeids",
    "selected_nodeids",
    "outcomes",
}
HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_INTERNAL_LAUNCH = (
    "import runpy,sys; "
    "ns=runpy.run_path(sys.argv[1],run_name='ci_partition_worker'); "
    "raise SystemExit(ns['_worker_entry'](sys.argv[2],sys.argv[3:]))"
)


class PartitionError(Exception):
    """An expected fail-closed input or execution error."""


def _canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
            + b"\n"
        )
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise PartitionError from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PartitionError
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise PartitionError


def _parse_json_object(raw: bytes, *, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise PartitionError
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise PartitionError from exc
    if type(value) is not dict:
        raise PartitionError
    return value


def _parse_canonical(raw: bytes, *, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum or not raw.endswith(b"\n"):
        raise PartitionError
    try:
        value = json.loads(
            raw[:-1].decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise PartitionError from exc
    if type(value) is not dict or _canonical_json(value) != raw:
        raise PartitionError
    return value


def _read_regular_file(path: Path, *, maximum: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except (OSError, TypeError, ValueError) as exc:
        raise PartitionError from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 or metadata.st_size > maximum:
            raise PartitionError
        chunks: list[bytes] = []
        size = 0
        while True:
            block = os.read(fd, min(65_536, maximum + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
            if size > maximum:
                raise PartitionError
        raw = b"".join(chunks)
        if len(raw) != metadata.st_size:
            raise PartitionError
        return raw
    except OSError as exc:
        raise PartitionError from exc
    finally:
        os.close(fd)


def _write_new_file(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except (OSError, TypeError, ValueError) as exc:
        raise PartitionError from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PartitionError
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    except OSError as exc:
        raise PartitionError from exc
    finally:
        os.close(fd)


def _exact_fields(value: dict[str, Any], fields: set[str]) -> None:
    if set(value) != fields:
        raise PartitionError


def _integer(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _bounded_string(value: Any, *, maximum: int = MAX_STRING_CHARS) -> bool:
    return type(value) is str and 0 < len(value) <= maximum


def _nodeids(value: Any) -> list[str]:
    if type(value) is not list or not value or len(value) > MAX_NODE_COUNT:
        raise PartitionError
    for nodeid in value:
        if not _bounded_string(nodeid, maximum=MAX_NODEID_CHARS):
            raise PartitionError
    if len(set(value)) != len(value):
        raise PartitionError
    return value


def _validate_binding(binding: Any) -> dict[str, Any]:
    if type(binding) is not dict or set(binding) != set(BINDING_FIELDS):
        raise PartitionError
    for key in ("source_sha", "checkout_sha"):
        if type(binding[key]) is not str or HEX_40.fullmatch(binding[key]) is None:
            raise PartitionError
    if type(binding["tree_sha"]) is not str or HEX_40.fullmatch(binding["tree_sha"]) is None:
        raise PartitionError
    if type(binding["lock_sha256"]) is not str or HEX_64.fullmatch(binding["lock_sha256"]) is None:
        raise PartitionError
    for key in ("workflow_run_id", "workflow_run_attempt"):
        if not _integer(binding[key], minimum=1):
            raise PartitionError
    for key in ("runner_os", "runner_image_os", "runner_image_version"):
        if not _bounded_string(binding[key]):
            raise PartitionError
    if type(binding["python_version"]) is not str or VERSION.fullmatch(binding["python_version"]) is None:
        raise PartitionError
    if binding["uv_version"] != UV_VERSION:
        raise PartitionError
    return binding


def _validate_manifest(value: dict[str, Any]) -> dict[str, Any]:
    _exact_fields(value, MANIFEST_FIELDS)
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise PartitionError
    binding = {key: value[key] for key in BINDING_FIELDS}
    _validate_binding(binding)
    nodeids = _nodeids(value["nodeids"])
    if nodeids != sorted(nodeids):
        raise PartitionError
    order = _nodeids(value["collection_order"])
    if len(order) != len(nodeids) or set(order) != set(nodeids):
        raise PartitionError
    return value


def _validate_outcomes(outcomes: Any, selected: list[str]) -> list[dict[str, Any]]:
    if type(outcomes) is not list or len(outcomes) != len(selected):
        raise PartitionError
    result: list[dict[str, Any]] = []
    for outcome, expected_nodeid in zip(outcomes, selected, strict=True):
        if type(outcome) is not dict or set(outcome) != {
            "nodeid",
            "setup",
            "call",
            "teardown",
            "xfail",
            "subtests",
        }:
            raise PartitionError
        if outcome["nodeid"] != expected_nodeid:
            raise PartitionError
        if outcome["setup"] not in {"passed", "skipped"}:
            raise PartitionError
        if outcome["teardown"] != "passed":
            raise PartitionError
        if outcome["setup"] == "skipped":
            if outcome["call"] is not None:
                raise PartitionError
        elif outcome["call"] not in {"passed", "skipped"}:
            raise PartitionError
        if type(outcome["xfail"]) is not bool:
            raise PartitionError
        if type(outcome["subtests"]) is not dict or set(outcome["subtests"]) != {
            "passed",
            "skipped",
            "failed",
        }:
            raise PartitionError
        if any(not _integer(count) for count in outcome["subtests"].values()):
            raise PartitionError
        if outcome["subtests"]["failed"] != 0:
            raise PartitionError
        result.append(outcome)
    return result


def _validate_receipt(
    value: dict[str, Any],
    *,
    binding: dict[str, Any],
    manifest: dict[str, Any],
    shard: str,
) -> dict[str, Any]:
    _exact_fields(value, RECEIPT_FIELDS)
    if value["schema_version"] != 1 or type(value["schema_version"]) is not int:
        raise PartitionError
    if value["shard"] != shard:
        raise PartitionError
    actual_binding = {key: value[key] for key in BINDING_FIELDS}
    _validate_binding(actual_binding)
    if actual_binding != binding:
        raise PartitionError
    if type(value["elapsed_ms"]) is not int or value["elapsed_ms"] < 0:
        raise PartitionError
    if value["pytest_exit_code"] != 0 or type(value["pytest_exit_code"]) is not int:
        raise PartitionError
    if value["completed"] is not True:
        raise PartitionError
    nodeids = _nodeids(value["nodeids"])
    if nodeids != manifest["nodeids"]:
        raise PartitionError
    selected = value["selected_nodeids"]
    if type(selected) is not list or not selected or len(selected) > MAX_NODE_COUNT:
        raise PartitionError
    if any(not _bounded_string(item, maximum=MAX_NODEID_CHARS) for item in selected):
        raise PartitionError
    nodeid_set = set(nodeids)
    if len(set(selected)) != len(selected) or any(item not in nodeid_set for item in selected):
        raise PartitionError
    if selected != [item for item in manifest["collection_order"] if item in set(selected)]:
        raise PartitionError
    _validate_outcomes(value["outcomes"], selected)
    return value


def _verify_values(
    expected_binding: Any,
    approved_weights_bytes: bytes,
    reference_bytes: bytes,
    shard_zero_bytes: bytes,
    shard_one_bytes: bytes,
    serial_bytes: bytes | None,
) -> dict[str, Any]:
    binding = _validate_binding(expected_binding)
    manifest = _validate_manifest(_parse_canonical(reference_bytes, maximum=MAX_REFERENCE_BYTES))
    if {key: manifest[key] for key in BINDING_FIELDS} != binding:
        raise PartitionError
    assignments = _partition(
        manifest["collection_order"], approved_weights_bytes=approved_weights_bytes
    )
    zero = _validate_receipt(
        _parse_canonical(shard_zero_bytes, maximum=MAX_RECEIPT_BYTES),
        binding=binding,
        manifest=manifest,
        shard="0",
    )
    one = _validate_receipt(
        _parse_canonical(shard_one_bytes, maximum=MAX_RECEIPT_BYTES),
        binding=binding,
        manifest=manifest,
        shard="1",
    )
    zero_set = set(zero["selected_nodeids"])
    one_set = set(one["selected_nodeids"])
    if zero_set & one_set or zero_set | one_set != set(manifest["nodeids"]):
        raise PartitionError
    if zero["selected_nodeids"] != assignments[0] or one["selected_nodeids"] != assignments[1]:
        raise PartitionError
    outcomes = zero["outcomes"] + one["outcomes"]
    if len(outcomes) != len(manifest["nodeids"]):
        raise PartitionError
    outcomes.sort(key=lambda item: item["nodeid"])
    serial_parity: bool | None = None
    if serial_bytes is not None:
        serial = _validate_receipt(
            _parse_canonical(serial_bytes, maximum=MAX_RECEIPT_BYTES),
            binding=binding,
            manifest=manifest,
            shard="serial",
        )
        if serial["selected_nodeids"] != manifest["collection_order"]:
            raise PartitionError
        serial_outcomes = sorted(serial["outcomes"], key=lambda item: item["nodeid"])
        if serial_outcomes != outcomes:
            raise PartitionError
        serial_parity = True
    coverage_bytes = _canonical_json({"nodeids": manifest["nodeids"], "outcomes": outcomes})
    return {
        "schema_version": 1,
        "completed": True,
        "node_count": len(manifest["nodeids"]),
        "shards": 2,
        "serial_parity": serial_parity,
        "binding": binding,
        "weights_sha256": hashlib.sha256(approved_weights_bytes).hexdigest(),
        "reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "shard_receipt_sha256": {
            "0": hashlib.sha256(shard_zero_bytes).hexdigest(),
            "1": hashlib.sha256(shard_one_bytes).hexdigest(),
        },
        "coverage_sha256": hashlib.sha256(coverage_bytes[:-1]).hexdigest(),
    }


def verify_artifact_bytes(
    expected_binding: dict[str, Any],
    approved_weights_bytes: bytes,
    reference_bytes: bytes,
    shard_zero_bytes: bytes,
    shard_one_bytes: bytes,
    serial_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Verify immutable native artifact snapshots against explicit runtime identity.

    ``approved_weights_bytes`` is an immutable snapshot of the candidate's fixed,
    reviewed weights file. The function performs no filesystem, environment, Git,
    or subprocess access.
    It raises ``ValueError`` for invalid inputs and returns a bounded coverage summary.
    """

    try:
        return _verify_values(
            expected_binding,
            approved_weights_bytes,
            reference_bytes,
            shard_zero_bytes,
            shard_one_bytes,
            serial_bytes,
        )
    except (PartitionError, TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        raise ValueError("invalid CI partition artifact evidence") from exc


def _parse_weights(raw: bytes) -> tuple[int, dict[str, int]]:
    value = _parse_canonical(raw, maximum=64_000)
    expected_fields = {"default_ms", "job_id", "run_id", "schema_version", "source_head", "weights_ms"}
    if set(value) != expected_fields:
        raise PartitionError
    for key in ("default_ms", "job_id", "run_id", "schema_version"):
        if not _integer(value[key], minimum=1):
            raise PartitionError
    if (
        value["schema_version"] != 1
        or value["source_head"] != "f80d14b537d70e86cffdc2e41f4d447ec875a68f"
        or value["run_id"] != 40995106582
        or value["job_id"] != 123866296171
        or value["default_ms"] != 1420
        or type(value["weights_ms"]) is not dict
    ):
        raise PartitionError
    weights: dict[str, int] = {}
    for nodeid, weight in value["weights_ms"].items():
        if not _bounded_string(nodeid, maximum=MAX_NODEID_CHARS) or not _integer(weight, minimum=1):
            raise PartitionError
        weights[nodeid] = weight
    return value["default_ms"], weights


def _approved_weights_bytes() -> bytes:
    path = Path(__file__).resolve().with_name("ci_partition_weights.json")
    return _read_regular_file(path, maximum=64_000)


def _partition(
    collection_order: list[str],
    *,
    approved_weights_bytes: bytes,
    shard_count: int = 2,
) -> list[list[str]]:
    if shard_count != 2:
        raise PartitionError
    default_ms, weights = _parse_weights(approved_weights_bytes)
    assigned = [[], []]
    loads = [0, 0]
    owners: dict[str, int] = {}
    for nodeid in sorted(collection_order, key=lambda item: (-weights.get(item, default_ms), item)):
        shard = 0 if loads[0] <= loads[1] else 1
        owners[nodeid] = shard
        loads[shard] += weights.get(nodeid, default_ms)
    for nodeid in collection_order:
        assigned[owners[nodeid]].append(nodeid)
    if not assigned[0] or not assigned[1]:
        raise PartitionError
    return assigned


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env={
                key: value
                for key, value in os.environ.items()
                if key not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"}
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PartitionError from exc
    if result.returncode != 0:
        raise PartitionError
    return result.stdout.strip()


def _event_source_sha() -> str:
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    if event_name == "pull_request":
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            raise PartitionError
        value = _parse_json_object(
            _read_regular_file(Path(event_path), maximum=2_000_000), maximum=2_000_000
        )
        pull_request = value.get("pull_request")
        if type(pull_request) is not dict or type(pull_request.get("head")) is not dict:
            raise PartitionError
        source_sha = pull_request["head"].get("sha")
    elif event_name in {"push", "workflow_dispatch"}:
        source_sha = os.environ.get("GITHUB_SHA")
    else:
        raise PartitionError
    if type(source_sha) is not str or HEX_40.fullmatch(source_sha) is None:
        raise PartitionError
    return source_sha


def _runtime_binding() -> dict[str, Any]:
    root = Path.cwd().resolve(strict=True)
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve(strict=True) != root:
        raise PartitionError
    checkout_sha = _git(root, "rev-parse", "HEAD")
    tree_sha = _git(root, "rev-parse", "HEAD^{tree}")
    if os.environ.get("GITHUB_SHA") != checkout_sha:
        raise PartitionError
    source_sha = _event_source_sha()
    lock_path = root / "uv.lock"
    lock_bytes = _read_regular_file(lock_path, maximum=4_000_000)
    uv = shutil.which("uv")
    if not uv:
        raise PartitionError
    try:
        version_result = subprocess.run(
            [uv, "--version"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PartitionError from exc
    if version_result.returncode != 0 or re.match(
        rf"uv {re.escape(UV_VERSION)}(?:\s|\Z)", version_result.stdout.strip()
    ) is None:
        raise PartitionError
    binding = {
        "source_sha": source_sha,
        "checkout_sha": checkout_sha,
        "tree_sha": tree_sha,
        "lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "workflow_run_id": _positive_env_integer("GITHUB_RUN_ID"),
        "workflow_run_attempt": _positive_env_integer("GITHUB_RUN_ATTEMPT"),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_image_os": os.environ.get("ImageOS"),  # noqa: SIM112 - exact GitHub Actions key
        "runner_image_version": os.environ.get("ImageVersion"),  # noqa: SIM112 - exact GitHub Actions key
        "python_version": platform.python_version(),
        "uv_version": UV_VERSION,
    }
    return _validate_binding(binding)


def _positive_env_integer(name: str) -> int:
    value = os.environ.get(name, "")
    if not value or not value.isascii() or not value.isdecimal() or value.startswith("0"):
        raise PartitionError
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PartitionError from exc
    if parsed < 1:
        raise PartitionError
    return parsed


def _clean_pytest_environment() -> dict[str, str]:
    forbidden = tuple(key for key in os.environ if key.startswith("PYTEST_"))
    if forbidden:
        raise PartitionError
    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"}
    }


def _child_process(root: Path, mode: str, report_path: Path, args: list[str]) -> tuple[int, dict[str, Any]]:
    command = [
        sys.executable,
        "-I",
        "-c",
        _INTERNAL_LAUNCH,
        str(Path(__file__).resolve()),
        mode,
        str(report_path),
        *args,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=_clean_pytest_environment(),
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=MAX_EXECUTION_SECONDS if mode == "run" else MAX_COLLECTION_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PartitionError from exc
    if result.returncode != 0:
        raise PartitionError
    report = _parse_canonical(_read_regular_file(report_path, maximum=MAX_RECEIPT_BYTES), maximum=MAX_RECEIPT_BYTES)
    if set(report) != {"exit_code", "nodeids", "collection_before", "collection_after", "lifecycle"}:
        raise PartitionError
    return result.returncode, report


class _WorkerPlugin:
    def __init__(
        self,
        mode: str,
        expected_nodeids: list[str] | None,
        selected_nodeids: list[str] | None,
    ) -> None:
        self.mode = mode
        self.expected_nodeids = expected_nodeids
        self.selected_nodeids = selected_nodeids
        self.collection_before: list[str] | None = None
        self.collection_after: list[str] | None = None
        self.nodeids: list[str] | None = None
        self.lifecycle: dict[str, dict[str, Any]] = {}
        self.exit_code: int | None = None
        self.collection_mutation = False

    @staticmethod
    def _validate_configuration(config: Any) -> None:
        if config.getini("testpaths") != ["tests"]:
            raise PartitionError
        if config.getini("addopts") != ["-ra", "--strict-markers"]:
            raise PartitionError

    def pytest_configure(self, config: Any) -> None:
        self._validate_configuration(config)

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodeids = [item.nodeid for item in session.items]

    def pytest_deselected(self, items: list[Any]) -> None:
        if items:
            self.collection_mutation = True

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        self.exit_code = int(exitstatus)

    def pytest_runtest_logreport(self, report: Any) -> None:
        nodeid = getattr(report, "nodeid", None)
        if type(nodeid) is not str:
            self.collection_mutation = True
            return
        if hasattr(report, "context"):
            current = self.lifecycle.get(nodeid)
            if current is None:
                self.collection_mutation = True
                return
            outcome = "passed" if report.passed else "skipped" if report.skipped else "failed"
            current["subtests"][outcome] += 1
            return
        if report.when not in {"setup", "call", "teardown"}:
            return
        current = self.lifecycle.get(nodeid)
        if current is None or current[report.when] is not None:
            self.collection_mutation = True
            return
        current[report.when] = "passed" if report.passed else "skipped" if report.skipped else "failed"
        if getattr(report, "wasxfail", None) is not None:
            current["xfail"] = True

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_collection_modifyitems(self, session: Any, config: Any, items: list[Any]):
        before = [item.nodeid for item in items]
        yield
        after = [item.nodeid for item in items]
        self.collection_before = before
        self.collection_after = after
        if after != before or self.collection_mutation:
            self.collection_mutation = True
            return
        if self.expected_nodeids is not None:
            if before != self.expected_nodeids or self.selected_nodeids is None:
                self.collection_mutation = True
                return
            selected_set = set(self.selected_nodeids)
            items[:] = [item for item in items if item.nodeid in selected_set]
            self.lifecycle = {
                nodeid: {
                    "setup": None,
                    "call": None,
                    "teardown": None,
                    "xfail": False,
                    "subtests": {"passed": 0, "skipped": 0, "failed": 0},
                }
                for nodeid in self.selected_nodeids
            }


def _worker_entry(mode: str, args: list[str]) -> int:
    if mode not in {"collect", "run"} or not args:
        return 2
    report_path = Path(args[0])
    expected_nodeids: list[str] | None = None
    selected_nodeids: list[str] | None = None
    try:
        if mode == "run":
            if len(args) != 3:
                return 2
            expected_bytes = _read_regular_file(Path(args[1]), maximum=MAX_REFERENCE_BYTES)
            expected_value = _parse_canonical(expected_bytes, maximum=MAX_REFERENCE_BYTES)
            expected_nodeids = _nodeids(expected_value.get("collection_order"))
            selected_value = _parse_canonical(
                _read_regular_file(Path(args[2]), maximum=MAX_REFERENCE_BYTES),
                maximum=MAX_REFERENCE_BYTES,
            )
            selected = _nodeids(selected_value.get("selected_nodeids"))
            expected_set = set(expected_nodeids)
            if any(nodeid not in expected_set for nodeid in selected):
                raise PartitionError
            selected_nodeids = selected
        elif len(args) != 1:
            return 2
        import pytest

        plugin = _WorkerPlugin(mode, expected_nodeids, selected_nodeids)
        pytest_args = ["-q", "--durations=25"] if mode == "run" else ["--collect-only"]
        try:
            exit_code = int(pytest.main(pytest_args, plugins=[plugin]))
        except BaseException:
            exit_code = 2
        if plugin.collection_before is None or plugin.collection_after is None or plugin.nodeids is None:
            raise PartitionError
        if plugin.collection_mutation:
            raise PartitionError
        if mode == "collect":
            if plugin.collection_before != plugin.collection_after or plugin.nodeids != plugin.collection_before:
                raise PartitionError
            lifecycle: dict[str, Any] = {}
        else:
            if plugin.expected_nodeids is None or plugin.nodeids != selected:
                raise PartitionError
            if set(plugin.lifecycle) != set(selected):
                raise PartitionError
            for phases in plugin.lifecycle.values():
                if phases["setup"] is None or phases["teardown"] is None:
                    raise PartitionError
                if phases["setup"] == "passed" and phases["call"] is None:
                    raise PartitionError
                if phases["setup"] == "skipped" and phases["call"] is not None:
                    raise PartitionError
            lifecycle = plugin.lifecycle
        report = {
            "exit_code": exit_code,
            "nodeids": plugin.nodeids,
            "collection_before": plugin.collection_before,
            "collection_after": plugin.collection_after,
            "lifecycle": lifecycle,
        }
        _write_new_file(report_path, _canonical_json(report))
        return 0
    except BaseException:
        return 2


def _collect(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ci-partition-collect-") as temp_dir:
        report_path = Path(temp_dir) / "worker-report.json"
        _child_process(root, "collect", report_path, [])
        report = _parse_canonical(_read_regular_file(report_path, maximum=MAX_RECEIPT_BYTES), maximum=MAX_RECEIPT_BYTES)
    if report["exit_code"] != 0 or not report["nodeids"]:
        raise PartitionError
    nodeids = _nodeids(report["nodeids"])
    return {"nodeids": sorted(nodeids), "collection_order": nodeids}


def _manifest(binding: dict[str, Any], collection: dict[str, Any]) -> dict[str, Any]:
    result = {**binding, **collection, "schema_version": 1}
    _validate_manifest(result)
    return result


def _run(
    root: Path, binding: dict[str, Any], shard: str, approved_weights_bytes: bytes
) -> dict[str, Any]:
    collection = _collect(root)
    if shard == "serial":
        selected = collection["collection_order"]
    else:
        assignments = _partition(
            collection["collection_order"], approved_weights_bytes=approved_weights_bytes
        )
        selected = assignments[int(shard)]
    started = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix="ci-partition-run-") as temp_dir:
        temp_root = Path(temp_dir)
        report_path = temp_root / "worker-report.json"
        expected_path = temp_root / "expected.json"
        selected_path = temp_root / "selected.json"
        _write_new_file(expected_path, _canonical_json(collection))
        _write_new_file(selected_path, _canonical_json({"selected_nodeids": selected}))
        _child_process(root, "run", report_path, [str(expected_path), str(selected_path)])
        report = _parse_canonical(_read_regular_file(report_path, maximum=MAX_RECEIPT_BYTES), maximum=MAX_RECEIPT_BYTES)
    elapsed_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    if report["exit_code"] != 0 or report["nodeids"] != selected:
        raise PartitionError
    outcomes = []
    for nodeid in selected:
        phases = report["lifecycle"][nodeid]
        outcome = {"nodeid": nodeid, **phases}
        outcomes.append(outcome)
    receipt = {
        **binding,
        "schema_version": 1,
        "shard": shard,
        "elapsed_ms": elapsed_ms,
        "pytest_exit_code": report["exit_code"],
        "completed": True,
        "nodeids": collection["nodeids"],
        "selected_nodeids": selected,
        "outcomes": outcomes,
    }
    _validate_receipt(receipt, binding=binding, manifest=_manifest(binding, collection), shard=shard)
    return receipt


def _verify_cli(
    reference_path: Path,
    receipts_dir: Path,
    serial_path: Path | None,
    approved_weights_bytes: bytes,
) -> tuple[dict[str, Any], bytes, bytes, bytes]:
    reference_bytes = _read_regular_file(reference_path, maximum=MAX_REFERENCE_BYTES)
    metadata = receipts_dir.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise PartitionError
    try:
        names = {entry.name for entry in os.scandir(receipts_dir)}
    except OSError as exc:
        raise PartitionError from exc
    if names != {"shard-0.json", "shard-1.json"}:
        raise PartitionError
    zero_bytes = _read_regular_file(receipts_dir / "shard-0.json", maximum=MAX_RECEIPT_BYTES)
    one_bytes = _read_regular_file(receipts_dir / "shard-1.json", maximum=MAX_RECEIPT_BYTES)
    serial_bytes = (
        _read_regular_file(serial_path, maximum=MAX_RECEIPT_BYTES) if serial_path is not None else None
    )
    summary = _verify_values(
        _runtime_binding(),
        approved_weights_bytes,
        reference_bytes,
        zero_bytes,
        one_bytes,
        serial_bytes,
    )
    return summary, reference_bytes, zero_bytes, one_bytes


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise PartitionError


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="ci_partition.py",
        description=__doc__,
        epilog=(
            "Fixed commands:\n"
            "  run --shard {0,1,serial} --output PATH\n"
            "  collect --output PATH\n"
            "  verify --reference PATH --receipts DIR [--serial PATH]"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--shard", choices=("0", "1", "serial"), required=True)
    run.add_argument("--output", type=Path, required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--reference", type=Path, required=True)
    verify.add_argument("--receipts", type=Path, required=True)
    verify.add_argument("--serial", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command in {"collect", "run"}:
            binding = _runtime_binding()
            root = Path.cwd().resolve(strict=True)
            if args.command == "collect":
                value = _manifest(binding, _collect(root))
            else:
                value = _run(root, binding, args.shard, _approved_weights_bytes())
            _write_new_file(args.output, _canonical_json(value))
            return 0
        summary, _, _, _ = _verify_cli(
            args.reference,
            args.receipts,
            args.serial,
            _approved_weights_bytes(),
        )
        sys.stdout.buffer.write(_canonical_json(summary))
        return 0
    except Exception:
        sys.stderr.write(FIXED_ERROR)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
