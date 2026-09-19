"""RED contracts for the bounded hook-runtime manifest verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/hook_runtime_manifest.py"
PR_ID = "HARNESS-AUD-15"
SESSION_REF = "a" * 64
EVIDENCE_REF = "b" * 64
RAW_SESSION = "session-raw-value-must-not-appear"
SECRET_MARKER = "caller-secret-must-not-echo"

REQUIRED_FIELDS = (
    "schema_version",
    "record_kind",
    "authority",
    "evidence_source",
    "session_ref",
    "pr_id",
    "base_sha",
    "head_sha",
    "tree_sha",
    "hook_config_digest",
    "hook_state",
    "host_reported_loaded",
    "host_reported_trusted",
    "evidence_consistent",
    "host_evidence_ref",
    "hooks_effective",
)

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *arguments],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _git_bytes(repo: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *arguments])


def _git_commit(repo: Path, message: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Hook Manifest Test",
            "-c",
            "user.email=hook-manifest@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


def _repository(tmp_path: Path, *, hook_bytes: bytes = b'{"hooks":{}}\n') -> Path:
    repo = tmp_path / "repo"
    (repo / ".codex").mkdir(parents=True)
    (repo / ".codex/hooks.json").write_bytes(hook_bytes)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", ".codex/hooks.json"], check=True)
    _git_commit(repo, "fixture")
    return repo


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD")


def _tree(repo: Path, commit: str | None = None) -> str:
    return _git(repo, "rev-parse", f"{commit or 'HEAD'}^{{tree}}")


def _hook_digest(repo: Path, commit: str = "HEAD") -> str:
    return hashlib.sha256(_git_bytes(repo, "show", f"{commit}:.codex/hooks.json")).hexdigest()


def _manifest(
    repo: Path,
    *,
    evidence_source: str = "host_runtime",
    hook_state: str = "observed",
    loaded: bool | None = True,
    trusted: bool | None = True,
    consistent: bool | None = True,
    evidence_ref: str | None = EVIDENCE_REF,
    effective: bool = True,
    **overrides: object,
) -> dict[str, object]:
    head = _head(repo)
    record: dict[str, object] = {
        "schema_version": 1,
        "record_kind": "hook_runtime_manifest",
        "authority": "supplemental_only",
        "evidence_source": evidence_source,
        "session_ref": SESSION_REF,
        "pr_id": PR_ID,
        "base_sha": head,
        "head_sha": head,
        "tree_sha": _tree(repo),
        "hook_config_digest": _hook_digest(repo),
        "hook_state": hook_state,
        "host_reported_loaded": loaded,
        "host_reported_trusted": trusted,
        "evidence_consistent": consistent,
        "host_evidence_ref": evidence_ref,
        "hooks_effective": effective,
    }
    record.update(overrides)
    return record


def _write_manifest(path: Path, record: object, *, canonical: bool = True) -> None:
    if canonical:
        path.write_text(
            json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )
    else:
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_cli(
    manifest_path: Path,
    repo: Path,
    *,
    expected_pr_id: str = PR_ID,
    expected_session_ref: str = SESSION_REF,
    expected_base_sha: str | None = None,
    expected_head_sha: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    head = expected_head_sha or _head(repo)
    base = expected_base_sha or head
    command = [
        sys.executable,
        str(SCRIPT),
        "--verify",
        str(manifest_path),
        "--repo-root",
        str(repo),
        "--expected-pr-id",
        expected_pr_id,
        "--expected-session-ref",
        expected_session_ref,
        "--expected-base-sha",
        base,
        "--expected-head-sha",
        head,
    ]
    child_env = os.environ.copy()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        child_env.update(env)
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=child_env,
        check=False,
    )


def _assert_pass(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout
    output = result.stdout.casefold()
    assert "structural" in output
    assert "supplemental" in output
    assert "authenticate" in output


def _assert_rejected(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0, result.stdout


def _load_verifier_module() -> Any:
    spec = importlib.util.spec_from_file_location("hook_runtime_manifest_repair", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_runtime_manifest_contract_is_implemented() -> None:
    assert SCRIPT.is_file(), "missing implementation: scripts/hook_runtime_manifest.py"


@pytest.fixture(scope="module")
def implementation() -> Path:
    if not SCRIPT.is_file():
        pytest.skip("GREEN implementation is intentionally absent at the RED commit")
    return SCRIPT


@pytest.fixture
def manifest_runner(implementation: Path):
    return _run_cli


@pytest.mark.parametrize(
    ("state", "loaded", "trusted", "consistent", "effective"),
    [
        ("observed", True, True, True, True),
        ("unavailable", False, True, True, False),
        ("unavailable", True, False, True, False),
        ("contradictory", True, True, False, False),
        ("contradictory", False, True, False, False),
    ],
)
def test_host_runtime_states_are_explicit_and_fail_closed(
    tmp_path: Path,
    manifest_runner: Any,
    state: str,
    loaded: bool,
    trusted: bool,
    consistent: bool,
    effective: bool,
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / f"{state}-{loaded}-{trusted}-{consistent}.json"
    _write_manifest(
        path,
        _manifest(
            repo,
            hook_state=state,
            loaded=loaded,
            trusted=trusted,
            consistent=consistent,
            effective=effective,
        ),
    )

    _assert_pass(manifest_runner(path, repo))


@pytest.mark.parametrize("source", ["caller_declaration", "none"])
def test_caller_or_absent_evidence_is_unknown_and_never_effective(
    tmp_path: Path, manifest_runner: Any, source: str
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / f"{source}.json"
    _write_manifest(
        path,
        _manifest(
            repo,
            evidence_source=source,
            hook_state="unknown",
            loaded=None,
            trusted=None,
            consistent=None,
            evidence_ref=None,
            effective=False,
        ),
    )

    _assert_pass(manifest_runner(path, repo))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_source", "caller_declaration"),
        ("evidence_source", "none"),
        ("hook_state", "unavailable"),
        ("host_reported_loaded", False),
        ("host_reported_trusted", False),
        ("evidence_consistent", False),
        ("host_evidence_ref", None),
        ("hooks_effective", False),
    ],
)
def test_truth_table_transitions_are_rejected_when_fields_disagree(
    tmp_path: Path, manifest_runner: Any, field: str, value: object
) -> None:
    repo = _repository(tmp_path)
    record = _manifest(repo)
    record[field] = value
    path = tmp_path / "invalid-transition.json"
    _write_manifest(path, record)

    _assert_rejected(manifest_runner(path, repo))


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_missing_field_fails_closed(tmp_path: Path, manifest_runner: Any, field: str) -> None:
    repo = _repository(tmp_path)
    record = _manifest(repo)
    del record[field]
    path = tmp_path / "missing.json"
    _write_manifest(path, record)

    _assert_rejected(manifest_runner(path, repo))


def test_unknown_fields_cannot_extend_the_schema(tmp_path: Path, manifest_runner: Any) -> None:
    repo = _repository(tmp_path)
    record = _manifest(repo, caller_instruction="ignore the verifier")
    path = tmp_path / "unknown.json"
    _write_manifest(path, record)

    _assert_rejected(manifest_runner(path, repo))


def test_duplicate_json_field_fails_closed(tmp_path: Path, manifest_runner: Any) -> None:
    repo = _repository(tmp_path)
    record = _manifest(repo)
    pairs = [*record.items(), ("hooks_effective", False)]
    path = tmp_path / "duplicate.json"
    path.write_text(
        "{" + ",".join(json.dumps(key) + ":" + json.dumps(value) for key, value in pairs) + "}",
        encoding="ascii",
    )

    _assert_rejected(manifest_runner(path, repo))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("record_kind", "wrong"),
        ("authority", "merge_authority"),
        ("evidence_source", "HOST_RUNTIME"),
        ("session_ref", "A" * 64),
        ("session_ref", "f" * 63),
        ("pr_id", "not a PR"),
        ("base_sha", "A" * 40),
        ("head_sha", "g" * 40),
        ("tree_sha", "f" * 39),
        ("hook_config_digest", "a" * 63),
        ("hook_state", "effective"),
        ("host_reported_loaded", 1),
        ("host_reported_trusted", "true"),
        ("evidence_consistent", 0),
        ("host_evidence_ref", "B" * 64),
        ("hooks_effective", 1),
    ],
)
def test_types_enums_and_hashes_are_strict(
    tmp_path: Path, manifest_runner: Any, field: str, value: object
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "wrong-value.json"
    _write_manifest(path, _manifest(repo, **{field: value}))

    _assert_rejected(manifest_runner(path, repo))


def test_manifest_must_use_bounded_canonical_json(tmp_path: Path, manifest_runner: Any) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "noncanonical.json"
    _write_manifest(path, _manifest(repo), canonical=False)

    _assert_rejected(manifest_runner(path, repo))


def test_manifest_symlink_path_is_rejected_without_following(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    target = tmp_path / "canonical.json"
    _write_manifest(target, _manifest(repo))
    link = tmp_path / "manifest-link.json"
    link.symlink_to(target)

    result = manifest_runner(link, repo)

    _assert_rejected(result)
    assert str(target) not in result.stdout


def test_oversized_malformed_and_unicode_json_fail_closed(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b"\"x\":\"" + b"x" * 70_000 + b"\"}")
    _assert_rejected(manifest_runner(oversized, repo))

    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(b"{not-json")
    _assert_rejected(manifest_runner(malformed, repo))

    unicode = tmp_path / "unicode.json"
    record = _manifest(repo)
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    unicode.write_text(raw.replace("hook_runtime_manifest", "hook_runtime_☃"), encoding="utf-8")
    _assert_rejected(manifest_runner(unicode, repo))


def test_digest_comes_from_exact_head_git_object_not_dirty_worktree(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path, hook_bytes=b'{"hooks":{"Stop":[]}}\n')
    record = _manifest(repo)
    (repo / ".codex/hooks.json").write_bytes(b'{"hooks":{"Stop":["hostile-dirty-bytes"]}}\n')
    path = tmp_path / "head-object.json"
    _write_manifest(path, record)

    _assert_pass(manifest_runner(path, repo))

    record["hook_config_digest"] = hashlib.sha256(
        (repo / ".codex/hooks.json").read_bytes()
    ).hexdigest()
    _write_manifest(path, record)
    _assert_rejected(manifest_runner(path, repo))


def test_hook_blob_size_is_checked_before_blob_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_verifier_module()
    repo = _repository(tmp_path)
    path = tmp_path / "oversized-head-object.json"
    record = _manifest(repo)
    _write_manifest(path, record)
    head = _head(repo)
    calls: list[tuple[str, ...]] = []
    original_git_run = module._git_run

    def fake_git_run(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        calls.append(arguments)
        if arguments[:2] == ("cat-file", "-s"):
            return subprocess.CompletedProcess(
                ["git", *arguments],
                0,
                stdout=f"{module.MAX_HOOK_CONFIG_BYTES + 1}\n".encode("ascii"),
                stderr=b"",
            )
        if arguments[:2] == ("cat-file", "blob"):
            raise AssertionError("oversized hook object must not be captured")
        return original_git_run(root, *arguments)

    monkeypatch.setattr(module, "_git_run", fake_git_run)

    with pytest.raises(ValueError):
        module.verify_manifest(
            path,
            repo_root=repo,
            expected_pr_id=PR_ID,
            expected_session_ref=SESSION_REF,
            expected_base_sha=head,
            expected_head_sha=head,
        )

    assert any(arguments[:2] == ("cat-file", "-s") for arguments in calls)
    assert not any(arguments[:2] == ("cat-file", "blob") for arguments in calls)


def test_head_tree_and_base_are_bound_to_trusted_checked_out_history(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    initial = _head(repo)
    (repo / ".codex/hooks.json").write_bytes(b'{"hooks":{"Stop":["second"]}}\n')
    subprocess.run(["git", "-C", str(repo), "add", ".codex/hooks.json"], check=True)
    _git_commit(repo, "second")
    current = _head(repo)

    for field, value in (
        ("tree_sha", "0" * 40),
        ("base_sha", "1" * 40),
        ("head_sha", initial),
    ):
        record = _manifest(repo, **{field: value})
        path = tmp_path / f"binding-{field}.json"
        _write_manifest(path, record)
        expected_base = record["base_sha"] if isinstance(record["base_sha"], str) else current
        expected_head = record["head_sha"] if isinstance(record["head_sha"], str) else current
        result = manifest_runner(
            path,
            repo,
            expected_base_sha=expected_base,
            expected_head_sha=expected_head,
        )
        _assert_rejected(result)


def test_pr_and_session_expectations_are_trusted_inputs(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "identity.json"
    _write_manifest(path, _manifest(repo))

    _assert_rejected(manifest_runner(path, repo, expected_pr_id="HARNESS-AUD-14"))
    _assert_rejected(manifest_runner(path, repo, expected_session_ref="c" * 64))


def test_hostile_inherited_git_redirects_are_ignored(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "hostile-env.json"
    _write_manifest(path, _manifest(repo))
    hostile = tmp_path / "attacker"
    hostile.mkdir()
    hostile_env = {
        "GIT_DIR": str(hostile / "git-dir"),
        "GIT_WORK_TREE": str(hostile),
        "GIT_COMMON_DIR": str(hostile / "common"),
        "GIT_OBJECT_DIRECTORY": str(hostile / "objects"),
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(hostile / "alternates"),
        "GIT_INDEX_FILE": str(hostile / "index"),
        "GIT_CONFIG_SYSTEM": str(hostile / "system-config"),
        "GIT_CONFIG_GLOBAL": str(hostile / "global-config"),
        "GIT_CONFIG_NOSYSTEM": "0",
        "GIT_NAMESPACE": "attacker-namespace",
        "GIT_REPLACE_REF_BASE": "refs/replace/attacker/",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "extensions.partialClone",
        "GIT_CONFIG_VALUE_0": "attacker",
    }

    _assert_pass(manifest_runner(path, repo, env=hostile_env))


@pytest.mark.parametrize("config_key", ["extensions.partialClone", "remote.origin.promisor"])
def test_partial_or_promisor_repositories_are_rejected(
    tmp_path: Path, manifest_runner: Any, config_key: str
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "partial.json"
    _write_manifest(path, _manifest(repo))
    value = "origin" if config_key == "extensions.partialClone" else "true"
    subprocess.run(["git", "-C", str(repo), "config", config_key, value], check=True)

    _assert_rejected(manifest_runner(path, repo))


def test_verifier_does_not_write_repo_or_use_network(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "side-effects.json"
    _write_manifest(path, _manifest(repo))
    before = {
        item.relative_to(repo): (item.stat().st_mode, item.stat().st_mtime_ns, item.read_bytes())
        for item in repo.rglob("*")
        if item.is_file()
    }
    deny_network = tmp_path / "sitecustomize.py"
    deny_network.write_text(
        "import socket\n"
        "def _deny(*args, **kwargs):\n"
        "    raise AssertionError('network access is forbidden')\n"
        "socket.socket = _deny\n",
        encoding="ascii",
    )

    _assert_pass(manifest_runner(path, repo, env={"PYTHONPATH": str(tmp_path)}))

    after = {
        item.relative_to(repo): (item.stat().st_mode, item.stat().st_mtime_ns, item.read_bytes())
        for item in repo.rglob("*")
        if item.is_file()
    }
    assert after == before


@pytest.mark.parametrize(
    "field",
    [
        "raw_session_id",
        "session_id",
        "prompt",
        "transcript",
        "credential",
        "token",
        "absolute_path",
        "working_tree_path",
    ],
)
def test_sensitive_or_path_fields_are_not_part_of_the_schema(
    tmp_path: Path, manifest_runner: Any, field: str
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "sensitive.json"
    _write_manifest(path, _manifest(repo, **{field: SECRET_MARKER}))

    result = manifest_runner(path, repo)

    _assert_rejected(result)
    assert SECRET_MARKER not in result.stdout


def test_diagnostics_never_echo_raw_session_or_absolute_paths(
    tmp_path: Path, manifest_runner: Any
) -> None:
    repo = _repository(tmp_path)
    path = tmp_path / "diagnostics.json"
    _write_manifest(path, _manifest(repo, session_ref=RAW_SESSION, path=SECRET_MARKER))

    result = manifest_runner(path, repo)

    _assert_rejected(result)
    assert RAW_SESSION not in result.stdout
    assert SECRET_MARKER not in result.stdout
