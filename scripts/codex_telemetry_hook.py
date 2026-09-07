"""Best-effort Codex lifecycle telemetry bridge.

This hook records only narrow, documented lifecycle metadata into the existing
Git-common-dir telemetry sink. It is advisory and deliberately fail-open: a
telemetry write failure must not steer or block an agentic turn.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import harness_telemetry

_SUPPORTED = {"SubagentStart", "SubagentStop", "PostCompact"}


def _repo_root(cwd: object) -> Path:
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    result = subprocess.check_output(
        ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    return Path(result)


def _payload(event: dict) -> dict | None:
    name = event.get("hook_event_name")
    if name not in _SUPPORTED:
        return None
    if name in {"SubagentStart", "SubagentStop"}:
        role = event.get("agent_type")
        if not isinstance(role, str) or not role.strip():
            return None
        payload: dict[str, object] = {
            "event": "agent_spawn" if name == "SubagentStart" else "agent_stop",
            "role": role,
        }
        model = event.get("model")
        if isinstance(model, str) and model.strip():
            payload["model"] = model
        return payload
    trigger = event.get("trigger")
    if trigger not in {"manual", "auto"}:
        return None
    return {"event": "context_compaction", "trigger": trigger}


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if type(event) is not dict:
            return 0
        payload = _payload(event)
        if payload is None:
            return 0
        harness_telemetry.record(_repo_root(event.get("cwd")), payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
        # Telemetry is observability, never an execution or merge authority.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
