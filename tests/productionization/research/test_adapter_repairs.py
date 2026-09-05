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


@pytest.mark.parametrize("location", ["function_call", "invalid_tool_calls", "raw_tool_calls"])
@pytest.mark.parametrize("arguments", ['{"nested": [{"order_intents": []}]}', 'not-json', '[{"citation": "e1"}]'])
def test_encoded_call_arguments_deny_authority_malformed_and_non_object(location, arguments):
    message = _encoded_call_message(location, arguments)
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("location", ["function_call", "invalid_tool_calls", "raw_tool_calls"])
def test_known_encoded_call_arguments_preserve_benign_messages(location):
    message = _encoded_call_message(location, '{"evidence_id": "e1", "nested": {"period": 2}}')
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert signal == "Hold"


def _encoded_call_message(location, arguments):
    if location == "function_call":
        return AIMessage(content="Research", additional_kwargs={
            "function_call": {"name": "research", "arguments": arguments},
        })
    if location == "invalid_tool_calls":
        return AIMessage(content="Research", invalid_tool_calls=[{
            "name": "research", "id": "call-1", "args": arguments, "error": "invalid call",
        }])
    # A supplied normalized call prevents automatic parsing of the raw call. Both
    # representations must be inspected even if they disagree.
    return AIMessage(content="Research", additional_kwargs={"tool_calls": [{
        "id": "raw-call", "type": "function", "function": {
            "name": "research", "arguments": arguments,
        },
    }]}, tool_calls=[{"name": "research", "id": "call-1", "args": {"evidence_id": "e1"}}])


def test_json_looking_research_prose_remains_prose():
    message = AIMessage(content='Research discussion of {"quantity": 5}',
                        response_metadata={"description": '{"order_intents": []}'})
    final, _ = _run_with_message(message)
    assert final["messages"][-1] is message


@pytest.mark.parametrize(
    "additional_kwargs",
    [
        {"tool_calls": ({"function": {"arguments": '{"order_intents": []}'}},)},
        {"tool_calls": {"function": {"arguments": '{"order_intents": []}'}}},
        {"tool_calls": ["malformed"]},
        {"tool_calls": [{}]},
        {"tool_calls": [{"function": "malformed"}]},
        {"tool_calls": [{"function": {"name": "research"}}]},
        {"function_call": "malformed"},
        {"function_call": {"name": "research"}},
    ],
)
def test_present_known_call_shapes_fail_closed_instead_of_skipping(additional_kwargs):
    message = AIMessage(content="Research", additional_kwargs=additional_kwargs,
                        tool_calls=[{"name": "research", "id": "call-1", "args": {}}])
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def _wire_message(representation, fields):
    fields = {"content": "Research", **deepcopy(fields)}
    if representation == "constructor":
        return {
            "lc": 1,
            "type": "constructor",
            "id": ["langchain", "schema", "messages", "AIMessage"],
            "kwargs": fields,
        }
    return {representation: "assistant" if representation == "role" else "ai", **fields}


def _wire_call_fields(location, arguments):
    if location == "function_call":
        return {"function_call": {"name": "research", "arguments": arguments}}
    if location == "invalid_tool_calls":
        return {"invalid_tool_calls": [{
            "type": "invalid_tool_call", "id": "call-1", "name": "research",
            "args": arguments, "error": "previous parsing error",
        }]}
    return {"tool_calls": [{
        "id": "call-1", "type": "function",
        "function": {"name": "research", "arguments": arguments},
    }]}


@pytest.mark.parametrize("representation", ["role", "type", "constructor"])
@pytest.mark.parametrize("location", ["tool_calls", "function_call", "invalid_tool_calls"])
@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "additional-kwargs"])
@pytest.mark.parametrize("arguments", [
    '{"nested": [{"order_intents": [{"quantity": 999}]}]}',
    "not-json", '[{"evidence_id": "e1"}]', "null",
])
def test_message_boundary_wire_arguments_deny_before_normalization(
    representation, location, nested, arguments,
):
    fields = _wire_call_fields(location, arguments)
    if nested:
        fields = {"additional_kwargs": fields}
    message = _wire_message(representation, fields)
    original = deepcopy(message)
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)
    assert message == original


