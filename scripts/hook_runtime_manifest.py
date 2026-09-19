"""Verify a bounded hook-runtime manifest as supplemental structural evidence.

This offline verifier does not generate manifests or authenticate the runtime
origin of any declaration.  It checks only the exact record shape, the
declared truth table, and immutable Git-object bindings supplied by trusted
CLI expectations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

MAX_RECORD_BYTES = 64 * 1024
MAX_HOOK_CONFIG_BYTES = 64 * 1024

REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "record_kind",
        "authority",
        "evidence_source",
        "session_ref",
        "pr_id",
        "base_sha",
        "head_sha",
        "tree_sha",
        "hook_config_digest",
        "hook_state",
        "host_reported_loaded",
        "host_reported_trusted",
        "evidence_consistent",
        "host_evidence_ref",
        "hooks_effective",
    }
)

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_PR_ID = re.compile(r"[A-Z][A-Z0-9_-]{2,63}\Z")
_EVIDENCE_SOURCES = frozenset({"host_runtime", "caller_declaration", "none"})
_HOOK_STATES = frozenset({"observed", "unavailable", "unknown", "contradictory"})


class _DuplicateField(ValueError):
    """Raised when a JSON object repeats a field name."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateField("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"unsupported JSON constant: {value}")


def _contains_non_ascii(value: object) -> bool:
    if isinstance(value, str):
        return any(ord(character) > 0x7F for character in value)
    if isinstance(value, Mapping):
        return any(
            _contains_non_ascii(key) or _contains_non_ascii(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_non_ascii(item) for item in value)
    return False


def _read_canonical_record(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    if len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ValueError("record size or line ending is invalid")
    try:
        text = raw[:-1].decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("record JSON is invalid") from exc
    if type(value) is not dict or _contains_non_ascii(value):
        raise ValueError("record JSON shape or encoding is invalid")
    canonical = (
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    if raw != canonical:
        raise ValueError("record JSON is not canonical")
    return value


def _exact_bool_or_none(value: object) -> bool:
    return value is None or type(value) is bool


def _validate_record(record: object) -> None:
    if type(record) is not dict or set(record) != REQUIRED_FIELDS:
        raise ValueError("record fields are invalid")
    assert isinstance(record, dict)

    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("record schema is invalid")
    if record["record_kind"] != "hook_runtime_manifest":
        raise ValueError("record kind is invalid")
    if record["authority"] != "supplemental_only":
        raise ValueError("record authority is invalid")

    string_fields = (
        "record_kind",
        "authority",
        "evidence_source",
        "session_ref",
        "pr_id",
        "base_sha",
        "head_sha",
        "tree_sha",
        "hook_config_digest",
        "hook_state",
    )
    if any(type(record[field]) is not str for field in string_fields):
        raise ValueError("record string fields are invalid")
    if record["evidence_source"] not in _EVIDENCE_SOURCES:
        raise ValueError("record evidence source is invalid")
    if record["hook_state"] not in _HOOK_STATES:
        raise ValueError("record hook state is invalid")
    if _SHA64.fullmatch(record["session_ref"]) is None:
        raise ValueError("record session reference is invalid")
    if _PR_ID.fullmatch(record["pr_id"]) is None:
        raise ValueError("record PR identifier is invalid")
    for field in ("base_sha", "head_sha", "tree_sha"):
        if _SHA40.fullmatch(record[field]) is None:
            raise ValueError("record Git object reference is invalid")
    if _SHA64.fullmatch(record["hook_config_digest"]) is None:
        raise ValueError("record hook digest is invalid")

    for field in (
        "host_reported_loaded",
        "host_reported_trusted",
        "evidence_consistent",
    ):
        if not _exact_bool_or_none(record[field]):
            raise ValueError("record host evidence type is invalid")
    if record["host_evidence_ref"] is not None and (
        type(record["host_evidence_ref"]) is not str
        or _SHA64.fullmatch(record["host_evidence_ref"]) is None
    ):
        raise ValueError("record host evidence reference is invalid")
    if type(record["hooks_effective"]) is not bool:
        raise ValueError("record effective flag is invalid")

    source = record["evidence_source"]
    if source == "host_runtime":
        if (
            type(record["host_reported_loaded"]) is not bool
            or type(record["host_reported_trusted"]) is not bool
            or type(record["evidence_consistent"]) is not bool
            or record["host_evidence_ref"] is None
        ):
            raise ValueError("host runtime evidence is incomplete")
        if record["evidence_consistent"] is False:
            expected_state = "contradictory"
            expected_effective = False
        elif record["host_reported_loaded"] and record["host_reported_trusted"]:
            expected_state = "observed"
            expected_effective = True
        else:
            expected_state = "unavailable"
            expected_effective = False
    else:
        if any(
            record[field] is not None
            for field in (
                "host_reported_loaded",
                "host_reported_trusted",
                "evidence_consistent",
                "host_evidence_ref",
            )
        ):
            raise ValueError("non-host evidence must not claim host facts")
        expected_state = "unknown"
        expected_effective = False

    if (
        record["hook_state"] != expected_state
        or record["hooks_effective"] is not expected_effective
    ):
        raise ValueError("record truth table is invalid")


def _git_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    environment.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
    )
    return environment


def _git_run(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=5,
    )


def _git_text(root: Path, *arguments: str) -> str:
    completed = _git_run(root, *arguments)
    if completed.returncode != 0 or not completed.stdout:
        raise ValueError("Git lookup failed")
    return completed.stdout.decode("ascii").strip()


def _git_blob(root: Path, *arguments: str) -> bytes:
    completed = _git_run(root, *arguments)
    if completed.returncode != 0:
        raise ValueError("Git object lookup failed")
    return completed.stdout


def _git_config_present(root: Path, *arguments: str) -> bool:
    completed = _git_run(root, "config", "--local", *arguments)
    if completed.returncode == 0:
        return bool(completed.stdout)
    if completed.returncode == 1:
        return False
    raise ValueError("Git configuration lookup failed")


def _repository_is_partial_or_promisor(root: Path) -> bool:
    if _git_config_present(root, "--get", "extensions.partialClone"):
        return True
    completed = _git_run(root, "config", "--local", "--get-regexp", r"^remote\..*\.promisor$")
    if completed.returncode == 1:
        return False
    if completed.returncode != 0:
        raise ValueError("Git promisor configuration lookup failed")
    truthy = {b"1", b"true", b"yes", b"on"}
    return any(line.rsplit(maxsplit=1)[-1].lower() in truthy for line in completed.stdout.splitlines())


def _validate_expected_inputs(
    expected_pr_id: object,
    expected_session_ref: object,
    expected_base_sha: object,
    expected_head_sha: object,
) -> None:
    if (
        type(expected_pr_id) is not str
        or _PR_ID.fullmatch(expected_pr_id) is None
        or type(expected_session_ref) is not str
        or _SHA64.fullmatch(expected_session_ref) is None
        or type(expected_base_sha) is not str
        or _SHA40.fullmatch(expected_base_sha) is None
        or type(expected_head_sha) is not str
        or _SHA40.fullmatch(expected_head_sha) is None
    ):
        raise ValueError("trusted verifier inputs are invalid")


def _validate_repository_binding(
    root: Path,
    record: Mapping[str, object],
    *,
    expected_pr_id: str,
    expected_session_ref: str,
    expected_base_sha: str,
    expected_head_sha: str,
) -> None:
    if record["pr_id"] != expected_pr_id or record["session_ref"] != expected_session_ref:
        raise ValueError("record identity does not match trusted expectations")
    if record["base_sha"] != expected_base_sha or record["head_sha"] != expected_head_sha:
        raise ValueError("record commit identity does not match trusted expectations")

    resolved_root = root.resolve()
    if not resolved_root.is_dir() or _repository_is_partial_or_promisor(resolved_root):
        raise ValueError("repository binding is unavailable")

    current_head = _git_text(resolved_root, "rev-parse", "--verify", "HEAD")
    expected_head = _git_text(
        resolved_root, "rev-parse", "--verify", f"{expected_head_sha}^{{commit}}"
    )
    expected_base = _git_text(
        resolved_root, "rev-parse", "--verify", f"{expected_base_sha}^{{commit}}"
    )
    expected_tree = _git_text(
        resolved_root, "rev-parse", "--verify", f"{expected_head_sha}^{{tree}}"
    )
    if current_head != expected_head_sha or expected_head != expected_head_sha:
        raise ValueError("expected head is not checked out")
    if expected_base != expected_base_sha or expected_tree != record["tree_sha"]:
        raise ValueError("record tree or commit binding is invalid")

    ancestry = _git_run(
        resolved_root, "merge-base", "--is-ancestor", expected_base_sha, expected_head_sha
    )
    if ancestry.returncode != 0:
        raise ValueError("record base ancestry is invalid")

    hook_bytes = _git_blob(
        resolved_root, "cat-file", "blob", f"{expected_head_sha}:.codex/hooks.json"
    )
    if len(hook_bytes) > MAX_HOOK_CONFIG_BYTES:
        raise ValueError("hook configuration is unbounded")
    if hashlib.sha256(hook_bytes).hexdigest() != record["hook_config_digest"]:
        raise ValueError("hook configuration digest is invalid")


def verify_manifest(
    manifest_path: Path,
    *,
    repo_root: Path,
    expected_pr_id: str,
    expected_session_ref: str,
    expected_base_sha: str,
    expected_head_sha: str,
) -> None:
    """Validate one manifest without granting runtime or merge authority."""
    _validate_expected_inputs(
        expected_pr_id,
        expected_session_ref,
        expected_base_sha,
        expected_head_sha,
    )
    record = _read_canonical_record(manifest_path)
    _validate_record(record)
    _validate_repository_binding(
        repo_root,
        record,
        expected_pr_id=expected_pr_id,
        expected_session_ref=expected_session_ref,
        expected_base_sha=expected_base_sha,
        expected_head_sha=expected_head_sha,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a hook runtime manifest as supplemental structural evidence."
    )
    parser.add_argument("--verify", metavar="MANIFEST", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--expected-pr-id", required=True)
    parser.add_argument("--expected-session-ref", required=True)
    parser.add_argument("--expected-base-sha", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        verify_manifest(
            Path(args.verify),
            repo_root=Path(args.repo_root),
            expected_pr_id=args.expected_pr_id,
            expected_session_ref=args.expected_session_ref,
            expected_base_sha=args.expected_base_sha,
            expected_head_sha=args.expected_head_sha,
        )
    except Exception:
        print(
            "REJECT: hook runtime manifest failed bounded structural validation; "
            "caller data was not echoed.",
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: structural supplemental-only evidence; this verifier cannot authenticate "
        "host trust or evidence provenance."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
