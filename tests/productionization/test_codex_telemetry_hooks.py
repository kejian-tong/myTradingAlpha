from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import multiprocessing
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts/codex_telemetry_hook.py"


def _git_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)


def _run(event: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
    )


def _run_raw(event_json: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=event_json,
        text=True,
        capture_output=True,
        check=False,
    )


def _rows(repo: Path) -> list[dict]:
    path = repo / ".git/codex-harness/telemetry.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _common(repo: Path) -> dict[str, str]:
    return {
        "session_id": "session-secret-like-but-not-durable",
        "cwd": str(repo),
        "model": "gpt-6-luna",
        "transcript_path": "/do/not/store/transcript.jsonl",
    }


def test_subagent_hooks_measure_active_agents_and_duration_without_durable_ids(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    common = _common(repo)
    first = {**common, "hook_event_name": "SubagentStart", "agent_id": "agent-123", "agent_type": "code_explorer"}
    second = {**common, "hook_event_name": "SubagentStart", "agent_id": "agent-456", "agent_type": "test_auditor"}

    assert _run(first).returncode == 0
    assert _run(second).returncode == 0

    runtime = repo / ".git/codex-harness/runtime"
    files = list(runtime.rglob("*.json"))
    assert len(files) == 2
    runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    runtime_names = "\n".join(str(path.relative_to(runtime)) for path in files)
    for raw_id in (common["session_id"], "agent-123", "agent-456"):
        assert raw_id not in runtime_text
        assert raw_id not in runtime_names

    stop_first = {
        **common,
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-123",
        "agent_type": "code_explorer",
        "last_assistant_message": "must not be stored",
    }
    stop_second = {
        **common,
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-456",
        "agent_type": "test_auditor",
    }
    assert _run(stop_first).returncode == 0
    assert _run(stop_second).returncode == 0

    rows = _rows(repo)
    assert [row["event"] for row in rows] == ["agent_spawn", "agent_spawn", "agent_stop", "agent_stop"]
    assert [row["active_agents"] for row in rows] == [1, 2, 1, 0]
    assert rows[2]["duration_ms"] >= 0
    assert rows[3]["duration_ms"] >= 0
    forbidden = {"session_id", "agent_id", "transcript_path", "last_assistant_message"}
    assert all(forbidden.isdisjoint(row) for row in rows)


def test_compaction_and_session_end_cleanup_remain_narrow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    common = _common(repo)
    start = {**common, "hook_event_name": "SubagentStart", "agent_id": "agent-live", "agent_type": "code_explorer"}
    compact = {**common, "hook_event_name": "PostCompact", "trigger": "auto"}
    session_end = {**common, "hook_event_name": "SessionEnd", "reason": "other"}

    assert _run(start).returncode == 0
    assert _run(compact).returncode == 0
    runtime = repo / ".git/codex-harness/runtime"
    assert list(runtime.rglob("*.json"))

    before = len(_rows(repo))
    assert _run(session_end).returncode == 0
    assert len(_rows(repo)) == before
    assert not list(runtime.rglob("*.json"))
    assert _rows(repo)[1] == {
        "event": "context_compaction",
        "observed_at_ms": _rows(repo)[1]["observed_at_ms"],
        "trigger": "auto",
    }


def test_runpy_loading_matches_windows_command_shape(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    event = {
        "hook_event_name": "SubagentStart",
        "cwd": str(repo),
        "agent_type": "test_auditor",
        "model": "gpt-6-luna",
    }
    code = f"import runpy; runpy.run_path({str(HOOK)!r}, run_name='__main__')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert _rows(repo)[0]["role"] == "test_auditor"
    assert "active_agents" not in _rows(repo)[0]


def test_telemetry_hook_is_best_effort_and_fail_open(tmp_path: Path) -> None:
    event = {
        "hook_event_name": "SubagentStart",
        "cwd": str(tmp_path),
        "session_id": "not-a-repo-session",
        "agent_id": "agent",
        "agent_type": "code_explorer",
        "model": "gpt-6-luna",
    }
    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_event_byte_limit_is_inclusive_and_oversize_input_is_silent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    limit = 65_536
    prefix = '{"hook_event_name":"PostCompact","trigger":"auto","cwd":' + json.dumps(str(repo)) + ',"pad":"'
    suffix = '"}'
    at_limit = prefix + ("x" * (limit - len(prefix.encode("utf-8")) - len(suffix))) + suffix
    over_limit = at_limit + " "
    assert len(at_limit.encode("utf-8")) == limit

    accepted = _run_raw(at_limit)
    assert accepted.returncode == 0
    assert accepted.stdout == ""
    assert accepted.stderr == ""
    assert [row["event"] for row in _rows(repo)] == ["context_compaction"]

    rejected = _run_raw(over_limit)
    assert rejected.returncode == 0
    assert rejected.stdout == ""
    assert rejected.stderr == ""
    assert [row["event"] for row in _rows(repo)] == ["context_compaction"]


def test_hook_never_persists_request_usage_or_transcript_fields(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    marker = "raw-hook-secret-marker-7b8e"
    event = {
        **_common(repo),
        "hook_event_name": "SubagentStart",
        "agent_id": "agent-usage-private",
        "agent_type": "normal_implementer",
        "usage": {
            "input_tokens": 1_000,
            "cached_input_tokens": 200,
            "cache_write_tokens": 20,
            "output_tokens": 100,
            "reasoning_output_tokens": 50,
            "raw_provider_payload": marker,
        },
        "total_tokens": 1_100,
        "prompt": marker,
        "last_assistant_message": marker,
        "transcript_path": f"/private/{marker}.jsonl",
    }

    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    durable = repo / ".git/codex-harness/telemetry.jsonl"
    runtime = repo / ".git/codex-harness/runtime"
    persisted = durable.read_text(encoding="utf-8") + "\n".join(
        path.read_text(encoding="utf-8") for path in runtime.rglob("*.json")
    )
    assert marker not in persisted
    assert "input_tokens" not in persisted
    assert "reasoning_output_tokens" not in persisted
    assert "total_tokens" not in persisted
    assert "transcript_path" not in persisted


def test_unreviewed_model_and_overlong_labels_fail_open_before_scratch_write(tmp_path: Path) -> None:
    model_repo = tmp_path / "model-repo"
    _git_repo(model_repo)
    base = {
        **_common(model_repo),
        "hook_event_name": "SubagentStart",
        "agent_id": "agent-invalid-label",
        "agent_type": "normal_implementer",
    }
    unknown_model = _run({**base, "model": "unknown-model-marker"})
    assert unknown_model.returncode == 0
    assert unknown_model.stdout == ""
    assert unknown_model.stderr == ""
    assert not (model_repo / ".git/codex-harness/telemetry.jsonl").exists()
    assert not (model_repo / ".git/codex-harness/runtime").exists()

    role_repo = tmp_path / "role-repo"
    _git_repo(role_repo)
    role_event = {
        **_common(role_repo),
        "hook_event_name": "SubagentStart",
        "agent_id": "agent-overlong",
        "agent_type": "r" * 129,
    }
    overlong_role = _run(role_event)
    assert overlong_role.returncode == 0
    assert overlong_role.stdout == ""
    assert overlong_role.stderr == ""
    assert not (role_repo / ".git/codex-harness/telemetry.jsonl").exists()
    assert not (role_repo / ".git/codex-harness/runtime").exists()


def test_hook_refuses_symlinked_scratch_state_without_modifying_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    session_id = "session-link-test"
    agent_id = "agent-link-test"
    session_ref = hashlib.sha256(session_id.encode()).hexdigest()
    agent_ref = hashlib.sha256(agent_id.encode()).hexdigest()
    session_dir = repo / ".git/codex-harness/runtime" / session_ref
    session_dir.mkdir(parents=True)
    outside = tmp_path / "outside-state.json"
    outside.write_text("preserve", encoding="utf-8")
    (session_dir / f"{agent_ref}.json").symlink_to(outside)
    event = {
        **_common(repo),
        "hook_event_name": "SubagentStart",
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": "code_explorer",
    }

    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert outside.read_text(encoding="utf-8") == "preserve"


def test_session_cleanup_refuses_symlinked_state_without_removing_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    session_id = "session-cleanup-link-test"
    agent_id = "agent-cleanup-link-test"
    session_ref = hashlib.sha256(session_id.encode()).hexdigest()
    agent_ref = hashlib.sha256(agent_id.encode()).hexdigest()
    session_dir = repo / ".git/codex-harness/runtime" / session_ref
    session_dir.mkdir(parents=True)
    outside = tmp_path / "outside-cleanup-state.json"
    outside.write_text("preserve", encoding="utf-8")
    (session_dir / f"{agent_ref}.json").symlink_to(outside)
    before = outside.read_text(encoding="utf-8")
    event = {
        **_common(repo),
        "hook_event_name": "SessionEnd",
        "session_id": session_id,
    }

    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert outside.read_text(encoding="utf-8") == before
    assert (session_dir / f"{agent_ref}.json").is_symlink()


def test_hook_refuses_oversized_scratch_state_without_deleting_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    session_id = "session-size-test"
    agent_id = "agent-size-test"
    session_ref = hashlib.sha256(session_id.encode()).hexdigest()
    agent_ref = hashlib.sha256(agent_id.encode()).hexdigest()
    session_dir = repo / ".git/codex-harness/runtime" / session_ref
    session_dir.mkdir(parents=True)
    state_file = session_dir / f"{agent_ref}.json"
    state_file.write_bytes(b"x" * 4_097)
    before = state_file.read_bytes()
    event = {
        **_common(repo),
        "hook_event_name": "SubagentStop",
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": "code_explorer",
    }

    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert state_file.read_bytes() == before


def test_hook_accepts_scratch_state_at_exact_byte_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    session_id = "session-exact-size"
    agent_id = "agent-exact-size"
    session_ref = hashlib.sha256(session_id.encode()).hexdigest()
    agent_ref = hashlib.sha256(agent_id.encode()).hexdigest()
    session_dir = repo / ".git/codex-harness/runtime" / session_ref
    session_dir.mkdir(parents=True)
    state_file = session_dir / f"{agent_ref}.json"
    payload = json.dumps(
        {"started_at_ms": 1, "role": "code_explorer"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    state_file.write_bytes(payload + (b" " * (4_096 - len(payload))))
    assert state_file.stat().st_size == 4_096
    event = {
        **_common(repo),
        "hook_event_name": "SubagentStop",
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": "code_explorer",
    }

    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert not state_file.exists()


def test_hook_never_creates_more_than_64_agent_scratch_files_per_session(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    common = _common(repo)
    for index in range(64):
        result = _run(
            {
                **common,
                "hook_event_name": "SubagentStart",
                "agent_id": f"agent-{index}",
                "agent_type": "code_explorer",
            }
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    runtime = repo / ".git/codex-harness/runtime"
    files = list(runtime.rglob("*.json"))
    assert len(files) == 64
    assert all(path.stat().st_size <= 4_096 for path in files)
    extra = _run(
        {
            **common,
            "hook_event_name": "SubagentStart",
            "agent_id": "agent-64",
            "agent_type": "code_explorer",
        }
    )
    assert extra.returncode == 0
    assert extra.stdout == ""
    assert extra.stderr == ""
    assert len(list(runtime.rglob("*.json"))) == 64


def test_hooks_json_uses_current_official_field_names() -> None:
    hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {
        "SessionStart",
        "PreToolUse",
        "SubagentStart",
        "SubagentStop",
        "PostCompact",
        "SessionEnd",
        "Stop",
    }
    for entries in hooks.values():
        handler = entries[0]["hooks"][0]
        assert "timeout" in handler
        assert "commandWindows" in handler
        assert not {"timeout_sec", "command_windows", "status_message"}.intersection(handler)
    session_end = hooks["SessionEnd"][0]["hooks"][0]
    assert session_end["timeout"] == 3
    assert session_end["async"] is False
    assert "codex_telemetry_hook.py" in session_end["command"]


def _r1_hook_module():
    spec = importlib.util.spec_from_file_location("r1_telemetry_hook", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _r1_event(repo: Path, name: str, agent_id: str = "agent-original") -> dict:
    return {
        **_common(repo),
        "hook_event_name": name,
        "agent_id": agent_id,
        "agent_type": "code_explorer",
        "trigger": "auto",
    }


def _r1_session(repo: Path) -> Path:
    session_ref = hashlib.sha256(_common(repo)["session_id"].encode()).hexdigest()
    return repo / ".git/codex-harness/runtime" / session_ref


def _r1_seed_state(repo: Path, agent_id: str = "agent-original", started: int = 123) -> Path:
    session = _r1_session(repo)
    session.mkdir(parents=True, exist_ok=True)
    path = session / (hashlib.sha256(agent_id.encode()).hexdigest() + ".json")
    path.write_text(json.dumps({"started_at_ms": started, "role": "code_explorer"}))
    return path


def _r1_snapshot(directory: Path) -> dict:
    if not directory.exists():
        return {}
    return {
        path.relative_to(directory).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in directory.rglob("*")
    }


def _r1_invoke_hook(hook, event: dict) -> tuple[int, str, str]:
    original_stdin = sys.stdin
    stdout, stderr = io.StringIO(), io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(event))
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = hook.main()
        return status, stdout.getvalue(), stderr.getvalue()
    finally:
        sys.stdin = original_stdin


def _r1_patch_os(patch, name: str, replacement) -> None:
    original = getattr(os, name)
    # Forwarding wrappers retain the real primitive's advertised platform capabilities.
    for capability in ("supports_dir_fd", "supports_fd", "supports_follow_symlinks", "supports_effective_ids"):
        supported = getattr(os, capability)
        if original in supported:
            patch.setattr(os, capability, supported | {replacement})
    patch.setattr(os, name, replacement)


def test_r1_stop_refuses_a_symlinked_session_and_preserves_outside_valid_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    inside = _r1_seed_state(repo)
    state_name, state_bytes = inside.name, inside.read_bytes()
    inside.unlink()
    session = inside.parent
    session.rmdir()
    outside = tmp_path / "outside-session"
    outside.mkdir()
    (outside / state_name).write_bytes(state_bytes)
    session.symlink_to(outside, target_is_directory=True)
    before = _r1_snapshot(outside)

    result = _run(_r1_event(repo, "SubagentStop"))

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert _r1_snapshot(outside) == before, "stop deleted valid state through a session symlink"
    assert session.is_symlink()


@pytest.mark.parametrize("ancestor_name", ("metadata", "runtime", "session"))
@pytest.mark.parametrize("event_name", ("SubagentStart", "SubagentStop", "SessionEnd"))
def test_r1_ancestor_swap_at_scratch_operation_never_writes_or_unlinks_outside(
    tmp_path: Path, monkeypatch, ancestor_name: str, event_name: str
) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    state = _r1_seed_state(repo, "agent-other" if event_name == "SubagentStart" else "agent-original")
    session = state.parent
    metadata = repo / ".git/codex-harness"
    ancestor = {"metadata": metadata, "runtime": session.parent, "session": session}[ancestor_name]
    outside = tmp_path / "outside-ancestor"
    outside_session = outside / session.relative_to(ancestor)
    outside_session.mkdir(parents=True)
    if event_name != "SubagentStart":
        (outside_session / state.name).write_bytes(state.read_bytes())
    guard = hashlib.sha256(b"outside-guard").hexdigest() + ".json"
    (outside / guard).write_text(json.dumps({"started_at_ms": 1, "role": "code_explorer"}))
    before = _r1_snapshot(outside)
    held = ancestor.with_name("held-" + ancestor.name)
    target_name = hashlib.sha256(b"agent-original").hexdigest() + ".json"
    session_info = session.stat()
    real_stat = os.stat
    swapped = False

    def is_session(target, **kwargs) -> bool:
        try:
            info = os.fstat(target) if isinstance(target, int) else real_stat(target, **kwargs)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == (session_info.st_dev, session_info.st_ino)

    def intercept(real_operation, *, scan: bool = False):
        def wrapped(target, *args, **kwargs):
            nonlocal swapped
            boundary = is_session(target) if scan else (
                not isinstance(target, int) and Path(os.fsdecode(target)).name == target_name
            )
            if not swapped and boundary:
                swapped = True
                ancestor.rename(held)
                ancestor.symlink_to(outside, target_is_directory=True)
            return real_operation(target, *args, **kwargs)

        return wrapped

    hook = _r1_hook_module()
    with monkeypatch.context() as patch:
        if event_name == "SessionEnd":
            _r1_patch_os(patch, "scandir", intercept(os.scandir, scan=True))
        else:
            for name in ("lstat", "stat", "open"):
                _r1_patch_os(patch, name, intercept(getattr(os, name)))
        result = _r1_invoke_hook(hook, _r1_event(repo, event_name))

    assert result == (0, "", "")
    assert swapped, "the scratch filesystem boundary was not exercised"
    assert _r1_snapshot(outside) == before, "scratch transaction followed a replaced ancestor"


class _R1ScanGate:
    """Pause after the real directory iterator is exhausted, before its caller can mutate."""

    def __init__(self, entries, after_scan):
        self.entries = entries
        self.after_scan = after_scan
        self.finished = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.entries)
        except StopIteration:
            if not self.finished:
                self.finished = True
                self.after_scan()
            raise

    def close(self):
        self.entries.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def _r1_process_hook(
    event, result, *, rendezvous=None, scanned=None, peer_scanned=None,
    paused=None, proceed=None, pause_boundary=None,
) -> None:
    """Run the real hook in a fresh process with bounded filesystem synchronization."""
    sync_errors = []
    original_scandir, original_unlink, original_remove = os.scandir, os.unlink, os.remove
    original_rmdir = os.rmdir
    capabilities = {
        name: getattr(os, name)
        for name in ("supports_dir_fd", "supports_fd", "supports_follow_symlinks", "supports_effective_ids")
    }
    session = _r1_session(Path(event["cwd"]))
    try:
        session_info = session.stat()
    except FileNotFoundError:
        session_info = None
    used_gate = False

    def wait_for(signal) -> None:
        if not signal.wait(timeout=10):
            sync_errors.append("filesystem synchronization deadline expired")
            raise RuntimeError("filesystem synchronization deadline expired")

    def at_scan_end() -> None:
        if scanned is not None:
            scanned.set()
            wait_for(peer_scanned)
        else:
            paused.set()
            wait_for(proceed)

    def scan(target):
        nonlocal used_gate
        entries = original_scandir(target)
        info = os.fstat(target) if isinstance(target, int) else os.stat(target)
        if session_info is not None and not used_gate and (scanned is not None or pause_boundary == "scan") and (
            info.st_dev, info.st_ino
        ) == (session_info.st_dev, session_info.st_ino):
            used_gate = True
            return _R1ScanGate(entries, at_scan_end)
        return entries

    def unlink(real_operation):
        def wrapped(target, *args, **kwargs):
            nonlocal used_gate
            if not used_gate and pause_boundary == "unlink" and str(target).endswith(".json"):
                used_gate = True
                paused.set()
                wait_for(proceed)
            return real_operation(target, *args, **kwargs)

        return wrapped

    def rmdir(target, *args, **kwargs):
        nonlocal used_gate
        removed = original_rmdir(target, *args, **kwargs)
        if not used_gate and pause_boundary == "removed" and Path(os.fsdecode(target)).name == session.name:
            used_gate = True
            paused.set()
            wait_for(proceed)
        return removed

    try:
        for name, replacement in (("scandir", scan), ("unlink", unlink(original_unlink)), ("remove", unlink(original_remove)), ("rmdir", rmdir)):
            original = getattr(os, name)
            for capability in capabilities:
                supported = getattr(os, capability)
                if original in supported:
                    setattr(os, capability, supported | {replacement})
            setattr(os, name, replacement)
        if rendezvous is not None:
            rendezvous.wait(timeout=10)
        result.put((*_r1_invoke_hook(_r1_hook_module(), event), sync_errors))
    except BaseException as exc:
        result.put(("worker_error", type(exc).__name__))
    finally:
        if scanned is not None:
            # A serialized contender may fail open before it can scan the session.
            scanned.set()
        os.scandir, os.unlink, os.remove = original_scandir, original_unlink, original_remove
        os.rmdir = original_rmdir
        for name, supported in capabilities.items():
            setattr(os, name, supported)


def _r1_collect(process, result) -> tuple:
    process.join(timeout=15)
    assert process.exitcode == 0, "hook process did not finish within its synchronization bound"
    outcome = result.get(timeout=3)
    assert outcome == (0, "", "", []), outcome
    return outcome


def _r1_close_processes(processes) -> None:
    for process in processes:
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)


def test_r1_process_starts_from_63_states_never_create_a_65th_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    for index in range(63):
        _r1_seed_state(repo, f"existing-{index}")
    context = multiprocessing.get_context("spawn")
    rendezvous = context.Barrier(2)
    scanned = [context.Event(), context.Event()]
    results = [context.Queue(), context.Queue()]
    processes = [
        context.Process(
            target=_r1_process_hook,
            args=(_r1_event(repo, "SubagentStart", f"contender-{index}"), results[index]),
            kwargs={"rendezvous": rendezvous, "scanned": scanned[index], "peer_scanned": scanned[1 - index]},
        )
        for index in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for process, result in zip(processes, results, strict=True):
            _r1_collect(process, result)
    finally:
        _r1_close_processes(processes)

    states = list(_r1_session(repo).glob("*.json"))
    assert len(states) == 64, "count and creation were not one process-shared transaction"


def test_r1_concurrent_duplicate_starts_preserve_the_original_timestamp(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    state = _r1_seed_state(repo, started=123)
    original_timestamp = json.loads(state.read_text())["started_at_ms"]
    context = multiprocessing.get_context("spawn")
    rendezvous = context.Barrier(2)
    results = [context.Queue(), context.Queue()]
    processes = [
        context.Process(
            target=_r1_process_hook,
            args=(_r1_event(repo, "SubagentStart"), result),
            kwargs={"rendezvous": rendezvous},
        )
        for result in results
    ]
    try:
        for process in processes:
            process.start()
        for process, result in zip(processes, results, strict=True):
            _r1_collect(process, result)
    finally:
        _r1_close_processes(processes)

    assert json.loads(state.read_text())["started_at_ms"] == original_timestamp
    assert len(list(state.parent.glob("*.json"))) == 1


@pytest.mark.parametrize(
    ("first_event", "pause_boundary"),
    (("SubagentStart", "scan"), ("SubagentStop", "unlink"), ("SessionEnd", "unlink"),
     ("SubagentStop", "removed"), ("SessionEnd", "removed")),
)
def test_r1_session_transactions_exclude_a_process_start_until_completion(
    tmp_path: Path, first_event: str, pause_boundary: str
) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    _r1_seed_state(repo)
    session = _r1_session(repo)
    before = _r1_snapshot(session)
    context = multiprocessing.get_context("spawn")
    paused, proceed = context.Event(), context.Event()
    first_result, second_result = context.Queue(), context.Queue()
    first = context.Process(
        target=_r1_process_hook,
        args=(_r1_event(repo, first_event, "agent-first" if first_event == "SubagentStart" else "agent-original"), first_result),
        kwargs={"paused": paused, "proceed": proceed, "pause_boundary": pause_boundary},
    )
    second = context.Process(
        target=_r1_process_hook,
        args=(_r1_event(repo, "SubagentStart", "agent-second"), second_result),
    )
    processes = [first]
    try:
        first.start()
        assert paused.wait(timeout=10), "the first transaction never reached its filesystem boundary"
        expected_exists = pause_boundary != "removed"
        assert session.exists() == expected_exists
        second.start()
        processes.append(second)
        _r1_collect(second, second_result)
        during = _r1_snapshot(session)
        during_exists = session.exists()
        durable = repo / ".git/codex-harness/telemetry.jsonl"
        during_rows = durable.read_bytes() if durable.exists() else b""
    finally:
        proceed.set()
        _r1_close_processes([process for process in processes if process is not first])
        first.join(timeout=15)
        _r1_close_processes([first])

    _r1_collect(first, first_result)
    assert during_exists == expected_exists, "a second process recreated an unfinished session"
    assert during == (before if expected_exists else {}), "a second process mutated a session during an unfinished transaction"
    assert during_rows == b"", "a second lifecycle transaction completed while the first held the session"

    # The stable lock must remain usable when stop/cleanup removes and later recreates the directory.
    after = _r1_event(repo, "SubagentStart", "agent-after-removal")
    assert _run(after).returncode == 0
    recreated = session / (hashlib.sha256(b"agent-after-removal").hexdigest() + ".json")
    assert recreated.is_file()
    assert _run({**after, "hook_event_name": "SubagentStop"}).returncode == 0
    assert _run({**after, "hook_event_name": "SessionEnd"}).returncode == 0
    assert not session.exists()


@pytest.mark.parametrize("missing", ("O_NOFOLLOW", "O_DIRECTORY", "dir_fd", "fd_scandir"))
@pytest.mark.parametrize("event_name", ("SubagentStart", "SubagentStop", "SessionEnd", "PostCompact"))
def test_r1_unsupported_primitives_make_hooks_silent_without_scratch_mutation(
    tmp_path: Path, monkeypatch, missing: str, event_name: str
) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    _r1_seed_state(repo)
    metadata = repo / ".git/codex-harness"
    before = _r1_snapshot(metadata)
    hook = _r1_hook_module()
    if missing in {"O_NOFOLLOW", "O_DIRECTORY"}:
        monkeypatch.delattr(os, missing, raising=False)
    elif missing == "dir_fd":
        monkeypatch.setattr(os, "supports_dir_fd", set())
    else:
        monkeypatch.setattr(os, "supports_fd", os.supports_fd - {os.scandir})

    result = _r1_invoke_hook(hook, _r1_event(repo, event_name, "agent-second" if event_name == "SubagentStart" else "agent-original"))

    assert result == (0, "", "")
    assert _r1_snapshot(metadata) == before, "unsupported hook storage used an unsafe fallback"
