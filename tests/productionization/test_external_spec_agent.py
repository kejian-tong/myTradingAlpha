from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _checker():
    path = ROOT / "scripts/check_agent_harness.py"
    spec = importlib.util.spec_from_file_location("agent_harness_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_spec_researcher_is_capability_isolated() -> None:
    checker = _checker()
    assert checker.configuration_errors(ROOT) == []


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
    assert "external_spec_researcher OpenAI docs MCP differs from reviewed policy" in checker.configuration_errors(tmp_path)


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
    assert "reviewer_high must not receive external MCP servers" in checker.configuration_errors(tmp_path)
