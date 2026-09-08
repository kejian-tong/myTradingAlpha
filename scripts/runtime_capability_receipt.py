"""Verify a bounded host-runtime capability receipt without granting authority.

This verifier checks only a receipt's declared structure, repository binding, and
the configured intent of the named project role.  A successful result is
structural contract evidence; it does not authenticate the runtime, source
references, model route, sandbox, tools, or any Codex transcript.
"""

from __future__ import annotations

import argparse
import json
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

_MODELS = frozenset(
    {
        "gpt-5.3-codex-spark",
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-6-astra",
    }
)
_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_SANDBOX_MODES = frozenset({"read-only", "workspace-write", "danger-full-access"})
_PERMISSION_PROFILES = frozenset(
    {"read-only", "workspace-write", "danger-full-access", "disabled", "standard"}
)
_READ_ONLY_PROFILES = frozenset({"read-only", "disabled"})
_APPROVAL_POLICIES = frozenset({"untrusted", "on-failure", "on-request", "never"})
_MULTI_AGENT_VERSIONS = frozenset({"v1", "v2"})

# These are explicit tool identities known to be capable of mutating the
# checkout, Codex collaboration state, GitHub, messaging, calendar, or Sites.
# The verifier deliberately rejects names by operation markers as well, so a
# newly prefixed connector mutation cannot become an accidental read-only tool.
_MUTATION_TOOLS = frozenset(
    {
        "apply_patch",
        "exec_command",
        "write_stdin",
        "mcp__codex_app__automation_update",
        "mcp__codex_app__create_thread",
        "mcp__codex_app__delete_sidebar_section",
        "mcp__codex_app__fork_thread",
        "mcp__codex_app__handoff_thread",
        "mcp__codex_app__move_project_to_sidebar_section",
        "mcp__codex_app__move_thread_to_sidebar_section",
        "mcp__codex_app__send_message_to_thread",
        "mcp__codex_app__set_thread_archived",
        "mcp__codex_app__set_thread_title",
        "mcp__codex_apps__github_create_pull_request",
        "mcp__codex_apps__github_merge_pull_request",
        "mcp__codex_apps__github_update_pull_request",
        "mcp__codex_apps__gmail_send_message",
        "mcp__codex_apps__calendar_create_event",
        "mcp__codex_apps__sites_deploy",
    }
)
_MUTATION_MARKERS = (
    "_create_",
    "_delete_",
    "_deploy",
    "_fork_",
    "_handoff_",
    "_merge_",
    "_send_",
    "_set_",
    "_update_",
    "apply_patch",
    "exec_command",
    "write_stdin",
)


