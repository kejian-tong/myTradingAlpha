"""AUD-H03 cold-import purity and ordinary-runtime compatibility contracts."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CANARY = "AUD_H03_IMPORT_CANARY"
_ORDINARY_IMPORTS = (
    "tradingagents.graph.trading_graph",
    "tradingagents.graph.setup",
    "tradingagents.graph.reflection",
    "tradingagents.graph.checkpointer",
    "tradingagents.graph.analyst_execution",
    "tradingagents.agents.analysts",
    "tradingagents.agents.managers",
    "tradingagents.agents.researchers",
    "tradingagents.agents.risk_mgmt",
    "tradingagents.agents.trader",
    "tradingagents.agents.utils.agent_utils",
    "tradingagents.dataflows",
    "tradingagents.llm_clients",
    "yfinance",
)


def _isolated_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("TRADINGAGENTS_") or key.startswith("AUD_H03_"):
            environment.pop(key)
    if extra:
        environment.update(extra)
    return environment


def _project_tree(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "synthetic-project"
    nested = project / "nested" / "cwd"
    nested.mkdir(parents=True)
    (project / ".env").write_text(
        "\n".join(
            (
                f"{_CANARY}=from-dotenv",
                "TRADINGAGENTS_LLM_PROVIDER=dotenv-provider",
                "TRADINGAGENTS_DEEP_THINK_LLM=dotenv-deep",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    (project / ".env.enterprise").write_text(
        "\n".join(
            (
                "AUD_H03_ENTERPRISE_CANARY=from-enterprise",
                "TRADINGAGENTS_LLM_PROVIDER=enterprise-provider",
                "TRADINGAGENTS_QUICK_THINK_LLM=enterprise-quick",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return project, nested


def _run_isolated(
    tmp_path: Path,
    source: str,
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    _project, nested = _project_tree(tmp_path)
    prefix = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(REPOSITORY_ROOT)!r})\n"
        f"os.chdir({str(nested)!r})\n"
    )
    return subprocess.run(
        [sys.executable, "-I", "-c", prefix + source],
        cwd=nested,
        env=_isolated_environment(environment),
        check=False,
        capture_output=True,
        text=True,
    )


def _json_result(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "module_name",
    (
        "tradingagents",
        "tradingagents.graph.historical",
        "mytradingalpha.research.cached_response",
        "mytradingalpha.research.tradingagents_adapter",
    ),
)
def test_cold_imports_do_not_cross_ordinary_runtime_boundaries(
    tmp_path: Path,
    module_name: str,
) -> None:
    source = f"""
import importlib
import json
import sys
import warnings

socket_calls = []
def reject_socket(event, args):
    if event != "socket.__new__":
        return
    socket_calls.append(args)
    raise AssertionError("cold import attempted to construct a socket")