@pytest.mark.parametrize("representation", ["role", "type", "constructor"])
@pytest.mark.parametrize("location", ["tool_calls", "function_call", "invalid_tool_calls"])
@pytest.mark.parametrize("nested", [False, True], ids=["top-level", "additional-kwargs"])
def test_message_boundary_wire_benign_calls_preserve_original(representation, location, nested):
    fields = _wire_call_fields(location, '{"evidence_id": "e1", "nested": {"period": 2}}')
    if nested:
        fields = {"additional_kwargs": fields}
    message = _wire_message(representation, fields)
    original = deepcopy(message)
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original
    assert signal == "Hold"


@pytest.mark.parametrize("representation", ["role", "type", "constructor", "concrete"])
@pytest.mark.parametrize("calls", [
    None, {}, (), ["call"], [{}],
    [{"name": "research", "id": "call-1", "args": '{"evidence_id": "e1"}'}],
    [{"name": "research", "id": "call-1", "args": '{"quantity": 999}'}],
    [{"name": "research", "id": "call-1", "args": []}],
])
def test_message_boundary_normalized_call_shapes_deny(representation, calls):
    if representation == "concrete":
        message = AIMessage(content="Research")
        message.tool_calls = deepcopy(calls)
    else:
        message = _wire_message(representation, {"tool_calls": calls})
    original = deepcopy(message)
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)
    assert message == original


@pytest.mark.parametrize("representation", ["role", "type", "constructor", "concrete"])
def test_message_boundary_normalized_benign_calls_preserve_original(representation):
    calls = [{"type": "tool_call", "name": "research", "id": "call-1",
              "args": {"evidence_id": "e1"}}]
    if representation == "concrete":
        message = AIMessage(content="Research", tool_calls=calls)
    else:
        message = _wire_message(representation, {"tool_calls": calls})
    original = deepcopy(message)
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original
    assert signal == "Hold"


@pytest.mark.parametrize("placement", [
    "top-function", "nested-function", "raw-behind-normalized", "envelope-outer",
    "extra-function", "function-and-args", "nested-additional",
])
def test_message_boundary_shadowed_call_fields_are_checked(placement):
    bad = _wire_call_fields("function_call", '{"order_intents": []}')
    good = _wire_call_fields("function_call", '{"evidence_id": "e1"}')
    if placement == "top-function":
        message = _wire_message("role", {**bad, "additional_kwargs": good})
    elif placement == "nested-function":
        message = _wire_message("role", {**good, "additional_kwargs": bad})
    elif placement == "raw-behind-normalized":
        message = _wire_message("type", {
            "tool_calls": [{"name": "research", "id": "call-1", "args": {}}],
            "additional_kwargs": _wire_call_fields("tool_calls", '{"quantity": 999}'),
        })
    elif placement == "envelope-outer":
        message = {**_wire_message("constructor", good), **bad}
    elif placement == "extra-function":
        message = AIMessage(content="Research", **bad)
    elif placement == "function-and-args":
        fields = _wire_call_fields("tool_calls", '{"evidence_id": "e1"}')
        fields["tool_calls"][0]["args"] = '{"quantity": 999}'
        message = _wire_message("role", fields)
    else:
        message = _wire_message("role", {"additional_kwargs": {
            **good, "additional_kwargs": bad,
        }})
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def _content_message(representation, block):
    content = [deepcopy(block)]
    if representation == "concrete":
        return AIMessage(content=content)
    if representation == "tuple":
        return ("assistant", content)
    if representation == "list":
        return ["assistant", content]
    return _wire_message(representation, {"content": content})