class _DuplicateField(ValueError):
    """Raised when a JSON object repeats a field name."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateField(f"duplicate field: {key}")
        result[key] = value
    return result


def _parse_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise ValueError("TOML parser unavailable") from exc
    with path.open("rb") as handle:
        parsed = tomllib.load(handle)
    if type(parsed) is not dict:
        raise ValueError("role TOML must decode to an object")
    return parsed


def _text(value: object, field: str, *, maximum: int = MAX_TEXT_LENGTH) -> list[str]:
    if type(value) is not str:
        return [f"{field} must be a string"]
    if not value or len(value) > maximum or any(ord(char) < 0x20 for char in value):
        return [f"{field} must be a bounded non-empty string"]
    return []


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or "git lookup failed")
    value = completed.stdout.strip()
    if not value:
        raise ValueError("git lookup returned no object")
    return value


def _resolve_role_config(root: Path, receipt: Mapping[str, object]) -> tuple[Path, dict[str, Any]]:
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
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError("config_path escapes the repository")
    if not candidate.is_file():
        raise ValueError("configured role file is missing")
    return candidate, _parse_toml(candidate)


def _mutation_tool(name: str) -> bool:
    return name in _MUTATION_TOOLS or any(marker in name for marker in _MUTATION_MARKERS)


def _decode_receipt(value: object) -> tuple[object, list[str]]:
    if not isinstance(value, (bytes, str)):
        return value, []
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
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
    keys = set(receipt)
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - keys)
    unknown = sorted(keys - REQUIRED_FIELDS)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if errors:
        return errors
    return errors


def _validate_values(receipt: dict[str, object]) -> list[str]:
    errors: list[str] = []

    if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
        errors.append("schema_version must be exactly 1")
    if receipt["evidence_source"] != "host_runtime":
        errors.append("evidence_source must be host_runtime")

    for field in ("source_ref", "session_digest", "turn_digest", "agent_digest"):
        value = receipt[field]
        if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase sha256 digest")

    if type(receipt["pr_id"]) is not str or _PR_ID_RE.fullmatch(receipt["pr_id"]) is None:
        errors.append("pr_id has an invalid identifier")
    if type(receipt["role"]) is not str or _ROLE_RE.fullmatch(receipt["role"]) is None:
        errors.append("role has an invalid identifier")

    for field in ("runtime_version", "multi_agent_version"):
        errors.extend(_text(receipt[field], field))
    if receipt["multi_agent_version"] not in _MULTI_AGENT_VERSIONS:
        errors.append("multi_agent_version is unsupported")
    errors.extend(_text(receipt["config_path"], "config_path", maximum=MAX_CONFIG_PATH_LENGTH))

    if receipt["model"] not in _MODELS:
        errors.append("model is unsupported")
    if receipt["reasoning_effort"] not in _REASONING_EFFORTS:
        errors.append("reasoning_effort is unsupported")
    for field in ("model", "reasoning_effort"):
        if type(receipt[field]) is not str:
            errors.append(f"{field} must be a string")

    for field in ("base_sha", "head_sha", "tree_sha"):
        value = receipt[field]
        if type(value) is not str or _OBJECT_SHA_RE.fullmatch(value) is None:
            errors.append(f"{field} must be a lowercase commit/tree SHA")

    if receipt["sandbox_mode"] not in _SANDBOX_MODES:
        errors.append("sandbox_mode is unsupported")
    if receipt["permission_profile"] not in _PERMISSION_PROFILES:
        errors.append("permission_profile is unsupported")
    if receipt["approval_policy"] not in _APPROVAL_POLICIES:
        errors.append("approval_policy is unsupported")
    for field in ("sandbox_mode", "permission_profile", "approval_policy"):
        if type(receipt[field]) is not str:
            errors.append(f"{field} must be a string")

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
            if _mutation_tool(name):
                errors.append(f"mutation-capable tool exposed: {name}")
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


def _validate_role_intent(root: Path, receipt: dict[str, object]) -> list[str]:
    try:
        config_path, configured = _resolve_role_config(root, receipt)
    except (OSError, ValueError) as exc:
        return [f"role configuration invalid: {exc}"]

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
            errors.append(f"{field} does not match configured intent in {config_path}")

    agent_config = configured.get("agents")
    if type(agent_config) is not dict or agent_config.get("enabled") is not False:
        errors.append("named role must disable nested delegation")

    configured_sandbox = configured.get("sandbox_mode")
    if configured_sandbox == "read-only":
        if receipt["sandbox_mode"] != "read-only":
            errors.append("read-only role has a non-read-only effective sandbox")
        if receipt["permission_profile"] not in _READ_ONLY_PROFILES:
            errors.append("read-only role has a non-read-only effective permission profile")
    elif configured_sandbox is not None and receipt["sandbox_mode"] != configured_sandbox:
        errors.append("sandbox_mode does not match configured intent")
    return errors


def _validate_repository_binding(root: Path, receipt: dict[str, object]) -> list[str]:
    try:
        resolved_root = root.resolve()
        current_head = _git(resolved_root, "rev-parse", "--verify", "HEAD")
        current_tree = _git(resolved_root, "rev-parse", "--verify", "HEAD^{tree}")
        base_commit = _git(
            resolved_root,
            "rev-parse",
            "--verify",
            f"{receipt['base_sha']}^{{commit}}",
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return [f"repository binding unavailable: {exc}"]

    errors: list[str] = []
    if base_commit != receipt["base_sha"]:
        errors.append("base_sha does not resolve to the exact repository commit")
    if receipt["head_sha"] != current_head:
        errors.append("head_sha is not the checked-out repository HEAD")
    if receipt["tree_sha"] != current_tree:
        errors.append("tree_sha is not the checked-out repository tree")
    return errors


def verify_receipt(receipt: object, *, repo_root: Path) -> list[str]:
    """Return strict admission errors for structural host-runtime evidence.

    The function performs no authentication and has no write/network authority.
    It accepts a mapping for in-process checks or raw JSON bytes/text for the
    duplicate-key and size-bounded parser path used by the CLI.
    """

    decoded, decode_errors = _decode_receipt(receipt)
    if decode_errors:
        return decode_errors
    shape_errors = _validate_shape(decoded)
    if shape_errors:
        return shape_errors
    assert type(decoded) is dict
    serialized = json.dumps(decoded, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_RECEIPT_BYTES:
        return ["receipt exceeds 64 KiB"]
    errors = _validate_values(decoded)
    if errors:
        return errors
    errors.extend(_validate_role_intent(repo_root, decoded))
    errors.extend(_validate_repository_binding(repo_root, decoded))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path, required=True, help="receipt JSON file to verify")
    parser.add_argument("--repo-root", type=Path, required=True, help="checked-out repository root")
    args = parser.parse_args(argv)
    try:
        raw = args.verify.read_bytes()
    except OSError as exc:
        print(f"ERROR: cannot read receipt: {exc}")
        return 1
    if len(raw) > MAX_RECEIPT_BYTES:
        print("ERROR: receipt exceeds 64 KiB")
        return 1
    errors = verify_receipt(raw, repo_root=args.repo_root)
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
