"""Verify a bounded host-runtime capability receipt without granting authority.

This verifier checks only a receipt's declared structure, repository binding, and
the configured intent of the named project role.  A successful result is
structural contract evidence; it does not authenticate the runtime, source
references, model route, sandbox, tools, or any Codex transcript.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MAX_RECEIPT_BYTES = 65_536
MAX_TEXT_LENGTH = 512
MAX_CONFIG_PATH_LENGTH = 256
MAX_TOOL_COUNT = 256
MAX_TOOL_NAME_LENGTH = 256

REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "evidence_source",
        "source_ref",
        "session_digest",
        "turn_digest",
        "agent_digest",
        "pr_id",
        "role",
        "config_path",
        "runtime_version",
        "multi_agent_version",
        "model",
        "reasoning_effort",
        "base_sha",
        "head_sha",
        "tree_sha",
        "sandbox_mode",
        "permission_system",
        "permission_profile",
        "approval_policy",
        "tool_inventory_complete",
        "tool_names",
        "observed_at_ms",
    }
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_OBJECT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_ROLE_RE = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")
_PR_ID_RE = re.compile(r"[A-Z][A-Z0-9_-]{2,63}\Z")
_SAFE_TOOL_RE = re.compile(r"[A-Za-z0-9_.:/_-]+\Z")

_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_SANDBOX_MODES = frozenset(
    {"disabled", "read-only", "workspace-write", "danger-full-access"}
)
_PERMISSION_SYSTEMS = frozenset({"legacy_sandbox", "permission_profile"})
_PERMISSION_PROFILES = frozenset(
    {"disabled", ":read-only", ":workspace", ":danger-full-access"}
)
_APPROVAL_POLICIES = frozenset({"untrusted", "on-failure", "on-request", "never"})
_MULTI_AGENT_VERSIONS = frozenset({"v1", "v2"})

# Local filesystem/process tools are governed by the effective local sandbox or
# permission profile. Their visibility is acceptable only under a read-only
# local enforcement system. Apps, connectors, MCP servers, browsers, and Codex
# collaboration controls are separate capability surfaces.
_SANDBOX_GOVERNED_TOOLS = frozenset({"apply_patch", "exec_command", "write_stdin"})
_CAPABILITY_GATEWAY_TOOLS = frozenset({"functions.exec", "functions__exec"})
_COLLABORATION_TOOLS = frozenset(
    {
        "collaboration.followup_task",
        "collaboration.interrupt_agent",
        "collaboration.send_message",
        "collaboration.spawn_agent",
        "collaboration__followup_task",
        "collaboration__interrupt_agent",
        "collaboration__send_message",
        "collaboration__spawn_agent",
        "followup_task",
        "interrupt_agent",
        "send_message",
        "spawn_agent",
    }
)
_EXTERNAL_SPEC_RESEARCHER_MCP_TOOLS = frozenset(
    {
        "mcp__openaiDeveloperDocs__fetch_openai_doc",
        "mcp__openaiDeveloperDocs__search_openai_docs",
    }
)

_STRING_FIELDS = (
    "evidence_source",
    "source_ref",
    "session_digest",
    "turn_digest",
    "agent_digest",
    "pr_id",
    "role",
    "config_path",
    "runtime_version",
    "multi_agent_version",
    "model",
    "reasoning_effort",
    "base_sha",
    "head_sha",
    "tree_sha",
    "sandbox_mode",
    "permission_system",
    "permission_profile",
    "approval_policy",
)


class _DuplicateField(ValueError):
    """Raised when a JSON object repeats a field name."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateField("duplicate JSON field")
        result[key] = value
    return result


def _parse_toml(raw: bytes) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise ValueError("TOML parser unavailable") from exc
    parsed = tomllib.loads(raw.decode("utf-8"))
    if type(parsed) is not dict:
        raise ValueError("role TOML must decode to an object")
    return parsed