@pytest.mark.parametrize("representation", ["concrete", "role", "constructor", "tuple", "list"])
@pytest.mark.parametrize("kind", ["tool_call", "server_tool_call"])
@pytest.mark.parametrize("arguments", ['{"evidence_id": "e1"}', '{"quantity": 999}', []])
def test_message_boundary_call_content_requires_object_args(representation, kind, arguments):
    message = _content_message(representation, {
        "type": kind, "name": "research", "id": "call-1", "args": arguments,
    })
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("representation", ["concrete", "role", "constructor", "tuple", "list"])
@pytest.mark.parametrize("kind", ["invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk"])
@pytest.mark.parametrize("arguments", ['{"quantity": 999}', '{"evidence_id":', '["e1"]'])
def test_message_boundary_encoded_call_content_is_checked(representation, kind, arguments):
    message = _content_message(representation, {
        "type": kind, "name": "research", "id": "call-1", "args": arguments,
    })
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("representation", ["concrete", "role", "constructor", "tuple", "list"])
@pytest.mark.parametrize("kind", [
    "tool_call", "server_tool_call", "invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk",
])
def test_message_boundary_benign_call_content_preserves_original(representation, kind):
    args = {"evidence_id": "e1"} if kind in {"tool_call", "server_tool_call"} else '{"evidence_id": "e1"}'
    message = _content_message(representation, {
        "type": kind, "name": "research", "id": "call-1", "args": args,
    })
    original = deepcopy(message)
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original
    assert signal == "Hold"


@pytest.mark.parametrize("message", [
    "Research discussion of {\"quantity\": 999}",
    {"role": "assistant", "content": "Research", "response_metadata": {
        "description": '{"function_call": {"arguments": "not-json"}}',
    }},
    {"role": "assistant", "content": [{"type": "text", "text": '{"quantity": 999}'}]},
    {"role": "assistant", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,"}}]},
])
def test_message_boundary_non_call_content_remains_data(message):
    original = deepcopy(message)
    final, _ = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original


@pytest.mark.parametrize("message", [
    {}, {"role": "assistant"}, {"role": "unknown", "content": "Research"},
    ["assistant"], ["assistant", "Research", "extra"],
    {"lc": 1, "type": "constructor", "id": ["custom", "OpaqueMessage"], "kwargs": {"content": "Research"}},
    {"role": "assistant", "content": [{"type": "custom_tool_call", "args": '{"evidence_id": "e1"}'}]},
    {"role": "assistant", "content": [{"type": "tool_use", "input": '{"quantity": 999}'}]},
])
def test_message_boundary_unknown_or_malformed_representations_deny(message):
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("placement", ["wire-metadata", "wire-argument", "envelope"])
def test_message_boundary_plain_input_denies_hooks_before_copy_or_conversion(placement):
    calls = []

    class Opaque:
        def model_dump(self, *args, **kwargs):
            calls.append("model_dump")
            raise AssertionError("serializer invoked")

        def __deepcopy__(self, memo):
            calls.append("deepcopy")
            raise AssertionError("copy hook invoked")

        def __str__(self):
            calls.append("str")
            raise AssertionError("string hook invoked")

    message = {"role": "assistant", "content": "Research"}
    if placement == "wire-metadata":
        message["additional_kwargs"] = {"opaque": Opaque()}
    elif placement == "wire-argument":
        message["tool_calls"] = [{"type": "function", "id": "call-1", "function": {
            "name": "research", "arguments": Opaque(),
        }}]
    else:
        message = {"lc": 1, "type": "constructor", "id": ["custom", "AIMessage"],
                   "kwargs": {"content": "Research", "opaque": Opaque()}}
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)
    assert calls == []


@pytest.mark.parametrize("representation", ["concrete", "role", "constructor", "tuple"])
@pytest.mark.parametrize("arguments", ['{"order_intents": [{"quantity": 999}]}', "not-json", "[]"])
def test_message_boundary_responses_function_call_blocks_deny(representation, arguments):
    message = _content_message(representation, {
        "type": "function_call", "call_id": "f1", "name": "research", "arguments": arguments,
    })
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def test_message_boundary_responses_function_call_benign_block_preserved():
    message = _content_message("role", {
        "type": "function_call", "call_id": "f1", "name": "research",
        "arguments": '{"evidence_id": "e1"}',
    })
    original = deepcopy(message)
    final, _ = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original


