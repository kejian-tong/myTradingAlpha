from __future__ import annotations

import json
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


def _rows(repo: Path) -> list[dict]:
    path = repo / ".git/codex-harness/telemetry.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _common(repo: Path) -> dict[str, str]:
    return {
        "session_id": "session-secret-like-but-not-durable",
        "cwd": str(repo),
        "model": "gpt-5.6-luna",
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
        "model": "gpt-5.6-luna",
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
        "model": "gpt-5.6-luna",
    }
    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""


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
