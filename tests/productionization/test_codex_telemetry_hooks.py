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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _rows(repo: Path) -> list[dict]:
    path = repo / ".git/codex-harness/telemetry.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_subagent_and_compaction_hooks_record_only_narrow_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _git_repo(repo)
    common = {
        "session_id": "session-secret-like-but-not-stored",
        "cwd": str(repo),
        "model": "gpt-5.6-luna",
        "transcript_path": "/do/not/store/transcript.jsonl",
    }
    start = {**common, "hook_event_name": "SubagentStart", "agent_id": "agent-123", "agent_type": "code_explorer"}
    stop = {
        **common,
        "hook_event_name": "SubagentStop",
        "agent_id": "agent-123",
        "agent_type": "code_explorer",
        "last_assistant_message": "must not be stored",
    }
    compact = {**common, "hook_event_name": "PostCompact", "trigger": "auto"}

    assert _run(start).returncode == 0
    assert _run(stop).returncode == 0
    assert _run(compact).returncode == 0

    rows = _rows(repo)
    assert [row["event"] for row in rows] == ["agent_spawn", "agent_stop", "context_compaction"]
    assert rows[0]["role"] == rows[1]["role"] == "code_explorer"
    assert rows[0]["model"] == rows[1]["model"] == "gpt-5.6-luna"
    assert rows[2]["trigger"] == "auto"
    forbidden = {"session_id", "agent_id", "transcript_path", "last_assistant_message"}
    assert all(forbidden.isdisjoint(row) for row in rows)


def test_telemetry_hook_is_best_effort_and_fail_open(tmp_path: Path) -> None:
    event = {
        "hook_event_name": "SubagentStart",
        "cwd": str(tmp_path),
        "agent_type": "code_explorer",
        "model": "gpt-5.6-luna",
    }
    result = _run(event)
    assert result.returncode == 0
    assert result.stdout == ""


def test_hooks_json_uses_current_official_field_names() -> None:
    hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert set(hooks) == {"SessionStart", "SubagentStart", "SubagentStop", "PostCompact", "Stop"}
    for entries in hooks.values():
        handler = entries[0]["hooks"][0]
        assert "timeout" in handler
        assert "commandWindows" in handler
        assert not {"timeout_sec", "command_windows", "status_message"}.intersection(handler)
