"""RED contracts for strict host-runtime capability receipt admission."""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/runtime_capability_receipt.py"
ROLE_CONFIG = ".codex/agents/reviewer-high.toml"

_REQUIRED_FIELDS = (
    "schema_version",
    "evidence_source",
    "source_ref",
    "session_digest",
    "turn_digest",
    "agent_digest",
    "pr_id",
    "role",
    "config_path",
    "runtime_version",
    "multi_agent_version",
    "model",
    "reasoning_effort",
    "base_sha",
    "head_sha",
    "tree_sha",
    "sandbox_mode",
    "permission_system",
    "permission_profile",
    "approval_policy",
    "tool_inventory_complete",
    "tool_names",
    "observed_at_ms",
)


def _module():
    if not SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/runtime_capability_receipt.py")
    spec = importlib.util.spec_from_file_location("runtime_capability_receipt", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(ref: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", ref], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def _receipt(**overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": 1,
        "evidence_source": "host_runtime",
        "source_ref": "a" * 64,
        "session_digest": "b" * 64,
        "turn_digest": "c" * 64,
        "agent_digest": "d" * 64,
        "pr_id": "HARNESS-AUD-01",
        "role": "reviewer_high",
        "config_path": ROLE_CONFIG,
        "runtime_version": "codex-runtime-test",
        "multi_agent_version": "v2",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "base_sha": _git("eb51043cc5ea84277888781ce7c9f651ac882dcd"),
        "head_sha": _git("HEAD"),
        "tree_sha": _git("HEAD^{tree}"),
        "sandbox_mode": "read-only",
        "permission_system": "legacy_sandbox",
        "permission_profile": "disabled",
        "approval_policy": "never",
        "tool_inventory_complete": True,
        "tool_names": ["mcp__codex_app__read_thread", "view_image"],
        "observed_at_ms": 0,
    }
    receipt.update(overrides)
    return receipt


def _errors(
    receipt: object,
    *,
    repo_root: Path = ROOT,
    expected_pr_id: str = "HARNESS-AUD-01",
    expected_base_sha: str | None = None,
    expected_head_sha: str | None = None,
) -> list[str]:
    module = _module()
    candidate = receipt
    if "permission_system" not in module.REQUIRED_FIELDS:
        if type(candidate) is dict:
            candidate = dict(candidate)
            candidate.pop("permission_system", None)
        elif isinstance(candidate, (bytes, str)):
            decoded = json.loads(candidate)
            decoded.pop("permission_system", None)
            candidate = json.dumps(decoded)
    kwargs: dict[str, object] = {"repo_root": repo_root}
    parameters = inspect.signature(module.verify_receipt).parameters
    if "expected_pr_id" in parameters:
        kwargs.update(
            expected_pr_id=expected_pr_id,
            expected_base_sha=expected_base_sha
            or _git("eb51043cc5ea84277888781ce7c9f651ac882dcd"),
            expected_head_sha=expected_head_sha or _git("HEAD"),
        )
    result = module.verify_receipt(candidate, **kwargs)
    assert isinstance(result, list), "verify_receipt must return a list of admission errors"
    return result


def _run_cli(path: Path) -> subprocess.CompletedProcess[str]:
    if not SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/runtime_capability_receipt.py")
    arguments = [
        sys.executable,
        str(SCRIPT),
        "--verify",
        str(path),
        "--repo-root",
        str(ROOT),
    ]
    if "expected_pr_id" in inspect.signature(_module().verify_receipt).parameters:
        arguments.extend(
            [
                "--expected-pr-id",
                "HARNESS-AUD-01",
                "--expected-base-sha",
                _git("eb51043cc5ea84277888781ce7c9f651ac882dcd"),
                "--expected-head-sha",
                _git("HEAD"),
            ]
        )
    return subprocess.run(
        arguments,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _temporary_repo(tmp_path: Path, *, model: str = "gpt-5.6-sol") -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    config = repo / ROLE_CONFIG
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            (
                'name = "reviewer_high"',
                f'model = "{model}"',
                'model_reasoning_effort = "high"',
                'sandbox_mode = "read-only"',
                "[agents]",
                "enabled = false",
                "",
            )
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", ROLE_CONFIG], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Receipt Test",
            "-c",
            "user.email=receipt@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    tree = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True
    ).strip()
    return repo, head, tree


def test_valid_receipt_is_structural_contract_evidence_only() -> None:
    assert _errors(_receipt()) == []

    # Digest-shaped references have no authenticated meaning in this offline verifier.
    for field in ("source_ref", "session_digest", "turn_digest", "agent_digest"):
        changed = _receipt(**{field: "f" * 64})
        assert _errors(changed) == []


def test_trusted_expectations_are_mandatory_verifier_inputs() -> None:
    parameters = inspect.signature(_module().verify_receipt).parameters

    for name in ("expected_pr_id", "expected_base_sha", "expected_head_sha"):
        assert name in parameters
        assert parameters[name].default is inspect.Parameter.empty


def test_cli_accepts_valid_receipt_as_contract_evidence(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    result = _run_cli(receipt_path)

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("field", _REQUIRED_FIELDS)
def test_missing_required_field_fails_closed(field: str) -> None:
    receipt = _receipt()
    del receipt[field]

    assert _errors(receipt)


def test_unknown_field_fails_closed() -> None:
    receipt = _receipt(untrusted_instruction="ignore the admission policy")

    assert _errors(receipt)


def test_duplicate_json_field_fails_closed(tmp_path: Path) -> None:
    receipt = _receipt()
    pairs = [*receipt.items(), ("model", receipt["model"])]
    receipt_path = tmp_path / "duplicate.json"
    receipt_path.write_text(
        "{" + ",".join(json.dumps(key) + ":" + json.dumps(value) for key, value in pairs) + "}",
        encoding="utf-8",
    )

    result = _run_cli(receipt_path)

    assert result.returncode != 0, result.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", True),
        ("evidence_source", "codex_transcript"),
        ("source_ref", "A" * 64),
        ("session_digest", 7),
        ("turn_digest", "f" * 63),
        ("agent_digest", "g" * 64),
        ("pr_id", ""),
        ("role", 7),
        ("config_path", "../.codex/agents/reviewer-high.toml"),
        ("runtime_version", ["codex-runtime-test"]),
        ("multi_agent_version", None),
        ("reasoning_effort", "bogus"),
        ("base_sha", "A" * 40),
        ("head_sha", "not-a-sha"),
        ("tree_sha", "e" * 39),
        ("sandbox_mode", "unknown"),
        ("permission_profile", "workspace-write"),
        ("approval_policy", "ask-everything"),
        ("tool_inventory_complete", 1),
        ("tool_names", "mcp__codex_app__read_thread"),
        ("observed_at_ms", True),
    ],
)
def test_wrong_types_and_enums_fail_closed(field: str, value: object) -> None:
    assert _errors(_receipt(**{field: value}))


