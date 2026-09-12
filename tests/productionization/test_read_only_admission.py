"""Static admission contracts for repository read-only roles."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]
READ_ONLY_ROLES = (
    "reviewer_high",
    "reviewer_xhigh",
    "code_explorer",
    "test_auditor",
    "boundary_reviewer",
    "external_spec_researcher",
    "astra_canary",
)
ORDINARY_ROLES = tuple(role for role in READ_ONLY_ROLES if role != "external_spec_researcher")
WRITER_ROLES = (
    "normal_implementer",
    "high_implementer",
    "critical_implementer",
)


def _role(role: str) -> dict[str, object]:
    path = ROOT / ".codex/agents" / f"{role.replace('_', '-')}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _launcher():
    path = ROOT / "scripts/read_only_role_launcher.py"
    spec = importlib.util.spec_from_file_location("read_only_admission", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_all_read_only_roles_disable_children_and_role_level_capabilities() -> None:
    for role in READ_ONLY_ROLES:
        config = _role(role)
        assert config["sandbox_mode"] == "read-only", role
        assert config["agents"] == {"enabled": False}, role
        assert "features" not in config, role
        assert "mcp_servers" not in config, role
        instructions = str(config["developer_instructions"])
        assert "read_only_role_launcher.py" in instructions, role
        assert "No model-accessible tools" in instructions, role
        for clause in (
            "Collaboration-control visibility alone is non-blocking.",
            "Do not invoke collaboration controls or delegate nested work.",
            "Any attempted or completed nested delegation is a blocking violation.",
        ):
            assert clause in instructions, role


def test_ordinary_roles_require_static_bundle_citations() -> None:
    for role in ORDINARY_ROLES:
        instructions = str(_role(role)["developer_instructions"])
        assert "static exact-object review bundle" in instructions, role
        assert "record ID" in instructions, role
        assert "base/head blob IDs" in instructions, role
        assert "untrusted data" in instructions, role


def test_external_spec_is_unavailable_before_model_start() -> None:
    instructions = str(_role("external_spec_researcher")["developer_instructions"])
    assert "before model start" in instructions
    assert "official OpenAI documentation" in instructions
    assert "Candidate bundles" in instructions
    assert "static exact-object review-bundle consumer" in instructions


def test_writer_roles_remain_writable_and_do_not_use_static_launcher() -> None:
    for role in WRITER_ROLES:
        config = _role(role)
        assert config.get("sandbox_mode") != "read-only", role
        assert "read_only_role_launcher.py" not in str(config["developer_instructions"]), role


def test_project_config_keeps_master_only_concurrency_and_apps_closed() -> None:
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
    assert config["agents"] == {
        "enabled": True,
        "max_concurrent_threads_per_session": 6,
    }
    assert config["features"]["apps"] is False
    assert "mcp_servers" not in config
    assert "permissions" not in config
    assert "default_permissions" not in config


def test_protocol_documents_zero_tool_bundle_and_same_pid_handshake() -> None:
    sources = (
        ROOT / "AGENTS.md",
        ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
        ROOT / "docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md",
        ROOT / "docs/productionization/CODEX_HARNESS_TELEMETRY.md",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    for marker in (
        "zero-tool",
        "canonical exact-object",
        "READY",
        "RELEASE",
        "PID == PGID == SID",
        "shell_tool=false",
        "insufficient_evidence",
        "candidate",
        "untrusted",
    ):
        assert marker in text
    for obsolete in (
        "shell_tool=true",
        "direct shell",
        "command-event parser",
        "arbitrary descendant",
    ):
        assert obsolete not in text


def test_launcher_role_sets_match_static_policy() -> None:
    module = _launcher()
    assert frozenset(ORDINARY_ROLES) == module.ORDINARY_READ_ONLY_ROLES
    assert frozenset(READ_ONLY_ROLES) == module.READ_ONLY_ROLES
    assert module.EXTERNAL_SPEC_ROLE == "external_spec_researcher"


@pytest.mark.parametrize("permission_profile", ["disabled", None, ""])
def test_disabled_or_missing_profile_never_means_read_only(
    permission_profile: object,
) -> None:
    receipt_path = ROOT / "scripts/runtime_capability_receipt.py"
    spec = importlib.util.spec_from_file_location("receipt_admission", receipt_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    receipt = {
        "permission_system": "permission_profile",
        "permission_profile": permission_profile,
        "sandbox_mode": "disabled",
    }
    assert module._local_enforcement_is_read_only(receipt) is False
