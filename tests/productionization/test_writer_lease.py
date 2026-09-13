"""RED contract for the cooperative repository-global writer lease."""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import multiprocessing
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/writer_lease.py"
STATE_DIRECTORY = "codex-writer-lease"
ZERO_DIGEST = "0" * 64
OWNER_REF = "a" * 64
SESSION_REF = "b" * 64
OTHER_OWNER_REF = "c" * 64
OTHER_SESSION_REF = "d" * 64
PR_ID = "HARNESS-AUD-05"
WRITER_ROLE = "normal_implementer"
OTHER_WRITER_ROLE = "high_implementer"
WRITER_ROLES = {
    "normal_implementer",
    "high_implementer",
    "critical_implementer",
}

# These caller-supplied digests are pseudonymous correlation references. They do not
# authenticate a runtime owner or session identity.
assert re.fullmatch(r"[0-9a-f]{64}", OWNER_REF)
assert re.fullmatch(r"[0-9a-f]{64}", SESSION_REF)


def _load_module(path: Path, name: str = "writer_lease_contract") -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_writer_lease_contract_is_implemented() -> None:
    assert SCRIPT.is_file(), "missing implementation: scripts/writer_lease.py"


@pytest.fixture(scope="module")
def lease() -> ModuleType:
    if not SCRIPT.is_file():
        pytest.skip("GREEN implementation is intentionally absent at the RED commit")
    return _load_module(SCRIPT)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _repository(tmp_path: Path) -> tuple[Path, Path, str, Path]:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    primary.mkdir()
    subprocess.run(["git", "-C", str(primary), "init", "-q"], check=True)
    (primary / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "-c",
            "user.name=Writer Lease Test",
            "-c",
            "user.email=writer-lease@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    base_sha = _git(primary, "rev-parse", "HEAD")
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "worktree",
            "add",
            "--detach",
            "-q",
            str(linked),
            base_sha,
        ],
        check=True,
    )
    common = Path(_git(primary, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return primary, linked, base_sha, common


def _identity(base_sha: str, **overrides: str) -> dict[str, str]:
    values = {
        "pr_id": PR_ID,
        "base_sha": base_sha,
        "writer_role": WRITER_ROLE,
        "owner_ref": OWNER_REF,
        "session_ref": SESSION_REF,
    }
    values.update(overrides)
    return values


def _assert_bound_identity(
    record: dict[str, Any],
    *,
    base_sha: str,
    lease_id: str,
    **overrides: str,
) -> None:
    expected = _identity(base_sha, **overrides)
    expected["lease_id"] = lease_id
    assert {field: record[field] for field in expected} == expected


def _acquire(
    module: ModuleType, repo: Path, base_sha: str, **overrides: str
) -> dict[str, Any]:
    result = module.acquire(repo_root=repo, **_identity(base_sha, **overrides))
    assert type(result) is dict
    assert re.fullmatch(r"[0-9a-f]{64}", result["lease_id"])
    _assert_bound_identity(
        result,
        base_sha=base_sha,
        lease_id=result["lease_id"],
        **overrides,
    )
    return result


def _verify(
    module: ModuleType,
    repo: Path,
    base_sha: str,
    lease_id: str,
    *,
    checkpoint: str = "writer_start",
    phase: str = "harness-aud-05",
    **overrides: str,
) -> dict[str, Any]:
    result = module.verify(
        repo_root=repo,
        lease_id=lease_id,
        checkpoint=checkpoint,
        phase=phase,
        **_identity(base_sha, **overrides),
    )
    assert type(result) is dict
    _assert_bound_identity(
        result,
        base_sha=base_sha,
        lease_id=lease_id,
        **overrides,
    )
    return result


def _release(
    module: ModuleType,
    repo: Path,
    base_sha: str,
    lease_id: str,
    **overrides: str,
) -> dict[str, Any]:
    result = module.release(
        repo_root=repo,
        lease_id=lease_id,
        **_identity(base_sha, **overrides),
    )
    assert type(result) is dict
    _assert_bound_identity(
        result,
        base_sha=base_sha,
        lease_id=lease_id,
        **overrides,
    )
    return result


def _state_dir(common: Path) -> Path:
    return common / STATE_DIRECTORY


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _race_worker(
    script: str,
    repo: str,
    base_sha: str,
    pr_id: str,
    writer_role: str,
    owner_ref: str,
    session_ref: str,
    barrier: Any,
    queue: Any,
) -> None:
    module = _load_module(Path(script), f"writer_lease_race_{owner_ref[:8]}")
    barrier.wait()
    try:
        result = module.acquire(
            repo_root=Path(repo),
            pr_id=pr_id,
            base_sha=base_sha,
            writer_role=writer_role,
            owner_ref=owner_ref,
            session_ref=session_ref,
        )
    except BaseException as exc:  # pragma: no cover - asserted in parent process
        queue.put(("rejected", type(exc).__name__))
    else:
        queue.put(("acquired", result["lease_id"]))


def _run_race(
    module: ModuleType,
    repo: Path,
    base_sha: str,
    pr_ids: list[str],
) -> list[tuple[str, str]]:
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(len(pr_ids))
    queue = context.Queue()
    processes = []
    for index, pr_id in enumerate(pr_ids):
        process = context.Process(
            target=_race_worker,
            args=(
                str(SCRIPT),
                str(repo),
                base_sha,
                pr_id,
                WRITER_ROLE,
                f"{index + 1:064x}",
                f"{index + 101:064x}",
                barrier,
                queue,
            ),
        )
        process.start()
        processes.append(process)
    results = [queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert module.inspect(repo_root=repo)["status"] == "active"
    return results


@pytest.mark.parametrize(
    "pr_ids",
    [
        [PR_ID] * 6,
        [f"HARNESS-AUD-{index:02d}" for index in range(10, 16)],
    ],
)
def test_multiprocess_race_has_exactly_one_winner_repo_globally(
    lease: ModuleType,
    tmp_path: Path,
    pr_ids: list[str],
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    results = _run_race(lease, primary, base_sha, pr_ids)
    assert [status for status, _ in results].count("acquired") == 1
    assert [status for status, _ in results].count("rejected") == len(pr_ids) - 1


def test_primary_and_linked_worktrees_share_one_fixed_common_dir_lease(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(
            lease,
            linked,
            base_sha,
            pr_id="HARNESS-AUD-99",
            owner_ref=OTHER_OWNER_REF,
            session_ref=OTHER_SESSION_REF,
        )
    assert _state_dir(common).parent == common.resolve()
    assert _state_dir(common).is_dir()
    assert not (primary / STATE_DIRECTORY).exists()
    active = lease.inspect(repo_root=linked)["active"]
    _assert_bound_identity(active, base_sha=base_sha, lease_id=acquired["lease_id"])


@pytest.mark.parametrize("writer_role", sorted(WRITER_ROLES))
def test_acquire_is_non_idempotent_and_verify_stays_bound_to_stable_base(
    lease: ModuleType, tmp_path: Path, writer_role: str
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha, writer_role=writer_role)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha, writer_role=writer_role)
    (primary / "tracked.txt").write_text("writer commit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(primary), "add", "tracked.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(primary),
            "-c",
            "user.name=Writer Lease Test",
            "-c",
            "user.email=writer-lease@example.invalid",
            "commit",
            "-qm",
            "writer advances head",
        ],
        check=True,
    )
    assert _git(primary, "rev-parse", "HEAD") != base_sha
    verified = _verify(
        lease,
        primary,
        base_sha,
        acquired["lease_id"],
        writer_role=writer_role,
    )
    assert verified["lease_id"] == acquired["lease_id"]


@pytest.mark.parametrize(
    "field",
    ["lease_id", "pr_id", "base_sha", "writer_role", "owner_ref", "session_ref"],
)
def test_wrong_identity_never_verifies_or_releases(
    lease: ModuleType, tmp_path: Path, field: str
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    values = {
        "lease_id": acquired["lease_id"],
        "pr_id": PR_ID,
        "base_sha": base_sha,
        "writer_role": WRITER_ROLE,
        "owner_ref": OWNER_REF,
        "session_ref": SESSION_REF,
    }
    values[field] = {
        "lease_id": "f" * 64,
        "pr_id": "HARNESS-AUD-99",
        "base_sha": "e" * 40,
        "writer_role": OTHER_WRITER_ROLE,
        "owner_ref": OTHER_OWNER_REF,
        "session_ref": OTHER_SESSION_REF,
    }[field]
    with pytest.raises(lease.WriterLeaseError):
        lease.verify(
            repo_root=primary,
            checkpoint="writer_start",
            phase="harness-aud-05",
            **values,
        )
    with pytest.raises(lease.WriterLeaseError):
        lease.release(repo_root=primary, **values)
    assert lease.inspect(repo_root=primary)["status"] == "active"


def test_checkpoint_lifecycle_and_release_are_durable_and_ordered(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    for checkpoint in (
        "writer_start",
        "before_red",
        "before_green",
        "before_commit",
        "before_push",
    ):
        _verify(
            lease,
            primary,
            base_sha,
            acquired["lease_id"],
            checkpoint=checkpoint,
            phase=f"phase-{checkpoint}",
        )
    _release(lease, primary, base_sha, acquired["lease_id"])

    state = _state_dir(common)
    assert not (state / "active.json").exists()
    event_paths = sorted((state / "events").glob("*.json"))
    assert [path.name for path in event_paths] == [
        f"{index:08d}.json" for index in range(len(event_paths))
    ]
    assert len(event_paths) == 7
    previous = ZERO_DIGEST
    observed = []
    for sequence, path in enumerate(event_paths):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        raw = path.read_bytes()
        assert raw == _canonical(json.loads(raw))
        event = json.loads(raw)
        assert event["sequence"] == sequence
        assert event["previous_event_digest"] == previous
        _assert_bound_identity(
            event,
            base_sha=base_sha,
            lease_id=acquired["lease_id"],
        )
        previous = hashlib.sha256(raw).hexdigest()
        observed.append(event["event_type"])
    assert observed == ["acquire", "verify", "verify", "verify", "verify", "verify", "release"]
    assert lease.inspect(repo_root=primary)["status"] == "released"


def test_state_permissions_and_create_flags_are_fail_closed(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    calls: list[tuple[int, int]] = []
    real_open = lease.os.open

    def recording_open(path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        if flags & os.O_CREAT:
            calls.append((flags, mode))
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(lease.os, "open", recording_open)
    acquired = _acquire(lease, primary, base_sha)
    state = _state_dir(common)
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "active.json").stat().st_mode) == 0o600
    _assert_bound_identity(
        json.loads((state / "active.json").read_bytes()),
        base_sha=base_sha,
        lease_id=acquired["lease_id"],
    )
    assert calls
    for flags, mode in calls:
        assert flags & os.O_CREAT
        assert flags & os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            assert flags & os.O_NOFOLLOW
        assert mode == 0o600


def test_complete_write_loop_handles_short_os_writes(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    real_write = lease.os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[: max(1, min(3, len(data)))])

    monkeypatch.setattr(lease.os, "write", short_write)
    acquired = _acquire(lease, primary, base_sha)
    _assert_bound_identity(
        lease.inspect(repo_root=primary)["active"],
        base_sha=base_sha,
        lease_id=acquired["lease_id"],
    )


@pytest.mark.parametrize("node_kind", ["malformed", "symlink", "fifo", "directory", "unsafe_mode"])
def test_hostile_active_node_is_never_followed_replaced_or_auto_removed(
    lease: ModuleType, tmp_path: Path, node_kind: str
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    active = _state_dir(common) / "active.json"
    valid = active.read_bytes()
    _release(lease, primary, base_sha, acquired["lease_id"])
    target = tmp_path / "outside-canary"
    target.write_text("must-not-change", encoding="utf-8")
    if node_kind == "malformed":
        active.write_bytes(b"{")
        active.chmod(0o600)
    elif node_kind == "symlink":
        active.symlink_to(target)
    elif node_kind == "fifo":
        os.mkfifo(active, 0o600)
    elif node_kind == "directory":
        active.mkdir(mode=0o700)
    else:
        active.write_bytes(valid)
        active.chmod(0o644)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(
            lease,
            primary,
            base_sha,
            owner_ref=OTHER_OWNER_REF,
            session_ref=OTHER_SESSION_REF,
        )
    assert active.exists() or active.is_symlink()
    assert target.read_text(encoding="utf-8") == "must-not-change"


def test_symlinked_state_directory_and_unsafe_common_directory_fail_closed(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    state = _state_dir(common)
    state.symlink_to(outside, target_is_directory=True)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha)
    assert list(outside.iterdir()) == []
    state.unlink()
    original_mode = stat.S_IMODE(common.stat().st_mode)
    common.chmod(original_mode | stat.S_IWGRP | stat.S_IWOTH)
    try:
        with pytest.raises(lease.WriterLeaseError):
            _acquire(lease, primary, base_sha)
    finally:
        common.chmod(original_mode)


@pytest.mark.skipif(os.geteuid() != 0, reason="safe wrong-owner fixture requires root")
def test_wrong_owner_active_file_fails_closed(lease: ModuleType, tmp_path: Path) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    active = _state_dir(common) / "active.json"
    os.chown(active, 1, -1)
    with pytest.raises(lease.WriterLeaseError):
        _verify(lease, primary, base_sha, acquired["lease_id"])


def test_git_environment_redirects_and_trace_writes_are_ignored(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    poison = tmp_path / "poison"
    trace = tmp_path / "git-trace-canary"
    for name, value in {
        "GIT_DIR": str(poison / "dir"),
        "GIT_COMMON_DIR": str(poison / "common"),
        "GIT_WORK_TREE": str(poison / "tree"),
        "GIT_INDEX_FILE": str(poison / "index"),
        "GIT_OBJECT_DIRECTORY": str(poison / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(poison / "alternate"),
        "GIT_CONFIG_GLOBAL": str(poison / "global-config"),
        "GIT_CONFIG_SYSTEM": str(poison / "system-config"),
        "GIT_TRACE": str(trace),
        "GIT_TRACE2_EVENT": str(trace),
    }.items():
        monkeypatch.setenv(name, value)
    _acquire(lease, primary, base_sha)
    assert _state_dir(common).is_dir()
    assert not poison.exists()
    assert not trace.exists()


def test_operation_does_not_mutate_source_ref_index_config_or_worktree_registration(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    before = {
        "head": _git(primary, "rev-parse", "HEAD"),
        "tree": _git(primary, "write-tree"),
        "status": _git(primary, "status", "--porcelain=v1", "--untracked-files=all"),
        "config": _git(primary, "config", "--local", "--list"),
        "worktrees": _git(primary, "worktree", "list", "--porcelain"),
    }
    acquired = _acquire(lease, primary, base_sha)
    _verify(lease, primary, base_sha, acquired["lease_id"], checkpoint="before_red")
    _release(lease, primary, base_sha, acquired["lease_id"])
    after = {
        "head": _git(primary, "rev-parse", "HEAD"),
        "tree": _git(primary, "write-tree"),
        "status": _git(primary, "status", "--porcelain=v1", "--untracked-files=all"),
        "config": _git(primary, "config", "--local", "--list"),
        "worktrees": _git(primary, "worktree", "list", "--porcelain"),
    }
    assert after == before


def test_canonical_ascii_json_has_golden_bytes_and_digest(lease: ModuleType) -> None:
    value = {
        "event_type": "verify",
        "lease_id": "e" * 64,
        "previous_event_digest": "f" * 64,
        "sequence": 1,
    }
    expected = (
        b'{"event_type":"verify","lease_id":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",'
        b'"previous_event_digest":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",'
        b'"sequence":1}'
    )
    assert lease.canonical_json_bytes(value) == expected
    assert hashlib.sha256(expected).hexdigest() == (
        "e9a98ea4e4d375fd332b7a90aa6ccb5acb221ce875a19e6073a87621f51805f6"
    )


def _completed_evidence(
    module: ModuleType, tmp_path: Path
) -> tuple[bytes, Path, str, str]:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    acquired = _acquire(module, primary, base_sha)
    _verify(module, primary, base_sha, acquired["lease_id"])
    _release(module, primary, base_sha, acquired["lease_id"])
    raw = module.export_evidence(
        repo_root=primary,
        lease_id=acquired["lease_id"],
        **_identity(base_sha),
    )
    assert type(raw) is bytes
    return raw, primary, base_sha, acquired["lease_id"]


def test_export_is_bounded_canonical_and_structurally_valid(
    lease: ModuleType, tmp_path: Path
) -> None:
    raw, _primary, base_sha, lease_id = _completed_evidence(lease, tmp_path)
    assert len(raw) <= lease.MAX_EVIDENCE_BYTES <= 262_144
    assert raw == _canonical(json.loads(raw))
    parsed = lease.validate_evidence(raw)
    _assert_bound_identity(parsed, base_sha=base_sha, lease_id=lease_id)
    for event in parsed["events"]:
        _assert_bound_identity(event, base_sha=base_sha, lease_id=lease_id)
    assert [event["event_type"] for event in parsed["events"]] == [
        "acquire",
        "verify",
        "release",
    ]
    assert lease.evidence_digest(raw) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "unknown",
        "trailing",
        "noncanonical",
        "bool_int",
        "unicode_confusable",
        "path",
        "oversize",
    ],
)
def test_evidence_parser_rejects_hostile_json_and_identifiers(
    lease: ModuleType, tmp_path: Path, mutation: str
) -> None:
    raw, _primary, _base_sha, _lease_id = _completed_evidence(lease, tmp_path)
    parsed = json.loads(raw)
    if mutation == "duplicate":
        hostile = raw.replace(b"{", b'{"schema_version":1,', 1)
    elif mutation == "unknown":
        parsed["unexpected"] = "field"
        hostile = _canonical(parsed)
    elif mutation == "trailing":
        hostile = raw + b"\n{}"
    elif mutation == "noncanonical":
        hostile = json.dumps(parsed, indent=2).encode("ascii")
    elif mutation == "bool_int":
        parsed["schema_version"] = True
        hostile = _canonical(parsed)
    elif mutation == "unicode_confusable":
        parsed["pr_id"] = "HARNESS-\N{CYRILLIC CAPITAL LETTER A}UD-05"
        hostile = _canonical(parsed)
    elif mutation == "path":
        parsed["pr_id"] = "../HARNESS-AUD-05"
        hostile = _canonical(parsed)
    else:
        hostile = b"{" + (b"x" * (lease.MAX_EVIDENCE_BYTES + 1))
    with pytest.raises(lease.WriterLeaseError):
        lease.validate_evidence(hostile)


@pytest.mark.parametrize(
    "mutation",
    ["gap", "reorder", "cross_lease", "predecessor", "event_unknown", "capacity"],
)
def test_structural_validation_rejects_broken_event_chains(
    lease: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    raw, _primary, _base_sha, _lease_id = _completed_evidence(lease, tmp_path)
    parsed = json.loads(raw)
    events = parsed["events"]
    if mutation == "gap":
        events[1]["sequence"] += 1
    elif mutation == "reorder":
        events[0], events[1] = events[1], events[0]
    elif mutation == "cross_lease":
        events[1]["lease_id"] = "f" * 64
    elif mutation == "predecessor":
        events[1]["previous_event_digest"] = "f" * 64
    elif mutation == "event_unknown":
        events[1]["unexpected"] = 1
    else:
        monkeypatch.setattr(lease, "MAX_EVENT_COUNT", 4)
        parsed["events"] = events * 2
    with pytest.raises(lease.WriterLeaseError):
        lease.validate_evidence(_canonical(parsed))


@pytest.mark.parametrize(
    ("field", "hostile"),
    [
        ("pr_id", "HARNESS-AUD-05/../../escape"),
        ("writer_role", "reviewer_high"),
        ("owner_ref", "a" * 63),
        ("session_ref", "A" * 64),
        ("base_sha", "g" * 40),
    ],
)
def test_acquire_rejects_path_digest_case_and_size_attacks_without_reflection(
    lease: ModuleType,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    hostile: str,
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    canary = f"SECRET-{hostile}-CANARY"
    with pytest.raises(lease.WriterLeaseError) as exc_info:
        _acquire(lease, primary, base_sha, **{field: canary})
    captured = capsys.readouterr()
    combined = f"{exc_info.value}\n{captured.out}\n{captured.err}"
    assert canary not in combined


def test_raw_identifiers_paths_and_credentials_never_enter_state_or_evidence(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    _verify(lease, primary, base_sha, acquired["lease_id"])
    _release(lease, primary, base_sha, acquired["lease_id"])
    all_bytes = b"".join(
        path.read_bytes() for path in _state_dir(common).rglob("*") if path.is_file()
    )
    for forbidden in (
        str(primary).encode(),
        str(common).encode(),
        b"raw-session-id",
        b"raw-agent-id",
        b"transcript",
        b"credential",
        b"secret",
        b"token",
    ):
        assert forbidden not in all_bytes.lower()


def test_fault_before_active_create_never_produces_two_leases(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    real_open = lease.os.open
    injected = False

    def fail_first_create(path: object, flags: int, mode: int = 0o777, **kwargs: object) -> int:
        nonlocal injected
        if not injected and flags & os.O_CREAT:
            injected = True
            raise OSError("injected create failure")
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(lease.os, "open", fail_first_create)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha)
    active = _state_dir(common) / "active.json"
    assert not active.exists()
    acquired = _acquire(lease, primary, base_sha)
    _assert_bound_identity(
        lease.inspect(repo_root=primary)["active"],
        base_sha=base_sha,
        lease_id=acquired["lease_id"],
    )


def test_partial_active_write_fails_blocked_without_auto_recovery(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    real_write = lease.os.write
    calls = 0

    def fail_after_partial(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(fd, data[:3])
        raise OSError("injected write failure")

    monkeypatch.setattr(lease.os, "write", fail_after_partial)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha)
    assert (_state_dir(common) / "active.json").exists()
    assert lease.inspect(repo_root=primary)["status"] == "blocked"
    with pytest.raises(lease.WriterLeaseError):
        _acquire(
            lease,
            primary,
            base_sha,
            owner_ref=OTHER_OWNER_REF,
            session_ref=OTHER_SESSION_REF,
        )


def test_event_fsync_failure_leaves_active_or_blocked_never_auto_recovered(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    state = _state_dir(common)
    real_fsync = lease.os.fsync

    def fail_when_event_exists(fd: int) -> None:
        events = state / "events"
        if events.is_dir() and any(events.iterdir()):
            raise OSError("injected event fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(lease.os, "fsync", fail_when_event_exists)
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha)
    assert (state / "active.json").exists()
    assert lease.inspect(repo_root=primary)["status"] == "blocked"


def test_release_event_precedes_unlink_and_unlink_failure_blocks_reacquire(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    active = _state_dir(common) / "active.json"
    real_unlink = lease.os.unlink

    def fail_active_unlink(path: object, **kwargs: object) -> None:
        if str(path).endswith("active.json"):
            raise OSError("injected unlink failure")
        real_unlink(path, **kwargs)

    monkeypatch.setattr(lease.os, "unlink", fail_active_unlink)
    with pytest.raises(lease.WriterLeaseError):
        _release(lease, primary, base_sha, acquired["lease_id"])
    assert active.exists()
    assert lease.inspect(repo_root=primary)["status"] == "blocked"
    with pytest.raises(lease.WriterLeaseError):
        _acquire(
            lease,
            primary,
            base_sha,
            owner_ref=OTHER_OWNER_REF,
            session_ref=OTHER_SESSION_REF,
        )


def test_event_capacity_supports_productionization_horizon_and_fails_closed(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert type(lease.MAX_EVENT_COUNT) is int
    assert 512 <= lease.MAX_EVENT_COUNT <= 4096
    monkeypatch.setattr(lease, "MAX_EVENT_COUNT", 4)
    primary, _linked, base_sha, _common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    for index in range(lease.MAX_EVENT_COUNT - 1):
        _verify(
            lease,
            primary,
            base_sha,
            acquired["lease_id"],
            checkpoint="before_commit",
            phase=f"p-{index}",
        )
    with pytest.raises(lease.WriterLeaseError):
        _verify(
            lease,
            primary,
            base_sha,
            acquired["lease_id"],
            checkpoint="before_push",
            phase="at-capacity",
        )
    assert lease.inspect(repo_root=primary)["status"] == "active"


def test_timestamps_are_not_validity_and_release_has_no_forgeable_stopped_proof(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    _release(lease, primary, base_sha, acquired["lease_id"])
    keys = {
        key
        for path in _state_dir(common).rglob("*.json")
        for key in json.loads(path.read_bytes())
    }
    assert not keys.intersection(
        {"timestamp", "created_at", "updated_at", "expires_at", "ttl", "heartbeat"}
    )
    release_parameters = inspect.signature(lease.release).parameters
    assert not set(release_parameters).intersection(
        {"force", "recover", "steal", "stopped", "stopped_proof", "master_proof"}
    )


def test_unsupported_platform_fails_closed(
    lease: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    monkeypatch.setattr(lease.sys, "platform", "win32")
    with pytest.raises(lease.WriterLeaseError):
        _acquire(lease, primary, base_sha)


def test_cli_surface_has_only_cooperative_lifecycle_actions(lease: ModuleType) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    lowered = result.stdout.lower()
    for action in ("acquire", "verify", "release", "inspect", "export", "validate"):
        assert action in lowered
    for forbidden in ("recover", "force", "steal", "ttl", "heartbeat", "cleanup", "stopped-proof"):
        assert forbidden not in lowered


def test_helper_is_isolated_from_telemetry_hooks_ci_network_and_roadmap_behavior(
    lease: ModuleType
) -> None:
    source = SCRIPT.read_text(encoding="utf-8").lower()
    for forbidden in (
        "codex-harness",
        "harness_telemetry",
        "codex_telemetry",
        ".codex/hooks",
        ".github/workflows",
        "requests.",
        "urllib",
        "http://",
        "https://",
        "broker",
        "paper",
        "sig-03",
    ):
        assert forbidden not in source
    checker_source = (ROOT / "scripts/check_agent_harness.py").read_text(encoding="utf-8")
    for required_static_contract in (
        "scripts/writer_lease.py",
        "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
        ".agents/skills/writer-lease/SKILL.md",
    ):
        assert required_static_contract in checker_source
    for forbidden_live_state_access in (
        "import writer_lease",
        "from writer_lease",
        "codex-writer-lease",
        "active.json",
        "export_evidence(",
    ):
        assert forbidden_live_state_access not in checker_source
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github/workflows").iterdir()
        if path.suffix in {".yml", ".yaml"}
    )
    assert "writer_lease" not in workflow_text
    hooks_text = (ROOT / ".codex/hooks.json").read_text(encoding="utf-8")
    assert "writer_lease" not in hooks_text


def test_checkpoint_is_cooperative_evidence_not_identity_or_order_attestation(
    lease: ModuleType, tmp_path: Path
) -> None:
    primary, _linked, base_sha, _common = _repository(tmp_path)
    acquired = _acquire(lease, primary, base_sha)
    evidence = _verify(
        lease,
        primary,
        base_sha,
        acquired["lease_id"],
        checkpoint="before_push",
        phase="declared-only",
    )
    assert evidence["checkpoint"] == "before_push"
    serialized = _canonical(evidence).lower()
    for forbidden in (b"authenticated", b"host_enforced", b"master_identity", b"executed_after"):
        assert forbidden not in serialized