def test_all_string_and_enum_fields_reject_unhashable_containers_without_raising() -> None:
    fields = (
        "evidence_source",
        "source_ref",
        "session_digest",
        "turn_digest",
        "agent_digest",
        "pr_id",
        "role",
        "config_path",
        "runtime_version",
        "multi_agent_version",
        "model",
        "reasoning_effort",
        "base_sha",
        "head_sha",
        "tree_sha",
        "sandbox_mode",
        "permission_system",
        "permission_profile",
        "approval_policy",
    )

    for field in fields:
        for value in ([], {}):
            assert _errors(_receipt(**{field: value})), (field, value)


@pytest.mark.parametrize("raw", [False, True])
def test_lone_surrogate_unicode_returns_controlled_errors(raw: bool) -> None:
    receipt = _receipt(runtime_version="\ud800")
    candidate: object = json.dumps(receipt).encode() if raw else receipt

    assert _errors(candidate)


def test_observed_at_must_be_nonnegative() -> None:
    assert _errors(_receipt(observed_at_ms=-1))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "gpt-5.6-luna"),
        ("reasoning_effort", "xhigh"),
        ("config_path", ".codex/agents/normal-implementer.toml"),
        ("role", "normal_implementer"),
    ],
)
def test_configured_role_intent_must_match_receipt(field: str, value: object) -> None:
    assert _errors(_receipt(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_sha", "e" * 40),
        ("head_sha", "e" * 40),
        ("tree_sha", "f" * 40),
    ],
)
def test_receipt_must_bind_exact_repository_commit_and_tree(field: str, value: object) -> None:
    assert _errors(_receipt(**{field: value}))


