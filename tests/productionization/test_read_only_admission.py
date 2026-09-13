"""Contracts for native host admission of repository read-only roles."""

from __future__ import annotations

import importlib.util
import shutil
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
WRITER_ROLES = (
    "normal_implementer",
    "high_implementer",
    "critical_implementer",
)
ROLE_ADMISSION_MARKER = (
    "Native read-only admission is governed by root AGENTS.md and must complete before "
    "substantive work or any tool call."
)
TWO_TURN_ADMISSION_CONTRACT = (
    "first child turn is admission-only",
    "receive no substantive task",
    "make no tool call",
    "cannot self-approve",
    "follow-up substantive task",
    "interrupt and discard the lane",
)
POLICY_PATHS = (
    ".codex/config.toml",
    "AGENTS.md",
    "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
    "docs/productionization/CODEX_FEATURE_WATCHLIST.md",
    "docs/productionization/CODEX_HARNESS_TELEMETRY.md",
    "docs/productionization/HYBRID_CONCURRENCY_PROTOCOL.md",
    "scripts/check_agent_harness.py",
    *(f".codex/agents/{role.replace('_', '-')}.toml" for role in READ_ONLY_ROLES),
)


def _role(role: str, root: Path = ROOT) -> dict[str, object]:
    path = root / ".codex/agents" / f"{role.replace('_', '-')}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("native_admission_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_harness_fixture(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    for relative in (
        "AGENTS.md",
        "mytradingalpha/AGENTS.md",
        "tradingagents/AGENTS.md",
        "tests/productionization/AGENTS.md",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    (tmp_path / "scripts").mkdir()
    for name in (
        "codex_hook_guard.py",
        "codex_telemetry_hook.py",
        "codex_pretool_guard.py",
    ):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    return tmp_path


def test_rejected_launcher_canary_and_policy_claims_are_absent() -> None:
    assert not (ROOT / "scripts/read_only_role_launcher.py").exists()
    assert not (ROOT / ".codex/read-only-probe.secret").exists()
    text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in POLICY_PATHS)
    for rejected in (
        "scripts/read_only_role_launcher.py",
        ".codex/read-only-probe.secret",
        "read_only_role_launcher.py",
        "read-only-probe.secret",
    ):
        assert rejected not in text


def test_exact_read_only_roles_declare_compact_intent_only_contract() -> None:
    for role in READ_ONLY_ROLES:
        config = _role(role)
        assert config["sandbox_mode"] == "read-only", role
        assert config["approval_policy"] == "never", role
        assert config["agents"] == {"enabled": False}, role
        instructions = str(config["developer_instructions"])
        assert ROLE_ADMISSION_MARKER in instructions, role
        admission_lines = [
            line for line in instructions.splitlines() if "admission" in line.casefold()
        ]
        assert admission_lines == [ROLE_ADMISSION_MARKER], role
    for role in WRITER_ROLES:
        assert "approval_policy" not in _role(role), role


def test_external_spec_preserves_docs_mcp_and_fallback_contract() -> None:
    config = _role("external_spec_researcher")
    assert config["mcp_servers"] == {
        "openaiDeveloperDocs": {
            "url": "https://developers.openai.com/mcp",
            "enabled_tools": ["fetch_openai_doc", "search_openai_docs"],
        }
    }
    instructions = str(config["developer_instructions"])
    assert "actually exposes and successfully calls it" in instructions
    assert "another official public source only when" in instructions


def test_root_policy_requires_host_origin_native_admission_and_fails_closed() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for required in (
        "fresh host-enforced read-only parent",
        "live parent overrides are controlling",
        "post-spawn host-origin evidence",
        "effective sandbox/profile/approval tuple",
        "complete tool inventory",
        "before substantive work or any tool call",
        "discard the lane",
        "insufficient_evidence",
    ):
        assert required in text
    for unauthenticated in (
        "model self-report",
        "caller-created JSON",
        "hooks",
        "telemetry",
        "static TOML",
        "offline verifier",
    ):
        assert unauthenticated in text
    assert "cannot authenticate" in text


def test_root_and_protocol_require_two_turn_master_owned_admission() -> None:
    for relative in (
        "AGENTS.md",
        "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for required in TWO_TURN_ADMISSION_CONTRACT:
            assert required in text, f"{relative}: {required}"
        assert "child/model prose" in text


def test_project_config_defers_to_native_parent_without_claiming_runtime_proof() -> None:
    config = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
    assert config["agents"] == {
        "enabled": True,
        "max_concurrent_threads_per_session": 6,
    }
    assert config["features"]["apps"] is False
    instructions = str(config["developer_instructions"])
    assert "fresh host-enforced read-only parent" in instructions
    assert "post-spawn host-origin" in instructions
    assert "configuration intent" in instructions
    assert "cannot authenticate" in instructions


@pytest.mark.parametrize("mutation", ["approval", "admission"])
def test_offline_validator_rejects_missing_intent_without_claiming_authentication(
    tmp_path: Path,
    mutation: str,
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/reviewer-high.toml"
    text = path.read_text(encoding="utf-8")
    if mutation == "approval":
        text = text.replace('approval_policy = "never"\n', "")
    else:
        text = text.replace(ROLE_ADMISSION_MARKER, "admission omitted")
    path.write_text(text, encoding="utf-8")
    errors = checker.configuration_errors(fixture)
    assert any("reviewer_high" in error and "intent" in error for error in errors)
    checker_source = (ROOT / "scripts/check_agent_harness.py").read_text(encoding="utf-8")
    assert "cannot authenticate host-origin runtime evidence" in checker_source


@pytest.mark.parametrize(
    "relative",
    ("AGENTS.md", "docs/productionization/AGENT_AUDIT_PROTOCOL.md"),
)
def test_offline_validator_rejects_missing_two_turn_admission_contract(
    tmp_path: Path,
    relative: str,
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / relative
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "first child turn is admission-only",
        "first child turn is unspecified",
    )
    path.write_text(text, encoding="utf-8")
    errors = checker.configuration_errors(fixture)
    assert any("two-turn native admission contract is missing" in error for error in errors)
