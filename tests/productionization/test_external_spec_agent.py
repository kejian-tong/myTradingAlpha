"""External specification lane remains fail-closed until isolation is proven."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("agent_harness_checker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_harness_fixture(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents")
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


def test_external_spec_researcher_has_no_mcp_or_candidate_bundle_access() -> None:
    role = _checker()._toml(ROOT / ".codex/agents/external-spec-researcher.toml")
    assert "mcp_servers" not in role
    instructions = role["developer_instructions"]
    assert "before model start" in instructions
    assert "No model-accessible tools" in instructions
    assert "Candidate bundles" in instructions
    assert "official OpenAI documentation" in instructions


def test_any_external_spec_mcp_declaration_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/external-spec-researcher.toml"
    path.write_text(
        path.read_text()
        + '\n[mcp_servers.openaiDeveloperDocs]\nurl = "https://developers.openai.com/mcp"\n'
    )
    errors = checker.configuration_errors(fixture)
    assert "external_spec_researcher must not declare role-level MCP configuration intent" in errors


def test_role_cannot_override_project_apps_disablement(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/reviewer-high.toml"
    text = path.read_text()
    path.write_text(text.replace("\n[agents]\n", "\n[features]\napps = true\n[agents]\n"))
    errors = checker.configuration_errors(fixture)
    assert any("reviewer_high" in error and "features" in error for error in errors)


def test_static_validator_diagnostic_describes_configuration_intent(
    tmp_path: Path,
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/config.toml"
    path.write_text(path.read_text().replace("apps = false", "apps = true"))
    errors = checker.configuration_errors(fixture)
    assert any("configuration intent" in error.lower() for error in errors)
    assert not any("runtime enforcement" in error.lower() for error in errors)
