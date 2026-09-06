"""AUD-H02 execution-carrier placement at every closed-response boundary."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mytradingalpha.data.bundle import BundleReplayPolicy
from mytradingalpha.research.cached_response import (
    CachedGraphResponseCorruptionError,
    CachedGraphResponseRepository,
    CachedGraphSelection,
    build_cached_graph_response,
    parse_cached_graph_response,
)
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    validate_historical_response,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/research/cached_graph_response_v1.json"
_RESPONSE_DOMAIN = b"mytradingalpha.cached_graph_response.v1\x00"
_CARRIERS = ("args", "arguments", "input", "function")
_BINDINGS = (
    "bundle_id",
    "bundle_hash",
    "knowledge_cutoff",
    "calendar_id",
    "replay_policy",
    "variant_id",
    "trade_date",
    "ticker",
    "instrument_id",
    "asset_type",
    "instrument_context",
)
_ARTIFACTS = (
    "graph_artifact_id",
    "graph_artifact_hash",
    "model_artifact_id",
    "model_artifact_hash",
    "runtime_manifest_id",
    "runtime_manifest_hash",
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _rehash(record: dict[str, object]) -> bytes:
    output = record["output"]
    output_hash = _digest(_canonical(output))
    record["output_hash"] = output_hash
    capture_manifest = record["capture_manifest"]
    assert type(capture_manifest) is dict
    capture_manifest["checksum"] = output_hash
    payload = {key: value for key, value in record.items() if key != "response_hash"}
    record["response_hash"] = _digest(_RESPONSE_DOMAIN + _canonical(payload))
    return _canonical(record)


def _validate(record: dict[str, object]) -> tuple[dict[str, object], str]:
    return validate_historical_response(
        record["output"],
        company_name=record["ticker"],
        trade_date=record["trade_date"],
        asset_type=record["asset_type"],
        instrument_context=record["instrument_context"],
    )


def _builder_kwargs(record: dict[str, object]) -> dict[str, object]:
    fields = {
        key: value
        for key, value in record.items()
        if key not in {"response_hash", "output_hash"}
    }
    fields["replay_policy"] = BundleReplayPolicy(fields["replay_policy"])
    return fields


def _record_with(message: object) -> dict[str, object]:
    record = json.loads(FIXTURE.read_bytes())
    record["output"]["messages"][-1] = message
    _rehash(record)
    return record


def _shadow_value(carrier: str) -> object:
    encoded_authority = '{"order_intents":[]}'
    if carrier == "function":
        return {"name": "shadow", "arguments": encoded_authority}
    return encoded_authority


def _base_message() -> dict[str, object]:
    return {"role": "assistant", "content": "Synthetic research."}


def _negative_message(case: tuple[str, str, str | None]) -> dict[str, object]:
    context, carrier, kind = case
    value = _shadow_value(carrier)
    message = _base_message()
    if context in {"message", "additional_kwargs", "response_metadata"}:
        if context == "message":
            message[carrier] = value
        else:
            message[context] = {carrier: value}
        return message
    if context == "raw_tool":
        message["tool_calls"] = [
            {
                "type": "function",
                "id": "c1",
                "function": {"name": "research", "arguments": "{}"},
                carrier: value,
            }
        ]
        return message
    if context == "raw_function":
        message["tool_calls"] = [
            {
                "type": "function",
                "id": "c1",
                "function": {
                    "name": "research",
                    "arguments": "{}",
                    carrier: value,
                },
            }
        ]
        return message
    if context == "object_content":
        block = {
            "type": kind,
            "id": "c1",
            "name": "research",
            "args": {"evidence_id": "e1"},
            carrier: value,
        }
    elif context == "encoded_content":
        block = {
            "type": kind,
            "id": "c1",
            "name": "research",
            "args": '{"evidence_id":"e1"}',
            carrier: value,
        }
    elif context == "function_content":
        block = {
            "type": "function_call",
            "call_id": "c1",
            "name": "research",
            "arguments": '{"evidence_id":"e1"}',
            carrier: value,
        }
    elif context == "wrapper":
        block = {
            "type": "non_standard",
            "value": {"type": "text", "text": "Synthetic research."},
            carrier: value,
        }
    else:
        assert context == "generic_content"
        block = {"type": kind, "text": "Synthetic research.", carrier: value}
    message["content"] = [block]
    return message


_NEGATIVE_CASES = [
    pytest.param((context, carrier, None), id=f"{context}-{carrier}")
    for context in ("message", "additional_kwargs", "response_metadata")
    for carrier in _CARRIERS
]
_NEGATIVE_CASES += [
    pytest.param(("raw_tool", carrier, None), id=f"raw-tool-{carrier}")
    for carrier in ("args", "arguments", "input")
]
_NEGATIVE_CASES += [
    pytest.param(("raw_function", carrier, None), id=f"raw-function-{carrier}")
    for carrier in ("args", "input", "function")
]
_NEGATIVE_CASES += [
    pytest.param(("object_content", carrier, kind), id=f"content-{kind}-{carrier}")
    for kind in ("tool_call", "server_tool_call")
    for carrier in ("arguments", "input", "function")
]
_NEGATIVE_CASES += [
    pytest.param(("encoded_content", carrier, kind), id=f"content-{kind}-{carrier}")
    for kind in ("invalid_tool_call", "tool_call_chunk", "server_tool_call_chunk")
    for carrier in ("arguments", "input", "function")
]
_NEGATIVE_CASES += [
    pytest.param(("function_content", carrier, None), id=f"content-function-{carrier}")
    for carrier in ("args", "input", "function")
]
_NEGATIVE_CASES += [
    pytest.param(("wrapper", carrier, None), id=f"wrapper-{carrier}")
    for carrier in _CARRIERS
]
_NEGATIVE_CASES += [
    pytest.param(("generic_content", carrier, kind), id=f"generic-{kind}-{carrier}")
    for kind, carrier in zip(
        ("text", "image", "extension_data", None),
        _CARRIERS,
        strict=True,
    )
]


@pytest.mark.parametrize("case", _NEGATIVE_CASES)
def test_unexpected_execution_carriers_fail_every_public_boundary(
    case: tuple[str, str, str | None],
) -> None:
    record = _record_with(_negative_message(case))
    raw = _canonical(record)

    with pytest.raises(HistoricalRuntimeOutputError):
        _validate(record)
    with pytest.raises(HistoricalRuntimeOutputError):
        build_cached_graph_response(**_builder_kwargs(record))
    with pytest.raises(
        CachedGraphResponseCorruptionError,
        match="cached response output validation failed",
    ):
        parse_cached_graph_response(raw)


def _valid_messages() -> list[object]:
    return [
        "Synthetic plain message.",
        ["assistant", "Synthetic role/content message."],
        {
            "role": "assistant",
            "content": '{"args":{"order_intents":[]}} is ordinary prose.',
            "response_metadata": {
                "provider_extension": {"finish_reason": "stop", "latency_ms": 2}
            },
        },
        {
            "role": "assistant",
            "content": "Synthetic research.",
            "additional_kwargs": {
                "function_call": {
                    "name": "research",
                    "arguments": '{"evidence_id":"e1"}',
                    "provider_extension": {"trace": "t1"},
                }
            },
        },
        {
            "role": "assistant",
            "content": "Synthetic research.",
            "tool_calls": [
                {
                    "type": "function",
                    "id": None,
                    "function": {
                        "name": "research",
                        "arguments": '{"evidence_id":"e1"}',
                    },
                    "provider_extension": {"trace": "t1"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Synthetic research.",
            "tool_calls": [
                {
                    "type": "tool_call",
                    "id": None,
                    "name": "research",
                    "args": {"evidence_id": "e1", "input": "argument data"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "Synthetic research.",
            "invalid_tool_calls": [
                {"id": None, "name": None, "args": '{"evidence_id":"e1"}', "error": None}
            ],
            "tool_call_chunks": [
                {"id": None, "name": None, "args": '{"evidence_id":"e1"}', "index": 0}
            ],
            "server_tool_call_chunks": [
                {"args": '{"evidence_id":"e1"}', "extras": {"provider": "synthetic"}}
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_call",
                    "id": None,
                    "name": "research",
                    "args": {"evidence_id": "e1", "function": "argument data"},
                    "extras": {"provider": "synthetic"},
                },
                {
                    "type": "server_tool_call",
                    "id": "c2",
                    "name": "research",
                    "args": {"evidence_id": "e2"},
                },
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "invalid_tool_call",
                    "id": None,
                    "name": None,
                    "args": '{"evidence_id":"e1"}',
                    "error": None,
                },
                {
                    "type": "tool_call_chunk",
                    "id": None,
                    "name": None,
                    "args": '{"evidence_id":"e2"}',
                    "index": "0",
                },
                {
                    "type": "server_tool_call_chunk",
                    "args": '{"evidence_id":"e3"}',
                },
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": "research",
                    "arguments": '{"evidence_id":"e1"}',
                }
            ],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "non_standard",
                    "value": {
                        "type": "tool_call",
                        "id": "c1",
                        "name": "research",
                        "args": {"evidence_id": "e1"},
                    },
                    "provider_extension": {"trace": "t1"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Synthetic text."},
                {"type": "image", "url": "fixture://image"},
                {"type": "extension_data", "provider_extension": {"trace": "t1"}},
            ],
        },
    ]


@pytest.mark.parametrize("message", _valid_messages())
def test_supported_call_and_message_shapes_remain_byte_compatible(message: object) -> None:
    record = _record_with(message)
    before = copy.deepcopy(record)
    raw = _canonical(record)

    state, signal = _validate(record)
    assert state == record["output"] and state is not record["output"]
    assert signal == "Hold"
    assert build_cached_graph_response(**_builder_kwargs(record)) == raw
    assert parse_cached_graph_response(raw).output == record["output"]
    assert record == before


def test_repository_reparse_rejects_rehashed_at_rest_shadow_record() -> None:
    baseline = parse_cached_graph_response(_canonical(json.loads(FIXTURE.read_bytes())))
    record = _record_with(
        {
            "role": "assistant",
            "content": "Synthetic research.",
            "arguments": '{"broker_credentials":{"token":"sealed"}}',
        }
    )
    raw = _canonical(record)
    repository = CachedGraphResponseRepository()

    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.seal(raw)

    repository._records[baseline.response_id] = raw
    selection = CachedGraphSelection(
        response_id=baseline.response_id,
        expected_response_hash=record["response_hash"],
        **{field: getattr(baseline, field) for field in _ARTIFACTS},
    )
    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.get_bound(
            selection,
            **{field: getattr(baseline, field) for field in _BINDINGS},
        )
