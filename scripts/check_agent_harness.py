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
from datetime import datetime
from pathlib import Path

_ROLES = {
    "normal_implementer": ("gpt-5.6-luna", "max", False),
    "high_implementer": ("gpt-5.6-sol", "high", False),
    "critical_implementer": ("gpt-5.6-sol", "xhigh", False),
    "reviewer_high": ("gpt-5.6-sol", "high", True),
    "reviewer_xhigh": ("gpt-5.6-sol", "xhigh", True),
    "code_explorer": ("gpt-5.6-luna", "max", True),
    "test_auditor": ("gpt-5.6-luna", "max", True),
    "boundary_reviewer": ("gpt-5.6-sol", "high", True),
    "external_spec_researcher": ("gpt-5.6-luna", "max", True),
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
_READ_ONLY_ADMISSION_MARKER = (
    "Native read-only admission is governed by root AGENTS.md and must complete before "
    "substantive work or any tool call."
)
_ROOT_NATIVE_ADMISSION_CONTRACT = (
    "fresh host-enforced read-only parent",
    "live parent overrides are controlling",
    "post-spawn host-origin evidence",
    "effective sandbox/profile/approval tuple",
    "complete tool inventory",
    "discard the lane",
    "cannot authenticate",
)
_TWO_TURN_NATIVE_ADMISSION_CONTRACT = (
    "first child turn is admission-only",
    "receive no substantive task",
    "make no tool call",
    "cannot self-approve",
    "follow-up substantive task",
    "interrupt and discard the lane",
    "child/model prose",
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
_GITHUB_BOUNDARY_FIELDS = {
    "schema_version", "pr_number", "pr_author_login", "head_sha", "captured_at",
    "open_main_prs_page_size", "open_main_prs_page_count", "open_main_prs_total_count",
    "open_main_prs_pagination_complete", "open_main_prs_limit_exhausted",
    "open_main_prs_base_ref", "open_main_prs_probe_pr_number",
    "review_actor_id", "review_actor_login", "review_actor_type", "initial_head_sha",
    "initial_review_id", "initial_review_actor_id", "initial_review_commit_sha",
    "initial_review_state", "initial_review_submitted_at", "moved_head_sha",
    "moved_head_review_id", "moved_head_review_actor_id", "moved_head_review_commit_sha",
    "moved_head_review_state", "moved_head_review_submitted_at",
    "negative_probe_dismissed_review_id", "negative_probe_head_sha",
    "negative_probe_review_decision", "negative_probe_merge_status",
    "negative_probe_merge_eligible", "final_review_id", "final_review_actor_id",
    "final_review_commit_sha", "final_review_state", "final_review_submitted_at",
    "positive_probe_head_sha", "positive_probe_review_decision", "positive_probe_merge_status",
    "positive_probe_merge_eligible", "reviewer_is_last_pusher", "reviewer_is_last_pusher_basis",
    "controlling_review_head_sha", "controlling_review_approved", "required_checks_head_sha",
    "required_checks_pass", "main_ruleset_id", "main_ruleset_preimage_updated_at",
    "main_ruleset_preimage_captured_at", "main_ruleset_postimage_updated_at",
    "main_ruleset_preimage_digest",
    "main_ruleset_postimage_digest", "main_ruleset_unchanged_preimage_digest",
    "main_ruleset_unchanged_postimage_digest", "main_ruleset_preimage_etag_digest",
    "main_ruleset_postimage_etag_digest", "main_ruleset_active", "main_ruleset_bypass_actor_count",
    "main_ruleset_required_statuses_strict", "main_ruleset_required_approvals",
    "main_ruleset_dismiss_stale_reviews", "main_ruleset_require_last_push_approval",
    "main_ruleset_require_thread_resolution", "main_ruleset_require_unattributed_approval",
    "auto_review_ruleset_id", "auto_review_ruleset_updated_at", "auto_review_ruleset_digest",
    "auto_review_ruleset_active", "auto_review_ruleset_bypass_actor_count", "auto_review_on_push",
    "auto_review_custom_instructions_enabled", "auto_review_mcp_enabled", "auto_review_effort",
    "auto_review_approvals_enabled", "reviews_page_size", "reviews_page_count",
    "reviews_total_count", "reviews_pagination_complete", "reviews_limit_exhausted",
}
_GITHUB_BOUNDARY_SHA_FIELDS = (
    "head_sha", "initial_head_sha", "initial_review_commit_sha", "moved_head_sha",
    "moved_head_review_commit_sha", "negative_probe_head_sha", "final_review_commit_sha",
    "positive_probe_head_sha", "controlling_review_head_sha", "required_checks_head_sha",
)
_GITHUB_BOUNDARY_DIGEST_FIELDS = (
    "main_ruleset_preimage_digest", "main_ruleset_postimage_digest",
    "main_ruleset_unchanged_preimage_digest", "main_ruleset_unchanged_postimage_digest",
    "main_ruleset_preimage_etag_digest", "main_ruleset_postimage_etag_digest",
    "auto_review_ruleset_digest",
)
_GITHUB_BOUNDARY_TIME_FIELDS = (
    "captured_at", "initial_review_submitted_at", "moved_head_review_submitted_at",
    "final_review_submitted_at", "main_ruleset_preimage_updated_at",
    "main_ruleset_preimage_captured_at", "main_ruleset_postimage_updated_at",
    "auto_review_ruleset_updated_at",
)
_GITHUB_BOUNDARY_POSITIVE_IDS = (
    "pr_number", "open_main_prs_probe_pr_number", "review_actor_id",
    "initial_review_id", "initial_review_actor_id",
    "moved_head_review_id", "moved_head_review_actor_id", "negative_probe_dismissed_review_id",
    "final_review_id", "final_review_actor_id", "main_ruleset_id", "auto_review_ruleset_id",
)
_COPILOT_REVIEW_ACTOR_ID = 175_728_472
_GUARD_HOOKS = {"SessionStart": "session-start", "Stop": "stop"}
_TELEMETRY_HOOKS = {"SubagentStart", "SubagentStop", "PostCompact"}
_TELEMETRY_CLEANUP_HOOK = "SessionEnd"
_PRETOOL_HOOK = "PreToolUse"
_OPENAI_DOCS_MCP_URL = "https://developers.openai.com/mcp"
_OPENAI_DOCS_MCP_TOOLS = ["fetch_openai_doc", "search_openai_docs"]
_WATCHLIST_PATH = "docs/productionization/CODEX_FEATURE_WATCHLIST.md"


def _toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise ValueError("TOML parser unavailable; use Python 3.11+ or locked dev") from exc
    return tomllib.loads(path.read_text(encoding="utf-8"))


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
    if isinstance(features, dict) and features.get("memories") not in (None, False):
        errors.append("Codex Memories are watch-only for this auditable repository harness")
    if "memories" in config:
        errors.append("Codex Memories configuration is watch-only for this repository")
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


def _instruction_and_skill_errors(root: Path) -> list[str]:
    errors = []
    root_agents = root / "AGENTS.md"
    root_text = root_agents.read_text(encoding="utf-8")
    if len(root_text.encode("utf-8")) > 18_000:
        errors.append("root AGENTS.md exceeds reviewed compact instruction budget")
    if any(clause not in root_text for clause in _ROOT_NATIVE_ADMISSION_CONTRACT):
        errors.append("root native read-only admission contract is missing")
    if any(clause not in root_text for clause in _TWO_TURN_NATIVE_ADMISSION_CONTRACT):
        errors.append("root two-turn native admission contract is missing")
    protocol_text = (root / "docs/productionization/AGENT_AUDIT_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    if any(clause not in protocol_text for clause in _TWO_TURN_NATIVE_ADMISSION_CONTRACT):
        errors.append("protocol two-turn native admission contract is missing")
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
    if "`astra_canary`" not in root_text or "GPT-6 production routes remain disabled" not in root_text:
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
        config = _toml(root / ".codex/config.toml")
        if (config.get("model"), config.get("model_reasoning_effort")) != ("gpt-5.6-sol", "xhigh"):
            errors.append("Master route differs from reviewed policy")
        if config.get("agents") != {"enabled": True, "max_concurrent_threads_per_session": 6}:
            errors.append("agent enablement/concurrency differs from reviewed policy")
        errors.extend(_watch_only_feature_errors(root, config))
        actual_paths = {path.name for path in (root / ".codex/agents").glob("*.toml")}
        expected_paths = {name.replace("_", "-") + ".toml" for name in _ROLES}
        if actual_paths != expected_paths:
            errors.append("named role file set differs from reviewed policy")
        for name, (model, effort, readonly) in _ROLES.items():
            role = _toml(root / ".codex/agents" / (name.replace("_", "-") + ".toml"))
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
                or _READ_ONLY_ADMISSION_MARKER not in instructions
            ):
                errors.append(f"{name} native read-only admission intent is missing")
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
        for path in (root / "AGENTS.md", root / "docs/productionization/AGENT_STATE.md"):
            if "strongest available compatible" in path.read_text():
                errors.append(f"generic fallback contradicts named-role policy: {path.name}")
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


def _parse_utc_timestamp(value: object) -> datetime | None:
    if type(value) is not str or re.fullmatch(
        r"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
        r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?Z",
        value,
    ) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.utcoffset().total_seconds() == 0 else None


def github_review_boundary_errors(raw: bytes) -> list[str]:
    """Check sanitized supplied facts; never authenticate GitHub or authorize merge."""
    if type(raw) is not bytes or not raw or len(raw) > 65_536:
        return ["invalid GitHub review-boundary evidence; insufficient_evidence"]
    try:
        record = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        return ["invalid GitHub review-boundary evidence; insufficient_evidence"]
    if type(record) is not dict or set(record) != _GITHUB_BOUNDARY_FIELDS:
        return ["missing or unknown GitHub review-boundary fields; insufficient_evidence"]
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if raw != canonical:
        return ["non-canonical GitHub review-boundary evidence; insufficient_evidence"]

    errors = []
    if record["schema_version"] != 1 or type(record["schema_version"]) is not int:
        errors.append("invalid GitHub review-boundary schema version")
    if any(type(record[field]) is not int or record[field] <= 0
           for field in _GITHUB_BOUNDARY_POSITIVE_IDS):
        errors.append("invalid GitHub identity or object ID")
    if any(type(record[field]) is not str or re.fullmatch(r"[0-9a-f]{40}", record[field]) is None
           for field in _GITHUB_BOUNDARY_SHA_FIELDS):
        errors.append("invalid GitHub review-boundary commit SHA")
    if any(type(record[field]) is not str or re.fullmatch(r"[0-9a-f]{64}", record[field]) is None
           for field in _GITHUB_BOUNDARY_DIGEST_FIELDS):
        errors.append("invalid sanitized ruleset projection digest")
    parsed_times = {field: _parse_utc_timestamp(record[field]) for field in _GITHUB_BOUNDARY_TIME_FIELDS}
    if any(value is None for value in parsed_times.values()):
        errors.append("invalid GitHub review-boundary UTC timestamp")
    else:
        captured = parsed_times["captured_at"]
        if not (
            parsed_times["auto_review_ruleset_updated_at"]
            < parsed_times["initial_review_submitted_at"]
            < parsed_times["main_ruleset_preimage_captured_at"]
            < parsed_times["main_ruleset_postimage_updated_at"]
            < parsed_times["moved_head_review_submitted_at"]
            < parsed_times["final_review_submitted_at"]
            <= captured
        ):
            errors.append("GitHub review/ruleset transition provenance is not strictly ordered")
        if parsed_times["main_ruleset_preimage_updated_at"] > parsed_times["main_ruleset_preimage_captured_at"]:
            errors.append("main ruleset preimage capture precedes its source update")

    if (
        type(record["open_main_prs_page_size"]) is not int
        or record["open_main_prs_page_size"] != 100
        or type(record["open_main_prs_page_count"]) is not int
        or not 1 <= record["open_main_prs_page_count"] <= 10
        or type(record["open_main_prs_total_count"]) is not int
        or record["open_main_prs_total_count"] != 1
        or record["open_main_prs_pagination_complete"] is not True
        or record["open_main_prs_limit_exhausted"] is not False
        or record["open_main_prs_base_ref"] != "main"
        or record["open_main_prs_probe_pr_number"] != record["pr_number"]
    ):
        errors.append("open main-targeting PR reconciliation is incomplete or ambiguous")

    if (
        type(record["pr_author_login"]) is not str
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", record["pr_author_login"]) is None
        or record["pr_author_login"] == record["review_actor_login"]
    ):
        errors.append("invalid or non-independent PR author identity")
    if (
        record["review_actor_login"] != "copilot-pull-request-reviewer[bot]"
        or record["review_actor_type"] != "Bot"
        or record["review_actor_id"] != _COPILOT_REVIEW_ACTOR_ID
    ):
        errors.append("invalid formal review actor identity")
    if any(
        record[field] != record["review_actor_id"]
        for field in ("initial_review_actor_id", "moved_head_review_actor_id", "final_review_actor_id")
    ):
        errors.append("review actor ID changed across probe reviews")

    head = record["head_sha"]
    if (
        record["initial_head_sha"] == head
        or record["initial_review_commit_sha"] != record["initial_head_sha"]
        or any(
            record[field] != head
            for field in (
                "moved_head_sha", "moved_head_review_commit_sha", "negative_probe_head_sha",
                "final_review_commit_sha", "positive_probe_head_sha", "controlling_review_head_sha",
                "required_checks_head_sha",
            )
        )
    ):
        errors.append("stale or mismatched GitHub review-boundary head")
    review_ids = (
        record["initial_review_id"], record["moved_head_review_id"], record["final_review_id"],
    )
    if len(set(review_ids)) != len(review_ids):
        errors.append("probe review IDs are not distinct")
    if (
        record["initial_review_state"] != "DISMISSED"
        or record["moved_head_review_state"] != "DISMISSED"
        or record["negative_probe_dismissed_review_id"] != record["moved_head_review_id"]
        or record["final_review_state"] != "APPROVED"
    ):
        errors.append("invalid stale or final formal review state")
    if (
        record["negative_probe_review_decision"] != "REVIEW_REQUIRED"
        or record["negative_probe_merge_status"] != "BLOCKED"
        or record["negative_probe_merge_eligible"] is not False
        or record["positive_probe_review_decision"] != "APPROVED"
        or record["positive_probe_merge_status"] != "CLEAN"
        or record["positive_probe_merge_eligible"] is not True
    ):
        errors.append("negative/positive GitHub enforcement probe is incomplete")
    if (
        record["reviewer_is_last_pusher"] is not False
        or record["reviewer_is_last_pusher_basis"] != "github_ruleset_evaluation"
    ):
        errors.append("reviewer/pusher distinction is not enforcement-derived")
    if record["controlling_review_approved"] is not True or record["required_checks_pass"] is not True:
        errors.append("substantive review or required checks are not exact-head PASS")

    if record["main_ruleset_id"] != 20_780_950 or record["auto_review_ruleset_id"] != 23_141_241:
        errors.append("unexpected GitHub ruleset identity")
    main_expected = {
        "main_ruleset_active": True,
        "main_ruleset_bypass_actor_count": 0,
        "main_ruleset_required_statuses_strict": True,
        "main_ruleset_required_approvals": 1,
        "main_ruleset_dismiss_stale_reviews": True,
        "main_ruleset_require_last_push_approval": True,
        "main_ruleset_require_thread_resolution": True,
        "main_ruleset_require_unattributed_approval": True,
    }
    auto_expected = {
        "auto_review_ruleset_active": True,
        "auto_review_ruleset_bypass_actor_count": 0,
        "auto_review_on_push": True,
        "auto_review_custom_instructions_enabled": False,
        "auto_review_mcp_enabled": False,
        "auto_review_effort": "Balanced",
        "auto_review_approvals_enabled": True,
    }
    if any(type(record[field]) is not type(expected) or record[field] != expected
           for expected_map in (main_expected, auto_expected)
           for field, expected in expected_map.items()):
        errors.append("GitHub ruleset or automatic-review policy differs")
    if record["main_ruleset_preimage_digest"] == record["main_ruleset_postimage_digest"]:
        errors.append("main ruleset transition projection did not change")
    if (
        record["main_ruleset_unchanged_preimage_digest"]
        != record["main_ruleset_unchanged_postimage_digest"]
    ):
        errors.append("main ruleset unchanged projection drifted")
    if record["main_ruleset_preimage_etag_digest"] == record["main_ruleset_postimage_etag_digest"]:
        errors.append("main ruleset sanitized ETag evidence did not change")

    if (
        type(record["reviews_page_size"]) is not int
        or record["reviews_page_size"] != 100
        or type(record["reviews_page_count"]) is not int
        or not 1 <= record["reviews_page_count"] <= 10
        or type(record["reviews_total_count"]) is not int
        or not 3 <= record["reviews_total_count"] <= 1_000
        or record["reviews_total_count"] > record["reviews_page_count"] * 100
        or record["reviews_pagination_complete"] is not True
        or record["reviews_limit_exhausted"] is not False
    ):
        errors.append("review pagination is incomplete, invalid, or exhausted")
    return errors


def github_review_boundary_file_errors(path: Path) -> list[str]:
    """Read at most 64 KiB from one regular no-follow file, then validate it offline."""
    required_flags = ("O_NOFOLLOW", "O_NONBLOCK")
    if not isinstance(path, Path) or any(not hasattr(os, name) for name in required_flags):
        return ["invalid GitHub review-boundary evidence; insufficient_evidence"]
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("not a regular evidence file")
            chunks = []
            remaining = 65_537
            while remaining:
                chunk = os.read(descriptor, min(8_192, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > 65_536:
                raise ValueError("evidence limit exceeded")
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        return ["invalid GitHub review-boundary evidence; insufficient_evidence"]
    return github_review_boundary_errors(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--gate", type=Path, help="optional offline evidence JSON; never executes a merge")
    parser.add_argument(
        "--github-review-boundary",
        type=Path,
        help="optional sanitized offline GitHub identity/status evidence; never authenticates GitHub",
    )
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
    if args.github_review_boundary is not None:
        errors.extend(github_review_boundary_file_errors(args.github_review_boundary))
    for error in errors:
        print(error)
    if not errors:
        print("PASS: offline consistency only; runtime loading and authorization require independent evidence")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