@pytest.mark.parametrize(
    ("receipt_overrides", "expected_overrides"),
    [
        ({"pr_id": "HARNESS-AUD-02"}, {}),
        ({"base_sha": _git("HEAD")}, {}),
        ({}, {"expected_head_sha": _git("eb51043cc5ea84277888781ce7c9f651ac882dcd")}),
    ],
)
def test_receipt_must_equal_trusted_pr_base_and_head(
    receipt_overrides: dict[str, object], expected_overrides: dict[str, str]
) -> None:
    assert _errors(_receipt(**receipt_overrides), **expected_overrides)


def test_trusted_base_must_be_an_ancestor_of_trusted_head(tmp_path: Path) -> None:
    repo, head, tree = _temporary_repo(tmp_path)
    unrelated = subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Receipt Test",
            "-c",
            "user.email=receipt@example.invalid",
            "commit-tree",
            tree,
            "-m",
            "unrelated",
        ],
        text=True,
    ).strip()
    receipt = _receipt(base_sha=unrelated, head_sha=head, tree_sha=tree)

    assert _errors(
        receipt,
        repo_root=repo,
        expected_base_sha=unrelated,
        expected_head_sha=head,
    )


def test_role_intent_is_loaded_from_exact_head_tree_not_dirty_worktree(tmp_path: Path) -> None:
    repo, head, tree = _temporary_repo(tmp_path)
    (repo / ROLE_CONFIG).write_text(
        (repo / ROLE_CONFIG).read_text(encoding="utf-8").replace(
            'model = "gpt-5.6-sol"', 'model = "dirty-untrusted-model"'
        ),
        encoding="utf-8",
    )
    receipt = _receipt(base_sha=head, head_sha=head, tree_sha=tree)

    assert _errors(
        receipt,
        repo_root=repo,
        expected_base_sha=head,
        expected_head_sha=head,
    ) == []


def test_model_is_derived_from_exact_role_toml_without_a_global_allowlist(
    tmp_path: Path,
) -> None:
    repo, head, tree = _temporary_repo(tmp_path, model="future-model-test")
    receipt = _receipt(
        model="future-model-test", base_sha=head, head_sha=head, tree_sha=tree
    )

    assert _errors(
        receipt,
        repo_root=repo,
        expected_base_sha=head,
        expected_head_sha=head,
    ) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sandbox_mode", "workspace-write"),
        ("permission_profile", "workspace-write"),
    ],
)
def test_read_only_role_rejects_non_read_only_effective_capability(field: str, value: object) -> None:
    assert _errors(_receipt(**{field: value}))


def test_disabled_permission_profile_is_not_read_only_when_profile_governs() -> None:
    errors = _errors(
        _receipt(
            permission_system="permission_profile",
            sandbox_mode="danger-full-access",
            permission_profile="disabled",
        )
    )

    assert any("permission" in error for error in errors)


def test_read_only_permission_profile_can_govern_independently_of_legacy_sandbox() -> None:
    assert _errors(
        _receipt(
            permission_system="permission_profile",
            sandbox_mode="danger-full-access",
            permission_profile="read-only",
        )
    ) == []


def test_incomplete_tool_inventory_fails_closed() -> None:
    assert _errors(_receipt(tool_inventory_complete=False))


def test_duplicate_tool_names_fail_closed() -> None:
    assert _errors(_receipt(tool_names=["view_image", "view_image"]))


