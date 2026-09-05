"""Typed input failures at UTC and persisted raw-manifest boundaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import UtcDateTime
from mytradingalpha.data.capture import CaptureClient
from mytradingalpha.data.raw_store import RawStore, RawStoreCorruptionError


@pytest.mark.parametrize(
    "value",
    [
        "0001-01-01T00:00:00+00:01",
        "9999-12-31T23:59:59-00:01",
        datetime(1, 1, 1, tzinfo=timezone(timedelta(minutes=1))),
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(minutes=-1))),
    ],
)
def test_utc_normalization_overflow_is_a_validation_error(value: object) -> None:
    with pytest.raises(ValidationError, match="invalid_timestamp"):
        TypeAdapter(UtcDateTime).validate_python(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0001-01-01T00:00:00Z", "0001-01-01T00:00:00Z"),
        ("9999-12-31T23:59:59.999999Z", "9999-12-31T23:59:59.999999Z"),
        ("0001-01-01T00:01:00+00:01", "0001-01-01T00:00:00Z"),
        ("9999-12-31T23:58:59.999999-00:01", "9999-12-31T23:59:59.999999Z"),
        ("2026-09-05T19:30:00.123456+05:30", "2026-09-05T14:00:00.123456Z"),
    ],
)
def test_representable_utc_boundaries_preserve_the_exact_instant(
    value: str, expected: str
) -> None:
    adapter = TypeAdapter(UtcDateTime)
    parsed = adapter.validate_python(value)
    assert parsed.tzinfo is timezone.utc
    assert adapter.dump_json(parsed) == f'"{expected}"'.encode()


@pytest.mark.parametrize(
    "corrupt_bytes",
    [b"[" * 12000 + b"0" + b"]" * 12000, b"{", b"[]"],
    ids=["deep-json", "incomplete-object", "wrong-root"],
)
def test_raw_store_classifies_corrupt_json_and_remains_usable(
    tmp_path: Path, corrupt_bytes: bytes
) -> None:
    captured = CaptureClient().capture(
        b"synthetic-input-boundary-canary",
        schema_version="v1",
        manifest_id="input-boundary-canary",
        source="synthetic",
        source_locator="fixture://input-boundary/canary",
        fetched_at="2026-01-15T21:00:00Z",
        event_time=None,
        published_at=None,
        available_at="2026-01-15T21:00:00Z",
        ingested_at="2026-01-15T21:00:00Z",
        terms="synthetic-only",
        revision=0,
    )
    store = RawStore(tmp_path)
    store.put(captured)
    assert store.get(captured.manifest.manifest_id) == captured
    manifest_path = tmp_path / "manifests" / "input-boundary-canary.json"
    original = manifest_path.read_bytes()
    manifest_path.write_bytes(corrupt_bytes)
    with pytest.raises(RawStoreCorruptionError):
        store.get(captured.manifest.manifest_id)
    # Restoring this temporary fixture is not a production overwrite/recovery API.
    manifest_path.write_bytes(original)
    assert store.get(captured.manifest.manifest_id) == captured
