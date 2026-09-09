"""RED contracts for isolated current-runtime read-only role invocation.

The launcher must be a top-level, policy-pinned process boundary. These tests
use temporary Git repositories and injected probes/runners; they never invoke
Codex, authenticate, access a broker, or use the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/read_only_role_launcher.py"
DOCS_MCP_URL = "https://developers.openai.com/mcp"
DOCS_MCP_TOOLS = ("fetch_openai_doc", "search_openai_docs")
CODEX_VERSION = "0.153.4"
TEAM_IDENTIFIER = "2DC432GLL2"
_READ_ONLY_ROLES = (
    "reviewer_high",
    "reviewer_xhigh",
    "code_explorer",
    "test_auditor",
    "boundary_reviewer",
    "external_spec_researcher",
    "astra_canary",
)
_WRITER_ROLES = (
    "normal_implementer",
    "high_implementer",
    "critical_implementer",
)
_PROBE_ORDER = (
    "policy_read",
    "target_read",
    "target_write_denied",
    "credential_read_denied",
    "scratch_write",
    "secret_env_absent",
    "network_denied",
)
_MAX_JSONL_BYTES = 1 * 1024 * 1024
_CAPABILITY_KEYS = (
    "agents",
    "apps",
    "plugins",
    "hooks",
    "memories",
    "browser",
    "computer",
    "image",
    "workspace",
    "remote",
    "code_mode",
    "web",
    "search",
    "mcp_elicitation",
)


@dataclass(frozen=True)
class GitFixture:
    root: Path
    head: str
    tree: str


@dataclass(frozen=True)
class BinaryFixture:
    path: Path
    sha256: str
    descriptor: dict[str, object]


@dataclass(frozen=True)
class Scenario:
    policy: GitFixture
    target: GitFixture
    binary: BinaryFixture
    credential_probe: Path


def _launcher_module():
    if not SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/read_only_role_launcher.py")
    spec = importlib.util.spec_from_file_location("read_only_role_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function(name: str):
    function = getattr(_launcher_module(), name, None)
    if function is None:
        pytest.fail(f"missing launcher API: {name}")
    return function


def _run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def _commit_all(root: Path, message: str) -> GitFixture:
    _run_git(root, "add", "-A")
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Launcher Test",
            "-c",
            "user.email=launcher@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )
    return _git_fixture(root)


def _git_fixture(root: Path) -> GitFixture:
    return GitFixture(
        root=root,
        head=_run_git(root, "rev-parse", "HEAD"),
        tree=_run_git(root, "rev-parse", "HEAD^{tree}"),
    )


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)


def _copy_policy_fixture(root: Path) -> GitFixture:
    root.mkdir(parents=True)
    shutil.copytree(ROOT / ".codex", root / ".codex")
    shutil.copytree(ROOT / ".agents/skills", root / ".agents/skills")
    shutil.copytree(ROOT / "docs/productionization", root / "docs/productionization")
    for relative in (
        "AGENTS.md",
        "mytradingalpha/AGENTS.md",
        "tradingagents/AGENTS.md",
        "tests/productionization/AGENTS.md",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    _init_git(root)
    return _commit_all(root, "policy fixture")


def _copy_target_fixture(root: Path, *, candidate_role: bool = False) -> GitFixture:
    root.mkdir(parents=True)
    (root / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("candidate target policy\n", encoding="utf-8")
    if candidate_role:
        role_path = root / ".codex/agents/reviewer-high.toml"
        role_path.parent.mkdir(parents=True)
        role_path.write_text(
            'name = "reviewer_high"\n'
            'model = "candidate-self-authorized-model"\n'
            'model_reasoning_effort = "none"\n'
            'sandbox_mode = "workspace-write"\n'
            '[agents]\n'
            'enabled = true\n',
            encoding="utf-8",
        )
    _init_git(root)
    fixture = _commit_all(root, "candidate fixture")
    _run_git(root, "checkout", "-q", "--detach", fixture.head)
    return _git_fixture(root)


def _binary_fixture(root: Path) -> BinaryFixture:
    root.mkdir(parents=True)
    path = root / "codex"
    contents = b"synthetic codex executable for deterministic launcher tests\n"
    path.write_bytes(contents)
    path.chmod(0o755)
    digest = hashlib.sha256(contents).hexdigest()
    descriptor = {
        "realpath": str(path.resolve()),
        "is_regular": True,
        "is_symlink": False,
        "owner_uid": os.getuid(),
        "mode": 0o755,
        "version": CODEX_VERSION,
        "sha256": digest,
        "team_identifier": TEAM_IDENTIFIER,
    }
    return BinaryFixture(path=path, sha256=digest, descriptor=descriptor)


@pytest.fixture
def scenario(tmp_path: Path) -> Scenario:
    policy = _copy_policy_fixture(tmp_path / "policy")
    target = _copy_target_fixture(tmp_path / "target")
    binary = _binary_fixture(tmp_path / "bin")
    credential = tmp_path / "bootstrap-auth" / "credentials.json"
    credential.parent.mkdir()
    credential.write_text("bootstrap credential fixture\n", encoding="utf-8")
    credential.chmod(0o600)
    return Scenario(policy=policy, target=target, binary=binary, credential_probe=credential)


def _binary_probe(descriptor: dict[str, object]):
    def probe(_path: object) -> dict[str, object]:
        return dict(descriptor)

    return probe


def _plan_kwargs(
    scenario: Scenario,
    *,
    role: str = "reviewer_high",
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "policy_root": scenario.policy.root,
        "target_root": scenario.target.root,
        "role": role,
        "expected_policy_sha": scenario.policy.head,
        "expected_policy_tree_sha": scenario.policy.tree,
        "expected_target_sha": scenario.target.head,
        "expected_target_tree_sha": scenario.target.tree,
        "codex_binary": scenario.binary.path,
        "expected_binary_version": CODEX_VERSION,
        "expected_binary_sha256": scenario.binary.sha256,
        "expected_binary_team_identifier": TEAM_IDENTIFIER,
        "supported_binary_versions": (CODEX_VERSION,),
        "binary_probe": _binary_probe(scenario.binary.descriptor),
        "credential_probe_path": scenario.credential_probe,
    }
    values.update(overrides)
    return values


def _call_plan(scenario: Scenario, values: dict[str, object]) -> dict[str, object]:
    module = _launcher_module()
    synthetic_root = ROOT / ".test-runtime-root" / scenario.target.head[:16]
    old_tempdir = module.tempfile.gettempdir
    old_provider = getattr(module, "temp_root_provider", None)
    old_getter = getattr(module, "get_temp_root", None)
    module.tempfile.gettempdir = lambda: str(synthetic_root)
    if old_provider is not None:
        module.temp_root_provider = lambda: synthetic_root
    if old_getter is not None:
        module.get_temp_root = lambda: synthetic_root
    try:
        result = module.build_invocation_plan(**values)
    finally:
        module.tempfile.gettempdir = old_tempdir
        if old_provider is not None:
            module.temp_root_provider = old_provider
        if old_getter is not None:
            module.get_temp_root = old_getter
    return result


def _plan(scenario: Scenario, *, role: str = "reviewer_high", **overrides: object) -> dict[str, object]:
    result = _call_plan(scenario, _plan_kwargs(scenario, role=role, **overrides))
    assert type(result) is dict, "launcher plan must be a plain mapping"
    return result


def _rejected_plan(scenario: Scenario, *, role: str = "reviewer_high", **overrides: object) -> None:
    try:
        result = _call_plan(scenario, _plan_kwargs(scenario, role=role, **overrides))
    except (OSError, PermissionError, RuntimeError, ValueError) as exc:
        assert str(exc), "rejected launcher plans need bounded diagnostics"
        return
    assert type(result) is dict
    errors = result.get("errors")
    assert isinstance(errors, list) and errors, result


def test_valid_plan_is_an_isolated_top_level_invocation_and_uses_protected_policy(
    tmp_path: Path,
) -> None:
    policy = _copy_policy_fixture(tmp_path / "policy")
    target = _copy_target_fixture(tmp_path / "target", candidate_role=True)
    binary = _binary_fixture(tmp_path / "bin")
    credential = tmp_path / "bootstrap-auth" / "credentials.json"
    credential.parent.mkdir()
    credential.write_text("bootstrap credential fixture\n", encoding="utf-8")
    credential.chmod(0o600)
    scenario = Scenario(policy=policy, target=target, binary=binary, credential_probe=credential)

    plan = _plan(scenario)

    assert plan["invocation_kind"] == "isolated_role_invocation"
    assert plan["role"] == "reviewer_high"
    assert plan["policy_head_sha"] == policy.head
    assert plan["policy_tree_sha"] == policy.tree
    assert plan["target_head_sha"] == target.head
    assert plan["target_tree_sha"] == target.tree
    assert plan["target_detached"] is True
    assert plan["policy_source"] == "protected_git_object"
    assert plan["role_source"] == "protected_git_object"
    assert plan["instructions_source"] == "protected_git_object"
    assert plan.get("named_agent_loaded") is not True
    assert plan.get("configured_actual") is not True
    assert plan["model"] == "gpt-5.6-sol"
    assert plan["reasoning_effort"] == "high"
    assert "candidate-self-authorized-model" not in json.dumps(plan)


@pytest.mark.parametrize(
    "override",
    [
        {"expected_policy_sha": "a" * 40},
        {"expected_policy_tree_sha": "b" * 40},
        {"expected_target_sha": "c" * 40},
        {"expected_target_tree_sha": "d" * 40},
    ],
)
def test_policy_and_target_exact_sha_tree_bindings_are_required(
    scenario: Scenario, override: dict[str, object]
) -> None:
    _rejected_plan(scenario, **override)


def test_dirty_policy_or_target_is_rejected(scenario: Scenario) -> None:
    (scenario.policy.root / "dirty-policy.txt").write_text("dirty\n", encoding="utf-8")
    _rejected_plan(scenario)

    (scenario.policy.root / "dirty-policy.txt").unlink()
    (scenario.target.root / "dirty-target.txt").write_text("dirty\n", encoding="utf-8")
    _rejected_plan(scenario)


def test_target_must_be_detached(scenario: Scenario) -> None:
    _run_git(scenario.target.root, "switch", "-q", "-c", "candidate-branch")
    _rejected_plan(scenario)


def test_policy_and_target_symlink_or_escape_paths_are_rejected(
    scenario: Scenario, tmp_path: Path
) -> None:
    policy_link = tmp_path / "policy-link"
    target_link = tmp_path / "target-link"
    policy_link.symlink_to(scenario.policy.root, target_is_directory=True)
    target_link.symlink_to(scenario.target.root, target_is_directory=True)
    _rejected_plan(scenario, policy_root=policy_link)
    _rejected_plan(scenario, target_root=target_link)
    _rejected_plan(scenario, policy_root=scenario.policy.root / "..")
    _rejected_plan(scenario, target_root=scenario.target.root / "..")


@pytest.mark.parametrize("setting", ["partial", "promisor"])
def test_partial_or_promisor_repositories_fail_closed(
    scenario: Scenario, setting: str
) -> None:
    if setting == "partial":
        _run_git(scenario.target.root, "config", "extensions.partialClone", "origin")
    else:
        _run_git(scenario.target.root, "config", "remote.origin.promisor", "true")
    _rejected_plan(scenario)


def test_replace_refs_cannot_substitute_target_objects(scenario: Scenario) -> None:
    replacement = _run_git(
        scenario.target.root,
        "commit-tree",
        scenario.target.tree,
        "-m",
        "replacement",
    )
    _run_git(scenario.target.root, "replace", scenario.target.head, replacement)
    try:
        _rejected_plan(scenario)
    finally:
        subprocess.run(
            ["git", "-C", str(scenario.target.root), "replace", "-d", scenario.target.head],
            check=True,
            capture_output=True,
            text=True,
        )


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"])
def test_ambient_git_redirects_are_rejected(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    value = {
        "GIT_DIR": str(scenario.policy.root / ".git"),
        "GIT_WORK_TREE": str(scenario.target.root),
        "GIT_OBJECT_DIRECTORY": str(scenario.policy.root / ".git/objects"),
    }[variable]
    monkeypatch.setenv(variable, value)
    _rejected_plan(scenario)


@pytest.mark.parametrize("role", _READ_ONLY_ROLES)
def test_only_the_seven_read_only_roles_are_accepted(
    scenario: Scenario, role: str
) -> None:
    plan = _plan(scenario, role=role)
    assert plan["invocation_kind"] == "isolated_role_invocation"
    assert plan["role"] == role
    assert plan.get("named_agent_loaded") is not True
    assert plan.get("configured_actual") is not True


@pytest.mark.parametrize("role", _WRITER_ROLES)
def test_writer_roles_are_rejected_from_read_only_launcher(
    scenario: Scenario, role: str
) -> None:
    _rejected_plan(scenario, role=role)


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("unknown_field", "unexpected"),
        ("wrong_model", 'model = "candidate-model"'),
        ("wrong_effort", 'model_reasoning_effort = "none"'),
        ("writable", 'sandbox_mode = "workspace-write"'),
        ("delegating", "enabled = true"),
    ],
)
def test_role_toml_fields_and_values_are_strict(
    scenario: Scenario, mutation: str, needle: str
) -> None:
    path = scenario.policy.root / ".codex/agents/reviewer-high.toml"
    original = path.read_text(encoding="utf-8")
    if mutation == "unknown_field":
        updated = original + "\nunexpected = true\n"
    elif mutation == "wrong_model":
        updated = original.replace('model = "gpt-5.6-sol"', needle)
    elif mutation == "wrong_effort":
        updated = original.replace('model_reasoning_effort = "high"', needle)
    elif mutation == "writable":
        updated = original.replace('sandbox_mode = "read-only"', needle)
    else:
        updated = original.replace("enabled = false", needle)
    path.write_text(updated, encoding="utf-8")
    _commit_all(scenario.policy.root, f"invalid role {mutation}")
    updated_scenario = Scenario(
        policy=_git_fixture(scenario.policy.root),
        target=scenario.target,
        binary=scenario.binary,
        credential_probe=scenario.credential_probe,
    )
    _rejected_plan(updated_scenario)


def test_ordinary_roles_have_no_mcp_and_external_researcher_has_exact_docs_mcp(
    scenario: Scenario,
) -> None:
    ordinary = _plan(scenario, role="reviewer_high")
    assert ordinary["mcp_servers"] in ({}, None)

    external = _plan(scenario, role="external_spec_researcher")
    assert external["mcp_servers"] == {
        "openaiDeveloperDocs": {
            "url": DOCS_MCP_URL,
            "enabled_tools": list(DOCS_MCP_TOOLS),
        }
    }


def test_external_mcp_endpoint_or_tool_allowlist_drift_is_rejected(
    scenario: Scenario,
) -> None:
    path = scenario.policy.root / ".codex/agents/external-spec-researcher.toml"
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace(DOCS_MCP_URL, "https://example.invalid/mcp"), encoding="utf-8")
    _commit_all(scenario.policy.root, "invalid docs MCP endpoint")
    updated_scenario = Scenario(
        policy=_git_fixture(scenario.policy.root),
        target=scenario.target,
        binary=scenario.binary,
        credential_probe=scenario.credential_probe,
    )
    _rejected_plan(updated_scenario, role="external_spec_researcher")


def _binary_errors(scenario: Scenario, **overrides: object) -> list[str]:
    descriptor = dict(scenario.binary.descriptor)
    descriptor.update(overrides.pop("descriptor", {}))
    result = _function("validate_binary")(
        path=overrides.pop("path", scenario.binary.path),
        expected_version=overrides.pop("expected_version", CODEX_VERSION),
        expected_sha256=overrides.pop("expected_sha256", scenario.binary.sha256),
        expected_team_identifier=overrides.pop(
            "expected_team_identifier", TEAM_IDENTIFIER
        ),
        supported_versions=overrides.pop("supported_versions", (CODEX_VERSION,)),
        probe=_binary_probe(descriptor),
        **overrides,
    )
    assert isinstance(result, list)
    return result


def test_binary_identity_accepts_only_exact_injected_probe(scenario: Scenario) -> None:
    assert _binary_errors(scenario) == []


@pytest.mark.parametrize(
    "descriptor",
    [
        {"is_regular": False},
        {"is_symlink": True},
        {"owner_uid": os.getuid() + 1},
        {"mode": 0o775},
        {"version": "0.153.3"},
        {"version": "0.154.0"},
        {"sha256": "0" * 64},
        {"team_identifier": "WRONGTEAM"},
    ],
)
def test_binary_path_version_hash_signature_and_ownership_drift_fail_closed(
    scenario: Scenario, descriptor: dict[str, object]
) -> None:
    assert _binary_errors(scenario, descriptor=descriptor)


def test_binary_requires_absolute_regular_non_symlink_path(scenario: Scenario) -> None:
    assert _binary_errors(scenario, path=Path("codex"))
    symlink = scenario.binary.path.parent / "codex-link"
    symlink.symlink_to(scenario.binary.path)
    assert _binary_errors(scenario, path=symlink)


def test_permission_profile_is_per_run_launcher_pilot_not_global_sandbox(
    scenario: Scenario, tmp_path: Path
) -> None:
    scratch = tmp_path / "private-scratch"
    scratch.mkdir(mode=0o700)
    common_git = (
        scenario.target.root
        / _run_git(scenario.target.root, "rev-parse", "--git-common-dir")
    ).resolve()
    dependency_root = tmp_path / "dependency"
    dependency_root.mkdir()
    profile = _function("build_permission_profile")(
        policy_root=scenario.policy.root,
        target_root=scenario.target.root,
        common_git_root=Path(common_git),
        dependency_roots=(dependency_root,),
        scratch_root=scratch,
    )
    assert type(profile) is dict
    permissions = profile["default_permissions"]
    assert permissions[":root"] == "deny"
    assert permissions[str(scenario.policy.root)] == "read"
    assert permissions[str(scenario.target.root)] == "read"
    assert permissions[str(common_git)] == "read"
    assert permissions[str(dependency_root)] == "read"
    assert permissions[str(scratch)] == "write"
    assert profile["network"] == "disabled"
    assert profile["scope"] == "launcher_pilot"
    assert "sandbox_mode" not in profile
    assert "--sandbox" not in json.dumps(profile)
    shell = profile["shell_environment"]
    assert shell["inherit"] is False
    assert shell["ignore_default_excludes"] is False
    allowed_shell_keys = {
        "PATH",
        "TMPDIR",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_OPTIONAL_LOCKS",
        "LANG",
        "LC_ALL",
        "TZ",
    }
    assert set(shell["set"]).issubset(allowed_shell_keys)
    assert {
        "PATH",
        "TMPDIR",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_OPTIONAL_LOCKS",
    }.issubset(shell["set"])
    assert shell["set"]
    assert not {str(key).lower() for key in shell["set"]} & {
        "token",
        "secret",
        "api_key",
        "credential",
    }
    denied = " ".join(str(value).lower() for value in profile["deny_paths"])
    for term in ("codex", "auth", "ssh", "cloud", "github", "keychain", "secret", "token"):
        assert term in denied


def test_plan_closes_capabilities_and_uses_strict_current_runtime_flags(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    argv = plan["argv"]
    assert type(argv) is list and all(type(value) is str for value in argv)
    for flag in ("--ignore-user-config", "--ephemeral", "--skip-git-repo-check"):
        assert flag in argv
    assert "--sandbox" not in argv
    assert "--agent" not in argv
    assert "--json" in argv
    assert "--color" in argv and "never" in argv
    assert plan["approval_policy"] == "never"
    assert plan["strict_config"] is True
    assert plan["capability_closure"] == dict.fromkeys(_CAPABILITY_KEYS, False)
    assert plan["cwd_is_private_empty"] is True


def test_preflight_order_uses_same_binary_profile_and_blocks_runner_on_failure(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    results = {
        "policy_read": {"allowed": True},
        "target_read": {"allowed": True},
        "target_write_denied": {"denied": True, "marker_absent": True},
        "credential_read_denied": {"denied": True, "stdout": "", "marker_absent": True},
        "scratch_write": {"allowed": True},
        "secret_env_absent": {"absent": True},
        "network_denied": {"denied": True, "marker_absent": True},
    }
    probe_calls: list[tuple[str, object]] = []
    runner_calls: list[dict[str, object]] = []

    def probe(
        name: str | None = None,
        observed_plan: object | None = None,
        *args: object,
        **kwargs: object,
    ):
        name = name or str(kwargs["name"])
        observed_plan = observed_plan if observed_plan is not None else kwargs["plan"]
        probe_calls.append((name, observed_plan))
        return results[name]

    def runner(**kwargs: object) -> dict[str, object]:
        runner_calls.append(kwargs)
        return {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""}

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        probe=probe,
        process_runner=runner,
    )
    assert result["status"] == "completed", result
    assert result["final_agent_message"] == "untrusted final output"
    assert "untrusted final output" not in json.dumps(result["manifest"])
    assert [name for name, _ in probe_calls] == list(_PROBE_ORDER)
    assert all(observed is plan for _, observed in probe_calls)
    assert len(runner_calls) == 1
    call = runner_calls[0]
    assert call["shell"] is False
    assert type(call["argv"]) is list
    assert type(call["stdin"]) is str
    assert len(call["stdin"].encode()) <= 96 * 1024
    assert Path(call["cwd"]) == Path(plan["cwd"])
    assert 0 < call["timeout"] <= 300
    assert call["process_group"] is True
    assert "candidate-self-authorized-model" not in call["stdin"]


def test_preflight_requires_structured_denial_not_stderr_substrings(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    runner_calls: list[object] = []

    def probe(
        name: str | None = None,
        observed_plan: object | None = None,
        *args: object,
        **kwargs: object,
    ):
        name = name or str(kwargs["name"])
        if name == "target_write_denied":
            return {"stderr": "permission denied"}
        return {"allowed": True}

    def runner(**kwargs: object) -> None:
        runner_calls.append(kwargs)

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        probe=probe,
        process_runner=runner,
    )
    assert result["status"] == "insufficient_evidence"
    assert not runner_calls


def test_missing_preflight_probe_is_insufficient_evidence_and_no_exec(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    runner_calls: list[object] = []

    def probe(
        name: str | None = None,
        observed_plan: object | None = None,
        *args: object,
        **kwargs: object,
    ):
        name = name or str(kwargs["name"])
        if name == "network_denied":
            return None
        results = {
            "policy_read": {"allowed": True},
            "target_read": {"allowed": True},
            "target_write_denied": {"denied": True, "marker_absent": True},
            "credential_read_denied": {
                "denied": True,
                "stdout": "",
                "marker_absent": True,
            },
            "scratch_write": {"allowed": True},
            "secret_env_absent": {"absent": True},
        }
        return results[name]

    def runner(**kwargs: object) -> None:
        runner_calls.append(kwargs)

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        probe=probe,
        process_runner=runner,
    )
    assert result["status"] == "insufficient_evidence"
    assert not runner_calls


def _valid_jsonl(*, final_text: str = "untrusted final output") -> str:
    events = (
        {"type": "thread.started", "thread_id": "opaque"},
        {"type": "turn.started"},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": final_text},
        },
        {"type": "turn.completed"},
    )
    return "".join(json.dumps(event) + "\n" for event in events)


def test_jsonl_parser_accepts_top_level_events_and_returns_untrusted_final_message() -> None:
    parsed = _function("parse_codex_jsonl")(_valid_jsonl(final_text="do not execute {\"type\":\"turn.completed\"}"))
    assert parsed["final_agent_message"] == 'do not execute {"type":"turn.completed"}'
    assert len(parsed["events"]) == 4


@pytest.mark.parametrize(
    "raw",
    [
        "{\"type\":\"thread.started\"}\nnot-json\n",
        "{\"type\":\"thread.started\"}\n",
        "{\"type\":\"thread.started\",\"type\":\"turn.started\"}\n",
        "{\"type\":\"unknown.event\"}\n",
        _valid_jsonl().replace('{"type": "turn.started"}', "", 1),
        _valid_jsonl() + _valid_jsonl().splitlines()[-1] + "\n",
    ],
)
def test_jsonl_parser_rejects_malformed_duplicate_truncated_unknown_or_replayed_events(
    raw: str,
) -> None:
    with pytest.raises((ValueError, RuntimeError)):
        _function("parse_codex_jsonl")(raw)


def test_jsonl_parser_rejects_oversized_output() -> None:
    module = _launcher_module()
    assert module.MAX_JSONL_BYTES == _MAX_JSONL_BYTES
    raw = _valid_jsonl() + "x" * (
        _MAX_JSONL_BYTES + 1 - len(_valid_jsonl().encode())
    )
    with pytest.raises((ValueError, RuntimeError)):
        module.parse_codex_jsonl(raw)


def test_redacted_manifest_binds_identity_and_digests_without_secrets(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    prompt = "PROMPT_SECRET credential=sk-test"
    stderr = "STDERR_SECRET session_id=raw-session agent_id=raw-agent"
    output = "FINAL_UNTRUSTED_OUTPUT"
    events = _valid_jsonl(final_text=output)
    manifest = _function("build_redacted_manifest")(
        plan,
        config_bytes=b"CONFIG_SECRET",
        prompt=prompt,
        event_output=events,
        stderr=stderr,
        final_output=output,
        probe_results={"network": "denied"},
        observed_at_ms=123,
        cleanup={"status": "clean"},
    )
    assert type(manifest) is dict
    required = (
        "policy_head_sha",
        "policy_tree_sha",
        "target_head_sha",
        "target_tree_sha",
        "role",
        "config_path",
        "model",
        "reasoning_effort",
        "binary_realpath",
        "binary_version",
        "binary_sha256",
        "binary_team_identifier",
        "config_digest",
        "prompt_digest",
        "event_digest",
        "output_digest",
        "probe_digest",
        "observed_at_ms",
        "cleanup",
        "final_output_digest",
    )
    for field in required:
        assert field in manifest, field
    serialized = json.dumps(manifest, sort_keys=True)
    for secret in (prompt, stderr, output, "raw-session", "raw-agent", "sk-test"):
        assert secret not in serialized
    for field in (
        "config_digest",
        "prompt_digest",
        "event_digest",
        "output_digest",
        "probe_digest",
        "final_output_digest",
    ):
        assert isinstance(manifest[field], str) and len(manifest[field]) == 64
    assert manifest.get("merge_authorized") is not True


def _snapshot(scenario: Scenario, *, dirty: bool = False) -> dict[str, object]:
    return {
        "policy_head_sha": scenario.policy.head,
        "policy_tree_sha": scenario.policy.tree,
        "target_head_sha": scenario.target.head,
        "target_tree_sha": scenario.target.tree,
        "target_status": "dirty" if dirty else "clean",
    }


def test_post_run_requires_unchanged_exact_heads_clean_status_and_no_markers(
    scenario: Scenario, tmp_path: Path
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    verify = _function("verify_post_run")
    assert verify(
        _plan(scenario),
        before=_snapshot(scenario),
        after=_snapshot(scenario),
        marker_paths=(),
        private_dirs=(scratch,),
    ) == []
    assert verify(
        _plan(scenario),
        before=_snapshot(scenario),
        after={**_snapshot(scenario), "target_status": "dirty"},
        marker_paths=(tmp_path / "unexpected-marker",),
        private_dirs=(scratch,),
    )


def test_post_run_detects_head_tree_drift_and_private_path_violations(
    scenario: Scenario, tmp_path: Path
) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    symlink = tmp_path / "private-link"
    symlink.symlink_to(private, target_is_directory=True)
    verify = _function("verify_post_run")
    errors = verify(
        _plan(scenario),
        before=_snapshot(scenario),
        after={**_snapshot(scenario), "target_head_sha": "f" * 40},
        marker_paths=(),
        private_dirs=(symlink,),
    )
    assert errors


def test_cleanup_is_non_force_and_preserves_dirty_or_unowned_paths(tmp_path: Path) -> None:
    clean = tmp_path / "clean"
    clean.mkdir(mode=0o700)
    dirty = tmp_path / "dirty"
    dirty.mkdir(mode=0o700)
    (dirty / "marker").write_text("keep\n", encoding="utf-8")
    result = _function("cleanup_private_dirs")((clean,), force=False)
    assert result == []
    assert not clean.exists()
    result = _function("cleanup_private_dirs")(
        (dirty,), force=False, ownership={str(dirty): False}
    )
    assert result
    assert dirty.exists()


def _common_git_root(scenario: Scenario) -> Path:
    return (
        scenario.target.root
        / _run_git(scenario.target.root, "rev-parse", "--git-common-dir")
    ).resolve()


def _valid_sandbox_results() -> dict[str, dict[str, object]]:
    return {
        "policy_read": {"allowed": True, "returncode": 0, "stdout": "", "stderr": ""},
        "target_read": {"allowed": True, "returncode": 0, "stdout": "", "stderr": ""},
        "target_write_denied": {
            "denied": True,
            "marker_absent": True,
            "returncode": 1,
            "stdout": "",
            "stderr": "",
        },
        "credential_read_denied": {
            "denied": True,
            "stdout": "",
            "marker_absent": True,
            "returncode": 1,
            "stderr": "",
        },
        "scratch_write": {"allowed": True, "returncode": 0, "stdout": "", "stderr": ""},
        "secret_env_absent": {"absent": True, "returncode": 0, "stdout": "", "stderr": ""},
        "network_denied": {
            "denied": True,
            "marker_absent": True,
            "returncode": 1,
            "stdout": "",
            "stderr": "",
        },
    }


def _sandbox_runner_for(results: dict[str, dict[str, object]], calls: list[dict[str, object]]):
    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        name = str(kwargs.get("probe_name"))
        return results[name]

    return runner


def _cli_identity_args(scenario: Scenario) -> list[str]:
    return [
        "--policy-root",
        str(scenario.policy.root),
        "--target-root",
        str(scenario.target.root),
        "--role",
        "reviewer_high",
        "--expected-policy-sha",
        scenario.policy.head,
        "--expected-policy-tree-sha",
        scenario.policy.tree,
        "--expected-target-sha",
        scenario.target.head,
        "--expected-target-tree-sha",
        scenario.target.tree,
        "--codex-binary",
        str(scenario.binary.path),
        "--expected-binary-sha256",
        scenario.binary.sha256,
        "--credential-probe-path",
        str(scenario.credential_probe),
    ]


def test_plan_keeps_runtime_roots_outside_policy_target_and_common_git(
    scenario: Scenario,
) -> None:
    common_git = _common_git_root(scenario)
    plan = _plan(scenario)
    runtime_root = Path(plan["runtime_root"])
    cwd = Path(plan["cwd"])
    for candidate in (runtime_root, cwd):
        assert not candidate.exists()
        assert not candidate.is_relative_to(scenario.policy.root.resolve())
        assert not candidate.is_relative_to(scenario.target.root.resolve())
        assert not candidate.is_relative_to(common_git)


def test_exec_argv_binds_strict_config_route_profile_environment_and_features(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    argv = plan["argv"]
    assert type(argv) is list and all(type(value) is str for value in argv)
    for flag in (
        "--strict-config",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
    ):
        assert flag in argv
    assert "--color" in argv and "never" in argv
    assert "-m" in argv and argv[argv.index("-m") + 1] == plan["model"]
    config_values = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-c"]
    profile_name = str(plan["permission_profile_name"])
    required_prefixes = (
        "model_reasoning_effort=",
        "developer_instructions=",
        "approval_policy=",
        "default_permissions=",
        "shell_environment_policy=",
        "agents.enabled=",
        "features.apps=",
        "features.plugins=",
        "features.hooks=",
        "features.memories=",
        "features.multi_agent=",
        "features.multi_agent_v2=",
        "features.browser_use=",
        "features.browser_use_external=",
        "features.browser_use_full_cdp_access=",
        "features.computer_use=",
        "features.image_generation=",
        "features.in_app_browser=",
        "features.workspace_dependencies=",
        "features.remote_plugin=",
        "features.skill_mcp_dependency_install=",
        "features.tool_call_mcp_elicitation=",
        "features.auth_elicitation=",
        "features.code_mode=",
        "features.code_mode_host=",
        "features.code_mode_only=",
        "mcp_servers=",
        f"permissions.{profile_name}.filesystem=",
        f"permissions.{profile_name}.network=",
    )
    for prefix in required_prefixes:
        assert any(value.startswith(prefix) for value in config_values), prefix
    assert "-p" not in argv and "--profile" not in argv
    assert any(
        value.startswith("default_permissions=") and profile_name in value
        for value in config_values
    )
    assert not any(value.startswith("sandbox_mode=") for value in config_values)
    forbidden = {"--sandbox", "--agent", "--approve-for-me", "--yolo"}
    assert not forbidden.intersection(argv)
    assert "-" in argv
    assert plan["prompt_transport"] == "stdin"
    assert not any(
        value in {"sh", "bash", "zsh", "eval"}
        or (index > 0 and value == "-c" and argv[index - 1] in {"sh", "bash", "zsh"})
        for index, value in enumerate(argv)
    )


@pytest.mark.parametrize("probe_name", _PROBE_ORDER)
def test_every_preflight_probe_is_sandboxed_with_same_binary_and_profile(
    scenario: Scenario, probe_name: str
) -> None:
    plan = _plan(scenario)
    result = _function("build_sandbox_probe_argv")(plan, probe_name)
    assert type(result) is dict
    argv = result["argv"]
    assert type(argv) is list and all(type(value) is str for value in argv)
    assert argv[0] == plan["argv"][0]
    assert "sandbox" in argv
    assert "--include-managed-config" in argv
    assert "-p" not in argv and "--profile" not in argv
    config_values = [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "-c"]
    assert any(value.startswith("default_permissions=") for value in config_values)
    assert not any(value.startswith("sandbox_mode=") for value in config_values)
    assert result["cwd"] == plan["cwd"]
    assert result["binary_realpath"] == plan["binary_realpath"]
    assert result["profile_digest"] == plan["permission_profile_digest"]
    assert result["shell"] is False


def test_sandbox_runner_order_blocks_exec_until_all_probes_pass(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    sandbox_calls: list[dict[str, object]] = []
    exec_calls: list[dict[str, object]] = []

    def process_runner(**kwargs: object) -> dict[str, object]:
        exec_calls.append(kwargs)
        return {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""}

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        sandbox_runner=_sandbox_runner_for(_valid_sandbox_results(), sandbox_calls),
        process_runner=process_runner,
    )
    assert result["status"] == "completed", result
    assert [call["probe_name"] for call in sandbox_calls] == list(_PROBE_ORDER)
    assert len(exec_calls) == 1
    assert all(call["argv"][0] == plan["argv"][0] for call in sandbox_calls)


def test_probe_failure_exception_or_timeout_cleans_only_launcher_owned_dirs(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    calls: list[dict[str, object]] = []

    def failing_runner(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        raise TimeoutError("probe timeout")

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        sandbox_runner=failing_runner,
        process_runner=lambda **kwargs: {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""},
    )
    assert result["status"] == "insufficient_evidence"
    assert not Path(plan["runtime_root"]).exists()
    assert not Path(plan["cwd"]).exists()


def test_default_path_cannot_claim_completed_without_real_sandbox_probe_runner(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _launcher_module()
    plan = _plan(scenario)
    monkeypatch.setattr(module, "_default_sandbox_runner", lambda **kwargs: None)
    exec_calls: list[object] = []
    result = module.run_isolated_role(
        plan,
        prompt="bounded prompt",
        process_runner=lambda **kwargs: exec_calls.append(kwargs)
        or {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""},
    )
    assert result["status"] == "insufficient_evidence"
    assert not exec_calls


def test_cli_reads_bounded_prompt_from_stdin_and_never_uses_prompt_argv(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _launcher_module()
    captured: dict[str, object] = {}
    plan = _plan(scenario)
    monkeypatch.setattr(module, "build_invocation_plan", lambda **kwargs: plan)

    def fake_run(plan_value: dict[str, object], *, prompt: str, **kwargs: object):
        captured["prompt"] = prompt
        return {"status": "insufficient_evidence", "manifest": {}}

    monkeypatch.setattr(module, "run_isolated_role", fake_run)
    monkeypatch.setattr(sys, "stdin", io.StringIO("stdin secret prompt\n"))
    result = module.main(_cli_identity_args(scenario))
    assert result != 0
    assert captured["prompt"] == "stdin secret prompt\n"
    assert "--prompt" not in _cli_identity_args(scenario)

    with pytest.raises(SystemExit):
        module.main(["--help"])
    help_output = capsys.readouterr().out
    assert "--prompt" not in help_output
    assert "--credential-probe-path" in help_output
    assert "stdin" in help_output.lower()


def test_protected_instruction_sources_are_complete_and_not_truncated(
    scenario: Scenario,
) -> None:
    role_path = scenario.policy.root / ".codex/agents/reviewer-high.toml"
    role_text = role_path.read_text(encoding="utf-8")
    role_text = role_text.rsplit('"""', 1)[0] + ("\n" + "R" * 10_000 + "ROLE_END_SENTINEL\n\"\"\"" + role_text.rsplit('"""', 1)[1])
    role_path.write_text(role_text, encoding="utf-8")
    (scenario.policy.root / "AGENTS.md").write_text(
        (scenario.policy.root / "AGENTS.md").read_text(encoding="utf-8")
        + "\n"
        + "A" * 10_000
        + "ROOT_END_SENTINEL\n",
        encoding="utf-8",
    )
    skill = scenario.policy.root / ".agents/skills/exact-head-review/SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "\n"
        + "S" * 10_000
        + "SKILL_END_SENTINEL\n",
        encoding="utf-8",
    )
    _commit_all(scenario.policy.root, "complete protected instruction fixture")
    updated = Scenario(
        _git_fixture(scenario.policy.root),
        scenario.target,
        scenario.binary,
        scenario.credential_probe,
    )
    plan = _plan(updated)
    instructions = plan["developer_instructions"]
    assert "ROLE_END_SENTINEL" in instructions
    assert "ROOT_END_SENTINEL" in instructions
    assert "SKILL_END_SENTINEL" in instructions
    assert len(instructions.encode()) <= 96 * 1024


def test_parser_accepts_observed_lifecycle_command_and_error_items() -> None:
    events = (
        {"type": "thread.started", "thread_id": "opaque"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"type": "agent_message"}},
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": ["pwd"]},
        },
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": ["pwd"],
                "exit_code": 0,
                "aggregated_output": "{\"type\":\"fake.nested\"}",
            },
        },
        {"type": "item.completed", "item": {"type": "warning", "message": "warning"}},
        {"type": "item.completed", "item": {"type": "error", "message": "error"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "final"}},
        {"type": "turn.completed"},
    )
    raw = "".join(json.dumps(event) + "\n" for event in events)
    parsed = _function("parse_codex_jsonl")(raw)
    assert parsed["final_agent_message"] == "final"
    assert parsed["error_event_count"] == 1
    assert parsed["warning_event_count"] == 1
    assert len(parsed["error_digest"]) == 64


def test_actual_run_recomputes_target_snapshot_before_claiming_completion(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    results = _valid_sandbox_results()

    def mutate_target(**kwargs: object) -> dict[str, object]:
        (scenario.target.root / "runtime-mutation.txt").write_text("mutated\n", encoding="utf-8")
        _commit_all(scenario.target.root, "runtime mutation")
        return results[str(kwargs["probe_name"])]

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        sandbox_runner=mutate_target,
        process_runner=lambda **kwargs: {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""},
    )
    assert result["status"] == "insufficient_evidence"


def test_permission_profile_uses_absolute_sensitive_paths_and_explicit_credential_probe(
    scenario: Scenario, tmp_path: Path
) -> None:
    credential = tmp_path / "protected" / "credentials.json"
    credential.parent.mkdir()
    credential.write_text("secret\n", encoding="utf-8")
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    profile = _function("build_permission_profile")(
        policy_root=scenario.policy.root,
        target_root=scenario.target.root,
        common_git_root=_common_git_root(scenario),
        dependency_roots=(tmp_path,),
        scratch_root=scratch,
        credential_probe_path=credential,
    )
    assert all(str(value).startswith("/") or str(value).startswith(":") for value in profile["deny_paths"])
    assert Path(profile["credential_probe_path"]).is_absolute()
    assert Path(profile["credential_probe_path"]).exists()
    manifest = _function("build_redacted_manifest")(
        _plan(scenario),
        config_bytes=b"config",
        prompt="prompt",
        event_output=_valid_jsonl(),
        stderr="stderr",
        final_output="output",
        probe_results={"credential": str(credential)},
        observed_at_ms=1,
        cleanup={"status": "clean"},
    )
    assert str(credential) not in json.dumps(manifest)


def test_credential_probe_is_explicit_existing_and_outside_runtime_root(
    scenario: Scenario, tmp_path: Path
) -> None:
    plan = _plan(scenario)
    credential = Path(plan["credential_probe_path"])
    assert credential == scenario.credential_probe.resolve()
    assert credential.is_file() and not credential.is_symlink()
    assert credential.stat().st_uid == os.getuid()
    assert not credential.is_relative_to(Path(plan["runtime_root"]))
    with pytest.raises((OSError, PermissionError, RuntimeError, ValueError, TypeError)):
        _plan(scenario, credential_probe_path=tmp_path / "missing-credential.json")


def test_profile_filesystem_mapping_merges_all_denials_and_network_is_toml_table(
    scenario: Scenario, tmp_path: Path
) -> None:
    profile = _function("build_permission_profile")(
        policy_root=scenario.policy.root,
        target_root=scenario.target.root,
        common_git_root=_common_git_root(scenario),
        dependency_roots=(tmp_path,),
        scratch_root=tmp_path / "scratch-profile",
        credential_probe_path=scenario.credential_probe,
    )
    name = profile["name"]
    permissions = profile["permissions"][name]
    filesystem = permissions["filesystem"]
    for path in profile["deny_paths"]:
        assert filesystem[path] == "deny"
    assert filesystem[str(scenario.policy.root)] == "read"
    assert filesystem[str(scenario.target.root)] == "read"
    assert filesystem[str(_common_git_root(scenario))] == "read"
    assert filesystem[str((tmp_path).resolve())] == "read"
    assert filesystem[str((tmp_path / "scratch-profile").resolve())] == "write"
    assert permissions["network"] == {"enabled": False}


def test_two_plans_for_same_target_use_distinct_random_runtime_tokens(
    scenario: Scenario,
) -> None:
    first = _plan(scenario)
    second = _plan(scenario)
    assert first["runtime_root"] != second["runtime_root"]
    assert len(Path(first["runtime_token"]).name) >= 32
    assert len(Path(second["runtime_token"]).name) >= 32
    assert not Path(first["runtime_root"]).exists()
    assert not Path(second["runtime_root"]).exists()


@pytest.mark.parametrize("probe_name", _PROBE_ORDER)
def test_sandbox_probe_argv_uses_supported_subcommand_order_and_fixed_commands(
    scenario: Scenario, probe_name: str
) -> None:
    plan = _plan(scenario)
    result = _function("build_sandbox_probe_argv")(plan, probe_name)
    argv = result["argv"]
    sandbox_index = argv.index("sandbox")
    assert sandbox_index > 0
    assert all(value != "--strict-config" for value in argv[sandbox_index + 1 :])
    assert all(value != "--ignore-user-config" for value in argv[sandbox_index + 1 :])
    assert all(value != "--ignore-rules" for value in argv[sandbox_index + 1 :])
    assert "--include-managed-config" in argv[sandbox_index + 1 :]
    assert "-P" not in argv[sandbox_index + 1 :] or argv[argv.index("-P") + 1] == plan["permission_profile_name"]
    assert "-C" in argv[sandbox_index + 1 :] or "--cd" in argv[sandbox_index + 1 :]
    separator = argv.index("--", sandbox_index + 1)
    command = argv[separator + 1 :]
    paths = plan["probe_paths"]
    if probe_name in {"policy_read", "target_read", "credential_read_denied"}:
        assert command[:3] == ["/usr/bin/head", "-c", "1"]
        assert command[3] == paths[probe_name]
    elif probe_name in {"target_write_denied", "scratch_write"}:
        assert command[:2] == ["/usr/bin/touch", "--"]
        assert command[2] == paths[probe_name]
    elif probe_name == "secret_env_absent":
        assert command[:2] == ["/bin/sh", "-c"]
        assert "SECRET" in command[2]
    else:
        assert command[0] == "/usr/bin/curl"
        assert "--max-time" in command


def test_host_and_exec_env_retain_auth_context_while_model_shell_filters_secret(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_HOME", "/tmp/codex-auth-context")
    monkeypatch.setenv("LAUNCHER_SECRET_SENTINEL", "must-not-enter-sandbox")
    plan = _plan(scenario)
    sandbox_envs: list[dict[str, str]] = []
    sandbox_probe_names: list[str] = []
    exec_envs: list[dict[str, str]] = []

    def sandbox_runner(**kwargs: object) -> dict[str, object]:
        sandbox_envs.append(dict(kwargs["env"]))
        sandbox_probe_names.append(str(kwargs["probe_name"]))
        return _valid_sandbox_results()[str(kwargs["probe_name"])]

    def process_runner(**kwargs: object) -> dict[str, object]:
        exec_envs.append(dict(kwargs["env"]))
        return {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""}

    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        sandbox_runner=sandbox_runner,
        process_runner=process_runner,
    )
    assert result["status"] == "completed", result
    assert exec_envs and exec_envs[0].get("CODEX_HOME") == "/tmp/codex-auth-context"
    assert sandbox_envs and sandbox_envs[0].get("CODEX_HOME") == "/tmp/codex-auth-context"
    assert exec_envs[0].get("LAUNCHER_SECRET_SENTINEL") == plan["launcher_secret_sentinel"]
    assert sandbox_envs[0].get("LAUNCHER_SECRET_SENTINEL") == plan["launcher_secret_sentinel"]
    shell_policy = plan["permission_profile"]["shell_environment"]
    assert shell_policy["inherit"] is False
    assert shell_policy["ignore_default_excludes"] is False
    assert "LAUNCHER_SECRET_SENTINEL" not in shell_policy["set"]
    assert all("LAUNCHER_SECRET_SENTINEL" not in value for value in plan["config_values"])
    assert "secret_env_absent" in sandbox_probe_names
    serialized = json.dumps(result["manifest"])
    assert "LAUNCHER_SECRET_SENTINEL" not in serialized


def test_default_sandbox_runner_preserves_direct_command_output_without_json_decode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _launcher_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="raw-probe-output", stderr="raw-probe-error"
        ),
    )
    monkeypatch.setattr(module.json, "loads", lambda value: (_ for _ in ()).throw(AssertionError("JSON decode")))
    result = module._default_sandbox_runner(
        argv=["/absolute/codex", "sandbox"], cwd=str(tmp_path), env={}, shell=False
    )
    assert result["returncode"] == 0
    assert result["stdout"] == "raw-probe-output"
    assert result["stderr"] == "raw-probe-error"


def test_canonical_permission_config_has_toml_network_and_exact_credential_denials(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    config = tomllib.loads("\n".join(plan["config_values"]))
    profile_name = plan["permission_profile_name"]
    permissions = config["permissions"][profile_name]
    assert permissions["network"] == {"enabled": False}
    filesystem = permissions["filesystem"]
    assert filesystem[str(scenario.credential_probe)] == "deny"
    assert filesystem[str(Path.home() / ".codex")] == "deny"
    assert filesystem[str(scenario.policy.root)] == "read"
    assert filesystem[str(scenario.target.root)] == "read"
    shell_policy = config["shell_environment_policy"]
    assert shell_policy["inherit"] == "none"
    assert shell_policy["ignore_default_excludes"] is False
    assert "LAUNCHER_SECRET_SENTINEL" not in shell_policy["set"]


def test_plan_generates_secret_sentinel_even_without_caller_launcher_env(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LAUNCHER_SECRET_SENTINEL", raising=False)
    plan = _plan(scenario)
    sentinel = plan["launcher_secret_sentinel"]
    assert isinstance(sentinel, str) and len(sentinel) >= 32
    assert plan["exec_env"]["LAUNCHER_SECRET_SENTINEL"] == sentinel
    assert "LAUNCHER_SECRET_SENTINEL" not in plan["permission_profile"]["shell_environment"]["set"]
    manifest = _function("build_redacted_manifest")(
        plan,
        config_bytes=b"config",
        prompt="prompt",
        event_output=_valid_jsonl(),
        stderr="stderr",
        final_output="output",
        probe_results={"secret_env_absent": True},
        observed_at_ms=1,
        cleanup={"status": "clean"},
    )
    assert sentinel not in json.dumps(manifest)


def test_target_read_probe_uses_committed_agents_policy_file(scenario: Scenario) -> None:
    plan = _plan(scenario)
    assert plan["probe_paths"]["target_read"] == str(scenario.target.root / "AGENTS.md")
    assert Path(plan["probe_paths"]["target_read"]).is_file()


@pytest.mark.parametrize(
    ("probe_name", "returncode", "stdout", "expected"),
    [
        ("policy_read", 0, "p", {"allowed": True}),
        ("target_read", 0, "t", {"allowed": True}),
        ("target_write_denied", 1, "", {"denied": True}),
        ("credential_read_denied", 1, "", {"denied": True}),
        ("scratch_write", 0, "", {"allowed": True}),
        ("secret_env_absent", 0, "", {"absent": True}),
        ("network_denied", 1, "", {"denied": True}),
    ],
)
def test_default_sandbox_runner_evaluates_direct_probe_return_facts(
    scenario: Scenario,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe_name: str,
    returncode: int,
    stdout: str,
    expected: dict[str, object],
) -> None:
    module = _launcher_module()
    plan = _plan(scenario)
    scratch_marker = tmp_path / "scratch-marker"
    target_marker = tmp_path / "target-marker"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = list(args[0])
        if probe_name == "scratch_write" and returncode == 0:
            scratch_marker.write_text("created\n", encoding="utf-8")
        if probe_name == "target_write_denied" and returncode != 0:
            target_marker.write_text("unexpected\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module._default_sandbox_runner(
        argv=["/absolute/codex", "sandbox"],
        cwd=str(tmp_path),
        env={},
        shell=False,
        probe_name=probe_name,
        plan=plan,
        marker_path=str(scratch_marker if probe_name == "scratch_write" else target_marker),
        credential_path_exists=True,
    )
    if probe_name == "target_write_denied" and target_marker.exists():
        assert result["status"] == "insufficient_evidence"
        assert result.get("denied") is not True
    else:
        for key, value in expected.items():
            assert result[key] == value
    assert result["returncode"] == returncode
    if probe_name == "scratch_write":
        assert not scratch_marker.exists()
    if probe_name == "target_write_denied":
        assert target_marker.exists()


def test_missing_credential_file_is_insufficient_not_a_sandbox_denial(
    scenario: Scenario, tmp_path: Path
) -> None:
    module = _launcher_module()
    plan = _plan(scenario)
    result = module._default_sandbox_runner(
        argv=["/absolute/codex", "sandbox"],
        cwd=str(tmp_path),
        env={},
        shell=False,
        probe_name="credential_read_denied",
        plan=plan,
        marker_path=str(tmp_path / "missing"),
        credential_path_exists=False,
    )
    assert result["status"] == "insufficient_evidence"
    assert result.get("denied") is not True


def test_default_run_path_uses_low_level_subprocess_for_all_seven_probes(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _launcher_module()
    plan = _plan(scenario)
    real_run = module.subprocess.run
    seen: list[str] = []

    def fake_run(*args: object, **kwargs: object):
        argv = list(args[0])
        if argv and argv[0] == "git":
            return real_run(*args, **kwargs)
        if "sandbox" in argv:
            command = argv[argv.index("--") + 1 :]
            executable = command[0]
            seen.append(executable)
            if executable == "/usr/bin/head":
                is_credential = command[-1] == str(scenario.credential_probe)
                return subprocess.CompletedProcess(argv, 1 if is_credential else 0, "" if is_credential else "x", "")
            if executable == "/usr/bin/touch":
                return subprocess.CompletedProcess(argv, 0 if "scratch" in command[-1] else 1, "", "")
            if executable == "/bin/sh":
                return subprocess.CompletedProcess(argv, 0, "", "")
            return subprocess.CompletedProcess(argv, 1, "", "")
        return subprocess.CompletedProcess(argv, 0, _valid_jsonl(), "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    result = module.run_isolated_role(
        plan,
        prompt="bounded prompt",
        process_runner=lambda **kwargs: {"returncode": 0, "stdout": _valid_jsonl(), "stderr": ""},
    )
    assert result["status"] == "completed", result
    assert seen == ["/usr/bin/head", "/usr/bin/head", "/usr/bin/touch", "/usr/bin/head", "/usr/bin/touch", "/bin/sh", "/usr/bin/curl"]


def test_successful_run_cleans_exact_launcher_runtime_and_cwd(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    result = _function("run_isolated_role")(
        plan,
        prompt="bounded prompt",
        sandbox_runner=_sandbox_runner_for(_valid_sandbox_results(), []),
        process_runner=lambda **kwargs: {
            "returncode": 0,
            "stdout": _valid_jsonl(),
            "stderr": "",
        },
    )
    assert result["status"] == "completed", result
    assert not Path(plan["cwd"]).exists()
    assert not Path(plan["runtime_root"]).exists()
    assert not Path(plan["runtime_token"]).exists()


def test_local_command_host_remains_enabled_inside_the_read_only_profile(
    scenario: Scenario,
) -> None:
    plan = _plan(scenario)
    config = tomllib.loads("\n".join(plan["config_values"]))
    features = config["features"]
    assert features["code_mode_host"] is True
    assert features["code_mode"] is False
    assert features["code_mode_only"] is False
    for key in (
        "apps",
        "plugins",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "computer_use",
        "image_generation",
        "multi_agent",
        "multi_agent_v2",
        "tool_call_mcp_elicitation",
    ):
        assert features[key] is False, key
    host = plan["capability_closure"]["local_command_host"]
    assert host["enabled"] is True
    assert set(host["allowed_commands"]) >= {"pwd", "rg", "pytest"}
    assert plan["capability_closure"].get("function_gateway") is not True
    assert "functions.exec" not in json.dumps(plan)
    profile = plan["permission_profile"]["permissions"][plan["permission_profile_name"]]
    assert profile["filesystem"][str(scenario.target.root)] == "read"
    assert profile["network"] == {"enabled": False}



def test_real_system_temp_policy_or_target_worktree_is_rejected_without_test_provider_patch(
    scenario: Scenario,
) -> None:
    module = _launcher_module()
    with pytest.raises((OSError, PermissionError, RuntimeError, ValueError)):
        module.build_invocation_plan(**_plan_kwargs(scenario))


def test_default_binary_probe_canonicalizes_codex_cli_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _launcher_module()
    binary = tmp_path / "codex"
    binary.write_bytes(b"binary")
    binary.chmod(0o755)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = list(args[0])
        if argv[:2] == [str(binary), "--version"]:
            return subprocess.CompletedProcess(argv, 0, "codex-cli 0.153.4\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "TeamIdentifier=2DC432GLL2\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    descriptor = module._default_binary_probe(binary)
    assert descriptor["version"] == "0.153.4"
    assert module.validate_binary(
        path=binary,
        expected_version="0.153.4",
        expected_sha256=hashlib.sha256(b"binary").hexdigest(),
        expected_team_identifier=TEAM_IDENTIFIER,
        supported_versions=("0.153.4",),
        probe=lambda _: descriptor,
    ) == []
