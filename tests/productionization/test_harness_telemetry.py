from __future__ import annotations

import importlib.util
import json
import os
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


def _r1_filename(path: object) -> str | None:
    return None if isinstance(path, int) else Path(os.fsdecode(path)).name


def _r1_patch_os(patch, name: str, replacement) -> None:
    original = getattr(os, name)
    # The interceptor forwards descriptor/flag arguments without changing platform support.
    for capability in ("supports_dir_fd", "supports_fd", "supports_follow_symlinks", "supports_effective_ids"):
        supported = getattr(os, capability)
        if original in supported:
            patch.setattr(os, capability, supported | {replacement})
    patch.setattr(os, name, replacement)


@pytest.mark.parametrize("schema_version", (1, 2))
def test_r1_hardlinked_stream_rejects_append_and_preserves_both_links(
    tmp_path: Path, schema_version: int
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    payload = _usage_event() if schema_version == 2 else {"event": "ci_rerun", "observed_at_ms": 1}
    path = telemetry.record(repo, payload)
    outside = tmp_path / "outside-evidence.jsonl"
    os.link(path, outside)
    before = outside.read_bytes()
    identity = (outside.stat().st_dev, outside.stat().st_ino, outside.stat().st_nlink)

    error = None
    try:
        telemetry.record(repo, payload)
    except (OSError, ValueError) as exc:
        error = exc

    assert outside.read_bytes() == before, "append changed evidence through an outside hardlink"
    assert path.read_bytes() == before
    for link in (path, outside):
        info = link.stat()
        assert (info.st_dev, info.st_ino, info.st_nlink) == identity
    assert error is not None, "multiply linked writable streams must be rejected"


@pytest.mark.parametrize("schema_version", (1, 2))
@pytest.mark.parametrize("operation", ("record", "load"))
def test_r1_metadata_swap_at_stream_operation_cannot_redirect_evidence(
    tmp_path: Path, monkeypatch, schema_version: int, operation: str
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    payload = _usage_event() if schema_version == 2 else {"event": "ci_rerun", "observed_at_ms": 1}
    path = telemetry.record(repo, payload)
    original_rows = telemetry.load(repo, schema_version=schema_version)
    metadata = path.parent
    held = metadata.with_name("held-metadata")
    outside = tmp_path / "outside-metadata"
    outside.mkdir()
    outside_stream = outside / path.name
    outside_stream.write_text(json.dumps({**payload, "observed_at_ms": 999}) + "\n")
    before = {entry.name: entry.read_bytes() for entry in outside.iterdir()}
    swapped = False

    def intercept(real_operation):
        def wrapped(target, *args, **kwargs):
            nonlocal swapped
            if not swapped and _r1_filename(target) == path.name:
                swapped = True
                metadata.rename(held)
                metadata.symlink_to(outside, target_is_directory=True)
            return real_operation(target, *args, **kwargs)

        return wrapped

    result = None
    with monkeypatch.context() as patch:
        for name in ("lstat", "stat", "open"):
            _r1_patch_os(patch, name, intercept(getattr(os, name)))
        try:
            if operation == "record":
                telemetry.record(repo, payload)
            else:
                result = telemetry.load(repo, schema_version=schema_version)
        except (OSError, ValueError):
            pass

    assert swapped, "the stream filesystem boundary was not exercised"
    assert {entry.name: entry.read_bytes() for entry in outside.iterdir()} == before
    if result is not None:
        assert result == original_rows, "load followed a replaced metadata ancestor"


@pytest.mark.parametrize("schema_version", (1, 2))
@pytest.mark.parametrize("replacement_kind", ("valid", "malformed"))
def test_r1_equal_size_stream_replacement_after_read_is_rejected_without_append(
    tmp_path: Path, monkeypatch, schema_version: int, replacement_kind: str
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    payload = _usage_event() if schema_version == 2 else {"event": "ci_rerun", "observed_at_ms": 1}
    path = telemetry.record(repo, payload)
    before = path.read_bytes()
    replacement = path.with_name("replacement.jsonl")
    if replacement_kind == "valid":
        # Both changes preserve byte length; v2 changes conflict at the same revision.
        replaced = before.replace(b'"input_tokens":100', b'"input_tokens":900') if schema_version == 2 else before.replace(b'"observed_at_ms":1', b'"observed_at_ms":2')
    else:
        replaced = b"x" * (len(before) - 1) + b"\n"
    assert replaced != before and len(replaced) == len(before)
    replacement.write_bytes(replaced)
    identity = path.stat()
    real_read = os.read
    swapped = False
    bytes_read = 0

    def read_and_replace(fd: int, size: int) -> bytes:
        nonlocal swapped, bytes_read
        data = real_read(fd, size)
        current = os.fstat(fd)
        if not swapped and (current.st_dev, current.st_ino) == (
            identity.st_dev, identity.st_ino
        ):
            bytes_read += len(data)
            if bytes_read >= identity.st_size:
                # The read descriptor still holds the original bytes after its name is replaced.
                swapped = True
                replacement.replace(path)
        return data

    error = None
    with monkeypatch.context() as patch:
        patch.setattr(os, "read", read_and_replace)
        try:
            telemetry.record(repo, payload)
        except (OSError, ValueError) as exc:
            error = exc

    assert swapped, "the stream read boundary was not exercised"
    assert path.read_bytes() == replaced, "append modified a replacement stream of equal size"
    assert error is not None, "replacement of the validated stream entry must reject the append"


def test_r1_disappearing_append_locks_still_obey_the_deadline(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    path = telemetry.record(repo, {"event": "ci_rerun"})
    before = path.read_bytes()
    now = 0.0
    attempts = 0
    real_open = os.open
    real_lstat = os.lstat
    real_stat = os.stat
    lock_name = f".{path.name}.lock"

    def vanished_open(target, flags, *args, **kwargs):
        nonlocal now, attempts
        if _r1_filename(target) == lock_name and flags & os.O_EXCL:
            attempts += 1
            now += 0.25
            if attempts > 16:
                raise AssertionError("disappearing locks retried beyond the bounded deadline")
            raise FileExistsError("disposable vanished lock")
        return real_open(target, flags, *args, **kwargs)

    def vanished_stat(real_operation):
        def wrapped(target, *args, **kwargs):
            if _r1_filename(target) == lock_name:
                raise FileNotFoundError("disposable vanished lock")
            return real_operation(target, *args, **kwargs)

        return wrapped

    with monkeypatch.context() as patch:
        _r1_patch_os(patch, "open", vanished_open)
        _r1_patch_os(patch, "lstat", vanished_stat(real_lstat))
        _r1_patch_os(patch, "stat", vanished_stat(real_stat))
        patch.setattr(telemetry.time, "monotonic", lambda: now)
        with pytest.raises((OSError, ValueError)):
            telemetry.record(repo, {"event": "ci_rerun"})

    assert attempts > 0
    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", ("O_NOFOLLOW", "O_DIRECTORY", "dir_fd", "fd_scandir"))
def test_r1_unsupported_storage_primitives_fail_before_metadata_mutation(
    tmp_path: Path, monkeypatch, missing: str
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    if missing in {"O_NOFOLLOW", "O_DIRECTORY"}:
        monkeypatch.delattr(os, missing, raising=False)
    elif missing == "dir_fd":
        monkeypatch.setattr(os, "supports_dir_fd", set())
    else:
        monkeypatch.setattr(os, "supports_fd", os.supports_fd - {os.scandir})

    error = None
    try:
        telemetry.record(repo, {"event": "ci_rerun"})
    except (OSError, ValueError) as exc:
        error = exc

    assert not (repo / ".git/codex-harness").exists(), "unsupported storage used a path fallback"
    assert error is not None
    assert len(str(error)) <= 256
    assert str(repo) not in str(error)


@pytest.mark.parametrize(
    "pr_id",
    ("FND-01", "PIT-01", "SIG-01", "BT-01", "RSK-01", "EXC-01", "EXP-01", "OMS-01", "FWD-01", "LIVE-01"),
)
def test_r1_legacy_roadmap_identifiers_remain_valid_telemetry_metadata(
    tmp_path: Path, pr_id: str
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    payload = {"event": "phase_complete", "pr_id": pr_id, "observed_at_ms": 1}

    telemetry.record(repo, payload)

    assert telemetry.load(repo) == [payload]


@pytest.mark.parametrize(
    ("field", "total_key"),
    (
        ("duration_ms", "duration_ms_total"),
        ("blocking_findings", "blocking_findings_total"),
        ("input_tokens", "input_tokens_observed"),
        ("cached_input_tokens", "cached_input_tokens_observed"),
        ("output_tokens", "output_tokens_observed"),
    ),
)
@pytest.mark.parametrize("increment", (0, 1))
def test_r2_legacy_additive_summary_bounds_preserve_evidence(
    tmp_path: Path, field: str, total_key: str, increment: int
) -> None:
    repo = _repo(tmp_path)
    telemetry = _module()
    maximum = 2**63 - 1
    path = telemetry.record(repo, {"event": "phase_complete", "observed_at_ms": 1, field: maximum})
    telemetry.record(repo, {"event": "phase_complete", "observed_at_ms": 2, field: increment})
    before = path.read_bytes()

    try:
        if increment == 0:
            assert telemetry.summarize(repo)[total_key] == maximum
        else:
            with pytest.raises(ValueError) as error:
                telemetry.summarize(repo)
            assert str(maximum) not in str(error.value)
            assert str(repo) not in str(error.value)
            assert len(str(error.value)) <= 256
    finally:
        assert path.read_bytes() == before
