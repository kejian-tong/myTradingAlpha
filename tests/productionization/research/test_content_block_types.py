"""Malformed plain-data content selectors fail through public typed boundaries.

All responses are synthetic. Recomputed canonical hashes ensure parser failures
exercise output validation, not an unrelated checksum or byte-format rejection.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from mytradingalpha.data.bundle import BundleReplayPolicy
from mytradingalpha.research.cached_response import (
    CachedGraphResponseCorruptionError,
    build_cached_graph_response,
    parse_cached_graph_response,
)
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    validate_historical_response,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/research/cached_graph_response_v1.json"
BOUNDARIES = ("validator", "sealer", "parser")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _checksum(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _record(block: dict, *, wrapped: bool = False) -> dict:
    record = json.loads(FIXTURE.read_bytes())
    content = copy.deepcopy(block)
    if wrapped:
        content = {"type": "non_standard", "value": content}
    record["output"]["messages"][-1]["content"] = [content]
    record["output_hash"] = _checksum(_canonical(record["output"]))
    record["capture_manifest"]["checksum"] = record["output_hash"]
    payload = {key: value for key, value in record.items() if key != "response_hash"}
    record["response_hash"] = _checksum(
        b"mytradingalpha.cached_graph_response.v1\x00" + _canonical(payload)
    )
    return record


def _exercise(record: dict, boundary: str) -> dict:
    if boundary == "validator":
        state, signal = validate_historical_response(
            record["output"], company_name=record["ticker"],
            trade_date=record["trade_date"], asset_type=record["asset_type"],
            instrument_context=record["instrument_context"],
        )
        assert signal == "Hold"
        return state
    if boundary == "sealer":
        fields = {key: value for key, value in record.items()
                  if key not in {"response_hash", "output_hash"}}
        fields["replay_policy"] = BundleReplayPolicy(fields["replay_policy"])
        raw = build_cached_graph_response(**fields)
        # Controls also verify the independent wire/hash construction matches v1.
        assert raw == _canonical(record)
    else:
        assert boundary == "parser"
        raw = _canonical(record)
    return parse_cached_graph_response(raw).output


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("wrapped", [False, True], ids=["direct", "wrapped"])
@pytest.mark.parametrize("kind", [[], {}], ids=["list", "object"])
def test_unhashable_content_type_has_a_typed_failure(boundary, wrapped, kind) -> None:
    record = _record({"type": kind, "text": "Synthetic evidence."}, wrapped=wrapped)
    if boundary == "parser":
        with pytest.raises(CachedGraphResponseCorruptionError,
                           match="cached response output validation failed"):
            _exercise(record, boundary)
    else:
        with pytest.raises(HistoricalRuntimeOutputError, match="content block type"):
            _exercise(record, boundary)


@pytest.mark.parametrize("boundary", BOUNDARIES)
@pytest.mark.parametrize("block", [
    {"type": "text", "text": "Synthetic evidence."},
    {"type": "extension_data", "text": "Non-executable extension data."},
    {"text": "Existing untyped data block."},
    {"type": None, "text": "Existing nullable data block."},
], ids=["text", "extension", "absent", "null"])
def test_legitimate_content_data_remains_compatible(boundary, block) -> None:
    record = _record(block)
    before = copy.deepcopy(record)
    assert _exercise(record, boundary) == before["output"]
    assert record == before
