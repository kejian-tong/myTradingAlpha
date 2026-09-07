from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts/codex_pretool_guard.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("codex_pretool_guard", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "command",
    [
        "git push --force origin main",
        "git push --force-with-lease origin main",
        "git -C repo reset --hard HEAD~1",
        "git clean -fdx",
        "git branch -D obsolete",
        "sudo -u root git reset --hard",
        "env SAFE=1 git push -f origin main",
        "rm -rf /",
        "rm --recursive --force .",
        "echo ok && git reset --hard",
    ],
)
def test_reviewed_destructive_direct_commands_are_denied(command: str) -> None:
    assert _module().destructive_command_reason(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git reset --soft HEAD~1",
        "git clean -n",
        "git branch -d merged-branch",
        "rm -rf /tmp/review-worktree",
        'echo "git reset --hard"',
        "printf '%s' 'rm -rf /'",
        "python -m pytest -q",
    ],
)
def test_benign_or_out_of_scope_commands_are_not_denied(command: str) -> None:
    assert _module().destructive_command_reason(command) is None


def _run(event: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
    )


def test_pretool_hook_returns_canonical_deny_output() -> None:
    result = _run(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard"},
        }
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "PreToolUse"
    assert output["permissionDecision"] == "deny"
    assert "reset --hard" in output["permissionDecisionReason"]


def test_matched_bash_event_fails_closed_when_command_shape_is_unknown() -> None:
    result = _run({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}})
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_non_bash_event_returns_no_decision() -> None:
    result = _run(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "git reset --hard"},
        }
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_hooks_json_binds_pretool_guard_to_bash_synchronously() -> None:
    hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
    entry = hooks["PreToolUse"][0]
    handler = entry["hooks"][0]
    assert entry["matcher"] == "Bash"
    assert handler["type"] == "command"
    assert handler["async"] is False
    assert handler["timeout"] == 5
    assert "codex_pretool_guard.py" in handler["command"]
    assert "codex_pretool_guard.py" in handler["commandWindows"]
