"""Contracts for configured read-only roles without a native admission gate."""

from __future__ import annotations

import importlib.util
import re
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
LEGACY_ADMISSION_MARKER = (
    "Native read-only admission is governed by root AGENTS.md and must complete before "
    "substantive work or any tool call."
)


def _role(role: str, root: Path = ROOT) -> dict[str, object]:
    path = root / ".codex/agents" / f"{role.replace('_', '-')}.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("review_assurance_checker", path)
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
    active_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "AGENTS.md",
            ROOT / "docs/productionization/AGENT_AUDIT_PROTOCOL.md",
            ROOT / "scripts/check_agent_harness.py",
        )
    )
    for rejected in (
        "scripts/read_only_role_launcher.py",
        ".codex/read-only-probe.secret",
        "read_only_role_launcher.py",
        "read-only-probe.secret",
    ):
        assert rejected not in active_text


def test_read_only_roles_keep_configuration_and_non_mutation_contracts() -> None:
    for role in READ_ONLY_ROLES:
        config = _role(role)
        assert config["sandbox_mode"] == "read-only", role
        assert config["approval_policy"] == "never", role
        assert config["agents"] == {"enabled": False}, role

        instructions = str(config["developer_instructions"])
        assert LEGACY_ADMISSION_MARKER not in instructions, role
        for pattern in (
            r"do not edit|never edit",
            r"do not.{0,80}(?:create )?commit|never.{0,80}commit",
            r"do not.{0,80}push|never.{0,80}push",
            r"do not.{0,80}merge|never.{0,80}merge",
            r"do not invoke collaboration controls or delegate nested work",
        ):
            assert re.search(pattern, instructions, flags=re.IGNORECASE | re.DOTALL), (
                f"{role} lost non-mutation/delegation boundary: {pattern}"
            )

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


def test_checker_no_longer_owns_native_admission_or_two_turn_gate() -> None:
    source = (ROOT / "scripts/check_agent_harness.py").read_text(encoding="utf-8")
    for legacy_symbol in (
        "_READ_ONLY_ADMISSION_MARKER",
        "_ROOT_NATIVE_ADMISSION_CONTRACT",
        "_TWO_TURN_NATIVE_ADMISSION_CONTRACT",
        "two-turn native admission contract is missing",
    ):
        assert legacy_symbol not in source
    assert "sandbox_mode" in source
    assert "approval_policy" in source


def test_offline_validator_allows_retired_role_admission_marker(
    tmp_path: Path,
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/reviewer-high.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(LEGACY_ADMISSION_MARKER, ""), encoding="utf-8")

    errors = checker.configuration_errors(fixture)
    assert not any(
        "reviewer_high" in error and "admission" in error.casefold()
        for error in errors
    ), errors


@pytest.mark.parametrize(
    "relative",
    ("AGENTS.md", "docs/productionization/AGENT_AUDIT_PROTOCOL.md"),
)
def test_offline_validator_allows_retired_two_turn_gate(
    tmp_path: Path,
    relative: str,
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / relative
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("first child turn is admission-only", "review context is separate"),
        encoding="utf-8",
    )

    errors = checker.configuration_errors(fixture)
    assert not any("two-turn native admission" in error for error in errors), errors