def _text(value: object, field: str, *, maximum: int = MAX_TEXT_LENGTH) -> list[str]:
    if type(value) is not str:
        return [f"{field} must be a string"]
    if not value or len(value) > maximum or any(ord(char) < 0x20 for char in value):
        return [f"{field} must be a bounded non-empty string"]
    return []


def _enum(value: object, field: str, allowed: frozenset[str]) -> list[str]:
    if type(value) is not str:
        return [f"{field} must be a string"]
    if value not in allowed:
        return [f"{field} is unsupported"]
    return []


def _local_enforcement_is_read_only(receipt: Mapping[str, object]) -> bool:
    system = receipt.get("permission_system")
    if system == "legacy_sandbox":
        return receipt.get("sandbox_mode") == "read-only"
    if system == "permission_profile":
        return receipt.get("permission_profile") == ":read-only"
    return False


def _git_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("GIT_")
    }
    environment.update(
        GIT_NO_LAZY_FETCH="1",
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
    )
    return environment


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("git lookup failed")
    value = completed.stdout.strip()
    if not value:
        raise ValueError("git lookup returned no object")
    return value


def _git_bytes(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("git object lookup failed")
    if not completed.stdout:
        raise ValueError("git object lookup returned no data")
    return completed.stdout


def _git_is_ancestor(root: Path, base_sha: str, head_sha: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", base_sha, head_sha],
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=5,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise ValueError("git ancestry lookup failed")


def _local_git_config(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), "config", "--local", *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
        text=True,
        timeout=5,
    )


def _repository_is_partial_or_promisor(root: Path) -> bool:
    partial = _local_git_config(root, "--get", "extensions.partialClone")
    if partial.returncode == 0:
        return True
    if partial.returncode != 1:
        raise ValueError("local partial-clone configuration lookup failed")

    promisors = _local_git_config(root, "--get-regexp", r"^remote\..*\.promisor$")
    if promisors.returncode == 1:
        return False
    if promisors.returncode != 0:
        raise ValueError("local promisor configuration lookup failed")
    truthy = {"1", "on", "true", "yes"}
    return any(
        line.rpartition(" ")[2].strip().lower() in truthy
        for line in promisors.stdout.splitlines()
    )


def _resolve_role_config(
    root: Path,
    receipt: Mapping[str, object],
    *,
    expected_head_sha: str,
) -> tuple[str, dict[str, Any]]:
    role = receipt.get("role")
    config_value = receipt.get("config_path")
    errors = [*_text(role, "role"), *_text(config_value, "config_path", maximum=MAX_CONFIG_PATH_LENGTH)]
    if errors:
        raise ValueError("; ".join(errors))
    assert isinstance(role, str)
    assert isinstance(config_value, str)
    if _ROLE_RE.fullmatch(role) is None:
        raise ValueError("role has an invalid identifier")
    if config_value != f".codex/agents/{role.replace('_', '-')}.toml":
        raise ValueError("config_path does not match role")
    if "\\" in config_value:
        raise ValueError("config_path must use a safe POSIX relative path")
    relative = Path(config_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("config_path must not escape the repository")
    raw = _git_bytes(root, "show", f"{expected_head_sha}:{relative.as_posix()}")
    return relative.as_posix(), _parse_toml(raw)


def _decode_receipt(value: object) -> tuple[object, list[str]]:
    if type(value) not in (bytes, str):
        return value, []
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
    except UnicodeError as exc:
        return None, [f"invalid receipt JSON: {exc}"]
    if len(raw) > MAX_RECEIPT_BYTES:
        return None, ["receipt exceeds 64 KiB"]
    try:
        decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (_DuplicateField, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return None, [f"invalid receipt JSON: {exc}"]
    return decoded, []


def _validate_shape(receipt: object) -> list[str]:
    if type(receipt) is not dict:
        return ["receipt must be a JSON object"]
    if any(type(key) is not str for key in receipt):
        return ["receipt field names must be exact strings"]
    keys = set(receipt)
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - keys)
    has_unknown = bool(keys - REQUIRED_FIELDS)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if has_unknown:
        errors.append("receipt contains unknown fields")
    if errors:
        return errors
    return errors


def _validate_exact_field_types(receipt: dict[str, object]) -> list[str]:
    if type(receipt["schema_version"]) is not int:
        return ["schema_version must be an exact integer"]
    for field in _STRING_FIELDS:
        if type(receipt[field]) is not str:
            return [f"{field} must be an exact string"]
    if type(receipt["tool_inventory_complete"]) is not bool:
        return ["tool_inventory_complete must be an exact boolean"]
    tool_names = receipt["tool_names"]
    if type(tool_names) is not list:
        return ["tool_names must be an exact list"]
    for name in tool_names:
        if type(name) is not str:
            return ["tool_names must contain exact strings"]
    if type(receipt["observed_at_ms"]) is not int:
        return ["observed_at_ms must be an exact integer"]
    return []


def _validate_values(receipt: dict[str, object]) -> list[str]:
    errors: list[str] = []

    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
        errors.append("schema_version must be exactly 1")
    if type(receipt["evidence_source"]) is not str:
        errors.append("evidence_source must be a string")
    elif receipt["evidence_source"] != "host_runtime":
        errors.append("evidence_source must be host_runtime")

    for field in ("source_ref", "session_digest", "turn_digest", "agent_digest"):
        value = receipt[field]
        if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase sha256 digest")

    if type(receipt["pr_id"]) is not str or _PR_ID_RE.fullmatch(receipt["pr_id"]) is None:
        errors.append("pr_id has an invalid identifier")
    if type(receipt["role"]) is not str or _ROLE_RE.fullmatch(receipt["role"]) is None:
        errors.append("role has an invalid identifier")

    errors.extend(_text(receipt["runtime_version"], "runtime_version"))
    errors.extend(_enum(receipt["multi_agent_version"], "multi_agent_version", _MULTI_AGENT_VERSIONS))
    errors.extend(_text(receipt["config_path"], "config_path", maximum=MAX_CONFIG_PATH_LENGTH))

    errors.extend(_text(receipt["model"], "model"))
    errors.extend(_enum(receipt["reasoning_effort"], "reasoning_effort", _REASONING_EFFORTS))

    for field in ("base_sha", "head_sha", "tree_sha"):
        value = receipt[field]
        if type(value) is not str or _OBJECT_SHA_RE.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase commit/tree SHA")

    errors.extend(_enum(receipt["sandbox_mode"], "sandbox_mode", _SANDBOX_MODES))
    errors.extend(
        _enum(receipt["permission_system"], "permission_system", _PERMISSION_SYSTEMS)
    )
    errors.extend(
        _enum(receipt["permission_profile"], "permission_profile", _PERMISSION_PROFILES)
    )
    errors.extend(_enum(receipt["approval_policy"], "approval_policy", _APPROVAL_POLICIES))

    if receipt["permission_system"] == "legacy_sandbox":
        if receipt["sandbox_mode"] == "disabled":
            errors.append("legacy sandbox system requires an active sandbox mode")
        if receipt["permission_profile"] != "disabled":
            errors.append("permission profile must be disabled under legacy sandbox")
    elif receipt["permission_system"] == "permission_profile":
        if receipt["sandbox_mode"] != "disabled":
            errors.append("legacy sandbox must be disabled under permission profiles")
        if receipt["permission_profile"] == "disabled":
            errors.append("permission profile system requires an active profile")

    if type(receipt["tool_inventory_complete"]) is not bool:
        errors.append("tool_inventory_complete must be an exact boolean")
    elif receipt["tool_inventory_complete"] is not True:
        errors.append("tool inventory observation is incomplete")

    names = receipt["tool_names"]
    if type(names) is not list:
        errors.append("tool_names must be a list")
    elif len(names) > MAX_TOOL_COUNT:
        errors.append("tool_names exceeds the bounded count")
    else:
        for name in names:
            if type(name) is not str or not name or len(name) > MAX_TOOL_NAME_LENGTH:
                errors.append("tool_names must contain bounded non-empty strings")
                continue
            if _SAFE_TOOL_RE.fullmatch(name) is None:
                errors.append("tool_names contains an invalid tool identifier")
                continue
            if name in _CAPABILITY_GATEWAY_TOOLS:
                errors.append("capability gateway exposed")
            elif name in _COLLABORATION_TOOLS:
                errors.append("collaboration control exposed")
            elif name in _SANDBOX_GOVERNED_TOOLS:
                if not _local_enforcement_is_read_only(receipt):
                    errors.append("local mutation tool lacks read-only enforcement")
            elif name.startswith("mcp__") and (
                receipt.get("role") != "external_spec_researcher"
                or name not in _EXTERNAL_SPEC_RESEARCHER_MCP_TOOLS
            ):
                errors.append("unapproved external MCP or connector tool exposed")
        if any(type(name) is not str for name in names):
            pass
        elif names != sorted(names):
            errors.append("tool_names must be sorted")
        elif len(set(names)) != len(names):
            errors.append("tool_names must be unique")

    observed = receipt["observed_at_ms"]
    if type(observed) is not int or observed < 0:
        errors.append("observed_at_ms must be a non-negative integer")
    return errors


def _validate_role_intent(
    root: Path,
    receipt: dict[str, object],
    *,
    expected_head_sha: str,
) -> list[str]:
    try:
        _config_path, configured = _resolve_role_config(
            root,
            receipt,
            expected_head_sha=expected_head_sha,
        )
    except (OSError, UnicodeError, ValueError):
        return ["role configuration is invalid or unavailable"]

    errors: list[str] = []
    configured_name = configured.get("name")
    configured_model = configured.get("model")
    configured_effort = configured.get("model_reasoning_effort")
    for field, configured_value in (
        ("role", configured_name),
        ("model", configured_model),
        ("reasoning_effort", configured_effort),
    ):
        if receipt[field] != configured_value:
            errors.append(f"{field} does not match exact-tree role configuration")

    agent_config = configured.get("agents")
    if type(agent_config) is not dict or agent_config.get("enabled") is not False:
        errors.append("named role must disable nested delegation")

    configured_sandbox = configured.get("sandbox_mode")
    if configured_sandbox == "read-only":
        if not _local_enforcement_is_read_only(receipt):
            errors.append("read-only role lacks effective read-only local enforcement")
    elif (
        configured_sandbox is not None
        and receipt["permission_system"] == "legacy_sandbox"
        and receipt["sandbox_mode"] != configured_sandbox
    ):
        errors.append("sandbox_mode does not match configured intent")
    return errors


def _validate_repository_binding(
    root: Path,
    receipt: dict[str, object],
    *,
    expected_pr_id: str,
    expected_base_sha: str,
    expected_head_sha: str,
) -> list[str]:
    try:
        resolved_root = root.resolve()
        if _repository_is_partial_or_promisor(resolved_root):
            return ["repository binding is unavailable"]
        current_head = _git(resolved_root, "rev-parse", "--verify", "HEAD")
        expected_head_commit = _git(
            resolved_root,
            "rev-parse",
            "--verify",
            f"{expected_head_sha}^{{commit}}",
        )
        expected_base_commit = _git(
            resolved_root,
            "rev-parse",
            "--verify",
            f"{expected_base_sha}^{{commit}}",
        )
        expected_tree = _git(resolved_root, "rev-parse", "--verify", f"{expected_head_sha}^{{tree}}")
        base_is_ancestor = _git_is_ancestor(
            resolved_root,
            expected_base_sha,
            expected_head_sha,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return ["repository binding is unavailable"]

    errors: list[str] = []
    if receipt["pr_id"] != expected_pr_id:
        errors.append("pr_id does not match the trusted expectation")
    if expected_base_commit != expected_base_sha or receipt["base_sha"] != expected_base_sha:
        errors.append("base_sha does not match the trusted exact commit")
    if expected_head_commit != expected_head_sha or receipt["head_sha"] != expected_head_sha:
        errors.append("head_sha does not match the trusted exact commit")
    if current_head != expected_head_sha:
        errors.append("trusted head is not the checked-out repository HEAD")
    if receipt["tree_sha"] != expected_tree:
        errors.append("tree_sha is not the trusted head tree")
    if not base_is_ancestor:
        errors.append("trusted base is not an ancestor of trusted head")
    return errors


def verify_receipt(
    receipt: object,
    *,
    repo_root: Path,
    expected_pr_id: str,
    expected_base_sha: str,
    expected_head_sha: str,
) -> list[str]:
    """Return strict admission errors for structural host-runtime evidence.

    The function performs no authentication and has no write/network authority.
    It accepts a mapping for in-process checks or raw JSON bytes/text for the
    duplicate-key and size-bounded parser path used by the CLI.
    """

    expectation_errors: list[str] = []
    if type(expected_pr_id) is not str or _PR_ID_RE.fullmatch(expected_pr_id) is None:
        expectation_errors.append("expected_pr_id has an invalid identifier")
    for field, value in (
        ("expected_base_sha", expected_base_sha),
        ("expected_head_sha", expected_head_sha),
    ):
        if type(value) is not str or _OBJECT_SHA_RE.fullmatch(value) is None:
            expectation_errors.append(f"{field} must be a lowercase commit SHA")
    if expectation_errors:
        return expectation_errors

    decoded, decode_errors = _decode_receipt(receipt)
    if decode_errors:
        return decode_errors
    shape_errors = _validate_shape(decoded)
    if shape_errors:
        return shape_errors
    assert type(decoded) is dict
    type_errors = _validate_exact_field_types(decoded)
    if type_errors:
        return type_errors
    errors = _validate_values(decoded)
    if errors:
        return errors
    try:
        serialized = json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
        serialized_size = len(serialized.encode("utf-8"))
    except (TypeError, UnicodeError, ValueError):
        return ["receipt contains non-serializable text or values"]
    if serialized_size > MAX_RECEIPT_BYTES:
        return ["receipt exceeds 64 KiB"]
    errors.extend(
        _validate_repository_binding(
            repo_root,
            decoded,
            expected_pr_id=expected_pr_id,
            expected_base_sha=expected_base_sha,
            expected_head_sha=expected_head_sha,
        )
    )
    if errors:
        return errors
    errors.extend(
        _validate_role_intent(
            repo_root,
            decoded,
            expected_head_sha=expected_head_sha,
        )
    )
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, required=True, help="receipt JSON file to verify")
    parser.add_argument("--repo-root", type=Path, required=True, help="checked-out repository root")
    parser.add_argument("--expected-pr-id", required=True, help="trusted expected PR identifier")
    parser.add_argument("--expected-base-sha", required=True, help="trusted exact base commit SHA")
    parser.add_argument("--expected-head-sha", required=True, help="trusted exact head commit SHA")
    args = parser.parse_args(argv)
    try:
        raw = args.verify.read_bytes()
    except OSError as exc:
        print(f"ERROR: cannot read receipt: {exc}")
        return 1
    if len(raw) > MAX_RECEIPT_BYTES:
        print("ERROR: receipt exceeds 64 KiB")
        return 1
    errors = verify_receipt(
        raw,
        repo_root=args.repo_root,
        expected_pr_id=args.expected_pr_id,
        expected_base_sha=args.expected_base_sha,
        expected_head_sha=args.expected_head_sha,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(
        "PASS: structural host-runtime receipt only; no runtime authentication "
        "or transcript parsing performed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
