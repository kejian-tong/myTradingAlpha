"""Decoder failures must remain typed corruption, without invoking any runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from mytradingalpha.research.cached_response import (
    MAX_CACHED_RESPONSE_BYTES,
    CachedGraphResponseCorruptionError,
    parse_cached_graph_response,
)


@pytest.mark.parametrize(
    "raw",
    [b"[" * 12000 + b"0" + b"]" * 12000, b"{", b"[]"],
    ids=["deep-json", "incomplete-object", "wrong-root"],
)
def test_cached_response_decoder_failure_is_typed_corruption(raw: bytes) -> None:
    assert len(raw) < MAX_CACHED_RESPONSE_BYTES
    with pytest.raises(CachedGraphResponseCorruptionError):
        parse_cached_graph_response(raw)


def test_existing_canonical_response_fixture_remains_readable() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures/research/cached_graph_response_v1.json"
    record = parse_cached_graph_response(fixture.read_bytes())
    assert record.response_id == "cached-response-sig01-v1"
    assert record.trade_date == "2024-06-30"
