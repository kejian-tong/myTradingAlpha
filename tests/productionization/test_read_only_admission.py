"""RED contracts for the current-runtime read-only role launcher.

The old schema-v2 receipt proposal is intentionally not an active admission
path. A receipt remains historical supplemental evidence while the launcher
owns the isolated top-level role invocation contract.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SCRIPT = ROOT / "scripts/runtime_capability_receipt.py"
ROLE_CONFIG = ".codex/agents/reviewer-high.toml"

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
_POLICY_SOURCES = (
    ROOT / "AGENTS.md",
    ROOT / ".codex/config.toml",
    ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
    ROOT / "docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md",
    ROOT / "docs/productionization/CODEX_HARNESS_TELEMETRY.md",
    ROOT / "docs/productionization/CODEX_FEATURE_WATCHLIST.md",
)


def _receipt_module():
    if not RECEIPT_SCRIPT.is_file():
        pytest.fail("missing implementation: scripts/runtime_capability_receipt.py")
    spec = importlib.util.spec_from_file_location("runtime_capability_receipt", RECEIPT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launcher_module():
    path = ROOT / "scripts/read_only_role_launcher.py"
    if not path.is_file():
        pytest.fail("missing implementation: scripts/read_only_role_launcher.py")
    spec = importlib.util.spec_from_file_location("read_only_role_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _launcher_function(name: str):
    function = getattr(_launcher_module(), name, None)
    if function is None:
        pytest.fail(f"missing launcher API: {name}")
    return function


def _git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, stderr=subprocess.STDOUT
    ).strip()


def _v1_receipt(**overrides: object) -> dict[str, object]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()
    receipt: dict[str, object] = {
        "schema_version": 1,
        "evidence_source": "host_runtime",
        "source_ref": "a" * 64,
        "session_digest": "b" * 64,
        "turn_digest": "c" * 64,
        "agent_digest": "d" * 64,
        "pr_id": "HARNESS-AUD-03",
        "role": "reviewer_high",
        "config_path": ROLE_CONFIG,
        "runtime_version": "codex-runtime-test",
        "multi_agent_version": "v2",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "base_sha": head,
        "head_sha": head,
        "tree_sha": tree,
        "sandbox_mode": "read-only",
        "permission_system": "legacy_sandbox",
        "permission_profile": "disabled",
        "approval_policy": "never",
        "tool_inventory_complete": True,
        "tool_names": ["view_image"],
        "observed_at_ms": 0,
    }
    receipt.update(overrides)
    return receipt


def test_schema_v1_remains_valid_for_generic_verification_only() -> None:
    module = _receipt_module()
    receipt = _v1_receipt()
    assert module.verify_receipt(
        receipt,
        repo_root=ROOT,
        expected_pr_id="HARNESS-AUD-03",
        expected_base_sha=receipt["base_sha"],
        expected_head_sha=receipt["head_sha"],
        expected_role="reviewer_high",
        expected_config_path=ROLE_CONFIG,
    ) == []


def test_active_schema_v2_read_only_admission_is_not_exposed() -> None:
    module = _receipt_module()
    source = RECEIPT_SCRIPT.read_text(encoding="utf-8").lower()

    assert not hasattr(module, "verify_read_only_admission")
    assert "schema v2" not in source
    assert "schema_version=2" not in source


def _role_config(role: str) -> dict[str, object]:
    path = ROOT / ".codex/agents" / f"{role.replace('_', '-')}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_policy_prefers_isolated_launcher_and_keeps_receipts_supplemental() -> None:
    policy = "\n".join(path.read_text(encoding="utf-8") for path in _POLICY_SOURCES).lower()

    assert "read_only_role_launcher.py" in policy
    assert "isolated role invocation" in policy
    assert "schema_version=1" in policy
    assert "structural" in policy
    assert "watch-only" in policy
    assert ("not mandatory" in policy or "no mandatory" in policy) and "handshake" in policy
    assert "insufficient_evidence" in policy
    assert "in-process" in policy and "non-admissible" in policy
    assert "host attestation" in policy
    assert "launcher" in policy and "permission profile" in policy and "pilot" in policy


def test_policy_requires_non_temp_review_worktrees_for_launcher_inputs() -> None:
    policy = "\n".join(path.read_text(encoding="utf-8") for path in _POLICY_SOURCES).lower()
    assert "non-temp" in policy or "non temp" in policy
    assert "worktree" in policy


def test_policy_documents_runtime_hardening_boundaries() -> None:
    policy = "\n".join(path.read_text(encoding="utf-8") for path in _POLICY_SOURCES).lower()
    for marker in (
        "bounded streaming",
        "timeout escalation",
        "toolchain roots",
        "codex_sandbox_network_disabled",
        "codesign --verify",
    ):
        assert marker in policy, marker


def test_read_only_roles_use_launcher_protocol_without_unenforceable_handshake() -> None:
    for role in _READ_ONLY_ROLES:
        instructions = str(_role_config(role).get("developer_instructions", "")).lower()
        assert "isolated role invocation" in instructions, role
        assert "read_only_role_launcher.py" in instructions, role
        assert "read-only admission is mandatory" not in instructions, role


def test_writer_roles_remain_writable_and_do_not_use_read_only_launcher_protocol() -> None:
    for role in _WRITER_ROLES:
        config = _role_config(role)
        assert config.get("sandbox_mode") != "read-only", role
        instructions = str(config.get("developer_instructions", "")).lower()
        assert "read_only_role_launcher.py" not in instructions, role
