"""Regression coverage retained while SIG-01 moves to closed data-only replay."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from mytradingalpha.contracts.schemas import RunContext
from mytradingalpha.data.replay_guard import HistoricalReplayDeniedError
from mytradingalpha.research.cached_response import (
    CachedGraphResponseCorruptionError,
    CachedGraphResponseMismatchError,
    CachedGraphResponseRepository,
    build_cached_graph_response,
)
from mytradingalpha.research.tradingagents_adapter import HistoricalInstrumentError, ResearchAdapter
from tests.productionization.data.test_bundle_replay import ObservedContextTzInfo
from tests.productionization.research.test_adapter import (
    run_adapter,
    sealed_adapter,
)
from tests.productionization.research.test_cached_response import (
    canonical,
    make_capture_manifest,
    make_output,
    make_response_kwargs,
    make_selection,
)
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    create_historical_initial_state,
    validate_historical_response,
)


def validate(output: object):
    return validate_historical_response(
        output,
        company_name="NEW",
        trade_date="2024-06-30",
        asset_type="stock",
        instrument_context=str(make_output()["instrument_context"]),
    )


class BoundArgumentProbe:
    def __init__(self, effects: list[str], label: str) -> None:
        object.__setattr__(self, "_effects", effects)
        object.__setattr__(self, "_label", label)

    def _record(self, operation: str) -> None:
        object.__getattribute__(self, "_effects").append(
            f"{object.__getattribute__(self, '_label')}.{operation}"
        )

    def __str__(self) -> str:
        self._record("str")
        return "2024-06-30"

    def __eq__(self, other: object) -> bool:
        self._record("eq")
        return False

    def __ne__(self, other: object) -> bool:
        self._record("ne")
        return True

    def __hash__(self) -> int:
        self._record("hash")
        return 1

    def model_dump(self, *args: object, **kwargs: object) -> object:
        self._record("model_dump")
        return {}


class BoundStringSubclass(str):
    def __new__(cls, value: str, effects: list[str], label: str):
        instance = str.__new__(cls, value)
        instance._effects = effects
        instance._label = label
        return instance

    def _record(self, operation: str) -> None:
        self._effects.append(f"{self._label}.{operation}")

    def __str__(self) -> str:
        self._record("str")
        return str.__str__(self)

    def __eq__(self, other: object) -> bool:
        self._record("eq")
        return str.__eq__(self, other)

    def __ne__(self, other: object) -> bool:
        self._record("ne")
        return str.__ne__(self, other)

    def __hash__(self) -> int:
        self._record("hash")
        return str.__hash__(self)

    def model_dump(self, *args: object, **kwargs: object) -> object:
        self._record("model_dump")
        return {}


def historical_bound_kwargs() -> dict[str, object]:
    return {
        "company_name": "NEW",
        "trade_date": "2024-06-30",
        "asset_type": "stock",
        "instrument_context": str(make_output()["instrument_context"]),
    }


@pytest.mark.parametrize("entrypoint", ["create", "validate"])
@pytest.mark.parametrize(
    "field", ["company_name", "trade_date", "asset_type", "instrument_context"]
)
@pytest.mark.parametrize("kind", ["object", "string-subclass"])
def test_historical_exports_reject_nonexact_bound_strings_without_observation(
    entrypoint: str, field: str, kind: str
) -> None:
    effects: list[str] = []
    valid = historical_bound_kwargs()[field]
    hostile: object = (
        BoundArgumentProbe(effects, field)
        if kind == "object"
        else BoundStringSubclass(str(valid), effects, field)
    )
    kwargs = historical_bound_kwargs()
    kwargs[field] = hostile
    effects.clear()
    with pytest.raises(HistoricalRuntimeOutputError):
        if entrypoint == "create":
            create_historical_initial_state(**kwargs)  # type: ignore[arg-type]
        else:
            validate_historical_response(
                make_output(),
                **kwargs,  # type: ignore[arg-type]
            )
    assert effects == []


def test_historical_exports_preserve_exact_string_state_and_signal_controls() -> None:
    kwargs = historical_bound_kwargs()
    initial = create_historical_initial_state(**kwargs)  # type: ignore[arg-type]
    assert initial["company_of_interest"] == "NEW"
    assert initial["trade_date"] == "2024-06-30"
    assert initial["asset_type"] == "stock"
    assert initial["instrument_context"] == make_output()["instrument_context"]
    final, signal = validate_historical_response(
        make_output(),
        **kwargs,  # type: ignore[arg-type]
    )
    assert final == make_output()
    assert signal == "Hold"


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
def test_cached_output_cannot_mutate_bound_state(field: str, replacement: object) -> None:
    output = make_output()
    output[field] = replacement
    with pytest.raises(HistoricalRuntimeOutputError, match=field):
        validate(output)


def test_plain_prose_and_debate_updates_remain_supported() -> None:
    output = make_output()
    output["market_report"] = "Updated evidence summary"
    output["investment_debate_state"].update(history="Evidence debate", count=1)
    final, signal = validate(output)
    assert final["market_report"] == "Updated evidence summary"
    assert final["investment_debate_state"]["history"] == "Evidence debate"
    assert final["investment_debate_state"]["count"] == 1 and signal == "Hold"


@pytest.mark.parametrize("ticker", ["OLD", "AAPL"])
def test_expired_or_missing_alias_denies_before_response_access(monkeypatch, ticker: str) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()
    monkeypatch.setattr(
        responses, "get_bound", lambda *args, **kwargs: pytest.fail("response accessed")
    )
    with pytest.raises(HistoricalInstrumentError, match="missing"):
        run_adapter(adapter, bundle, context, ticker=ticker)


def test_adapter_passes_guard_bound_canonical_context_to_response_repository(monkeypatch) -> None:
    bundle, context, evidence, responses, selection, _ = sealed_adapter()
    raw = RunContext.model_construct(**context.model_dump(mode="json"))
    observed: list[tuple[object, dict[str, object]]] = []
    original = responses.get_bound

    def recording(selection_arg, **bindings):
        observed.append((selection_arg, bindings))
        return original(selection_arg, **bindings)

    monkeypatch.setattr(responses, "get_bound", recording)
    final, signal = run_adapter(ResearchAdapter(evidence, responses, selection), bundle, raw)
    assert final == make_output() and signal == "Hold"
    assert len(observed) == 1
    assert observed[0][1]["knowledge_cutoff"] == context.knowledge_cutoff
    assert type(observed[0][1]["knowledge_cutoff"]) is datetime
    assert observed[0][1]["knowledge_cutoff"].tzinfo is timezone.utc
    assert raw.knowledge_cutoff == "2024-06-30T23:59:59Z"


@pytest.mark.parametrize("field", ["decision_time", "knowledge_cutoff", "earliest_execution_time"])
def test_adapter_rejects_custom_tzinfo_context_without_observation(field: str) -> None:
    bundle, context, _, _, _, adapter = sealed_adapter()
    payload = context.model_dump(mode="python")
    baseline = payload[field]
    assert type(baseline) is datetime
    effects: list[str] = []
    payload[field] = datetime(
        baseline.year,
        baseline.month,
        baseline.day,
        baseline.hour,
        baseline.minute,
        baseline.second,
        tzinfo=ObservedContextTzInfo(effects),
    )
    raw = RunContext.model_construct(**payload)
    effects.clear()
    with pytest.raises(HistoricalReplayDeniedError):
        run_adapter(adapter, bundle, raw)
    assert effects == []


@pytest.mark.parametrize(
    "update",
    [
        {"mode": "unknown"},
        {"mode": "forward_paper"},
        {"network_policy": {"research_tool_egress": True}},
        {"network_policy": {"unexpected": False}},
        {"decision_time": "not-a-time"},
        {"knowledge_cutoff": "2024-06-30T23:59:59"},
        {"bundle_hash": "not-a-hash"},
    ],
)
def test_invalid_raw_context_is_denied_before_response_access(monkeypatch, update) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()
    raw = RunContext.model_construct(**{**context.model_dump(mode="json"), **update})
    monkeypatch.setattr(
        responses, "get_bound", lambda *args, **kwargs: pytest.fail("response accessed")
    )
    with pytest.raises(HistoricalReplayDeniedError):
        run_adapter(adapter, bundle, raw)


def test_context_subclass_is_denied_before_serializer_or_response_access(monkeypatch) -> None:
    bundle, context, _, responses, _, adapter = sealed_adapter()

    class HostileContext(RunContext):
        def model_dump(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("serializer")

    raw = HostileContext.model_construct(**context.model_dump(mode="python"))
    monkeypatch.setattr(
        responses, "get_bound", lambda *args, **kwargs: pytest.fail("response accessed")
    )
    with pytest.raises(HistoricalReplayDeniedError):
        run_adapter(adapter, bundle, raw)


def with_message(message: object) -> dict[str, object]:
    output = make_output()
    output["messages"].append(message)
    return output


@pytest.mark.parametrize(
    "message",
    [
        "Research prose",
        ["assistant", "Research prose"],
        {"role": "assistant", "content": "Research", "response_metadata": {"model": "cached"}},
        {"type": "ai", "content": "Research", "response_metadata": {}},
        {"role": "assistant", "content": [{"type": "text", "text": "Research"}]},
        {
            "role": "assistant",
            "content": [{"type": "image_url", "image_url": {"url": "fixture:data"}}],
        },
    ],
)
def test_selected_plain_message_representations_preserve_output(message: object) -> None:
    original = deepcopy(message)
    final, signal = validate(with_message(message))
    assert final["messages"][-1] == original and signal == "Hold"


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"role": "assistant"},
        {"role": "unknown", "content": "Research"},
        {"type": "unknown", "content": "Research"},
        {"role": "assistant", "type": "ai", "content": "Research"},
        ["assistant"],
        ["assistant", "Research", "extra"],
        {
            "lc": 1,
            "type": "constructor",
            "id": ["custom", "AIMessage"],
            "kwargs": {"content": "Research"},
        },
        {"role": "assistant", "content": [{"type": "custom_tool_call", "args": "{}"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "input": "{}"}]},
    ],
)
def test_unknown_constructor_or_execution_bearing_messages_are_denied(message: object) -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(message))


def raw_function_call(arguments: object) -> dict[str, object]:
    return {
        "role": "assistant",
        "content": "Research",
        "additional_kwargs": {"function_call": {"name": "research", "arguments": arguments}},
    }


def encoded_call(location: str, arguments: object) -> dict[str, object]:
    if location == "function_call":
        fields = {"function_call": {"name": "research", "arguments": arguments}}
    elif location == "raw_tool_calls":
        fields = {
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "research", "arguments": arguments},
                }
            ]
        }
    else:
        fields = {location: [{"id": "c1", "name": "research", "args": arguments, "error": None}]}
    return {"role": "assistant", "content": "Research", "additional_kwargs": fields}


@pytest.mark.parametrize(
    "arguments",
    [
        '{"nested":[{"order_intents":[]}]}',
        "not-json",
        "[]",
        "null",
        '{"nested":{"x":1,"x":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":1e400}',
    ],
)
def test_encoded_call_arguments_deny_authority_malformed_duplicate_and_nonfinite(
    arguments: str,
) -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(raw_function_call(arguments)))


@pytest.mark.parametrize(
    "location",
    [
        "function_call",
        "raw_tool_calls",
        "invalid_tool_calls",
        "tool_call_chunks",
        "server_tool_call_chunks",
    ],
)
@pytest.mark.parametrize(
    "arguments", ['{"nested":[{"quantity":5}]}', "not-json", "[]", '{"x":NaN}', '{"x":1e400}']
)
def test_all_selected_encoded_call_locations_fail_closed(location: str, arguments: str) -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(encoded_call(location, arguments)))


@pytest.mark.parametrize(
    "location",
    [
        "function_call",
        "raw_tool_calls",
        "invalid_tool_calls",
        "tool_call_chunks",
        "server_tool_call_chunks",
    ],
)
def test_all_selected_encoded_call_locations_preserve_benign_data(location: str) -> None:
    message = encoded_call(location, '{"evidence_id":"e1","period":2}')
    final, signal = validate(with_message(message))
    assert final["messages"][-1] == message and signal == "Hold"


@pytest.mark.parametrize("kind", ["tool_call", "server_tool_call"])
@pytest.mark.parametrize("arguments", [{"quantity": 5}, "not-an-object", []])
def test_object_argument_content_calls_reject_authority_or_wrong_shape(
    kind: str, arguments: object
) -> None:
    message = {
        "role": "assistant",
        "content": [{"type": kind, "id": "c1", "name": "research", "args": arguments}],
    }
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(message))


@pytest.mark.parametrize("kind", ["invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk"])
@pytest.mark.parametrize("arguments", ['{"quantity":5}', "not-json", "[]"])
def test_encoded_argument_content_calls_reject_authority_or_malformed(
    kind: str, arguments: str
) -> None:
    message = {
        "role": "assistant",
        "content": [{"type": kind, "id": "c1", "name": "research", "args": arguments}],
    }
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(message))


@pytest.mark.parametrize(
    "kind",
    [
        "tool_call",
        "server_tool_call",
        "invalid_tool_call",
        "tool_call_chunk",
        "server_tool_call_chunk",
        "function_call",
    ],
)
def test_selected_content_call_records_preserve_benign_data(kind: str) -> None:
    if kind in {"tool_call", "server_tool_call"}:
        block = {"type": kind, "id": "c1", "name": "research", "args": {"evidence_id": "e1"}}
    elif kind == "function_call":
        block = {
            "type": kind,
            "call_id": "c1",
            "name": "research",
            "arguments": '{"evidence_id":"e1"}',
        }
    else:
        block = {"type": kind, "id": "c1", "name": "research", "args": '{"evidence_id":"e1"}'}
    message = {"role": "assistant", "content": [{"type": "non_standard", "value": block}]}
    final, signal = validate(with_message(message))
    assert final["messages"][-1] == message and signal == "Hold"


@pytest.mark.parametrize(
    "block",
    [
        {"type": "tool_call", "id": [], "name": "research", "args": {}},
        {"type": "server_tool_call", "id": None, "name": "research", "args": {}},
        {"type": "invalid_tool_call", "id": {}, "name": [], "args": "{}"},
        {"type": "tool_call_chunk", "id": "c1", "name": 7, "args": "{}"},
        {"type": "server_tool_call_chunk", "id": None, "args": "{}"},
        {"type": "function_call", "call_id": None, "name": "research", "arguments": "{}"},
        {"type": "function_call", "call_id": "c1", "name": "research", "arguments": {}},
        {
            "role": "assistant",
            "content": "Research",
            "tool_calls": [{"name": "research", "args": {}}],
        },
    ],
)
def test_selected_call_record_identity_and_argument_types_fail_closed(
    block: dict[str, object],
) -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message({"role": "assistant", "content": [block]}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("index", True),
        ("index", 1.5),
        ("extras", []),
        ("extras", None),
        ("error", 7),
    ],
)
def test_optional_call_metadata_requires_declared_types(field: str, value: object) -> None:
    block = {"type": "invalid_tool_call", "id": None, "name": None, "args": "{}", field: value}
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message({"role": "assistant", "content": [block]}))


def test_shadowed_raw_and_normalized_call_fields_are_both_checked() -> None:
    message = {
        "role": "assistant",
        "content": "Research",
        "tool_calls": [
            {"type": "tool_call", "id": "c1", "name": "research", "args": {"evidence_id": "e1"}}
        ],
        "additional_kwargs": {
            "function_call": {"name": "research", "arguments": '{"order_intents":[]}'}
        },
    }
    assert type(message) is dict
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(message))


def nested_argument_json(max_depth: int) -> str:
    return '{"n":' * (max_depth - 1) + "0" + "}" * (max_depth - 1)


def encoded_depth_message(max_depth: int) -> dict[str, object]:
    return raw_function_call(nested_argument_json(max_depth))


def json_node_count(value: object) -> int:
    if type(value) is dict:
        return 1 + sum(json_node_count(item) for item in value.values())
    if type(value) is list:
        return 1 + sum(json_node_count(item) for item in value)
    return 1


def output_at_depth(max_depth: int) -> dict[str, object]:
    output = make_output()
    value: object = "leaf"
    # output -> messages -> message -> response_metadata -> value is five nodes deep.
    for index in range(max_depth - 5):
        value = {f"n{index}": value}
    output["messages"].append(
        {"role": "assistant", "content": "Research", "response_metadata": {"value": value}}
    )
    return output


def test_deep_encoded_arguments_fail_with_typed_historical_error() -> None:
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(encoded_depth_message(1_500)))


def test_direct_historical_depth_boundary_is_exact() -> None:
    assert validate(output_at_depth(64))[1] == "Hold"
    with pytest.raises(HistoricalRuntimeOutputError, match="depth"):
        validate(output_at_depth(65))


def test_direct_historical_decoded_argument_depth_boundary_is_exact() -> None:
    assert validate(with_message(encoded_depth_message(64)))[1] == "Hold"
    with pytest.raises(HistoricalRuntimeOutputError, match="depth"):
        validate(with_message(encoded_depth_message(65)))


def test_direct_historical_node_boundary_is_exact() -> None:
    output = make_output()
    remaining = 100_000 - json_node_count(output)
    output["messages"].extend("Research" for _ in range(remaining))
    assert json_node_count(output) == 100_000
    assert validate(output)[1] == "Hold"
    output["messages"].append("one-too-many")
    with pytest.raises(HistoricalRuntimeOutputError, match="node"):
        validate(output)


def test_direct_historical_decoded_argument_node_boundary_is_exact() -> None:
    accepted = raw_function_call('{"values":[' + ",".join("0" for _ in range(99_998)) + "]}")
    rejected = raw_function_call('{"values":[' + ",".join("0" for _ in range(99_999)) + "]}")
    assert validate(with_message(accepted))[1] == "Hold"
    with pytest.raises(HistoricalRuntimeOutputError, match="node"):
        validate(with_message(rejected))


def test_direct_historical_utf8_key_and_string_boundaries_are_exact() -> None:
    for field in ("market_report", "metadata-key"):
        accepted = make_output()
        rejected = make_output()
        if field == "market_report":
            accepted[field] = "x" * 1_048_576
            rejected[field] = "x" * 1_048_577
        else:
            accepted["messages"].append(
                {
                    "role": "assistant",
                    "content": "Research",
                    "response_metadata": {"k" * 1_048_576: "ok"},
                }
            )
            rejected["messages"].append(
                {
                    "role": "assistant",
                    "content": "Research",
                    "response_metadata": {"k" * 1_048_577: "no"},
                }
            )
        assert validate(accepted)[1] == "Hold"
        with pytest.raises(HistoricalRuntimeOutputError, match="string"):
            validate(rejected)


def test_benign_encoded_and_object_call_arguments_are_preserved_as_data() -> None:
    messages = [
        raw_function_call('{"evidence_id":"e1","period":2}'),
        {
            "role": "assistant",
            "content": [
                {"type": "tool_call", "id": "c1", "name": "research", "args": {"evidence_id": "e1"}}
            ],
        },
    ]
    output = make_output()
    output["messages"].extend(messages)
    final, signal = validate(output)
    assert final["messages"][-2:] == messages and signal == "Hold"


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nested_nonfinite_plain_call_arguments_are_denied(number: float) -> None:
    message = {
        "role": "assistant",
        "content": [
            {"type": "tool_call", "id": "c1", "name": "research", "args": {"scores": [1.5, number]}}
        ],
    }
    with pytest.raises(HistoricalRuntimeOutputError):
        validate(with_message(message))


def test_json_looking_prose_is_never_reclassified_as_executable_arguments() -> None:
    message = {
        "role": "assistant",
        "content": 'Discussion of {"quantity":999}',
        "response_metadata": {"description": '{"order_intents":[]}'},
    }
    final, _ = validate(with_message(message))
    assert final["messages"][-1] == message


def test_opaque_callback_import_and_host_handle_inputs_fail_before_hooks() -> None:
    calls: list[str] = []

    class Opaque:
        def __str__(self):
            calls.append("str")
            raise AssertionError("hook")

        def __deepcopy__(self, memo):
            calls.append("copy")
            raise AssertionError("hook")

        def model_dump(self, *args, **kwargs):
            calls.append("dump")
            raise AssertionError("hook")

    for value in (Opaque(), lambda: None, __import__, object()):
        output = with_message(value)
        with pytest.raises(CachedGraphResponseCorruptionError):
            build_cached_graph_response(
                **make_response_kwargs(
                    output=output, capture_manifest=make_capture_manifest(make_output())
                )
            )
    assert calls == []


def test_response_provenance_fields_are_hash_bound_and_cannot_be_backdated() -> None:
    raw = build_cached_graph_response(**make_response_kwargs())
    record = CachedGraphResponseRepository().seal(raw)
    selection = make_selection(expected_response_hash=record.response_hash)
    payload = record.model_dump(mode="json")
    for field, value in (
        ("response_id", "different-response"),
        ("graph_artifact_id", "different-graph"),
        ("model_artifact_id", "different-model"),
        ("runtime_manifest_id", "different-runtime"),
        (
            "capture_manifest",
            {
                **record.capture_manifest.model_dump(mode="json"),
                "manifest_id": "different-capture",
            },
        ),
    ):
        changed = {**payload, field: value}
        repository = CachedGraphResponseRepository()
        repository._records[record.response_id] = canonical(changed)
        with pytest.raises((CachedGraphResponseCorruptionError, CachedGraphResponseMismatchError)):
            repository.get_bound(
                selection,
                bundle_id=record.bundle_id,
                bundle_hash=record.bundle_hash,
                knowledge_cutoff=record.knowledge_cutoff,
                calendar_id=record.calendar_id,
                replay_policy=record.replay_policy,
                variant_id=record.variant_id,
                trade_date=record.trade_date,
                ticker=record.ticker,
                instrument_id=record.instrument_id,
                asset_type=record.asset_type,
                instrument_context=record.instrument_context,
            )
