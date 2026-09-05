"""Audit A03: structure, not spelling, determines reserved output authority.

Fixtures are synthetic replay contracts, not model inference or authenticated captures.
"""

from __future__ import annotations

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
KEYS = ("target_weights", "targetWeights", "target-weights", "ORDER_TYPE", "orderType",
        "brokerCredentials", "riskAuthorization", "quantity")
BINDINGS = ("bundle_id", "bundle_hash", "knowledge_cutoff", "calendar_id", "replay_policy",
            "variant_id", "trade_date", "ticker", "instrument_id", "asset_type", "instrument_context")
ARTIFACTS = ("graph_artifact_id", "graph_artifact_hash", "model_artifact_id",
             "model_artifact_hash", "runtime_manifest_id", "runtime_manifest_hash")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _rehash(payload: dict) -> bytes:
    payload["output_hash"] = "sha256:" + hashlib.sha256(_canonical(payload["output"])).hexdigest()
    payload["capture_manifest"]["checksum"] = payload["output_hash"]
    body = {k: v for k, v in payload.items() if k != "response_hash"}
    payload["response_hash"] = "sha256:" + hashlib.sha256(
        b"mytradingalpha.cached_graph_response.v1\x00" + _canonical(body)
    ).hexdigest()
    return _canonical(payload)


def _validate(payload: dict) -> tuple:
    return validate_historical_response(
        payload["output"], company_name=payload["ticker"], trade_date=payload["trade_date"],
        asset_type=payload["asset_type"], instrument_context=payload["instrument_context"],
    )


def _seal(payload: dict) -> bytes:
    kwargs = {k: v for k, v in payload.items() if k not in {"response_hash", "output_hash"}}
    kwargs["replay_policy"] = BundleReplayPolicy(kwargs["replay_policy"])
    return build_cached_graph_response(**kwargs)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("location", ["metadata", "decoded_arguments"])
def test_reserved_aliases_are_rejected_at_every_cached_boundary(key: str, location: str) -> None:
    payload = json.loads(FIXTURE.read_bytes())
    baseline = parse_cached_graph_response(_canonical(json.loads(FIXTURE.read_bytes())))
    message = payload["output"]["messages"][1]
    if location == "metadata":
        message["response_metadata"]["nested"] = [{key: {"NEW": 1}}]
    else:
        message["additional_kwargs"] = {
            "function_call": {"name": "research", "arguments": json.dumps({key: 1})}
        }
    raw = _rehash(payload)  # A valid new hash must not make forbidden fields acceptable.
    with pytest.raises(HistoricalRuntimeOutputError):
        _validate(payload)
    with pytest.raises(HistoricalRuntimeOutputError):
        _seal(payload)
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(raw)
    repository = CachedGraphResponseRepository()
    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.seal(raw)
    # Negative at-rest/corruption fixture only; public API never permits this mutation.
    repository._records[baseline.response_id] = raw
    selection = CachedGraphSelection(
        response_id=baseline.response_id, expected_response_hash=payload["response_hash"],
        **{field: getattr(baseline, field) for field in ARTIFACTS},
    )
    with pytest.raises(CachedGraphResponseCorruptionError):
        repository.get_bound(selection, **{field: getattr(baseline, field) for field in BINDINGS})


def test_legitimate_metadata_and_prose_remain_compatible() -> None:
    payload = json.loads(FIXTURE.read_bytes())
    payload["output"]["messages"][1]["response_metadata"] = {
        "token_usage": {"input_tokens": 12, "output_tokens": 7},
        "finish_reason": "stop", "model_name": "synthetic-fixture",
    }
    payload["output"]["market_report"] = "Legacy prose about portfolio weights is not authority."
    _rehash(payload)
    raw = _seal(payload)
    parsed = parse_cached_graph_response(raw)
    assert parsed.output == payload["output"]
    assert _validate(payload)[1] == "Hold"
    assert build_cached_graph_response(**{
        **{k: v for k, v in json.loads(FIXTURE.read_bytes()).items()
           if k not in {"response_hash", "output_hash"}},
        "replay_policy": BundleReplayPolicy(json.loads(FIXTURE.read_bytes())["replay_policy"]),
    }) == _canonical(json.loads(FIXTURE.read_bytes()))
