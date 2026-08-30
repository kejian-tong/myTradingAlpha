"""Contract tests for the immutable, versioned RunContext."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from mytradingalpha.contracts import Mode, RunContext

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "run_context_v1.json"


def _context_payload() -> dict[str, object]:
    return {
        "schema_version": "v1",
        "run_id": "run-2026-01-15-001",
        "mode": "historical",
        "variant_id": "quant_only_v1",
        "decision_time": "2026-01-15T21:00:00Z",
        "knowledge_cutoff": "2026-01-15T21:00:00Z",
        "earliest_execution_time": "2026-01-16T14:30:00Z",
        "bundle_id": "bundle-2026-01-15-001",
        "bundle_hash": "sha256:0123456789abcdef",
        "calendar_id": "XNYS-regular-v1",
    }


def test_run_context_accepts_v1_and_defaults_base_currency() -> None:
    context = RunContext.model_validate(_context_payload())

    assert context.schema_version == "v1"
    assert context.mode is Mode.HISTORICAL
    assert context.base_currency == "USD"
    assert context.knowledge_cutoff == context.decision_time


@pytest.mark.parametrize("mode", [Mode.HISTORICAL, Mode.FORWARD_PAPER, Mode.LIVE_PILOT])
def test_run_context_supports_only_stable_modes(mode: Mode) -> None:
    payload = _context_payload()
    payload["mode"] = mode

    assert RunContext.model_validate(payload).mode is mode


@pytest.mark.parametrize("schema_version", [None, "", "v0", "v2", 1])
def test_run_context_requires_exact_schema_version(schema_version: object) -> None:
    payload = _context_payload()
    if schema_version is None:
        del payload["schema_version"]
    else:
        payload["schema_version"] = schema_version

    with pytest.raises(ValidationError):
        RunContext.model_validate(payload)


def test_run_context_normalizes_all_aware_timestamps_to_utc() -> None:
    payload = _context_payload()
    payload.update(
        decision_time="2026-01-15T16:00:00-05:00",
        knowledge_cutoff="2026-01-15T16:00:00-05:00",
        earliest_execution_time="2026-01-16T09:30:00-05:00",
    )

    context = RunContext.model_validate(payload)

    assert context.decision_time == datetime(2026, 1, 15, 21, tzinfo=timezone.utc)
    assert context.knowledge_cutoff == context.decision_time
    assert context.earliest_execution_time == datetime(2026, 1, 16, 14, 30, tzinfo=timezone.utc)
    assert all(
        timestamp.tzinfo == timezone.utc
        for timestamp in (
            context.decision_time,
            context.knowledge_cutoff,
            context.earliest_execution_time,
        )
    )


@pytest.mark.parametrize(
    ("knowledge_cutoff", "decision_time", "earliest_execution_time"),
    [
        ("2026-01-15T21:01:00Z", "2026-01-15T21:00:00Z", "2026-01-16T14:30:00Z"),
        ("2026-01-15T21:00:00Z", "2026-01-15T21:00:00Z", "2026-01-15T21:00:00Z"),
    ],
)
def test_run_context_rejects_invalid_time_order(
    knowledge_cutoff: str, decision_time: str, earliest_execution_time: str
) -> None:
    payload = _context_payload()
    payload.update(
        knowledge_cutoff=knowledge_cutoff,
        decision_time=decision_time,
        earliest_execution_time=earliest_execution_time,
    )

    with pytest.raises(ValidationError):
        RunContext.model_validate(payload)


def test_run_context_rejects_naive_timestamps() -> None:
    payload = _context_payload()
    payload["decision_time"] = "2026-01-15T21:00:00"

    with pytest.raises(ValidationError):
        RunContext.model_validate(payload)


def test_run_context_is_frozen_and_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RunContext.model_validate({**_context_payload(), "unexpected": "field"})

    context = RunContext.model_validate(_context_payload())
    with pytest.raises(ValidationError):
        context.run_id = "run-2"


def test_run_context_schema_snapshot_is_normalized_and_path_independent() -> None:
    actual = RunContext.model_json_schema()
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    assert actual == expected
    serialized = json.dumps(actual)
    assert "/Users/" not in serialized
    assert "/private/tmp/" not in serialized


def test_mode_is_a_lowercase_string_enum() -> None:
    assert [member.value for member in Mode] == ["historical", "forward_paper", "live_pilot"]