@pytest.mark.parametrize("kind", ["human", "system", "tool", "chunk-envelope"])
@pytest.mark.parametrize("unsafe", [True, False], ids=["authority", "benign"])
def test_message_boundary_calls_are_checked_independent_of_role(kind, unsafe):
    arguments = '{"quantity": 999}' if unsafe else '{"evidence_id": "e1"}'
    additional = _wire_call_fields("function_call", arguments)
    if kind == "human":
        message = HumanMessage(content="Research", additional_kwargs=additional)
    elif kind == "system":
        message = SystemMessage(content="Research", additional_kwargs=additional)
    elif kind == "tool":
        message = ToolMessage(content="Research", tool_call_id="call-1", additional_kwargs=additional)
    else:
        message = _wire_message("constructor", {"tool_call_chunks": [{
            "name": "research", "id": "call-1", "index": 0, "args": arguments,
        }]})
        message["id"][-1] = "AIMessageChunk"
    original = deepcopy(message)
    if unsafe:
        with pytest.raises(HistoricalRuntimeOutputError):
            _run_with_message(message)
    else:
        final, _ = _run_with_message(message)
        assert final["messages"][-1] is message
    assert message == original


@pytest.mark.parametrize("arguments", [
    '{"nested": {"quantity": 999}, "nested": {"evidence_id": "e1"}}',
    '{"evidence_id": NaN}', '{"evidence_id": Infinity}',
])
def test_message_boundary_ambiguous_or_non_json_encoded_objects_deny(arguments):
    message = _wire_message("role", _wire_call_fields("tool_calls", arguments))
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("representation", ["remove", "overridden-constructor-role"])
def test_message_boundary_discarded_or_reclassified_call_content_still_denies(representation):
    block = {"type": "function_call", "name": "research", "call_id": "call-1",
             "arguments": '{"quantity": 999}'}
    if representation == "remove":
        message = {"role": "remove", "id": "prior-message", "content": [block]}
    else:
        message = _wire_message("constructor", {"role": "human", "content": [block]})
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("update", [
    {"type": "function"}, {"type": "invalid_tool_call"}, {"name": None}, {"name": 7},
    {"id": []},
])
def test_message_boundary_mutated_normalized_call_record_denies(update):
    message = AIMessage(content="Research", tool_calls=[{
        "type": "tool_call", "name": "research", "id": "call-1", "args": {},
    }])
    message.tool_calls[0].update(update)
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("field", ["invalid_tool_calls", "tool_call_chunks"])
@pytest.mark.parametrize("arguments", [{"evidence_id": "e1"}, None, []])
def test_message_boundary_encoded_call_records_require_strings(field, arguments):
    message = _wire_message("role", {field: [{
        "name": "research", "id": "call-1", "args": arguments,
    }]})
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def test_message_boundary_mutated_concrete_discriminator_denies():
    message = HumanMessage(content="Research")
    message.type = "custom"
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("kind", ["unknown_operation", "custom_tool"])
def test_message_boundary_unknown_argument_bearing_content_denies(kind):
    message = _content_message("role", {
        "type": kind, "name": "research", "args": '{"evidence_id": "e1"}',
    })
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def test_message_boundary_cyclic_plain_metadata_denies_with_typed_error():
    message = {"role": "assistant", "content": "Research", "additional_kwargs": {}}
    message["additional_kwargs"]["cycle"] = message
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


def test_message_boundary_raw_object_arguments_preserve_original():
    message = _wire_message("role", _wire_call_fields("tool_calls", {"evidence_id": "e1"}))
    original = deepcopy(message)
    final, _ = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original


@pytest.mark.parametrize("representation", ["role", "type", "constructor"])
@pytest.mark.parametrize("field", ["additional_kwargs", "response_metadata"])
@pytest.mark.parametrize("metadata", [[], (), False])
def test_message_boundary_original_metadata_shape_denies_before_erasure(representation, field, metadata):
    message = _wire_message(representation, {field: metadata})
    with pytest.raises(HistoricalRuntimeOutputError):
        _run_with_message(message)


@pytest.mark.parametrize("event_type", ["earnings_call", "conference_call"])
@pytest.mark.parametrize("encoded", [False, True], ids=["normalized", "encoded"])
def test_message_boundary_benign_event_types_are_not_execution_blocks(event_type, encoded):
    if encoded:
        arguments = f'{{"type": "{event_type}", "evidence_id": "e1"}}'
        message = _wire_message("role", _wire_call_fields("tool_calls", arguments))
    else:
        message = AIMessage(content="Research", tool_calls=[{
            "name": "research", "id": "event-1",
            "args": {"type": event_type, "evidence_id": "e1"},
        }])
    original = deepcopy(message)
    final, signal = _run_with_message(message)
    assert final["messages"][-1] is message
    assert message == original
    assert signal == "Hold"