sys.addaudithook(reject_socket)
filters_before = list(warnings.filters)
importlib.import_module({module_name!r})
forbidden_prefixes = {list(_ORDINARY_IMPORTS)!r}
forbidden_loaded = sorted(
    name
    for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
bare_preloads = sorted(
    name
    for name in sys.modules
    if name.startswith(("tradingagents.graph", "tradingagents.agents", "langchain", "langgraph"))
)
print(json.dumps({{
    "canary": os.environ.get({_CANARY!r}),
    "enterprise_canary": os.environ.get("AUD_H03_ENTERPRISE_CANARY"),
    "filters_unchanged": filters_before == warnings.filters,
    "forbidden_loaded": forbidden_loaded,
    "bare_preloads": bare_preloads if {module_name!r} == "tradingagents" else [],
    "socket_calls": len(socket_calls),
}}))
"""
    observed = _json_result(_run_isolated(tmp_path, source))

    assert observed == {
        "canary": None,
        "enterprise_canary": None,
        "filters_unchanged": True,
        "forbidden_loaded": [],
        "bare_preloads": [],
        "socket_calls": 0,
    }


@pytest.mark.parametrize(
    "import_source",
    (
        "import tradingagents.default_config",
        "from tradingagents.graph.trading_graph import TradingAgentsGraph",
        "import cli.main",
    ),
)
def test_ordinary_entry_points_preserve_dotenv_precedence(
    tmp_path: Path,
    import_source: str,
) -> None:
    source = f"""
import json
{import_source}
from tradingagents.default_config import DEFAULT_CONFIG
print(json.dumps({{
    "canary": os.environ.get({_CANARY!r}),
    "enterprise_canary": os.environ.get("AUD_H03_ENTERPRISE_CANARY"),
    "provider": DEFAULT_CONFIG["llm_provider"],
    "deep": DEFAULT_CONFIG["deep_think_llm"],
    "quick": DEFAULT_CONFIG["quick_think_llm"],
}}))
"""
    observed = _json_result(
        _run_isolated(
            tmp_path,
            source,
            environment={"TRADINGAGENTS_LLM_PROVIDER": "exported-provider"},
        )
    )

    assert observed == {
        "canary": "from-dotenv",
        "enterprise_canary": "from-enterprise",
        "provider": "exported-provider",
        "deep": "dotenv-deep",
        "quick": "enterprise-quick",
    }


def test_default_config_reload_rechecks_exports_without_rereading_dotenv(
    tmp_path: Path,
) -> None:
    source = f"""
import importlib
import json
import tradingagents.default_config as default_config

os.environ.pop({_CANARY!r})
os.environ["TRADINGAGENTS_OUTPUT_LANGUAGE"] = "Reloaded language"
default_config = importlib.reload(default_config)
print(json.dumps({{
    "canary": os.environ.get({_CANARY!r}),
    "language": default_config.DEFAULT_CONFIG["output_language"],
}}))
"""
    observed = _json_result(_run_isolated(tmp_path, source))

    assert observed == {"canary": None, "language": "Reloaded language"}


def test_invalid_ordinary_config_still_fails_loudly(tmp_path: Path) -> None:
    source = """
import json
try:
    import tradingagents.default_config
except Exception as exc:
    print(json.dumps({"type": type(exc).__name__, "message": str(exc)}))
else:
    print(json.dumps({"type": None, "message": ""}))
"""
    observed = _json_result(
        _run_isolated(
            tmp_path,
            source,
            environment={"TRADINGAGENTS_MAX_DEBATE_ROUNDS": "not-an-integer"},
        )
    )

    assert observed["type"] == "ValueError"
    assert "TRADINGAGENTS_MAX_DEBATE_ROUNDS" in observed["message"]


_GRAPH_EXPORTS = {
    "TradingAgentsGraph": "tradingagents.graph.trading_graph",
    "ConditionalLogic": "tradingagents.graph.conditional_logic",
    "GraphSetup": "tradingagents.graph.setup",
    "HistoricalRuntimeError": "tradingagents.graph.historical",
    "HistoricalRuntimeOutputError": "tradingagents.graph.historical",
    "Propagator": "tradingagents.graph.propagation",
    "Reflector": "tradingagents.graph.reflection",
    "SignalProcessor": "tradingagents.graph.signal_processing",
    "create_historical_initial_state": "tradingagents.graph.historical",
    "validate_historical_response": "tradingagents.graph.historical",
}
_AGENT_EXPORTS = {
    "AgentState": "tradingagents.agents.utils.agent_states",
    "create_msg_delete": "tradingagents.agents.utils.agent_utils",
    "InvestDebateState": "tradingagents.agents.utils.agent_states",
    "RiskDebateState": "tradingagents.agents.utils.agent_states",
    "create_bear_researcher": "tradingagents.agents.researchers.bear_researcher",
    "create_bull_researcher": "tradingagents.agents.researchers.bull_researcher",
    "create_research_manager": "tradingagents.agents.managers.research_manager",
    "create_fundamentals_analyst": "tradingagents.agents.analysts.fundamentals_analyst",
    "create_market_analyst": "tradingagents.agents.analysts.market_analyst",
    "create_neutral_debator": "tradingagents.agents.risk_mgmt.neutral_debator",
    "create_news_analyst": "tradingagents.agents.analysts.news_analyst",
    "create_aggressive_debator": "tradingagents.agents.risk_mgmt.aggressive_debator",
    "create_portfolio_manager": "tradingagents.agents.managers.portfolio_manager",
    "create_conservative_debator": "tradingagents.agents.risk_mgmt.conservative_debator",
    "create_sentiment_analyst": "tradingagents.agents.analysts.sentiment_analyst",
    "create_social_media_analyst": "tradingagents.agents.analysts.sentiment_analyst",
    "create_trader": "tradingagents.agents.trader.trader",
}


@pytest.mark.parametrize(
    ("package_name", "expected_exports"),
    (
        ("tradingagents.graph", _GRAPH_EXPORTS),
        ("tradingagents.agents", _AGENT_EXPORTS),
    ),
)
def test_lazy_public_exports_preserve_names_wildcards_and_identities(
    package_name: str,
    expected_exports: dict[str, str],
) -> None:
    package = importlib.import_module(package_name)

    assert package.__all__ == list(expected_exports)
    wildcard_namespace: dict[str, object] = {}
    exec(f"from {package_name} import *", {}, wildcard_namespace)
    assert set(wildcard_namespace).difference({"__builtins__"}) == set(expected_exports)

    for name, source_module_name in expected_exports.items():
        source_module = importlib.import_module(source_module_name)
        source_object = getattr(source_module, name)
        assert getattr(package, name) is source_object
        assert wildcard_namespace[name] is source_object
