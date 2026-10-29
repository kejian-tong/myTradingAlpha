"""Offline harness consistency and merge-candidate predicates; no execution authority.

A passing predicate checks supplied facts, not their authenticity. The Master must
obtain authorization, role loading, reviews and CI from independent trusted evidence.
This checker cannot authenticate host-origin runtime evidence.
Master-only delegation is a behavioral policy declaration, not repo-level host identity enforcement.
This program never spawns an agent, writes a file, contacts GitHub, or merges a PR.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from contextlib import suppress
from pathlib import Path

_ROLES = {
    "normal_implementer": ("gpt-6-luna", "max", False),
    "high_implementer": ("gpt-6.1-sol", "xhigh", False),
    "critical_implementer": ("gpt-6.1-sol", "xhigh", False),
    "reviewer_high": ("gpt-6.1-sol", "xhigh", True),
    "reviewer_xhigh": ("gpt-6.1-sol", "xhigh", True),
    "code_explorer": ("gpt-6-luna", "max", True),
    "test_auditor": ("gpt-6-luna", "max", True),
    "boundary_reviewer": ("gpt-6.1-sol", "xhigh", True),
    "external_spec_researcher": ("gpt-6-luna", "max", True),
    "astra_canary": ("gpt-6-astra", "xhigh", True),
}
_SCOPED_AGENT_PATHS = (
    "docs/productionization/AGENTS.md",
    "mytradingalpha/AGENTS.md",
    "tradingagents/AGENTS.md",
    "tests/productionization/AGENTS.md",
)
_COLLABORATION_INSTRUCTION_CONTRACT = (
    "Collaboration-control visibility alone is non-blocking.",
    "Do not invoke collaboration controls or delegate nested work.",
    "Any attempted or completed nested delegation is a blocking policy violation.",
)
_READ_ONLY_REVIEW_MARKER = (
    "Remain separate from the writer. Do not edit files, create commits, push, merge, or delegate."
)
_ROOT_REVIEW_ASSURANCE_CONTRACT = (
    "Read-only review assurance",
    "detached exact-head worktree",
    "cleanliness before and after review",
    "supplemental disclosure",
    "does not itself block or stop review",
    "The Master alone owns the merge decision",
)
_PROTOCOL_REVIEW_ASSURANCE_CONTRACT = (
    "Read-only role assurance",
    "fresh context separate from the writer",
    "exact SHA and cleanliness before and after review",
    "supplemental disclosure",
    "Independent review assurance",
)
_RETIRED_ROLE_ADMISSION_MARKER = (
    "Native read-only admission is governed by root AGENTS.md and must complete before "
    "substantive work or any tool call."
)
_RETIRED_TWO_TURN_PHRASES = (
    "first child turn is admission-only",
    "receive no substantive task",
    "make no tool call",
    "cannot self-approve",
    "follow-up substantive task",
    "interrupt and discard the lane",
)
_SKILL_NAMES = (
    "productionization-preflight",
    "jit-scope-contract",
    "tdd-red-green-evidence",
    "exact-head-review",
    "merge-gate",
    "writer-lease",
)
_WRITER_LEASE_STATIC_SURFACES = (
    "scripts/writer_lease.py",
    "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
    ".agents/skills/writer-lease/SKILL.md",
)
_ORDER = tuple(
    f"{prefix}-{number:02d}"
    for prefix, count in (("FND", 4), ("PIT", 6), ("SIG", 5), ("BT", 6), ("RSK", 5),
                          ("EXC", 4), ("EXP", 4), ("OMS", 6), ("FWD", 3), ("LIVE", 4))
    for number in range(1, count + 1)
)
_HASH_FIELDS = ("head_sha", "base_sha", "review_head_sha", "review_base_sha", "ci_head_sha",
                "source_tree", "ci_checkout_tree")
_TRUE_FIELDS = ("prerequisites_verified", "named_role_loaded", "ci_pass", "review_approved")
_FALSE_FIELDS = ("telemetry_conflict", "blocking_findings")
_TEXT_FIELDS = ("operation", "session_id", "authorized_session_id", "pr_id", "stop_after",
                "implementer_context", "reviewer_context")
_GATE_FIELDS = {*_HASH_FIELDS, *_TRUE_FIELDS, *_FALSE_FIELDS, *_TEXT_FIELDS,
                "authorized_operations", "active_writers", "collaboration_controls_visible",
                "collaboration_observation_complete", "non_master_collaboration_invoked",
                "delegation_control_mode"}
_GUARD_HOOKS = {"SessionStart": "session-start", "Stop": "stop"}
_TELEMETRY_HOOKS = {"SubagentStart", "SubagentStop", "PostCompact"}
_TELEMETRY_CLEANUP_HOOK = "SessionEnd"
_PRETOOL_HOOK = "PreToolUse"
_OPENAI_DOCS_MCP_URL = "https://developers.openai.com/mcp"
_OPENAI_DOCS_MCP_TOOLS = ["fetch_openai_doc", "search_openai_docs"]
_WATCHLIST_PATH = "docs/productionization/CODEX_FEATURE_WATCHLIST.md"
_STATE_PATH = Path("docs/productionization/AGENT_STATE.md")
_STATE_MAX_BYTES = 12_288
_STATE_READ_MAX_BYTES = _STATE_MAX_BYTES + 1
_STATE_CONTROL_HEADING = "## Current control state"
_STATE_KEY_RE = re.compile(r"^- `([A-Za-z0-9_]+)`: (.+)$")
_STATE_SHA_RE = re.compile(r"`[0-9a-f]{40}`\Z")
_CONTEXT_POLICY_PATH = Path("docs/productionization/CONTEXT_MANAGEMENT.md")
_CONTEXT_POLICY_MAX_BYTES = 6_144
_MEMORY_WATCHLIST_CAPABILITY = "Codex Memories (`features.memories`)"
_MEMORY_WATCHLIST_STATUS = "explicitly disabled / watch-only"
_MEMORY_WATCHLIST_REASON = (
    "this repository requires GitHub/repository-grounded, cross-session and cross-machine auditable "
    "recovery; `features.memories = false` is prospective configuration intent for a fresh session in a "
    "trusted project, while CLI `--config`/`--enable` flags remain higher-precedence overrides; it does not "
    "retroactively change running sessions; project configuration does not authenticate live-runtime state; "
    "hidden/local learned state must not become execution authority"
)


def _toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise ValueError("TOML parser unavailable; use Python 3.11+ or locked dev") from exc
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _contains_toml_key(record: object, key: str) -> bool:
    if type(record) is not dict:
        return False
    return key in record or any(_contains_toml_key(value, key) for value in record.values())


def _normalize_memory_watchlist_cell(value: str) -> str:
    return " ".join(value.strip().split())


def _memory_watchlist_errors(root: Path) -> list[str]:
    path = root / _WATCHLIST_PATH
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    rows = [
        line.strip()
        for line in text.splitlines()
        if line.strip().lower().startswith("| codex memories (")
    ]
    if len(rows) != 1:
        return ["Codex Memory watchlist must contain exactly one Memory decision row"]
    parts = rows[0].split("|")
    if len(parts) != 6 or parts[0].strip() or parts[-1].strip():
        return ["Codex Memory watchlist must contain exactly four Markdown cells"]
    actual = tuple(_normalize_memory_watchlist_cell(cell) for cell in parts[1:4])
    expected = tuple(
        _normalize_memory_watchlist_cell(cell)
        for cell in (
            _MEMORY_WATCHLIST_CAPABILITY,
            _MEMORY_WATCHLIST_STATUS,
            _MEMORY_WATCHLIST_REASON,
        )
    )
    if actual != expected:
        return [
            "Codex Memory watchlist configuration (capability, status, and reason) must match "
            "the canonical reviewed policy"
        ]
    return []


def _single_hook_handler(event_map: dict, event: str, errors: list[str]) -> tuple[dict, dict] | None:
    entries = event_map.get(event)
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        errors.append(f"{event} must have exactly one project hook entry")
        return None
    entry = entries[0]
    handlers = entry.get("hooks")
    if not isinstance(handlers, list) or len(handlers) != 1 or not isinstance(handlers[0], dict):
        errors.append(f"{event} must have exactly one command handler")
        return None
    return entry, handlers[0]


def _hook_errors(root: Path) -> list[str]:
    errors = []
    hook_path = root / ".codex/hooks.json"
    guard_path = root / "scripts/codex_hook_guard.py"
    telemetry_path = root / "scripts/codex_telemetry_hook.py"
    pretool_path = root / "scripts/codex_pretool_guard.py"
    if not guard_path.is_file():
        errors.append("missing lightweight Codex hook guard")
    if not telemetry_path.is_file():
        errors.append("missing Codex lifecycle telemetry hook")
    if not pretool_path.is_file():
        errors.append("missing Codex PreToolUse destructive-command guard")
    hooks = json.loads(hook_path.read_text(encoding="utf-8"))
    event_map = hooks.get("hooks") if isinstance(hooks, dict) else None
    expected_events = set(_GUARD_HOOKS) | _TELEMETRY_HOOKS | {_TELEMETRY_CLEANUP_HOOK, _PRETOOL_HOOK}
    if not isinstance(event_map, dict) or set(event_map) != expected_events:
        return [*errors, "project hooks differ from reviewed telemetry-v3 event set"]

    for event, mode in _GUARD_HOOKS.items():
        found = _single_hook_handler(event_map, event, errors)
        if found is None:
            continue
        _, handler = found
        command = handler.get("command")
        command_windows = handler.get("commandWindows")
        if handler.get("type") != "command" or handler.get("async") is not False:
            errors.append(f"{event} hook must be a synchronous command")
        if handler.get("timeout") != 15:
            errors.append(f"{event} hook timeout differs from reviewed policy")
        if not isinstance(command, str) or "codex_hook_guard.py" not in command or mode not in command:
            errors.append(f"{event} Unix hook command differs from reviewed policy")
        if (
            not isinstance(command_windows, str)
            or "codex_hook_guard.py" not in command_windows
            or mode not in command_windows
        ):
            errors.append(f"{event} Windows hook command differs from reviewed policy")

    pretool = _single_hook_handler(event_map, _PRETOOL_HOOK, errors)
    if pretool is not None:
        entry, handler = pretool
        command = handler.get("command")
        command_windows = handler.get("commandWindows")
        if entry.get("matcher") != "Bash":
            errors.append("PreToolUse matcher must remain the reviewed Bash-only guard")
        if handler.get("type") != "command" or handler.get("async") is not False:
            errors.append("PreToolUse destructive-command guard must be synchronous")
        if handler.get("timeout") != 5:
            errors.append("PreToolUse destructive-command guard timeout differs from reviewed policy")
        if not isinstance(command, str) or "codex_pretool_guard.py" not in command:
            errors.append("PreToolUse Unix command differs from reviewed policy")
        if not isinstance(command_windows, str) or "codex_pretool_guard.py" not in command_windows:
            errors.append("PreToolUse Windows command differs from reviewed policy")

    for event in _TELEMETRY_HOOKS:
        found = _single_hook_handler(event_map, event, errors)
        if found is None:
            continue
        entry, handler = found
        if event == "PostCompact" and entry.get("matcher") != "manual|auto":
            errors.append("PostCompact matcher differs from reviewed policy")
        if event != "PostCompact" and "matcher" in entry:
            errors.append(f"{event} should not narrow the reviewed telemetry matcher")
        command = handler.get("command")
        command_windows = handler.get("commandWindows")
        if handler.get("type") != "command" or handler.get("async") is not True:
            errors.append(f"{event} telemetry hook must be an asynchronous command")
        if handler.get("timeout") != 5:
            errors.append(f"{event} telemetry hook timeout differs from reviewed policy")
        if not isinstance(command, str) or "codex_telemetry_hook.py" not in command:
            errors.append(f"{event} Unix telemetry command differs from reviewed policy")
        if not isinstance(command_windows, str) or "codex_telemetry_hook.py" not in command_windows:
            errors.append(f"{event} Windows telemetry command differs from reviewed policy")

    cleanup = _single_hook_handler(event_map, _TELEMETRY_CLEANUP_HOOK, errors)
    if cleanup is not None:
        entry, handler = cleanup
        command = handler.get("command")
        command_windows = handler.get("commandWindows")
        if "matcher" in entry:
            errors.append("SessionEnd telemetry cleanup must not narrow its matcher")
        if handler.get("type") != "command" or handler.get("async") is not False:
            errors.append("SessionEnd telemetry cleanup must be synchronous")
        if handler.get("timeout") != 3:
            errors.append("SessionEnd telemetry cleanup timeout differs from reviewed policy")
        if not isinstance(command, str) or "codex_telemetry_hook.py" not in command:
            errors.append("SessionEnd Unix telemetry command differs from reviewed policy")
        if not isinstance(command_windows, str) or "codex_telemetry_hook.py" not in command_windows:
            errors.append("SessionEnd Windows telemetry command differs from reviewed policy")

    legacy_keys = {"timeout_sec", "command_windows", "status_message"}
    for event in expected_events:
        found = _single_hook_handler(event_map, event, [])
        if found is not None and legacy_keys.intersection(found[1]):
            errors.append(f"{event} uses legacy hooks.json field names")
    return errors


def _watch_only_feature_errors(root: Path, config: dict) -> list[str]:
    """Reject unreviewed project features and enforce narrow configuration intent."""
    errors = []
    if (root / ".codex/rules").exists():
        errors.append("project-local Codex Rules require a separate reviewed adoption PR")
    if "default_permissions" in config or "permissions" in config:
        errors.append("Codex Permission Profiles are watch-only while sandbox_mode isolation is active")
    features = config.get("features")
    if type(features) is not dict or features.get("memories") is not False:
        errors.append("Codex Memories are watch-only for this auditable repository harness")
    if "memories" in config:
        errors.append("Codex Memories configuration is watch-only for this repository")
    errors.extend(_memory_watchlist_errors(root))
    if "otel" in config:
        errors.append("Codex OpenTelemetry exporters require a separate reviewed adoption PR")
    if "plugins" in config:
        errors.append("repo-level Codex plugin configuration requires a separate reviewed adoption PR")
    if type(features) is not dict or features.get("apps") is not False:
        errors.append(
            "project Codex Apps configuration intent must set features.apps = false; "
            "inherited/global/plugin/managed runtime Apps remain outside this checker"
        )
    if "mcp_servers" in config:
        errors.append("project-level MCP servers are not permitted; configure only the reviewed role intent")
    return errors


def _same_regular_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
    )


def _read_agent_state(root: Path) -> tuple[bytes | None, str | None]:
    """Read the state through one bounded descriptor bound to the inspected path."""
    path = root / _STATE_PATH
    try:
        inspected = os.lstat(path)
    except (OSError, TypeError, ValueError):
        return None, "AGENT_STATE.md is missing or unavailable"
    if not stat.S_ISREG(inspected.st_mode):
        return None, "AGENT_STATE.md must be a regular file, not a symlink"
    if inspected.st_size < 0:
        return None, "AGENT_STATE.md has an invalid size"
    if inspected.st_size > _STATE_MAX_BYTES:
        return None, "AGENT_STATE.md exceeds the 12 KiB hard ceiling"

    flags = os.O_RDONLY
    for flag_name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK"):
        flags |= getattr(os, flag_name, 0)

    descriptor = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not _same_regular_file(inspected, opened):
            return None, "AGENT_STATE.md changed before its bounded read"
        if opened.st_size < 0:
            return None, "AGENT_STATE.md has an invalid size"
        if opened.st_size > _STATE_MAX_BYTES:
            return None, "AGENT_STATE.md exceeds the 12 KiB hard ceiling"

        read_limit = min(_STATE_READ_MAX_BYTES, opened.st_size + 1)
        content = bytearray()
        while len(content) < read_limit:
            chunk = os.read(descriptor, read_limit - len(content))
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > _STATE_MAX_BYTES:
                return None, "AGENT_STATE.md exceeds the 12 KiB hard ceiling"

        after_read = os.fstat(descriptor)
        if (
            not _same_regular_file(opened, after_read)
            or len(content) != opened.st_size
        ):
            return None, "AGENT_STATE.md changed during its bounded read"
        return bytes(content), None
    except (OSError, TypeError, ValueError):
        return None, "AGENT_STATE.md is missing or unavailable"
    finally:
        if descriptor is not None:
            with suppress(OSError):
                os.close(descriptor)


def _agent_state_structure_errors(text: str) -> list[str]:
    """Check only schema-3 current identity fields; values remain inert text."""
    headings = 0
    in_current_section = False
    fence_character = None
    fence_length = 0
    fields: dict[str, str] = {}
    invalid = False

    for line in text.splitlines():
        stripped = line.strip()
        fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if fence is not None:
            marker = fence.group(1)
            if fence_character is None:
                fence_character = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            continue
        if fence_character is not None or stripped.startswith(">"):
            continue
        if line == _STATE_CONTROL_HEADING:
            headings += 1
            in_current_section = True
            continue
        if in_current_section and re.match(r"^\s{0,3}#{1,6}\s", line):
            in_current_section = False
            continue
        if not in_current_section or not stripped:
            continue

        match = _STATE_KEY_RE.fullmatch(line)
        if match is None:
            invalid = True
            continue
        key, value = match.groups()
        if not value.strip() or key in fields:
            invalid = True
        fields[key] = value

    if (
        headings != 1
        or invalid
        or fields.get("schema_version") != "3"
        or _STATE_SHA_RE.fullmatch(fields.get("last_reconciled_main_sha", "")) is None
        or _STATE_SHA_RE.fullmatch(fields.get("last_reconciled_main_tree", "")) is None
    ):
        return ["AGENT_STATE.md has an invalid schema-3 current control section"]
    return []


def _agent_state_errors(root: Path) -> tuple[list[str], str | None]:
    raw, read_error = _read_agent_state(root)
    if read_error is not None:
        return [read_error], None
    if not raw:
        return ["AGENT_STATE.md is empty"], ""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ["AGENT_STATE.md is not valid UTF-8"], None
    return _agent_state_structure_errors(text), text


def _instruction_and_skill_errors(root: Path) -> list[str]:
    errors = []
    root_agents = root / "AGENTS.md"
    root_text = root_agents.read_text(encoding="utf-8")
    if len(root_text.encode("utf-8")) > 18_000:
        errors.append("root AGENTS.md exceeds reviewed compact instruction budget")
    if any(clause not in root_text for clause in _ROOT_REVIEW_ASSURANCE_CONTRACT):
        errors.append("root read-only review assurance contract is missing")
    protocol_text = (root / "docs/productionization/AGENT_AUDIT_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    productionization_agents_text = (root / "docs/productionization/AGENTS.md").read_text(
        encoding="utf-8"
    )
    if any(clause not in protocol_text for clause in _PROTOCOL_REVIEW_ASSURANCE_CONTRACT):
        errors.append("protocol read-only review assurance contract is missing")
    if _CONTEXT_POLICY_PATH.as_posix() not in root_text:
        errors.append("root context-management policy reference is missing")
    if _CONTEXT_POLICY_PATH.name not in productionization_agents_text:
        errors.append("productionization context-management policy reference is missing")
    if _CONTEXT_POLICY_PATH.name not in protocol_text:
        errors.append("audit protocol context-management policy reference is missing")
    try:
        context_info = os.lstat(root / _CONTEXT_POLICY_PATH)
        if not stat.S_ISREG(context_info.st_mode):
            errors.append("context-management policy must be a regular file")
        elif context_info.st_size > _CONTEXT_POLICY_MAX_BYTES:
            errors.append("context-management policy exceeds the 6 KiB limit")
    except (OSError, TypeError, ValueError):
        errors.append("context-management policy is missing or unavailable")
    for relative, text in (
        ("AGENTS.md", root_text),
        ("docs/productionization/AGENT_AUDIT_PROTOCOL.md", protocol_text),
    ):
        folded = text.casefold()
        if any(phrase in folded for phrase in _RETIRED_TWO_TURN_PHRASES):
            errors.append(f"retired two-turn admission phrase is forbidden: {relative}")
    active_policy_text = "\n".join(
        (
            root_text,
            protocol_text,
            productionization_agents_text,
            (root / "docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md").read_text(
                encoding="utf-8"
            ),
            (root / ".codex/config.toml").read_text(encoding="utf-8"),
            *(path.read_text(encoding="utf-8") for path in (root / ".agents/skills").glob("*/SKILL.md")),
        )
    )
    if "DEGRADED_MASTER_REVIEW" in active_policy_text:
        errors.append("retired degraded review fallback remains in active policy")
    for relative in _SCOPED_AGENT_PATHS:
        path = root / relative
        if not path.is_file():
            errors.append(f"missing scoped agent instructions: {relative}")
        if relative not in root_text:
            errors.append(f"root AGENTS.md does not route to scoped instructions: {relative}")
    for name in _SKILL_NAMES:
        relative = f".agents/skills/{name}/SKILL.md"
        path = root / relative
        if not path.is_file():
            errors.append(f"missing repo skill: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n") or f"name: {name}\n" not in text:
            errors.append(f"invalid skill metadata: {name}")
        if "description:" not in text.split("---", 2)[1]:
            errors.append(f"missing skill description: {name}")
        if name not in root_text:
            errors.append(f"root AGENTS.md does not advertise repo skill: {name}")
    for relative in _WRITER_LEASE_STATIC_SURFACES:
        if not (root / relative).is_file():
            errors.append(f"missing writer lease static surface: {relative}")
    if "`astra_canary`" not in root_text or "GPT-6 Astra production routes remain disabled" not in root_text:
        errors.append("root Astra canary policy is missing or activates GPT-6 production routing")
    watchlist = root / _WATCHLIST_PATH
    if not watchlist.is_file():
        errors.append("missing Codex feature adoption watchlist")
    else:
        text = watchlist.read_text(encoding="utf-8")
        for term in ("Codex Rules", "Permission Profiles", "Codex Memories", "OpenTelemetry", "plugin"):
            if term not in text:
                errors.append(f"Codex feature watchlist is missing decision: {term}")
    return errors


def configuration_errors(root: Path) -> list[str]:
    errors = []
    try:
        state_errors, state_text = _agent_state_errors(root)
        errors.extend(state_errors)
        config = _toml(root / ".codex/config.toml")
        if (config.get("model"), config.get("model_reasoning_effort")) != ("gpt-6.1-sol", "xhigh"):
            errors.append("Master route differs from reviewed policy")
        if (
            type(config.get("model_auto_compact_token_limit")) is not int
            or config["model_auto_compact_token_limit"] != 128_000
        ):
            errors.append("native model_auto_compact_token_limit must be the exact integer 128000")
        if (
            type(config.get("model_auto_compact_token_limit_scope")) is not str
            or config["model_auto_compact_token_limit_scope"] != "total"
        ):
            errors.append("native model_auto_compact_token_limit_scope must be exactly 'total'")
        if _contains_toml_key(config, "model_context_window"):
            errors.append("project model_context_window override is forbidden")
        if config.get("agents") != {"enabled": True, "max_concurrent_threads_per_session": 8}:
            errors.append("agent enablement/concurrency differs from reviewed policy")
        errors.extend(_watch_only_feature_errors(root, config))
        actual_paths = {path.name for path in (root / ".codex/agents").glob("*.toml")}
        expected_paths = {name.replace("_", "-") + ".toml" for name in _ROLES}
        if actual_paths != expected_paths:
            errors.append("named role file set differs from reviewed policy")
        for name, (model, effort, readonly) in _ROLES.items():
            role = _toml(root / ".codex/agents" / (name.replace("_", "-") + ".toml"))
            if any(
                _contains_toml_key(role, key)
                for key in (
                    "model_context_window",
                    "model_auto_compact_token_limit",
                    "model_auto_compact_token_limit_scope",
                )
            ):
                errors.append(f"{name} must not override model compaction or capacity")
            if (role.get("name"), role.get("model"), role.get("model_reasoning_effort")) != (name, model, effort):
                errors.append(f"invalid name/model/effort for {name}")
            if role.get("agents") != {"enabled": False}:
                errors.append(f"{name} must disable nested delegation")
            if "features" in role:
                errors.append(f"{name} must not declare role-level features or override project Apps")
            if readonly and role.get("sandbox_mode") != "read-only":
                errors.append(f"{name} must request read-only mode")
            if readonly and role.get("approval_policy") != "never":
                errors.append(f"{name} read-only approval policy intent must be never")
            mcp_servers = role.get("mcp_servers")
            if name == "external_spec_researcher":
                expected_mcp = {
                    "openaiDeveloperDocs": {
                        "url": _OPENAI_DOCS_MCP_URL,
                        "enabled_tools": _OPENAI_DOCS_MCP_TOOLS,
                    }
                }
                if mcp_servers != expected_mcp:
                    errors.append("external_spec_researcher OpenAI docs MCP configuration intent differs from reviewed policy")
            elif "mcp_servers" in role:
                errors.append(f"{name} must not declare role-level MCP configuration intent")
            instructions = role.get("developer_instructions", "")
            if type(instructions) is not str or any(
                clause not in instructions for clause in _COLLABORATION_INSTRUCTION_CONTRACT
            ):
                errors.append(f"{name} collaboration instruction contract is missing")
            if readonly and (
                type(instructions) is not str
                or _READ_ONLY_REVIEW_MARKER not in instructions
            ):
                errors.append(f"{name} read-only non-mutation contract is missing")
            if (
                readonly
                and type(instructions) is str
                and _RETIRED_ROLE_ADMISSION_MARKER.casefold() in instructions.casefold()
            ):
                errors.append(f"{name} retired native admission marker is forbidden")
            if name == "normal_implementer" and (
                type(instructions) is not str or "normal/high/critical" not in instructions
            ):
                errors.append("initial implementer must inherit normal/high/critical safety class")
            if name == "astra_canary" and (
                type(instructions) is not str
                or not all(term in instructions for term in ("shadow-only", "historical", "active candidate"))
            ):
                errors.append("astra_canary instructions must remain shadow-only historical evaluation")
        errors.extend(_hook_errors(root))
        errors.extend(_instruction_and_skill_errors(root))
        for filename in ("AGENT_AUDIT_PROTOCOL.md", "PR_IMPLEMENTATION_SPEC_TEMPLATE.md"):
            if "sol_high_sol_high" not in (root / "docs/productionization" / filename).read_text():
                errors.append(f"missing approved implementation-only route in {filename}")
        root_agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
        for name, text in (("AGENTS.md", root_agents_text), ("AGENT_STATE.md", state_text)):
            if text is not None and "strongest available compatible" in text:
                errors.append(f"generic fallback contradicts named-role policy: {name}")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(f"configuration unavailable/invalid: {exc}")
    return errors


def gate_errors(record: object) -> list[str]:
    """Validate an offline merge-candidate record; PASS is not permission to merge."""
    if type(record) is not dict or set(record) != _GATE_FIELDS:
        return ["missing or unknown gate fields; insufficient_evidence"]
    errors = []
    if any(type(record[key]) is not str or not record[key] or record[key] != record[key].strip()
           for key in _TEXT_FIELDS):
        return ["invalid gate identity fields"]
    if any(type(record[key]) is not str or re.fullmatch(r"[0-9a-f]{40}", record[key]) is None
           for key in _HASH_FIELDS):
        errors.append("invalid full commit/tree SHA")
    if type(record["collaboration_controls_visible"]) is not bool:
        errors.append("collaboration_controls_visible must be an exact boolean")
    if type(record["collaboration_observation_complete"]) is not bool:
        errors.append("collaboration_observation_complete must be an exact boolean")
    elif record["collaboration_observation_complete"] is not True:
        errors.append("collaboration observation is incomplete or untrusted")
    if type(record["non_master_collaboration_invoked"]) is not bool:
        errors.append("non_master_collaboration_invoked must be an exact boolean")
    elif record["non_master_collaboration_invoked"] is not False:
        errors.append("non-master collaboration-control invocation is a blocking policy violation")
    if record["delegation_control_mode"] != "behavioral_policy":
        errors.append(
            "delegation_control_mode must be exactly behavioral_policy; "
            "the offline validator cannot authenticate host caller identity"
        )
    if any(record[key] is not True for key in _TRUE_FIELDS):
        errors.append("required evidence is not verified")
    if any(record[key] is not False for key in _FALSE_FIELDS):
        errors.append("conflicting telemetry or blocking findings")
    operations = record["authorized_operations"]
    if type(operations) is not list or any(type(item) is not str for item in operations):
        errors.append("invalid authorization scope")
    elif record["operation"] != "merge" or "merge" not in operations:
        errors.append("operation is not explicitly authorized")
    if record["session_id"] != record["authorized_session_id"]:
        errors.append("historical authorization is not current-session authority")
    if record["pr_id"] not in _ORDER or record["stop_after"] not in _ORDER:
        errors.append("unknown roadmap ID")
    elif _ORDER.index(record["pr_id"]) > _ORDER.index(record["stop_after"]):
        errors.append("stop_after would be crossed")
    if type(record["active_writers"]) is not int or record["active_writers"] != 0:
        errors.append("freeze candidate and stop writers before the merge gate")
    for actual, expected in (("review_head_sha", "head_sha"), ("review_base_sha", "base_sha"),
                             ("ci_head_sha", "head_sha"), ("ci_checkout_tree", "source_tree")):
        if record[actual] != record[expected]:
            errors.append(f"stale or mismatched {actual}")
    if record["implementer_context"] == record["reviewer_context"]:
        errors.append("review is not independent")
    return errors


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate evidence field")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--gate", type=Path, help="optional offline evidence JSON; never executes a merge")
    args = parser.parse_args()
    errors = configuration_errors(args.root.resolve())
    if args.gate is not None:
        try:
            raw = args.gate.read_bytes()
            if len(raw) > 65_536:
                raise ValueError("gate evidence exceeds 64 KiB")
            errors.extend(gate_errors(json.loads(raw, object_pairs_hook=_unique_object)))
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append(f"invalid gate evidence: {exc}")
    for error in errors:
        print(error)
    if not errors:
        print("PASS: offline consistency only; runtime loading and authorization require independent evidence")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
