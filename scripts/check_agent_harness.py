"""Offline harness consistency and merge-candidate predicates; no execution authority.

A passing predicate checks supplied facts, not their authenticity. The Master must
obtain authorization, role loading, reviews and CI from independent trusted evidence.
This program never spawns an agent, writes a file, contacts GitHub, or merges a PR.
"""

from __future__ import annotations

import argparse
import json
import re
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
_SKILL_NAMES = (
    "productionization-preflight",
    "jit-scope-contract",
    "tdd-red-green-evidence",
    "exact-head-review",
    "merge-gate",
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
                "authorized_operations", "active_writers"}
_HOOK_EVENTS = {"SessionStart": "session-start", "Stop": "stop"}
_OPENAI_DOCS_MCP_URL = "https://developers.openai.com/mcp"


def _toml(path: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise ValueError("TOML parser unavailable; use Python 3.11+ or locked dev") from exc
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _hook_errors(root: Path) -> list[str]:
    errors = []
    hook_path = root / ".codex/hooks.json"
    guard_path = root / "scripts/codex_hook_guard.py"
    if not guard_path.is_file():
        errors.append("missing lightweight Codex hook guard")
    hooks = json.loads(hook_path.read_text(encoding="utf-8"))
    event_map = hooks.get("hooks") if isinstance(hooks, dict) else None
    if not isinstance(event_map, dict) or set(event_map) != set(_HOOK_EVENTS):
        return [*errors, "project hooks must contain only SessionStart and Stop v1 events"]
    for event, mode in _HOOK_EVENTS.items():
        entries = event_map.get(event)
        if not isinstance(entries, list) or len(entries) != 1:
            errors.append(f"{event} must have exactly one project hook entry")
            continue
        entry = entries[0]
        handlers = entry.get("hooks") if isinstance(entry, dict) else None
        if not isinstance(handlers, list) or len(handlers) != 1:
            errors.append(f"{event} must have exactly one command handler")
            continue
        handler = handlers[0]
        command = handler.get("command") if isinstance(handler, dict) else None
        command_windows = handler.get("command_windows") if isinstance(handler, dict) else None
        if handler.get("type") != "command" or handler.get("async") is not False:
            errors.append(f"{event} hook must be a synchronous command")
        if handler.get("timeout_sec") != 15:
            errors.append(f"{event} hook timeout differs from reviewed policy")
        if not isinstance(command, str) or "codex_hook_guard.py" not in command or mode not in command:
            errors.append(f"{event} Unix hook command differs from reviewed policy")
        if (
            not isinstance(command_windows, str)
            or "codex_hook_guard.py" not in command_windows
            or mode not in command_windows
        ):
            errors.append(f"{event} Windows hook command differs from reviewed policy")
    return errors


def _instruction_and_skill_errors(root: Path) -> list[str]:
    errors = []
    root_agents = root / "AGENTS.md"
    root_text = root_agents.read_text(encoding="utf-8")
    if len(root_text.encode("utf-8")) > 18_000:
        errors.append("root AGENTS.md exceeds reviewed compact instruction budget")
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
    if "`astra_canary`" not in root_text or "GPT-6 production routes remain disabled" not in root_text:
        errors.append("root Astra canary policy is missing or activates GPT-6 production routing")
    return errors


def configuration_errors(root: Path) -> list[str]:
    errors = []
    try:
        config = _toml(root / ".codex/config.toml")
        if (config.get("model"), config.get("model_reasoning_effort")) != ("gpt-5.6-sol", "xhigh"):
            errors.append("Master route differs from reviewed policy")
        if config.get("agents") != {"enabled": True, "max_concurrent_threads_per_session": 6}:
            errors.append("agent enablement/concurrency differs from reviewed policy")
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
            if readonly and role.get("sandbox_mode") != "read-only":
                errors.append(f"{name} must request read-only mode")
            mcp_servers = role.get("mcp_servers")
            if name == "external_spec_researcher":
                expected_mcp = {"openaiDeveloperDocs": {"url": _OPENAI_DOCS_MCP_URL}}
                if mcp_servers != expected_mcp:
                    errors.append("external_spec_researcher OpenAI docs MCP differs from reviewed policy")
            elif mcp_servers:
                errors.append(f"{name} must not receive external MCP servers")
            instructions = role.get("developer_instructions", "")
            if name == "normal_implementer" and "normal/high/critical" not in instructions:
                errors.append("initial implementer must inherit normal/high/critical safety class")
            if name == "astra_canary" and not all(term in instructions for term in ("shadow-only", "historical", "active candidate")):
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
        return ["missing or unknown gate fields"]
    errors = []
    if any(type(record[key]) is not str or not record[key] or record[key] != record[key].strip()
           for key in _TEXT_FIELDS):
        return ["invalid gate identity fields"]
    if any(type(record[key]) is not str or re.fullmatch(r"[0-9a-f]{40}", record[key]) is None
           for key in _HASH_FIELDS):
        errors.append("invalid full commit/tree SHA")
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
