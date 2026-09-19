"""Contract tests for the advisory Codex stop hook."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts/codex_hook_guard.py"


def _module() -> ModuleType:
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("codex_hook_guard_advisory", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "codex-tests@example.invalid")
    _git(repo, "config", "user.name", "Codex tests")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _invoke(module: ModuleType, event: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(module.sys, "argv", [str(HOOK), event])
    return module.main()


def test_clean_stop_returns_zero_without_advisory_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", _repository(tmp_path))
    monkeypatch.setattr(module, "configuration_errors", lambda _root: [])

    assert _invoke(module, "stop", monkeypatch) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_session_start_still_fails_closed_on_configuration_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", _repository(tmp_path))
    monkeypatch.setattr(module, "configuration_errors", lambda _root: ["invalid harness fixture"])

    assert _invoke(module, "session-start", monkeypatch) != 0
    captured = capsys.readouterr()
    assert "invalid harness fixture" in captured.err


def test_stop_configuration_errors_are_advisory_and_repeated_stops_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", _repository(tmp_path))
    monkeypatch.setattr(module, "configuration_errors", lambda _root: ["harness drift"])

    assert _invoke(module, "stop", monkeypatch) == 0
    first = capsys.readouterr()
    assert _invoke(module, "stop", monkeypatch) == 0
    second = capsys.readouterr()

    for captured in (first, second):
        assert captured.out == ""
        assert captured.err.count("codex hook advisory:") == 1
        assert "harness drift" in captured.err
        assert "stop again" not in captured.err.lower()


def test_stop_allows_ordinary_agent_owned_dirty_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    repo = _repository(tmp_path)
    (repo / "tracked.txt").write_text("agent-owned update\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(module, "configuration_errors", lambda _root: [])

    assert _invoke(module, "stop", monkeypatch) == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_stop_reports_unrelated_whitespace_errors_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    repo = _repository(tmp_path)
    (repo / "unrelated.txt").write_text("pre-existing whitespace\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    _git(repo, "commit", "-qm", "baseline unrelated file")
    # Keep the whitespace error in the working tree so git diff --check observes it.
    (repo / "unrelated.txt").write_text("pre-existing whitespace  \n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", repo)
    monkeypatch.setattr(module, "configuration_errors", lambda _root: [])

    assert _invoke(module, "stop", monkeypatch) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "codex hook advisory:" in captured.err
    assert "trailing whitespace" in captured.err


def test_stop_validator_exception_is_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", _repository(tmp_path))

    def fail(_root: Path) -> list[str]:
        raise OSError("validator unavailable")

    monkeypatch.setattr(module, "configuration_errors", fail)

    assert _invoke(module, "stop", monkeypatch) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "codex hook advisory:" in captured.err
    assert "validator unavailable" in captured.err


def test_stop_git_diagnostic_timeout_is_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module, "ROOT", _repository(tmp_path))
    monkeypatch.setattr(module, "configuration_errors", lambda _root: [])

    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["git", "diff", "--check"], 15)

    monkeypatch.setattr(module.subprocess, "run", timeout)

    assert _invoke(module, "stop", monkeypatch) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "codex hook advisory:" in captured.err
    assert "timed out" in captured.err.lower()


def test_malformed_cli_event_is_bounded_argparse_rejection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    monkeypatch.setattr(module.sys, "argv", [str(HOOK), "unexpected"])

    with pytest.raises(SystemExit) as exc_info:
        module.main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice" in captured.err
    assert "codex hook advisory:" not in captured.err


def test_stop_and_pretool_hook_boundaries_remain_declared() -> None:
    hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]

    for event, cli_event in (("SessionStart", "session-start"), ("Stop", "stop")):
        assert len(hooks[event]) == 1
        entry = hooks[event][0]
        handler = entry["hooks"][0]
        assert handler["type"] == "command"
        assert handler["async"] is False
        assert "codex_hook_guard.py" in handler["command"]
        assert f"'{cli_event}'" in handler["command"]

    pretool = hooks["PreToolUse"]
    assert len(pretool) == 1
    assert pretool[0]["matcher"] == "Bash"
    handler = pretool[0]["hooks"][0]
    assert handler["type"] == "command"
    assert handler["async"] is False
    assert handler["timeout"] == 5
    assert "codex_pretool_guard.py" in handler["command"]
    assert "codex_pretool_guard.py" in handler["commandWindows"]


def test_stop_remains_supplemental_to_exact_head_and_ci_enforcement() -> None:
    policy = (ROOT / "docs/productionization/CODEX_HOOKS.md").read_text(encoding="utf-8")
    assert "authoritative merge requirements remain" in policy
    assert "exact-head required GitHub CI/checks" in policy
    assert "master merge gate" in policy
