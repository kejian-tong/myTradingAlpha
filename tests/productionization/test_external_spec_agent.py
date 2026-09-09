from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_OPENAI_DOCS_MCP = "https://developers.openai.com/mcp"
_OPENAI_DOCS_TOOLS = ["fetch_openai_doc", "search_openai_docs"]


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("agent_harness_checker", path)
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
    for name in ("codex_hook_guard.py", "codex_telemetry_hook.py", "codex_pretool_guard.py"):
        shutil.copyfile(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    return tmp_path


def test_external_spec_researcher_mcp_configuration_intent_is_exact() -> None:
    """Static TOML intent is checked here; it is not runtime capability proof."""
    checker = _checker()
    role = checker._toml(ROOT / ".codex/agents/external-spec-researcher.toml")
    assert role.get("mcp_servers") == {
        "openaiDeveloperDocs": {
            "url": _OPENAI_DOCS_MCP,
            "enabled_tools": _OPENAI_DOCS_TOOLS,
        }
    }


def test_external_spec_researcher_mcp_tool_allowlist_drift_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/external-spec-researcher.toml"
    text = path.read_text()
    text = text.replace(
        'enabled_tools = ["fetch_openai_doc", "search_openai_docs"]',
        'enabled_tools = ["fetch_openai_doc", "search_openai_docs", "unexpected"]',
    )
    path.write_text(text)
    errors = checker.configuration_errors(fixture)
    assert any("OpenAI docs MCP" in error for error in errors), errors


def test_external_spec_researcher_extra_mcp_server_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/external-spec-researcher.toml"
    path.write_text(
        path.read_text() + '\n[mcp_servers.unapproved]\nurl = "https://example.com/mcp"\n'
    )
    errors = checker.configuration_errors(fixture)
    assert any("OpenAI docs MCP" in error for error in errors), errors


def test_role_cannot_override_project_apps_disablement(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    for path in sorted((fixture / ".codex/agents").glob("*.toml")):
        original = path.read_text()
        path.write_text(original + "\n[features]\napps = true\n")
        errors = checker.configuration_errors(fixture)
        role = path.stem.replace("-", "_")
        assert any(role in error.lower() and "apps" in error.lower() for error in errors), (
            path.name,
            errors,
        )
        path.write_text(original)


def _insert_role_features(path: Path, declaration: str) -> None:
    text = path.read_text()
    marker = "\n[agents]\n"
    assert marker in text
    path.write_text(text.replace(marker, f"\n{declaration}\n[agents]\n", 1))


@pytest.mark.parametrize(
    "declaration",
    [
        'features = "not-a-table"',
        "features = []",
        "features = {apps = false}",
        '[features]\napps = "false"',
        "[features]\napps = 0",
        "[features]\napps = 1",
        "[features]\napps = []",
        "[features]\napps = {nested = 1}",
        "[features]\napps = true",
    ],
)
def test_malformed_role_features_and_apps_values_are_rejected(
    tmp_path: Path, declaration: str
) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/agents/reviewer-high.toml"
    _insert_role_features(path, declaration)
    errors = checker.configuration_errors(fixture)
    assert errors, (declaration, errors)


def test_static_validator_diagnostic_describes_configuration_intent(tmp_path: Path) -> None:
    checker = _checker()
    fixture = _copy_harness_fixture(tmp_path)
    path = fixture / ".codex/config.toml"
    path.write_text(path.read_text().replace("apps = false", "apps = true"))
    errors = checker.configuration_errors(fixture)
    assert any("configuration intent" in error.lower() for error in errors), errors
    assert not any("runtime enforcement" in error.lower() for error in errors)


def test_mcp_endpoint_drift_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents")
    shutil.copytree(ROOT / "mytradingalpha", tmp_path / "mytradingalpha")
    shutil.copytree(ROOT / "tradingagents", tmp_path / "tradingagents")
    (tmp_path / "tests/productionization").mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/productionization/AGENTS.md", tmp_path / "tests/productionization/AGENTS.md")
    shutil.copyfile(ROOT / "AGENTS.md", tmp_path / "AGENTS.md")
    path = tmp_path / ".codex/agents/external-spec-researcher.toml"
    path.write_text(path.read_text().replace("https://developers.openai.com/mcp", "https://example.com/mcp"))
    assert "external_spec_researcher OpenAI docs MCP configuration intent differs from reviewed policy" in checker.configuration_errors(tmp_path)


def test_mcp_leak_to_reviewer_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents")
    shutil.copytree(ROOT / "mytradingalpha", tmp_path / "mytradingalpha")
    shutil.copytree(ROOT / "tradingagents", tmp_path / "tradingagents")
    (tmp_path / "tests/productionization").mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/productionization/AGENTS.md", tmp_path / "tests/productionization/AGENTS.md")
    shutil.copyfile(ROOT / "AGENTS.md", tmp_path / "AGENTS.md")
    path = tmp_path / ".codex/agents/reviewer-high.toml"
    path.write_text(path.read_text() + '\n[mcp_servers.bad]\nurl = "https://example.com"\n')
    errors = checker.configuration_errors(tmp_path)
    assert "reviewer_high must not declare role-level MCP configuration intent" in errors
    assert not any("receive" in error.lower() for error in errors)
