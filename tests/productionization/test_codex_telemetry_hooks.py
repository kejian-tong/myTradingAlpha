from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

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
