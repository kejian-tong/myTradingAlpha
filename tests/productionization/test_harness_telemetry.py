from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts/harness_telemetry.py"
    spec = importlib.util.spec_from_file_location("harness_telemetry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    return repo


def test_telemetry_lives_in_git_metadata_not_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, {"event": "agent_spawn", "role": "code_explorer", "active_agents": 2})
    assert path.is_file()
    assert repo not in path.parents or ".git" in path.parts
    assert not (repo / "telemetry.jsonl").exists()
    assert telemetry.summarize(repo)["peak_active_agents"] == 2


def test_summary_counts_only_observed_values(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    telemetry.record(repo, {"event": "review_result", "role": "reviewer_high", "review_round": 1, "blocking_findings": 2})
    telemetry.record(repo, {"event": "phase_complete", "phase": "review", "duration_ms": 250, "input_tokens": 10, "output_tokens": 4})
    summary = telemetry.summarize(repo)
    assert summary["records"] == 2
    assert summary["review_round_max"] == 1
    assert summary["blocking_findings_total"] == 2
    assert summary["duration_ms_total"] == 250
    assert summary["token_observation_records"] == 1
    assert summary["input_tokens_observed"] == 10
    assert summary["cached_input_tokens_observed"] == 0
    assert summary["output_tokens_observed"] == 4


def test_rejects_untrusted_or_fabricated_shape(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    with pytest.raises(ValueError, match="unsupported telemetry event"):
        telemetry.record(repo, {"event": "merge_now"})
    with pytest.raises(ValueError, match="non-negative integer"):
        telemetry.record(repo, {"event": "ci_rerun", "input_tokens": -1})
    with pytest.raises(ValueError, match="unknown telemetry fields"):
        telemetry.record(repo, {"event": "ci_rerun", "prompt": "secret text"})
