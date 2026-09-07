"""Best-effort Codex lifecycle telemetry bridge.

Durable telemetry remains narrow and identifier-free. Session/agent identifiers are
used only through SHA-256-derived names in ephemeral Git-common-dir runtime state so
SubagentStart/Stop can measure active concurrency and duration. SessionEnd removes the
session's ephemeral state. Telemetry failures never steer or block an agentic turn.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

_SUPPORTED = {"SubagentStart", "SubagentStop", "PostCompact", "SessionEnd"}
_RUNTIME_DIR = "runtime"


def _telemetry_module() -> ModuleType:
    path = Path(__file__).resolve().with_name("harness_telemetry.py")
    spec = importlib.util.spec_from_file_location("codex_harness_telemetry", path)
    if spec is None or spec.loader is None:
        raise OSError("cannot load harness telemetry module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo_root(cwd: object) -> Path:
    base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
    result = subprocess.check_output(
        ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    return Path(result)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _runtime_root(repo: Path, telemetry: ModuleType) -> Path:
    return telemetry.telemetry_path(repo).parent / _RUNTIME_DIR


def _session_dir(repo: Path, telemetry: ModuleType, session_id: object) -> Path | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    return _runtime_root(repo, telemetry) / _digest(session_id)


def _agent_file(session_dir: Path | None, agent_id: object) -> Path | None:
    if session_dir is None or not isinstance(agent_id, str) or not agent_id:
        return None
    return session_dir / f"{_digest(agent_id)}.json"


def _basic_agent_payload(event: dict, *, started: bool) -> dict | None:
    role = event.get("agent_type")
    if not isinstance(role, str) or not role.strip():
        return None
    payload: dict[str, object] = {
        "event": "agent_spawn" if started else "agent_stop",
        "role": role,
    }
    model = event.get("model")
    if isinstance(model, str) and model.strip():
        payload["model"] = model
    return payload


def _active_agents(session_dir: Path | None) -> int | None:
    if session_dir is None or not session_dir.is_dir():
        return None
    return sum(1 for path in session_dir.iterdir() if path.is_file() and path.suffix == ".json")


def _start_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, started=True)
    if payload is None:
        return None
    session_dir = _session_dir(repo, telemetry, event.get("session_id"))
    state_file = _agent_file(session_dir, event.get("agent_id"))
    if state_file is None or session_dir is None:
        return payload
    session_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, object] = {
        "started_at_ms": time.time_ns() // 1_000_000,
        "role": payload["role"],
    }
    if "model" in payload:
        state["model"] = payload["model"]
    state_file.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    active = _active_agents(session_dir)
    if active is not None:
        payload["active_agents"] = active
    return payload


def _stop_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, started=False)
    if payload is None:
        return None
    session_dir = _session_dir(repo, telemetry, event.get("session_id"))
    state_file = _agent_file(session_dir, event.get("agent_id"))
    started_at_ms: int | None = None
    if state_file is not None and state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            candidate = state.get("started_at_ms") if type(state) is dict else None
            if type(candidate) is int and candidate >= 0:
                started_at_ms = candidate
        finally:
            state_file.unlink(missing_ok=True)
    active = _active_agents(session_dir)
    if active is not None:
        payload["active_agents"] = active
    if started_at_ms is not None:
        payload["duration_ms"] = max(0, time.time_ns() // 1_000_000 - started_at_ms)
    if session_dir is not None and session_dir.is_dir() and not any(session_dir.iterdir()):
        session_dir.rmdir()
    return payload


def _cleanup_session(event: dict, repo: Path, telemetry: ModuleType) -> None:
    session_dir = _session_dir(repo, telemetry, event.get("session_id"))
    if session_dir is not None and session_dir.is_dir():
        shutil.rmtree(session_dir)


def _payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    name = event.get("hook_event_name")
    if name not in _SUPPORTED:
        return None
    if name == "SubagentStart":
        return _start_payload(event, repo, telemetry)
    if name == "SubagentStop":
        return _stop_payload(event, repo, telemetry)
    if name == "SessionEnd":
        _cleanup_session(event, repo, telemetry)
        return None
    trigger = event.get("trigger")
    if trigger not in {"manual", "auto"}:
        return None
    return {"event": "context_compaction", "trigger": trigger}


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
        if type(event) is not dict:
            return 0
        telemetry = _telemetry_module()
        repo = _repo_root(event.get("cwd"))
        payload = _payload(event, repo, telemetry)
        if payload is not None:
            telemetry.record(repo, payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
        # Telemetry is observability, never an execution or merge authority.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
