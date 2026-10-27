from __future__ import annotations

import importlib.util
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
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
    repo.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    return repo


def _usage(*, observation_ref: str = "a" * 64, revision: int = 0, input_tokens: int | None = 100) -> dict:
    return {
        "observation_ref": observation_ref,
        "revision": revision,
        "source_kind": "runtime_report",
        "usage_scope": "task",
        "aggregation_scope": "exclusive",
        "input_tokens": input_tokens,
        "cached_input_tokens": 20,
        "cache_write_tokens": 0,
        "cache_write_30m_tokens": 0,
        "cache_write_12h_tokens": 0,
        "output_tokens": 30,
        "reasoning_output_tokens": 10,
    }


def _usage_event(*, model: str = "gpt-6-luna", usage: dict | None = None) -> dict:
    return {
        "schema_version": 2,
        "event": "usage_observation",
        "observed_at_ms": 1_800_000_000_000,
        "role": "normal_implementer",
        "model": model,
        "effort": "max",
        "head_sha": "c" * 40,
        "pr_ref": "d" * 64,
        "usage": usage if usage is not None else _usage(),
    }


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


def test_legacy_metadata_domains_preserve_historical_models_and_current_roles(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    historical_and_current_models = (
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-6-astra",
        "gpt-5.6-terra",
    )
    current_roles = (
        "master",
        "normal_implementer",
        "high_implementer",
        "critical_implementer",
        "reviewer_high",
        "reviewer_xhigh",
        "code_explorer",
        "test_auditor",
        "boundary_reviewer",
        "external_spec_researcher",
        "astra_canary",
    )
    for model in historical_and_current_models:
        telemetry.record(repo, {"event": "phase_complete", "model": model})
    for role in current_roles:
        telemetry.record(repo, {"event": "review_result", "role": role})
    for effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
        telemetry.record(repo, {"event": "phase_complete", "model": "gpt-6.1-sol", "effort": effort})

    assert len(telemetry.load(repo)) == len(historical_and_current_models) + len(current_roles) + 8
    with pytest.raises(ValueError, match="model"):
        telemetry.record(repo, {"event": "phase_complete", "model": "unknown-model"})
    with pytest.raises(ValueError, match="role"):
        telemetry.record(repo, {"event": "review_result", "role": "unknown-role"})


def test_v2_usage_stream_is_separate_and_legacy_summary_marks_unknown_cache(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    legacy_path = telemetry.record(
        repo,
        {"event": "phase_complete", "input_tokens": 10, "output_tokens": 4},
    )
    legacy_bytes = legacy_path.read_bytes()

    v2_path = telemetry.record(repo, _usage_event())
    assert v2_path != legacy_path
    assert v2_path.name == "telemetry-v2.jsonl"
    assert legacy_path.read_bytes() == legacy_bytes
    assert json.loads(v2_path.read_text(encoding="utf-8")) == _usage_event()

    summary = telemetry.summarize(repo)
    assert summary["records"] == 1
    assert summary["input_tokens_observed"] == 10
    assert summary["cached_input_tokens_observed"] == 0
    assert summary["legacy_token_accounting_complete"] is False


def test_usage_snapshot_series_replaces_revisions_and_cannot_rebind_outer_identity(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, _usage_event(usage=_usage(revision=0, input_tokens=100)))
    telemetry.record(repo, _usage_event(usage=_usage(revision=1, input_tokens=120)))
    before = path.read_bytes()

    conflicting = _usage_event(
        model="gpt-6-sol",
        usage=_usage(revision=2, input_tokens=140),
    )
    try:
        telemetry.record(repo, conflicting)
    except ValueError as error:
        assert "identity" in str(error)
    else:
        with pytest.raises(ValueError, match="identity"):
            telemetry.summarize(repo)
    assert path.read_bytes().startswith(before)


def test_identical_usage_retry_with_later_observation_time_is_not_double_counted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    event = _usage_event()
    path = telemetry.record(repo, event)
    retry = {**event, "observed_at_ms": event["observed_at_ms"] + 60_000}
    retry["usage"] = dict(reversed(list(event["usage"].items())))
    telemetry.record(repo, retry)

    summary = telemetry.summarize(repo)
    assert summary["usage_v2_records"] == 2
    assert summary["usage_v2"]["by_usage_scope"]["task"]["coverage"][
        "selected_records"
    ] == 1
    assert summary["usage_v2"]["by_usage_scope"]["task"]["complete_totals"][
        "input_tokens"
    ] == 100
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_v2_metadata_and_pseudonymous_references_are_validated_without_echo(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    invalid = _usage_event(model="private-model-marker")
    with pytest.raises(ValueError) as error:
        telemetry.record(repo, invalid)
    assert "private-model-marker" not in str(error.value)

    invalid = _usage_event(usage=_usage(observation_ref="not-a-pseudonymous-reference"))
    with pytest.raises(ValueError) as error:
        telemetry.record(repo, invalid)
    assert "not-a-pseudonymous-reference" not in str(error.value)


def test_v2_stream_rejects_symlink_target_without_modifying_outside_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    metadata = repo / ".git/codex-harness"
    metadata.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"keep this evidence\n")
    target = metadata / "telemetry-v2.jsonl"
    target.symlink_to(outside)

    with pytest.raises((OSError, ValueError)):
        telemetry.record(repo, _usage_event())
    assert outside.read_bytes() == b"keep this evidence\n"


def test_metadata_directory_symlink_is_rejected_without_outside_write(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    telemetry = _module()
    outside = tmp_path / "outside-metadata"
    outside.mkdir()
    (repo / ".git/codex-harness").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        telemetry.record(repo, {"event": "ci_rerun"})
    assert not (outside / "telemetry.jsonl").exists()


@pytest.mark.parametrize("redirect", ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE"))
def test_git_redirect_environment_does_not_select_another_repository_metadata(
    tmp_path: Path,
    monkeypatch,
    redirect: str,
) -> None:
    repo = _repo(tmp_path / "target")
    redirected = _repo(tmp_path / "redirected")
    telemetry = _module()
    if redirect == "GIT_DIR":
        monkeypatch.setenv("GIT_DIR", str(redirected / ".git"))
    elif redirect == "GIT_COMMON_DIR":
        monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
        monkeypatch.setenv("GIT_COMMON_DIR", str(redirected / ".git"))
    else:
        monkeypatch.setenv("GIT_DIR", str(redirected / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(repo))

    path = telemetry.record(repo, {"event": "ci_rerun"})
    assert path == repo / ".git/codex-harness/telemetry.jsonl"
    assert not (redirected / ".git/codex-harness/telemetry.jsonl").exists()


def test_linked_worktree_telemetry_uses_canonical_git_common_metadata(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test User"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (repo / "tracked.txt").write_text("tracked", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "test base"], check=True)
    linked = tmp_path / "linked-worktree"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", "telemetry-test", str(linked)],
        check=True,
    )
    telemetry = _module()

    path = telemetry.record(linked, {"event": "ci_rerun"})
    assert path == repo / ".git/codex-harness/telemetry.jsonl"
    assert not (linked / ".git/codex-harness/telemetry.jsonl").exists()


def test_legacy_partial_tail_is_failure_and_is_not_rewritten(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, {"event": "ci_rerun"})
    with path.open("ab") as handle:
        handle.write(b'{"event":')
    before = path.read_bytes()

    with pytest.raises((ValueError, OSError)):
        telemetry.load(repo)
    assert path.read_bytes() == before


def test_v2_partial_tail_is_failure_and_is_not_rewritten(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, _usage_event())
    with path.open("ab") as handle:
        handle.write(b'{"schema_version":2')
    before = path.read_bytes()

    with pytest.raises(ValueError, match="incomplete tail"):
        telemetry.load(repo, schema_version=2)
    assert path.read_bytes() == before


def test_forced_append_contention_fails_without_changing_stream(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, {"event": "ci_rerun"})
    before = path.read_bytes()
    lock = path.with_name(f".{path.name}.lock")
    lock.write_bytes(b"")

    with pytest.raises(ValueError, match="contended"):
        telemetry.record(repo, {"event": "ci_rerun"})
    assert path.read_bytes() == before
    assert lock.is_file()


def test_concurrent_legacy_appends_leave_only_complete_jsonl_records(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    payloads = [
        {"event": "ci_rerun", "observed_at_ms": index}
        for index in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda payload: telemetry.record(repo, payload), payloads))

    rows = telemetry.load(repo)
    assert len(rows) == len(payloads)
    assert {row["observed_at_ms"] for row in rows} == set(range(16))


def test_telemetry_labels_and_timestamp_are_bounded() -> None:
    telemetry = _module()
    with pytest.raises(ValueError, match="observed_at_ms"):
        telemetry._validate({"event": "ci_rerun", "observed_at_ms": 2**63})
    with pytest.raises(ValueError, match="pr_id"):
        telemetry._validate({"event": "review_result", "pr_id": "x" * 129})
