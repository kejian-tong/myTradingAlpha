"""SIG-01 contract for sealed, zero-egress Research Graph execution."""

from __future__ import annotations

import ast
import builtins
import inspect
import os
import socket
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import mytradingalpha.research.tradingagents_adapter as adapter_module
import pytest
import tradingagents.graph.historical as historical_module
from mytradingalpha.research.tradingagents_adapter import (
    HistoricalInstrumentError,
    ResearchAdapter,
)
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    HistoricalRuntimeTypeError,
    HistoricalRuntimeUnavailableError,
    OfflineGraphRuntime,
    run_historical,
)

import tradingagents.agents.analysts.sentiment_analyst as sentiment_module
import tradingagents.agents.utils.agent_utils as agent_utils_module
import tradingagents.dataflows.fred as fred_module
import tradingagents.dataflows.polymarket as polymarket_module
import tradingagents.dataflows.reddit as reddit_module
import tradingagents.dataflows.stocktwits as stocktwits_module
import tradingagents.graph.checkpointer as checkpointer_module
import tradingagents.graph.trading_graph as trading_graph_module
import tradingagents.llm_clients as llm_clients_module
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.data.replay_guard import (
    HistoricalReplayDeniedError,
    HistoricalReplayMismatchError,
)
from mytradingalpha.data.repository import EvidenceBundleNotFoundError, EvidenceRepository
from tests.productionization.data.test_bundle_replay import (
    _build as build_fixture_bundle,
    _candidate_fields as fixture_candidate_fields,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.graph import TradingAgentsGraph
from tradingagents.graph.reflection import Reflector

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPORT_FIELDS = {
    "market_report",
    "fundamentals_report",
    "sentiment_report",
    "news_report",
}
INVEST_DEBATE_FIELDS = {
    "bull_history",
    "bear_history",
    "history",
    "current_response",
    "judge_decision",
    "count",
}
RISK_DEBATE_FIELDS = {
    "aggressive_history",
    "conservative_history",
    "neutral_history",
    "history",
    "latest_speaker",
    "current_aggressive_response",
    "current_conservative_response",
    "current_neutral_response",
    "judge_decision",
    "count",
}
INITIAL_STATE_FIELDS = {
    "messages",
    "company_of_interest",
    "asset_type",
    "instrument_context",
    "trade_date",
    "past_context",
    "investment_debate_state",
    "risk_debate_state",
    *REPORT_FIELDS,
}
AUTHORITY_FIELDS = {
    "target_weight",
    "target_weights",
    "portfolio_allocation",
    "order",
    "order_intent",
    "quantity",
    "broker",
    "broker_id",
    "credentials",
    "risk_authorization",
}


def _context(bundle: object, **overrides: object) -> RunContext:
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


def _replace_context(context: RunContext, **updates: object) -> RunContext:
    return RunContext.model_validate(
        {**context.model_dump(mode="python"), **updates}
    )


def _bypassed_context(context: RunContext, **updates: object) -> RunContext:
    payload = {**context.model_dump(mode="python"), **updates}
    return RunContext.model_construct(**payload)


def _final_state(initial_state: dict[str, object], rating: str = "Hold") -> dict[str, object]:
    final_state = deepcopy(initial_state)
    final_state.update(
        {
            "market_report": "Market evidence summary.",
            "fundamentals_report": "Fundamentals evidence summary.",
            "sentiment_report": "Sentiment evidence summary.",
            "news_report": "News evidence summary.",
            "investment_plan": "Prose investment plan.",
            "trader_investment_plan": "Prose trader plan.",
            "final_trade_decision": f"**Rating**: {rating}\n\nProse research decision.",
        }
    )
    return final_state


class RecordingRunner:
    """Deterministic test runner; it is not evidence of a deployable model runtime."""

    def __init__(self, *, rating: str = "Hold", output: object | None = None) -> None:
        self.rating = rating
        self.output = output
        self.calls: list[tuple[object, RunContext, dict[str, object]]] = []
        self.returned_state: dict[str, object] | None = None

    def __call__(
        self,
        bundle: object,
        context: RunContext,
        initial_state: dict[str, object],
    ) -> object:
        self.calls.append((bundle, context, deepcopy(initial_state)))
        if self.output is not None:
            return self.output
        self.returned_state = _final_state(initial_state, self.rating)
        return self.returned_state


def _sealed_adapter(
    *,
    bundle: object | None = None,
    runner: RecordingRunner | None = None,
) -> tuple[object, RunContext, EvidenceRepository, RecordingRunner, ResearchAdapter]:
    sealed_bundle = bundle or build_fixture_bundle()
    context = _context(sealed_bundle)
    repository = EvidenceRepository()
    repository.seal(sealed_bundle)
    recording_runner = runner or RecordingRunner()
    runtime = OfflineGraphRuntime(recording_runner)
    adapter = ResearchAdapter(repository, runtime)
    return sealed_bundle, context, repository, recording_runner, adapter


def _run(
    adapter: ResearchAdapter,
    bundle: object,
    context: RunContext,
    **overrides: object,
) -> tuple[dict[str, object], str]:
    fields: dict[str, object] = {
        "bundle_id": bundle.bundle_id,
        "context": context,
        "ticker": "NEW",
        "trade_date": "2024-06-30",
        "asset_type": "stock",
    }
    fields.update(overrides)
    return adapter.run(**fields)  # type: ignore[arg-type]


def _bomb(*args: object, **kwargs: object) -> object:
    del args, kwargs
    raise AssertionError("historical adapter crossed a forbidden side-effect boundary")


def _patch_runtime_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install tripwires only after imports and fixture construction are complete."""

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
            monkeypatch.setattr(owner, name, _bomb)

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
        (
            sentiment_module,
            ("get_news", "fetch_stocktwits_messages", "fetch_reddit_posts"),
        ),
        (stocktwits_module, ("fetch_stocktwits_messages",)),
        (reddit_module, ("fetch_reddit_posts",)),
        (fred_module, ("get_api_key", "get_macro_data")),
        (polymarket_module, ("get_prediction_markets",)),
        (llm_clients_module, ("create_llm_client",)),
    ):
        for name in names:
            monkeypatch.setattr(owner, name, _bomb)

    monkeypatch.setattr(trading_graph_module.yf, "Ticker", _bomb)
    monkeypatch.setattr(os, "makedirs", _bomb)
    monkeypatch.setattr(builtins, "open", _bomb)
    monkeypatch.setattr(Path, "open", _bomb)
    monkeypatch.setattr(Path, "read_text", _bomb)
    monkeypatch.setattr(Path, "write_text", _bomb)
    monkeypatch.setattr(Path, "mkdir", _bomb)
    monkeypatch.setattr(socket, "socket", _bomb)
    monkeypatch.setattr(socket, "create_connection", _bomb)
    monkeypatch.setattr(time, "time", _bomb)

    class ForbiddenDateTime:
        @classmethod
        def now(cls, *args: object, **kwargs: object) -> object:
            return _bomb(*args, **kwargs)

        @classmethod
        def utcnow(cls, *args: object, **kwargs: object) -> object:
            return _bomb(*args, **kwargs)

    for module in (
        trading_graph_module,
        sentiment_module,
        adapter_module,
        historical_module,
    ):
        if hasattr(module, "datetime"):
            monkeypatch.setattr(module, "datetime", ForbiddenDateTime)


def test_adapter_invokes_offline_runtime_once_with_exact_sealed_inputs() -> None:
    bundle, context, repository, runner, adapter = _sealed_adapter()

    final_state, signal = _run(adapter, bundle, context)

    assert len(runner.calls) == 1
    replayed_bundle, received_context, initial_state = runner.calls[0]
    assert type(replayed_bundle) is type(bundle)
    assert replayed_bundle == repository.get(bundle.bundle_id)
    assert received_context == context
    assert final_state == runner.returned_state
    assert signal == "Hold"
    assert set(initial_state) == INITIAL_STATE_FIELDS
    assert initial_state["messages"] == [("human", "NEW")]
    assert initial_state["company_of_interest"] == "NEW"
    assert initial_state["asset_type"] == "stock"
    assert initial_state["trade_date"] == "2024-06-30"
    assert initial_state["past_context"] == ""
    assert initial_state["instrument_context"] == (
        "Symbol: NEW; instrument_id: inst-acme; asset_class: equity; "
        "exchange: XNYS; currency: USD"
    )
    assert initial_state.keys() >= REPORT_FIELDS
    assert all(initial_state[field] == "" for field in REPORT_FIELDS)
    assert set(initial_state["investment_debate_state"]) == INVEST_DEBATE_FIELDS
    assert set(initial_state["risk_debate_state"]) == RISK_DEBATE_FIELDS


@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
def test_adapter_preserves_current_prose_state_and_five_tier_signal(rating: str) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter(
        runner=RecordingRunner(rating=rating)
    )

    final_state, signal = _run(adapter, bundle, context)

    assert signal == rating
    assert final_state == runner.returned_state
    assert isinstance(final_state, dict)
    assert isinstance(final_state["final_trade_decision"], str)
    assert all(isinstance(final_state[field], str) for field in REPORT_FIELDS)
    assert all(field not in final_state for field in AUTHORITY_FIELDS)


@pytest.mark.parametrize(
    ("requested_id", "context_update", "error_type"),
    [
        ("bundle-other", {}, HistoricalReplayMismatchError),
        (
            "bundle-2024-06-30",
            {"bundle_hash": f"sha256:{'0' * 64}"},
            HistoricalReplayMismatchError,
        ),
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
        (
            "bundle-2024-06-30",
            {"mode": Mode.FORWARD_PAPER},
            HistoricalReplayDeniedError,
        ),
    ],
)
def test_bundle_context_mismatches_fail_before_runtime(
    requested_id: str,
    context_update: dict[str, object],
    error_type: type[Exception],
) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()
    changed_context = _replace_context(context, **context_update)

    with pytest.raises(error_type):
        _run(
            adapter,
            bundle,
            changed_context,
            bundle_id=requested_id,
        )

    assert runner.calls == []


def test_requested_context_id_mismatch_precedes_repository_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()
    monkeypatch.setattr(EvidenceRepository, "get", _bomb)

    with pytest.raises(HistoricalReplayMismatchError):
        _run(adapter, bundle, context, bundle_id="bundle-other")

    assert runner.calls == []


def test_context_id_for_absent_sealed_bundle_fails_before_runtime() -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()
    absent_context = _replace_context(context, bundle_id="bundle-other")

    with pytest.raises(EvidenceBundleNotFoundError):
        _run(adapter, bundle, absent_context, bundle_id="bundle-other")

    assert runner.calls == []


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
def test_each_historical_egress_flag_fails_before_runtime(egress_field: str) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()
    policy_payload = context.network_policy.model_dump(mode="python")
    policy_payload[egress_field] = True
    bypassed = _bypassed_context(
        context,
        network_policy=NetworkPolicy.model_construct(**policy_payload),
    )

    with pytest.raises(HistoricalReplayDeniedError):
        _run(adapter, bundle, bypassed)

    assert runner.calls == []


def test_exact_repository_type_is_required_before_runtime() -> None:
    bundle = build_fixture_bundle()
    context = _context(bundle)

    class RepositorySubclass(EvidenceRepository):
        pass

    repository = RepositorySubclass()
    repository.seal(bundle)
    runner = RecordingRunner()
    adapter = ResearchAdapter(repository, OfflineGraphRuntime(runner))

    with pytest.raises(HistoricalReplayDeniedError):
        _run(adapter, bundle, context)

    assert runner.calls == []


def test_historical_path_has_no_pending_provider_persistence_clock_or_io_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()
    _patch_runtime_side_effects(monkeypatch)

    final_state, signal = _run(adapter, bundle, context)

    assert len(runner.calls) == 1
    assert final_state == runner.returned_state
    assert signal == "Hold"


def test_missing_runtime_fails_closed_without_default_graph_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = build_fixture_bundle()
    context = _context(bundle)
    repository = EvidenceRepository()
    repository.seal(bundle)
    monkeypatch.setattr(TradingAgentsGraph, "propagate", _bomb)
    monkeypatch.setattr(trading_graph_module, "create_llm_client", _bomb)

    with pytest.raises(HistoricalRuntimeUnavailableError):
        _run(ResearchAdapter(repository, None), bundle, context)


def test_wrong_runtime_object_is_rejected_before_attribute_access() -> None:
    bundle = build_fixture_bundle()
    context = _context(bundle)
    repository = EvidenceRepository()
    repository.seal(bundle)

    class HostileObject:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(f"hostile runtime attribute accessed: {name}")

    with pytest.raises(HistoricalRuntimeTypeError):
        _run(ResearchAdapter(repository, HostileObject()), bundle, context)  # type: ignore[arg-type]


def test_runtime_subclass_is_rejected_before_overridable_method_access() -> None:
    bundle = build_fixture_bundle()
    context = _context(bundle)
    repository = EvidenceRepository()
    repository.seal(bundle)

    class HostileRuntime(OfflineGraphRuntime):
        def __getattribute__(self, name: str) -> object:
            if name not in {"__class__", "__dict__"}:
                raise AssertionError(f"hostile runtime attribute accessed: {name}")
            return super().__getattribute__(name)

    hostile = object.__new__(HostileRuntime)
    with pytest.raises(HistoricalRuntimeTypeError):
        _run(ResearchAdapter(repository, hostile), bundle, context)


@pytest.mark.parametrize(
    "output",
    [
        "not-a-state",
        {},
        {"final_trade_decision": 3},
        {"final_trade_decision": "**Rating**: Hold", "market_report": 4},
    ],
)
def test_malformed_runtime_output_fails_closed(output: object) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter(
        runner=RecordingRunner(output=output)
    )

    with pytest.raises(HistoricalRuntimeOutputError):
        _run(adapter, bundle, context)

    assert len(runner.calls) == 1


@pytest.mark.parametrize("authority_field", sorted(AUTHORITY_FIELDS))
def test_runtime_output_cannot_gain_portfolio_order_broker_or_risk_authority(
    authority_field: str,
) -> None:
    bundle, context, _, _, _ = _sealed_adapter()
    initial = historical_module.create_historical_initial_state(
        company_name="NEW",
        trade_date="2024-06-30",
        asset_type="stock",
        instrument_context=(
            "Symbol: NEW; instrument_id: inst-acme; asset_class: equity; "
            "exchange: XNYS; currency: USD"
        ),
    )
    hostile_state = _final_state(initial)
    hostile_state[authority_field] = 1
    runner = RecordingRunner(output=hostile_state)
    runtime = OfflineGraphRuntime(runner)

    with pytest.raises(HistoricalRuntimeOutputError):
        run_historical(
            runtime,
            bundle,
            context,
            company_name="NEW",
            trade_date="2024-06-30",
            asset_type="stock",
            instrument_context=str(initial["instrument_context"]),
        )


@pytest.mark.parametrize(
    ("ticker", "trade_date", "asset_type", "message"),
    [
        ("MISSING", "2024-06-30", "stock", "missing"),
        ("NEW", "2024-07-01", "stock", "date"),
        ("NEW", "2024-06-30", "crypto", "asset"),
    ],
)
def test_missing_date_invalid_or_asset_mismatched_instrument_fails_closed(
    ticker: str,
    trade_date: str,
    asset_type: str,
    message: str,
) -> None:
    bundle, context, _, runner, adapter = _sealed_adapter()

    with pytest.raises(HistoricalInstrumentError, match=message):
        _run(
            adapter,
            bundle,
            context,
            ticker=ticker,
            trade_date=trade_date,
            asset_type=asset_type,
        )

    assert runner.calls == []


def test_ambiguous_sealed_instrument_identity_fails_closed() -> None:
    baseline = build_fixture_bundle()
    aapl = next(item for item in baseline.instruments if item.instrument_id == "AAPL")
    duplicate = aapl.model_copy(
        update={
            "instrument_id": "AAPL-DUP",
            "manifest": aapl.manifest.model_copy(
                update={
                    "manifest_id": "instrument-aapl-dup-r0",
                    "source_locator": "fixture://universe/instruments/AAPL-DUP/r0",
                }
            ),
        }
    )
    bundle = build_fixture_bundle(
        bundle_id="bundle-ambiguous-aapl",
        instrument_candidates=(*fixture_candidate_fields()["instrument_candidates"], duplicate),
    )
    context = _context(bundle)
    repository = EvidenceRepository()
    repository.seal(bundle)
    runner = RecordingRunner()
    adapter = ResearchAdapter(repository, OfflineGraphRuntime(runner))

    with pytest.raises(HistoricalInstrumentError, match="ambiguous"):
        _run(adapter, bundle, context, ticker="AAPL")

    assert runner.calls == []


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_dependency_direction_and_sig_01_scope_are_static_and_narrow() -> None:
    adapter_path = REPOSITORY_ROOT / "mytradingalpha/research/tradingagents_adapter.py"
    historical_path = REPOSITORY_ROOT / "tradingagents/graph/historical.py"
    assert adapter_path.is_file()
    assert historical_path.is_file()

    for path in (REPOSITORY_ROOT / "tradingagents").rglob("*.py"):
        assert all(
            module != "mytradingalpha" and not module.startswith("mytradingalpha.")
            for module in _absolute_imports(path)
        ), path

    production_reverse_importers = []
    for path in (REPOSITORY_ROOT / "mytradingalpha").rglob("*.py"):
        imports = _absolute_imports(path)
        if any(module == "tradingagents" or module.startswith("tradingagents.") for module in imports):
            production_reverse_importers.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert production_reverse_importers == [
        "mytradingalpha/research/tradingagents_adapter.py"
    ]

    adapter_imports = _absolute_imports(adapter_path)
    forbidden_contexts = (
        "mytradingalpha.portfolio",
        "mytradingalpha.risk",
        "mytradingalpha.execution",
        "mytradingalpha.backtest",
    )
    assert not any(
        module == root or module.startswith(f"{root}.")
        for module in adapter_imports
        for root in forbidden_contexts
    )

    research_root = REPOSITORY_ROOT / "mytradingalpha/research"
    assert not (research_root / "evidence_tools.py").exists()
    assert not (research_root / "notes.py").exists()
    for name in ("EvidenceToolset", "ResearchNote", "ResearchNoteBuilder"):
        assert not hasattr(adapter_module, name)


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
        "repository",
        "runtime",
    )
    assert tuple(inspect.signature(ResearchAdapter.run).parameters) == (
        "self",
        "bundle_id",
        "context",
        "ticker",
        "trade_date",
        "asset_type",
    )
    assert tuple(inspect.signature(run_historical).parameters) == (
        "runtime",
        "bundle",
        "context",
        "company_name",
        "trade_date",
        "asset_type",
        "instrument_context",
    )
    assert datetime.now(timezone.utc).tzinfo is timezone.utc
