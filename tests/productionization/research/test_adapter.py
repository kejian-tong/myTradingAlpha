"""SIG-01 closed cached-response replay adapter contract.

The cached graph output used here is deterministic fixture data. It is not a
captured production transcript and is not evidence of real model inference.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import mytradingalpha.research.tradingagents_adapter as adapter_module
import tradingagents.agents.analysts.sentiment_analyst as sentiment_module
import tradingagents.agents.utils.agent_utils as agent_utils_module
import tradingagents.dataflows.fred as fred_module
import tradingagents.dataflows.polymarket as polymarket_module
import tradingagents.dataflows.reddit as reddit_module
import tradingagents.dataflows.stocktwits as stocktwits_module
import tradingagents.graph.checkpointer as checkpointer_module
import tradingagents.graph.historical as historical_module
import tradingagents.graph.trading_graph as trading_graph_module
import tradingagents.llm_clients as llm_clients_module
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.data.replay_guard import (
    HistoricalReplayDeniedError,
    HistoricalReplayMismatchError,
)
from mytradingalpha.data.repository import EvidenceBundleNotFoundError, EvidenceRepository
from mytradingalpha.research.cached_response import (
    CachedGraphResponseMismatchError,
    CachedGraphResponseRepository,
    CachedGraphResponseUnavailableError,
    CachedGraphSelection,
    build_cached_graph_response,
)
from mytradingalpha.research.tradingagents_adapter import HistoricalInstrumentError, ResearchAdapter
from tests.productionization.data.test_bundle_replay import _build as build_fixture_bundle
from tests.productionization.research.test_cached_response import (
    make_output,
    make_response_kwargs,
    make_selection,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.graph import TradingAgentsGraph
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    validate_historical_response,
)
from tradingagents.graph.reflection import Reflector

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPORT_FIELDS = {"market_report", "fundamentals_report", "sentiment_report", "news_report"}
AUTHORITY_FIELDS = {
    "target_weight",
    "target_weights",
    "portfolio_allocation",
    "portfolio",
    "portfolio_weights",
    "order",
    "orders",
    "order_intent",
    "order_intents",
    "order_type",
    "quantity",
    "quantities",
    "broker",
    "broker_fields",
    "broker_id",
    "broker_credentials",
    "credential",
    "credentials",
    "risk_authorization",
    "risk_authorizations",
}


def make_context(bundle: object, **overrides: object) -> RunContext:
    fields: dict[str, object] = {
        "schema_version": "v1",
        "run_id": "run-sig-01",
        "mode": Mode.HISTORICAL,
        "variant_id": "variant-research-adapter",
        "decision_time": "2024-07-01T20:00:00Z",
        "knowledge_cutoff": bundle.knowledge_cutoff,
        "earliest_execution_time": "2024-07-02T13:30:00Z",
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "calendar_id": bundle.calendar.calendar_id,
        "base_currency": "USD",
        "network_policy": NetworkPolicy(),
    }
    fields.update(overrides)
    return RunContext(**fields)  # type: ignore[arg-type]


def replace_context(context: RunContext, **updates: object) -> RunContext:
    return RunContext.model_validate({**context.model_dump(mode="python"), **updates})


def bypassed_context(context: RunContext, **updates: object) -> RunContext:
    return RunContext.model_construct(**{**context.model_dump(mode="python"), **updates})


def sealed_adapter(
    *, output: dict[str, object] | None = None, selection: CachedGraphSelection | None = None
):
    bundle = build_fixture_bundle()
    context = make_context(bundle)
    evidence_repository = EvidenceRepository()
    evidence_repository.seal(bundle)
    response_repository = CachedGraphResponseRepository()
    raw = build_cached_graph_response(
        **make_response_kwargs(bundle=bundle, context=context, output=output or make_output())
    )
    record = response_repository.seal(raw)
    exact_selection = selection or make_selection(expected_response_hash=record.response_hash)
    adapter = ResearchAdapter(evidence_repository, response_repository, exact_selection)
    return bundle, context, evidence_repository, response_repository, exact_selection, adapter


def run_adapter(adapter: ResearchAdapter, bundle: object, context: RunContext, **overrides: object):
    fields: dict[str, object] = {
        "bundle_id": bundle.bundle_id,
        "context": context,
        "ticker": "NEW",
        "trade_date": "2024-06-30",
        "asset_type": "stock",
    }
    fields.update(overrides)
    return adapter.run(**fields)  # type: ignore[arg-type]


def bomb(*args: object, **kwargs: object) -> object:
    del args, kwargs
    raise AssertionError("historical adapter crossed a forbidden side-effect boundary")


def install_side_effect_observers(monkeypatch: pytest.MonkeyPatch) -> None:
    for owner, names in (
        (
            TradingAgentsGraph,
            (
                "propagate",
                "_run_graph",
                "_resolve_pending_entries",
                "_fetch_returns",
                "resolve_instrument_context",
                "save_reports",
                "_log_state",
            ),
        ),
        (
            TradingMemoryLog,
            (
                "load_entries",
                "get_pending_entries",
                "get_past_context",
                "store_decision",
                "update_with_outcome",
                "batch_update_with_outcomes",
            ),
        ),
        (Reflector, ("reflect_on_final_decision",)),
        (
            checkpointer_module,
            (
                "get_checkpointer",
                "checkpoint_step",
                "has_checkpoint",
                "clear_checkpoint",
                "clear_all_checkpoints",
            ),
        ),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, bomb)
    for owner, names in (
        (
            trading_graph_module,
            (
                "create_llm_client",
                "resolve_instrument_identity",
                "write_report_tree",
                "get_stock_data",
                "get_indicators",
                "get_verified_market_snapshot",
                "get_news",
                "get_global_news",
                "get_insider_transactions",
                "get_macro_indicators",
                "get_prediction_markets",
                "get_fundamentals",
                "get_balance_sheet",
                "get_cashflow",
                "get_income_statement",
            ),
        ),
        (agent_utils_module, ("resolve_instrument_identity",)),
        (sentiment_module, ("get_news", "fetch_stocktwits_messages", "fetch_reddit_posts")),
        (stocktwits_module, ("fetch_stocktwits_messages",)),
        (reddit_module, ("fetch_reddit_posts",)),
        (fred_module, ("get_api_key", "get_macro_data")),
        (polymarket_module, ("get_prediction_markets",)),
        (llm_clients_module, ("create_llm_client",)),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, bomb)
    monkeypatch.setattr(trading_graph_module.yf, "Ticker", bomb)
    original_env_get = os.environ.get

    def guarded_env_get(key: str, *args: object, **kwargs: object) -> object:
        # Pydantic consults only its own plugin-disable control while rebuilding
        # an existing StableId adapter. Application/credential reads still trip.
        if key == "PYDANTIC_DISABLE_PLUGINS":
            return original_env_get(key, *args, **kwargs)
        return bomb(key, *args, **kwargs)

    monkeypatch.setattr(os.environ, "get", guarded_env_get)
    monkeypatch.setattr(os, "makedirs", bomb)
    monkeypatch.setattr(builtins, "open", bomb)
    monkeypatch.setattr(Path, "open", bomb)
    monkeypatch.setattr(Path, "read_text", bomb)
    monkeypatch.setattr(Path, "write_text", bomb)
    monkeypatch.setattr(Path, "mkdir", bomb)
    monkeypatch.setattr(socket, "socket", bomb)
    monkeypatch.setattr(socket, "create_connection", bomb)
    monkeypatch.setattr(time, "time", bomb)
    monkeypatch.setattr(subprocess, "run", bomb)
    monkeypatch.setattr(subprocess, "Popen", bomb)
    monkeypatch.setattr(importlib, "import_module", bomb)


@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
def test_adapter_replays_exact_cached_state_and_preserves_five_tier_signal(rating: str) -> None:
    output = make_output(rating=rating)
    bundle, context, _, _, _, adapter = sealed_adapter(output=output)
    final_state, signal = run_adapter(adapter, bundle, context)
    assert final_state == output and final_state is not output
    assert signal == rating
    assert all(isinstance(final_state[field], str) for field in REPORT_FIELDS)
    assert not AUTHORITY_FIELDS.intersection(final_state)


def test_valid_replay_touches_no_host_or_provider_side_effect_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, context, _, _, _, adapter = sealed_adapter()
    install_side_effect_observers(monkeypatch)
    final_state, signal = run_adapter(adapter, bundle, context)
    assert final_state == make_output() and signal == "Hold"


@pytest.mark.parametrize(
    ("requested_id", "context_update", "error_type"),
    [
        ("bundle-other", {}, HistoricalReplayMismatchError),
        ("bundle-2024-06-30", {"bundle_hash": f"sha256:{'0' * 64}"}, HistoricalReplayMismatchError),
        (
            "bundle-2024-06-30",
            {"knowledge_cutoff": "2024-06-29T23:59:59Z"},
            HistoricalReplayMismatchError,
        ),
        (
            "bundle-2024-06-30",
            {"calendar_id": "XNYS.synthetic.other"},
            HistoricalReplayMismatchError,
        ),
        ("bundle-2024-06-30", {"mode": Mode.FORWARD_PAPER}, HistoricalReplayDeniedError),
    ],
)
def test_bundle_context_mismatch_fails_before_response_access(
    monkeypatch, requested_id, context_update, error_type
):
    bundle, context, _, responses, _, adapter = sealed_adapter()
    monkeypatch.setattr(responses, "get_bound", bomb)
    with pytest.raises(error_type):
        run_adapter(
            adapter, bundle, replace_context(context, **context_update), bundle_id=requested_id
        )


def test_absent_bundle_fails_without_response_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()
    monkeypatch.setattr(responses, "get_bound", bomb)
    with pytest.raises(EvidenceBundleNotFoundError):
        run_adapter(
            adapter,
            bundle,
            replace_context(context, bundle_id="bundle-other"),
            bundle_id="bundle-other",
        )


@pytest.mark.parametrize(
    "egress_field",
    [
        "data_capture_egress",
        "model_provider_egress",
        "research_tool_egress",
        "paper_broker_egress",
        "live_broker_egress",
    ],
)
def test_each_historical_egress_flag_fails_before_response_access(
    monkeypatch, egress_field: str
) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()
    policy = context.network_policy.model_dump(mode="python")
    policy[egress_field] = True
    monkeypatch.setattr(responses, "get_bound", bomb)
    with pytest.raises(HistoricalReplayDeniedError):
        run_adapter(
            adapter,
            bundle,
            bypassed_context(context, network_policy=NetworkPolicy.model_construct(**policy)),
        )


@pytest.mark.parametrize(
    "trade_date", ["2024-06-29", "2024-07-01", "2024-06-30T00:00:00Z", "2024-6-30", "not-a-date"]
)
def test_trade_date_must_equal_utc_cutoff_date_before_alias_or_response_access(
    monkeypatch, trade_date: str
) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()
    monkeypatch.setattr(responses, "get_bound", bomb)
    monkeypatch.setattr(adapter_module, "_resolve_instrument", bomb)
    with pytest.raises(HistoricalInstrumentError, match="trade date"):
        run_adapter(adapter, bundle, context, trade_date=trade_date)


def test_offset_context_normalizes_cutoff_to_utc_date_and_weekend_is_allowed() -> None:
    bundle, context, _, _, _, adapter = sealed_adapter()
    offset = bypassed_context(
        context,
        knowledge_cutoff="2024-06-30T18:59:59-05:00",
        decision_time="2024-07-01T15:00:00-05:00",
        earliest_execution_time="2024-07-02T08:30:00-05:00",
    )
    final_state, signal = run_adapter(adapter, bundle, offset)
    assert final_state["trade_date"] == "2024-06-30" and signal == "Hold"


def test_cutoff_date_may_precede_decision_date() -> None:
    bundle, context, _, _, _, adapter = sealed_adapter()
    assert context.knowledge_cutoff.date().isoformat() == "2024-06-30"
    assert context.decision_time.date().isoformat() == "2024-07-01"
    assert run_adapter(adapter, bundle, context)[1] == "Hold"


@pytest.mark.parametrize(
    ("ticker", "asset_type", "message"),
    [("MISSING", "stock", "missing"), ("NEW", "crypto", "asset")],
)
def test_missing_or_asset_mismatched_instrument_fails_before_response_access(
    monkeypatch, ticker, asset_type, message
):
    bundle, context, _, responses, _, adapter = sealed_adapter()
    monkeypatch.setattr(responses, "get_bound", bomb)
    with pytest.raises(HistoricalInstrumentError, match=message):
        run_adapter(adapter, bundle, context, ticker=ticker, asset_type=asset_type)


def test_missing_exact_response_has_no_retry_synthesis_or_default_fallback() -> None:
    bundle = build_fixture_bundle()
    context = make_context(bundle)
    evidence = EvidenceRepository()
    evidence.seal(bundle)
    adapter = ResearchAdapter(evidence, CachedGraphResponseRepository(), make_selection())
    with pytest.raises(CachedGraphResponseUnavailableError):
        run_adapter(adapter, bundle, context)


def test_selection_hash_mismatch_fails_closed() -> None:
    bundle, context, evidence, responses, selection, _ = sealed_adapter()
    wrong = selection.model_copy(update={"expected_response_hash": f"sha256:{'0' * 64}"})
    with pytest.raises(CachedGraphResponseMismatchError):
        run_adapter(ResearchAdapter(evidence, responses, wrong), bundle, context)


def test_exact_repository_and_selection_types_are_required_before_overridable_access() -> None:
    bundle, context, evidence, responses, selection, _ = sealed_adapter()

    class EvidenceSubclass(EvidenceRepository):
        def get(self, bundle_id: str) -> object:
            raise AssertionError(bundle_id)

    class ResponseSubclass(CachedGraphResponseRepository):
        def get_bound(self, *args: object, **kwargs: object) -> object:
            raise AssertionError((args, kwargs))

    class SelectionSubclass(CachedGraphSelection):
        def model_dump(self, *args: object, **kwargs: object) -> object:
            raise AssertionError((args, kwargs))

    hostile = SelectionSubclass.model_construct(**selection.model_dump(mode="python"))
    for candidate in (
        ResearchAdapter(EvidenceSubclass(), responses, selection),
        ResearchAdapter(evidence, ResponseSubclass(), selection),
        ResearchAdapter(evidence, responses, hostile),
    ):
        with pytest.raises((HistoricalReplayDeniedError, CachedGraphResponseMismatchError)):
            run_adapter(candidate, bundle, context)


@pytest.mark.parametrize("authority_field", sorted(AUTHORITY_FIELDS))
def test_pure_validator_rejects_authority_fields_recursively(authority_field: str) -> None:
    output = make_output()
    output["messages"].append(
        {"role": "assistant", "content": "Research", "metadata": {authority_field: []}}
    )
    with pytest.raises(HistoricalRuntimeOutputError, match="authority"):
        validate_historical_response(
            output,
            company_name="NEW",
            trade_date="2024-06-30",
            asset_type="stock",
            instrument_context=str(make_output()["instrument_context"]),
        )


@pytest.mark.parametrize(
    "output", ["not-an-object", {}, {"final_trade_decision": 3}, {"unexpected": "field"}]
)
def test_pure_validator_rejects_malformed_output(output: object) -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate_historical_response(
            output,
            company_name="NEW",
            trade_date="2024-06-30",
            asset_type="stock",
            instrument_context=str(make_output()["instrument_context"]),
        )


def absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_dependency_direction_scope_and_callable_surface_are_static_and_narrow() -> None:
    adapter_path = REPOSITORY_ROOT / "mytradingalpha/research/tradingagents_adapter.py"
    cached_path = REPOSITORY_ROOT / "mytradingalpha/research/cached_response.py"
    historical_path = REPOSITORY_ROOT / "tradingagents/graph/historical.py"
    assert cached_path.is_file()
    for path in (REPOSITORY_ROOT / "tradingagents").rglob("*.py"):
        assert not any(
            module == "mytradingalpha" or module.startswith("mytradingalpha.")
            for module in absolute_imports(path)
        ), path
    reverse = sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "mytradingalpha").rglob("*.py")
        if any(
            module == "tradingagents" or module.startswith("tradingagents.")
            for module in absolute_imports(path)
        )
    )
    assert reverse == [
        "mytradingalpha/research/cached_response.py",
        "mytradingalpha/research/tradingagents_adapter.py",
    ]
    forbidden_imports = {"pickle", "cloudpickle", "dill", "importlib", "subprocess", "os"}
    for path in (adapter_path, cached_path, historical_path):
        assert not forbidden_imports.intersection(absolute_imports(path))
    forbidden_symbols = {
        "HistoricalRunner",
        "OfflineGraphRuntime",
        "_require_runtime",
        "run_historical",
        "HistoricalRuntimeUnavailableError",
        "HistoricalRuntimeTypeError",
    }
    assert not forbidden_symbols.intersection(vars(historical_module))
    assert not forbidden_symbols.intersection(
        vars(__import__("tradingagents.graph", fromlist=["*"]))
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (adapter_path, cached_path, historical_path)
    )
    for token in (
        "eval(",
        "exec(",
        "import_module(",
        "pickle",
        "cloudpickle",
        "dill",
        "module_path",
        "class_path",
        "callback",
        "subprocess",
    ):
        assert token not in source
    research_root = REPOSITORY_ROOT / "mytradingalpha/research"
    for later in ("overlay.py", "overlay_validator.py"):
        assert not (research_root / later).exists()


def test_public_signatures_and_default_graph_contract_remain_compatible() -> None:
    from tradingagents.graph import TradingAgentsGraph as exported_graph

    assert exported_graph is TradingAgentsGraph
    assert tuple(inspect.signature(TradingAgentsGraph.__init__).parameters) == (
        "self",
        "selected_analysts",
        "debug",
        "config",
        "callbacks",
    )
    assert tuple(inspect.signature(TradingAgentsGraph.propagate).parameters) == (
        "self",
        "company_name",
        "trade_date",
        "asset_type",
    )
    assert tuple(inspect.signature(ResearchAdapter.__init__).parameters) == (
        "self",
        "evidence_repository",
        "response_repository",
        "selection",
    )
    assert tuple(inspect.signature(ResearchAdapter.run).parameters) == (
        "self",
        "bundle_id",
        "context",
        "ticker",
        "trade_date",
        "asset_type",
    )
    assert tuple(inspect.signature(validate_historical_response).parameters) == (
        "output",
        "company_name",
        "trade_date",
        "asset_type",
        "instrument_context",
    )
    assert datetime.now(timezone.utc).tzinfo is timezone.utc
