"""RED contracts for strict host-runtime capability receipt admission."""

from __future__ import annotations

import importlib.util
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
        "base_sha": _git("HEAD"),
        "head_sha": _git("HEAD"),
        "tree_sha": _git("HEAD^{tree}"),
        "sandbox_mode": "read-only",
        "permission_profile": "read-only",
        "approval_policy": "never",
        "tool_inventory_complete": True,
        "tool_names": ["mcp__codex_app__read_thread", "view_image"],
        "observed_at_ms": 0,
    }
    receipt.update(overrides)
    return receipt


def _errors(receipt: object, *, repo_root: Path = ROOT) -> list[str]:
    result = _module().verify_receipt(receipt, repo_root=repo_root)
    assert isinstance(result, list), "verify_receipt must return a list of admission errors"
    return result


def _run_cli(path: Path) -> subprocess.CompletedProcess[str]:
    if not SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/runtime_capability_receipt.py")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--verify",
            str(path),
            "--repo-root",
            str(ROOT),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_valid_receipt_is_structural_contract_evidence_only() -> None:
    assert _errors(_receipt()) == []

    # Digest-shaped references have no authenticated meaning in this offline verifier.
    for field in ("source_ref", "session_digest", "turn_digest", "agent_digest"):
        changed = _receipt(**{field: "f" * 64})
        assert _errors(changed) == []


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
    pairs = [*receipt.items(), ("model", "gpt-5.6-luna")]
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
    ("field", "value"),
    [
        ("sandbox_mode", "workspace-write"),
        ("permission_profile", "workspace-write"),
    ],
)
def test_read_only_role_rejects_non_read_only_effective_capability(field: str, value: object) -> None:
    assert _errors(_receipt(**{field: value}))


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
    receipt = _receipt(padding="x" * 70_000)
    receipt_path = tmp_path / "oversize.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = _run_cli(receipt_path)

    assert result.returncode != 0, result.stdout


def test_cli_rejects_exposed_mutation_tool(tmp_path: Path) -> None:
    receipt_path = tmp_path / "mutation-tool.json"
    receipt_path.write_text(
        json.dumps(_receipt(tool_names=["apply_patch"])), encoding="utf-8"
    )

    result = _run_cli(receipt_path)

    assert result.returncode != 0, result.stdout
