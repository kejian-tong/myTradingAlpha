"""Execute documented data examples against v1 validators, without model inference.

JSON examples are data only. No documentation code, model, provider, or broker runs.
The fixture is synthetic and does not establish historical source authenticity.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs/productionization"
FIXTURE = ROOT / "tests/productionization/fixtures/research/cached_graph_response_v1.json"


def _examples() -> dict:
    text = (DOCS / "03_CONTRACTS_AND_SCHEMAS.md").read_text(encoding="utf-8")
    match = re.search(r"<!-- sig01-response-examples -->\s*```json\n(.*?)\n```", text, re.S)
    assert match, "missing executable closed-response policy examples"
    assert len(match.group(1)) < 8192
    example = json.loads(match.group(1))
    assert set(example) == {"knowledge_cutoff", "message_representation", "cases"}
    return example


def test_examples_cover_both_policies_and_cutoff_edges() -> None:
    example = _examples()
    rows = example["cases"]
    assert len(rows) == 8
    assert {(row["policy"], row["case"]) for row in rows} == {
        (policy, case)
        for policy in ("availability", "archive_realistic")
        for case in ("before", "at_cutoff", "late_ingestion", "late_availability")
    }
    for row in rows:
        assert set(row) == {"policy", "case", "available_at", "ingested_at", "eligible"}
        assert type(row["eligible"]) is bool


@pytest.mark.parametrize("index", range(8))
def test_documented_response_eligibility_matches_existing_sealer_and_parser(index: int) -> None:
    example = _examples()
    row = example["cases"][index]
    from mytradingalpha.data.bundle import BundleReplayPolicy
    from mytradingalpha.research.cached_response import (
        CachedGraphResponseUnavailableError,
        build_cached_graph_response,
        parse_cached_graph_response,
    )

    fixture = json.loads(FIXTURE.read_bytes())
    assert example["knowledge_cutoff"] == fixture["knowledge_cutoff"]
    payload = {key: value for key, value in fixture.items()
               if key not in {"response_hash", "output_hash"}}
    payload["replay_policy"] = BundleReplayPolicy(row["policy"])
    capture = payload["capture_manifest"]
    capture.update(available_at=row["available_at"], ingested_at=row["ingested_at"],
                   fetched_at=row["ingested_at"], published_at=row["available_at"],
                   event_time=row["available_at"])
    if row["eligible"]:
        raw = build_cached_graph_response(**payload)
        record = parse_cached_graph_response(raw)
        assert record.replay_policy is payload["replay_policy"]
        assert record.output == fixture["output"]
    else:
        with pytest.raises(CachedGraphResponseUnavailableError):
            build_cached_graph_response(**payload)


@pytest.mark.parametrize("as_object", [False, True])
def test_documented_message_representation_matches_plain_data_validator(as_object: bool) -> None:
    assert _examples()["message_representation"] == "plain_json"
    from langchain_core.messages import AIMessage
    from tradingagents.graph.historical import (
        HistoricalRuntimeOutputError,
        validate_historical_response,
    )

    fixture = json.loads(FIXTURE.read_bytes())
    output = copy.deepcopy(fixture["output"])
    bindings = {"company_name": fixture["ticker"], "trade_date": fixture["trade_date"],
                "asset_type": fixture["asset_type"], "instrument_context": fixture["instrument_context"]}
    if as_object:
        output["messages"][0] = AIMessage(content="synthetic fixture, not an inference")
        with pytest.raises(HistoricalRuntimeOutputError, match="plain JSON"):
            validate_historical_response(output, **bindings)
    else:
        state, signal = validate_historical_response(output, **bindings)
        assert state == output
        assert signal == "Hold"


def test_overviews_do_not_reintroduce_superseded_closed_replay_claims() -> None:
    architecture = (DOCS / "02_TARGET_ARCHITECTURE.md").read_text(encoding="utf-8")
    phase = (DOCS / "phases/02-evidence-agent-boundary/DESIGN.md").read_text(encoding="utf-8")
    contracts = (DOCS / "03_CONTRACTS_AND_SCHEMAS.md").read_text(encoding="utf-8")
    assert "No document in this set asserts that the target package currently exists" not in architecture
    assert "only cached responses in the bundle" not in architecture
    assert "scheduler captures the same inputs at the close" not in architecture
    assert "Supported concrete LangChain messages are checked as data" not in phase
    assert "The stricter\nresponse ingestion rule is not a change" not in contracts