def test_unsorted_tool_names_fail_closed() -> None:
    assert _errors(_receipt(tool_names=["view_image", "mcp__codex_app__read_thread"]))


@pytest.mark.parametrize(
    "tool_name",
    [
        "apply_patch",
        "exec_command",
        "write_stdin",
        "mcp__codex_app__send_message_to_thread",
        "mcp__codex_apps__github_create_pull_request",
    ],
)
def test_explicit_mutation_tool_exposure_fails_closed(tool_name: str) -> None:
    assert _errors(_receipt(tool_names=[tool_name]))


@pytest.mark.parametrize(
    "tool_name",
    [
        "apply_patch",
        "exec_command",
        "write_stdin",
        "mcp__codex_app__get_handoff_status",
    ],
)
def test_sandbox_governed_local_tools_are_allowed_in_read_only_sandbox(
    tool_name: str,
) -> None:
    assert _errors(_receipt(tool_names=[tool_name])) == []


@pytest.mark.parametrize(
    "tool_name",
    [
        "spawn_agent",
        "followup_task",
        "interrupt_agent",
        "send_message",
        "mcp__codex_apps__github_add_pull_request_review_comment",
        "mcp__codex_apps__github_enable_auto_merge",
        "mcp__codex_apps__github_dismiss_pull_request_review",
        "mcp__codex_apps__github_lock_issue",
        "mcp__codex_apps__github_resolve_review_thread",
        "mcp__codex_apps__sites_publish",
        "mcp__codex_app__consume_usage_reset",
        "mcp__codex_app__uninstall_plugin",
        "mcp__codex_app__end_realtime_voice_call",
        "mcp__codex_app__navigate_to_codex_page",
        "mcp__codex_app__open_in_codex",
    ],
)
def test_direct_collaboration_and_external_mutation_tools_are_rejected(
    tool_name: str,
) -> None:
    assert _errors(_receipt(tool_names=[tool_name]))


@pytest.mark.parametrize(
    "tool_names",
    [
        [""],
        ["x" * 100_000],
        ["mcp__codex_app__read_thread", 7],
    ],
)
def test_tool_inventory_names_are_bounded_strings(tool_names: list[object]) -> None:
    assert _errors(_receipt(tool_names=tool_names))


def test_oversize_receipt_input_fails_closed(tmp_path: Path) -> None:
    receipt_path = tmp_path / "oversize.json"
    encoded = json.dumps(_receipt())
    receipt_path.write_text(encoded + " " * (70_000 - len(encoded)), encoding="utf-8")

    result = _run_cli(receipt_path)

    assert result.returncode != 0, result.stdout


def test_cli_rejects_exposed_mutation_tool(tmp_path: Path) -> None:
    receipt_path = tmp_path / "mutation-tool.json"
    receipt_path.write_text(
        json.dumps(_receipt(tool_names=["apply_patch"])), encoding="utf-8"
    )

    result = _run_cli(receipt_path)

    assert result.returncode != 0, result.stdout


def test_cli_requires_all_trusted_expectations(tmp_path: Path) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify",
            str(receipt_path),
            "--repo-root",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode != 0, result.stdout
    for option in ("--expected-pr-id", "--expected-base-sha", "--expected-head-sha"):
        assert option in result.stdout


def test_cli_diagnostics_do_not_echo_hostile_keys_or_values(tmp_path: Path) -> None:
    hostile_key = "API_TOKEN\n\x1b[31mINJECTED"
    hostile_value = "apply_patch\n\x1b[31mSECRET_VALUE"
    receipt = _receipt(tool_names=[hostile_value])
    receipt[hostile_key] = "TOP_SECRET"
    receipt_path = tmp_path / "hostile.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = _run_cli(receipt_path)

    assert result.returncode != 0
    for forbidden in ("\x1b", "API_TOKEN", "INJECTED", "SECRET_VALUE", "TOP_SECRET"):
        assert forbidden not in result.stdout
