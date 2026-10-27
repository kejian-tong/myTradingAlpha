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
import stat
import subprocess
import sys
import time
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


def _runtime_root(repo: Path, telemetry: ModuleType, *, create: bool = False) -> Path:
    return telemetry._runtime_directory(repo, create=create)


def _valid_identifier(value: object) -> bool:
    if type(value) is not str or not value or len(value) > 128:
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return len(encoded) <= 128


def _session_dir(
    repo: Path,
    telemetry: ModuleType,
    session_id: object,
    *,
    create: bool = False,
) -> Path | None:
    if not _valid_identifier(session_id):
        return None
    runtime = _runtime_root(repo, telemetry, create=create)
    directory = runtime / _digest(session_id)
    if create:
        telemetry._ensure_directory(directory, create=True)
    return directory


def _agent_file(session_dir: Path | None, agent_id: object) -> Path | None:
    if session_dir is None or not _valid_identifier(agent_id):
        return None
    return session_dir / f"{_digest(agent_id)}.json"


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


def _read_state(path: Path, telemetry: ModuleType) -> tuple[dict, os.stat_result] | None:
    info = telemetry._regular_file_info(path)
    if info is None:
        return None
    if info.st_size > _MAX_SCRATCH_BYTES:
        raise ValueError("scratch state exceeds the reviewed byte limit")
    observations = telemetry._observations_module()
    raw = observations._safe_read(path, max_bytes=_MAX_SCRATCH_BYTES)
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
    return validated, info


def _write_state_new(path: Path, state: dict) -> None:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    if len(encoded) > _MAX_SCRATCH_BYTES:
        raise ValueError("scratch state exceeds the reviewed byte limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise
    except OSError as exc:
        raise ValueError("scratch state cannot be created safely") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("scratch state is not a regular file")
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                raise ValueError("scratch state write did not complete")
            offset += written
    finally:
        os.close(fd)


def _safe_unlink(path: Path, expected: os.stat_result) -> None:
    current = path.lstat()
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
    ):
        raise ValueError("scratch state changed before removal")
    path.unlink()


def _active_agents(session_dir: Path | None) -> int | None:
    if session_dir is None:
        return None
    try:
        info = session_dir.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("session scratch path is not a real directory")
    count = 0
    try:
        with os.scandir(session_dir) as entries:
            for entry in entries:
                if count >= _MAX_SESSION_AGENTS:
                    raise ValueError("session scratch file limit exceeded")
                if _HEX64.fullmatch(entry.name.removesuffix(".json")) is None or not entry.name.endswith(
                    ".json"
                ):
                    raise ValueError("session scratch contains an unsafe entry")
                if not entry.is_file(follow_symlinks=False):
                    raise ValueError("session scratch contains a non-regular entry")
                state_info = entry.stat(follow_symlinks=False)
                if state_info.st_size > _MAX_SCRATCH_BYTES:
                    raise ValueError("scratch state exceeds the reviewed byte limit")
                count += 1
    except OSError as exc:
        raise ValueError("session scratch cannot be scanned safely") from exc
    return count


def _start_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, telemetry, started=True)
    if payload is None:
        return None
    session_id = event.get("session_id")
    agent_id = event.get("agent_id")
    session_dir = _session_dir(repo, telemetry, session_id, create=False)
    state_file = _agent_file(session_dir, agent_id)
    if session_dir is None or state_file is None:
        return payload

    session_dir = _session_dir(repo, telemetry, session_id, create=True)
    assert session_dir is not None
    current = _active_agents(session_dir)
    existing = _read_state(state_file, telemetry)
    if existing is None:
        if current is not None and current >= _MAX_SESSION_AGENTS:
            raise ValueError("session scratch file limit exceeded")
        state: dict[str, object] = {
            "started_at_ms": time.time_ns() // 1_000_000,
            "role": payload["role"],
        }
        if "model" in payload:
            state["model"] = payload["model"]
        try:
            _write_state_new(state_file, state)
        except FileExistsError:
            existing = _read_state(state_file, telemetry)
            if existing is None:
                raise ValueError("scratch state changed during creation") from None
    active = _active_agents(session_dir)
    if active is not None:
        payload["active_agents"] = active
    return payload


def _stop_payload(event: dict, repo: Path, telemetry: ModuleType) -> dict | None:
    payload = _basic_agent_payload(event, telemetry, started=False)
    if payload is None:
        return None
    session_dir = _session_dir(repo, telemetry, event.get("session_id"), create=False)
    state_file = _agent_file(session_dir, event.get("agent_id"))
    started_at_ms = None
    if state_file is not None:
        saved = _read_state(state_file, telemetry)
        if saved is not None:
            state, info = saved
            started_at_ms = state["started_at_ms"]
            _safe_unlink(state_file, info)
    active = _active_agents(session_dir)
    if active is not None:
        payload["active_agents"] = active
    if started_at_ms is not None:
        payload["duration_ms"] = max(0, time.time_ns() // 1_000_000 - started_at_ms)
    if session_dir is not None and active == 0:
        session_dir.rmdir()
    return payload


def _cleanup_session(event: dict, repo: Path, telemetry: ModuleType) -> None:
    session_dir = _session_dir(repo, telemetry, event.get("session_id"), create=False)
    if session_dir is None:
        return
    try:
        info = session_dir.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("session scratch path is not a real directory")

    states: list[tuple[Path, os.stat_result]] = []
    try:
        with os.scandir(session_dir) as entries:
            for entry in entries:
                if len(states) >= _MAX_SESSION_AGENTS:
                    raise ValueError("session scratch file limit exceeded")
                if (
                    not entry.name.endswith(".json")
                    or _HEX64.fullmatch(entry.name[:-5]) is None
                    or not entry.is_file(follow_symlinks=False)
                ):
                    raise ValueError("session scratch contains an unsafe entry")
                state_path = session_dir / entry.name
                saved = _read_state(state_path, telemetry)
                if saved is None:
                    raise ValueError("session scratch changed during cleanup")
                _, state_info = saved
                states.append((state_path, state_info))
    except OSError as exc:
        raise ValueError("session scratch cannot be scanned safely") from exc

    for state_path, state_info in states:
        _safe_unlink(state_path, state_info)
    session_dir.rmdir()


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
