"""RED contracts for isolated current-runtime read-only role invocation.

The launcher must be a top-level, policy-pinned process boundary. These tests
use temporary Git repositories and injected probes/runners; they never invoke
Codex, authenticate, access a broker, or use the network.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

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
    return Scenario(policy=policy, target=target, binary=binary)


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
    }
    values.update(overrides)
    return values


def _plan(scenario: Scenario, *, role: str = "reviewer_high", **overrides: object) -> dict[str, object]:
    result = _function("build_invocation_plan")(
        **_plan_kwargs(scenario, role=role, **overrides)
    )
    assert type(result) is dict, "launcher plan must be a plain mapping"
    return result


def _rejected_plan(scenario: Scenario, *, role: str = "reviewer_high", **overrides: object) -> None:
    function = _function("build_invocation_plan")
    try:
        result = function(**_plan_kwargs(scenario, role=role, **overrides))
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
    scenario = Scenario(policy=policy, target=target, binary=binary)

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
    assert set(shell["set"]).issubset({"PATH", "LANG", "LC_ALL", "TZ"})
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
    assert result["status"] == "completed"
    assert [name for name, _ in probe_calls] == list(_PROBE_ORDER)
    assert all(observed is plan for _, observed in probe_calls)
    assert len(runner_calls) == 1
    call = runner_calls[0]
    assert call["shell"] is False
    assert type(call["argv"]) is list
    assert type(call["stdin"]) is str
    assert len(call["stdin"].encode()) <= 32_768
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
    raw = _valid_jsonl() + "x" * 70_000
    with pytest.raises((ValueError, RuntimeError)):
        _function("parse_codex_jsonl")(raw)


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
