"""Bounded SIG-01 H1/H2/H3/H5 repairs; no runtime or date-horizon proof."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from langchain_core.messages import (
    AIMessage,
    ChatMessage,
    FunctionMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.data.replay_guard import HistoricalDataGuard, HistoricalReplayDeniedError
from mytradingalpha.research.tradingagents_adapter import HistoricalInstrumentError, ResearchAdapter
from tests.productionization.research.test_adapter import (
    _final_state,
    _run,
    _sealed_adapter,
)
from tradingagents.graph.historical import HistoricalRuntimeOutputError, OfflineGraphRuntime


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("company_of_interest", "UNSEALED"),
        ("asset_type", "crypto"),
        ("instrument_context", "unsealed identity"),
        ("trade_date", "2099-01-01"),
        ("past_context", "current unsealed memory"),
    ],
)
def test_in_place_bound_field_mutation_is_denied(field, replacement):
    bundle, context, repository, _, _ = _sealed_adapter()

    def runner(_bundle, _context, initial):
        initial.update(_final_state(initial))
        initial[field] = replacement
        return initial

    adapter = ResearchAdapter(repository, OfflineGraphRuntime(runner))
    with pytest.raises(HistoricalRuntimeOutputError, match=field):
        _run(adapter, bundle, context)


def test_in_place_prose_and_debate_updates_remain_supported():
    bundle, context, repository, _, _ = _sealed_adapter()

    def runner(_bundle, _context, initial):
        initial.update(_final_state(initial))
        initial["market_report"] = "Updated evidence summary"
        initial["investment_debate_state"].update(history="Evidence debate", count=1)
        return initial

    final, signal = _run(ResearchAdapter(repository, OfflineGraphRuntime(runner)), bundle, context)
    assert final["market_report"] == "Updated evidence summary"
    assert final["investment_debate_state"]["history"] == "Evidence debate"
    assert final["investment_debate_state"]["count"] == 1
    assert signal == "Hold"


@pytest.mark.parametrize(
    ("ticker", "trade_date"),
    [("OLD", "2024-06-30"), ("OLD", "2024-03-15"), ("AAPL", "2024-06-30")],
)
def test_expired_or_missing_sealed_alias_denies_before_runner(ticker, trade_date):
    bundle, context, _, runner, adapter = _sealed_adapter()
    with pytest.raises(HistoricalInstrumentError, match="missing"):
        _run(adapter, bundle, context, ticker=ticker, trade_date=trade_date)
    assert runner.calls == []


@pytest.mark.parametrize(("ticker", "trade_date"), [("OLD", "2024-03-14"), ("NEW", "2024-03-15")])
def test_alias_interval_identity_only_includes_start_and_precedes_expiry(ticker, trade_date):
    # These cases test alias identity only, not acceptance of any research date horizon.
    bundle, context, _, runner, adapter = _sealed_adapter()
    final, _ = _run(adapter, bundle, context, ticker=ticker, trade_date=trade_date)
    assert len(runner.calls) == 1
    assert final["company_of_interest"] == ticker
    assert "instrument_id: inst-acme;" in final["instrument_context"]


def test_adapter_passes_the_single_guard_bound_canonical_context(monkeypatch):
    bundle, context, _, runner, adapter = _sealed_adapter()
    payload = context.model_dump(mode="json")
    original_payload = deepcopy(payload)
    raw = RunContext.model_construct(**payload)
    calls = []
    replay_bound = HistoricalDataGuard.replay_bound

    def recording_bound(repository, bundle_id, supplied):
        result = replay_bound(repository, bundle_id, supplied)
        calls.append((supplied, result))
        return result

    monkeypatch.setattr(HistoricalDataGuard, "replay_bound", staticmethod(recording_bound))
    _run(adapter, bundle, raw)
    assert len(calls) == len(runner.calls) == 1
    assert calls[0][0] is raw
    received = runner.calls[0][1]
    assert received is calls[0][1][1]
    assert received is not raw
    assert received == context
    assert received.mode is Mode.HISTORICAL
    assert type(received.network_policy) is NetworkPolicy
    for field in ("decision_time", "knowledge_cutoff", "earliest_execution_time"):
        assert type(getattr(received, field)) is datetime
        assert getattr(received, field).tzinfo is timezone.utc
        assert getattr(raw, field) == original_payload[field]
    assert raw.mode == original_payload["mode"] and type(raw.mode) is str
    assert raw.network_policy == original_payload["network_policy"]
    assert type(raw.network_policy) is dict
    assert payload == original_payload


@pytest.mark.parametrize(
    "update",
    [
        {"mode": "unknown"},
        {"mode": "forward_paper"},
        {"network_policy": {"research_tool_egress": True}},
        {"network_policy": {"unexpected": False}},
        {"decision_time": "not-a-time"},
        {"knowledge_cutoff": "2024-06-30T23:59:59"},
        {"bundle_hash": "not-a-canonical-hash"},
    ],
)
def test_invalid_raw_context_is_denied_before_runner(update):
    bundle, context, _, runner, adapter = _sealed_adapter()
    raw = RunContext.model_construct(**{**context.model_dump(mode="json"), **update})
    with pytest.raises(HistoricalReplayDeniedError):
        _run(adapter, bundle, raw)
    assert runner.calls == []


def test_context_subclass_is_denied_before_serializer_and_runner():
    bundle, context, _, runner, adapter = _sealed_adapter()

    class HostileContext(RunContext):
        def model_dump(self, *args, **kwargs):
            raise AssertionError("custom context serializer invoked")

    raw = HostileContext.model_construct(**context.model_dump(mode="python"))
    with pytest.raises(HistoricalReplayDeniedError):
        _run(adapter, bundle, raw)
    assert runner.calls == []


def _run_with_message(message):
    bundle, context, repository, _, _ = _sealed_adapter()

    def runner(_bundle, _context, initial):
        final = _final_state(initial)
        final["messages"].append(message)
        return final

    return _run(ResearchAdapter(repository, OfflineGraphRuntime(runner)), bundle, context)


@pytest.mark.parametrize(
    "message",
    [
        AIMessage(content="Research", additional_kwargs={"nested": [{"order_intents": []}]}),
        HumanMessage(content="Research", response_metadata={"nested": {"target_weights": {}}}),
        AIMessage(content="Research", tool_calls=[{
            "name": "research", "id": "call-1", "args": {"nested": [{"quantity": 999}]},
        }]),
        AIMessage(content=[{"type": "text", "text": "Research", "broker_credentials": {}}]),
        ToolMessage(content="Research", tool_call_id="call-1", artifact={"risk_authorization": True}),
        AIMessage(content="Research", custom_metadata={"credentials": "forbidden"}),
    ],
)
def test_standard_message_nested_authority_is_denied(message):
    with pytest.raises(HistoricalRuntimeOutputError, match="authority"):
        _run_with_message(message)


@pytest.mark.parametrize(
    "message",
    [
        AIMessage(content="Research", additional_kwargs={"citations": ["evidence-1"]},
                  response_metadata={"model": "cached"}, tool_calls=[{
                      "name": "research", "id": "call-1", "args": {"evidence_id": "evidence-1"},
                  }]),
        HumanMessage(content="Research"),
        SystemMessage(content="Research"),
        ToolMessage(content="Research", tool_call_id="call-1", artifact={"citation": "evidence-1"}),
        FunctionMessage(content="Research", name="research"),
        ChatMessage(content="Research", role="analyst"),
        RemoveMessage(id="prior-message"),
        ("human", "Research"),
        ["human", "Research"],
        {"role": "assistant", "content": [{"type": "text", "text": "Research"}]},
    ],
)
def test_standard_and_plain_messages_preserve_output_shape(message):
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert signal == "Hold"


@pytest.mark.parametrize("placement", ["message", "metadata", "subclass"])
def test_opaque_messages_fail_before_custom_serializer(placement):
    calls = []

    class OpaqueMessage:
        def model_dump(self, *args, **kwargs):
            calls.append("serializer")
            raise AssertionError("custom serializer invoked")

    class CustomAIMessage(AIMessage):
        def model_dump(self, *args, **kwargs):
            calls.append("serializer")
            raise AssertionError("custom serializer invoked")

    if placement == "message":
        message = OpaqueMessage()
    elif placement == "metadata":
        message = AIMessage(content="Research", additional_kwargs={"opaque": OpaqueMessage()})
    else:
        message = CustomAIMessage(content="Research")
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)
    assert calls == []
