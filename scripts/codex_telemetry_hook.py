"""Best-effort bounded Codex lifecycle telemetry bridge.

Hooks project only approved lifecycle labels and timing. They never retain
request usage, prompts, transcripts, or raw session and agent identifiers.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

_SUPPORTED = {"SubagentStart", "SubagentStop", "PostCompact", "SessionEnd"}
_RUNTIME_DIR = "runtime"
_MAX_HOOK_EVENT_BYTES = 65_536
_MAX_SCRATCH_BYTES = 4_096
_MAX_SESSION_AGENTS = 64
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _telemetry_module() -> ModuleType:
    path = Path(__file__).resolve().with_name("harness_telemetry.py")
    spec = importlib.util.spec_from_file_location("codex_harness_telemetry", path)
    if spec is None or spec.loader is None:
        raise OSError("cannot load harness telemetry module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo_root(cwd: object, telemetry: ModuleType) -> Path:
    base = (
        Path.cwd()
        if type(cwd) is not str or not cwd or len(cwd) > 4_096
        else Path(cwd)
    )
    try:
        result = subprocess.check_output(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            env=telemetry._clean_git_environment(),
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("hook repository could not be resolved") from exc
    if not result:
        raise ValueError("hook repository could not be resolved")
    return Path(result)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_identifier(value: object) -> bool:
    if type(value) is not str or not value or len(value) > 128:
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= 128


@contextmanager
def _session_transaction(
    repo: Path, telemetry: ModuleType, session_id: object, *, create: bool = False,
):
    if not _valid_identifier(session_id):
        yield None
        return
    session_ref = _digest(session_id)
    with telemetry._metadata_handle(repo, create=create) as metadata:
        if metadata is None:
            yield None
            return
        with telemetry._child_directory(metadata, _RUNTIME_DIR, create=create) as runtime:
            if runtime is None:
                yield None
                return
            # The lock outlives removal/recreation of the session directory it protects.
            with (
                telemetry._entry_lock(runtime, f".{session_ref}.lock"),
                telemetry._child_directory(runtime, session_ref, create=create) as session,
            ):
                yield session


def _agent_name(agent_id: object) -> str | None:
    return f"{_digest(agent_id)}.json" if _valid_identifier(agent_id) else None


def _basic_agent_payload(
    event: dict,
    telemetry: ModuleType,
    *,
    started: bool,
) -> dict | None:
    role = event.get("agent_type")
    if type(role) is not str:
        return None
    payload: dict[str, object] = {
        "event": "agent_spawn" if started else "agent_stop",
        "role": role,
    }
    model = event.get("model")
    if model is not None:
        if type(model) is not str:
            return None
        payload["model"] = model
    try:
        return telemetry._validate(payload)
    except ValueError:
        return None


def _read_state(session, name: str, telemetry: ModuleType) -> tuple[dict, os.stat_result] | None:
    with telemetry._regular_handle(session, name, mutable=True) as fd:
        if fd is None:
            return None
        info = os.fstat(fd)
        if info.st_size > _MAX_SCRATCH_BYTES:
            raise ValueError("scratch state exceeds the reviewed byte limit")
        observations = telemetry._observations_module()
        raw = telemetry._read_fd(fd, max_bytes=_MAX_SCRATCH_BYTES)
        state = observations.decode_json(raw, max_bytes=_MAX_SCRATCH_BYTES)
        keys = telemetry._safe_keys(
            state,
            {"started_at_ms", "role", "model"},
            {"started_at_ms", "role"},
            label="scratch state",
        )
        assert type(state) is dict
        started = state["started_at_ms"]
        if type(started) is not int or not 0 <= started <= telemetry.MAX_SIGNED_INT:
            raise ValueError("scratch timestamp is invalid")
        validated: dict[str, object] = {"started_at_ms": started}
        record: dict[str, object] = {"event": "agent_spawn", "role": state["role"]}
        if "model" in keys:
            record["model"] = state["model"]
        safe_record = telemetry._validate(record)
        validated["role"] = safe_record["role"]
        if "model" in safe_record:
            validated["model"] = safe_record["model"]
        session.verify_file(name, info, fd=fd, mutable=True, expected_size=len(raw))
        return validated, info


def _write_state_new(session, name: str, state: dict, telemetry: ModuleType) -> None:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    if len(encoded) > _MAX_SCRATCH_BYTES:
        raise ValueError("scratch state exceeds the reviewed byte limit")
    with telemetry._regular_handle(session, name, write=True, create=True, exclusive=True) as fd:
        assert fd is not None
        info = os.fstat(fd)
        offset = 0
        while offset < len(encoded):
            session.verify_file(name, info, fd=fd, mutable=True, expected_size=offset)
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                raise ValueError("scratch state write did not complete")
            offset += written
        session.verify_file(name, info, fd=fd, mutable=True, expected_size=offset)


def _scan_states(session) -> list[tuple[str, os.stat_result]]:
    states = []
    session.verify()
    with os.scandir(session.fd) as entries:
        for entry in entries:
            if len(states) >= _MAX_SESSION_AGENTS:
                raise ValueError("session scratch file limit exceeded")
            if not entry.name.endswith(".json") or _HEX64.fullmatch(entry.name[:-5]) is None:
                raise ValueError("session scratch contains an unsafe entry")
            info = session.entry_info(entry.name, mutable=True)
            if info is None:
                raise ValueError("session scratch changed during scan")
            if info.st_size > _MAX_SCRATCH_BYTES:
                raise ValueError("scratch state exceeds the reviewed byte limit")
            states.append((entry.name, info))
    session.verify()
    return states


def _active_agents(session) -> int | None:
    return None if session is None else len(_scan_states(session))


def _start_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, telemetry, started=True)
    if payload is None:
        return None
    session_id = event.get("session_id")
    name = _agent_name(event.get("agent_id"))
    if not _valid_identifier(session_id) or name is None:
        return payload

    with _session_transaction(repo, telemetry, session_id, create=True) as session:
        assert session is not None
        current = _active_agents(session)
        existing = _read_state(session, name, telemetry)
        if existing is None:
            if current is not None and current >= _MAX_SESSION_AGENTS:
                raise ValueError("session scratch file limit exceeded")
            state: dict[str, object] = {
                "started_at_ms": time.time_ns() // 1_000_000,
                "role": payload["role"],
            }
            if "model" in payload:
                state["model"] = payload["model"]
            _write_state_new(session, name, state, telemetry)
        active = _active_agents(session)
        if active is not None:
            payload["active_agents"] = active
    return payload


def _stop_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, telemetry, started=False)
    if payload is None:
        return None
    started_at_ms = None
    with _session_transaction(repo, telemetry, event.get("session_id")) as session:
        if session is None:
            return payload
        name = _agent_name(event.get("agent_id"))
        if name is not None:
            saved = _read_state(session, name, telemetry)
            if saved is not None:
                state, info = saved
                started_at_ms = state["started_at_ms"]
                session.unlink_file(name, info)
        active = _active_agents(session)
        if active is not None:
            payload["active_agents"] = active
        if started_at_ms is not None:
            payload["duration_ms"] = max(0, time.time_ns() // 1_000_000 - started_at_ms)
        if active == 0:
            session.remove()
    return payload


def _cleanup_session(event: dict, repo: Path, telemetry: ModuleType) -> None:
    with _session_transaction(repo, telemetry, event.get("session_id")) as session:
        if session is None:
            return
        states = []
        for name, _info in _scan_states(session):
            saved = _read_state(session, name, telemetry)
            if saved is None:
                raise ValueError("session scratch changed during cleanup")
            _, info = saved
            states.append((name, info))
        for name, info in states:
            session.unlink_file(name, info)
        session.remove()


def _payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    name = event.get("hook_event_name")
    if type(name) is not str or name not in _SUPPORTED:
        return None
    if name == "SubagentStart":
        return _start_payload(event, repo, telemetry)
    if name == "SubagentStop":
        return _stop_payload(event, repo, telemetry)
    if name == "SessionEnd":
        _cleanup_session(event, repo, telemetry)
        return None
    trigger = event.get("trigger")
    if type(trigger) is not str or trigger not in {"manual", "auto"}:
        return None
    return {"event": "context_compaction", "trigger": trigger}


def _read_event() -> object:
    binary = getattr(sys.stdin, "buffer", None)
    if binary is not None:
        raw = binary.read(_MAX_HOOK_EVENT_BYTES + 1)
    else:
        text = sys.stdin.read(_MAX_HOOK_EVENT_BYTES + 1)
        if type(text) is not str:
            raise ValueError("hook input is unavailable")
        raw = text.encode("utf-8", errors="strict")
    if len(raw) > _MAX_HOOK_EVENT_BYTES:
        raise ValueError("hook input exceeds the reviewed byte limit")
    return _telemetry_module()._observations_module().decode_json(
        raw,
        max_bytes=_MAX_HOOK_EVENT_BYTES,
    )


def main() -> int:
    try:
        telemetry = _telemetry_module()
        event = _read_event()
        if type(event) is not dict:
            return 0
        repo = _repo_root(event.get("cwd"), telemetry)
        payload = _payload(event, repo, telemetry)
        if payload is not None:
            telemetry.record(repo, payload)
    except Exception:
        # Telemetry is observability only; malformed or unsafe input fails open silently.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
