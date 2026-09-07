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


def _copy_harness(tmp_path: Path) -> None:
    shutil.copytree(ROOT / ".codex", tmp_path / ".codex")
    shutil.copytree(ROOT / "docs/productionization", tmp_path / "docs/productionization")
    shutil.copytree(ROOT / ".agents", tmp_path / ".agents")
    shutil.copytree(ROOT / "mytradingalpha", tmp_path / "mytradingalpha")
    shutil.copytree(ROOT / "tradingagents", tmp_path / "tradingagents")
    (tmp_path / "tests/productionization").mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/productionization/AGENTS.md", tmp_path / "tests/productionization/AGENTS.md")
    shutil.copyfile(ROOT / "AGENTS.md", tmp_path / "AGENTS.md")


def test_astra_canary_is_read_only_shadow_and_not_a_production_route() -> None:
    checker = _checker()
    assert checker.configuration_errors(ROOT) == []
    role = checker._toml(ROOT / ".codex/agents/astra-canary.toml")
    assert role["model"] == "gpt-6-astra"
    assert role["model_reasoning_effort"] == "xhigh"
    assert role["sandbox_mode"] == "read-only"
    assert role["agents"] == {"enabled": False}
    assert "mcp_servers" not in role
    root_policy = (ROOT / "AGENTS.md").read_text()
    assert "GPT-6 production routes remain disabled" in root_policy
    assert "shadow-only" in root_policy


def test_writable_astra_canary_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    _copy_harness(tmp_path)
    path = tmp_path / ".codex/agents/astra-canary.toml"
    path.write_text(path.read_text().replace('sandbox_mode = "read-only"', 'sandbox_mode = "workspace-write"'))
    assert "astra_canary must request read-only mode" in checker.configuration_errors(tmp_path)


def test_astra_canary_mcp_leak_is_rejected(tmp_path: Path) -> None:
    checker = _checker()
    _copy_harness(tmp_path)
    path = tmp_path / ".codex/agents/astra-canary.toml"
    path.write_text(path.read_text() + '\n[mcp_servers.bad]\nurl = "https://example.com"\n')
    assert "astra_canary must not receive external MCP servers" in checker.configuration_errors(tmp_path)
