"""Focused tests for the shared scalar contract types."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from mytradingalpha.contracts import DecimalString, StableId, UtcDateTime


class _ScalarContract(BaseModel):
    identifier: StableId
    timestamp: UtcDateTime
    amount: DecimalString


@pytest.mark.parametrize(
    "value",
    ["", " ", " run-1", "run-1 ", "run id", "run/id", "run@id", "\trun-1"],
)
def test_stable_id_rejects_empty_whitespace_and_unstable_values(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(StableId).validate_python(value)


@pytest.mark.parametrize("value", [None, True, 1, 1.0, object()])
def test_stable_id_accepts_strings_only(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(StableId).validate_python(value)


def test_stable_id_accepts_practical_token_characters() -> None:
    value = "run-2026.01:close_variant_1"

    assert TypeAdapter(StableId).validate_python(value) == value


def test_utc_datetime_rejects_naive_values_and_normalizes_offsets() -> None:
    offset_value = datetime(2026, 1, 15, 10, 30, tzinfo=timezone(timedelta(hours=-5)))
    parsed = TypeAdapter(UtcDateTime).validate_python(offset_value)
    parsed_from_string = TypeAdapter(UtcDateTime).validate_python(
        "2026-01-15T10:30:00-05:00"
    )

    assert parsed == datetime(2026, 1, 15, 15, 30, tzinfo=timezone.utc)
    assert parsed_from_string == parsed
    assert parsed.tzinfo == timezone.utc

    with pytest.raises(ValidationError):
        TypeAdapter(UtcDateTime).validate_python(datetime(2026, 1, 15, 10, 30))
    with pytest.raises(ValidationError):
        TypeAdapter(UtcDateTime).validate_python("2026-01-15T10:30:00")


def test_utc_datetime_json_serialization_is_explicitly_utc() -> None:
    value = _ScalarContract(
        identifier="run-1",
        timestamp="2026-01-15T10:30:00-05:00",
        amount="1.20",
    )

    assert value.model_dump(mode="json")["timestamp"] == "2026-01-15T15:30:00Z"
    assert '"timestamp":"2026-01-15T15:30:00Z"' in value.model_dump_json()


@pytest.mark.parametrize("value", [True, False, 1.25, float("nan"), float("inf")])
def test_decimal_string_rejects_bool_float_and_non_exact_values(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(DecimalString).validate_python(value)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", Decimal("sNaN")])
def test_decimal_string_rejects_non_finite_decimals(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(DecimalString).validate_python(value)


def test_decimal_string_accepts_exact_inputs_and_serializes_as_string() -> None:
    value = _ScalarContract(identifier="run-1", timestamp="2026-01-15T15:30:00Z", amount="1.20")
    from_decimal = _ScalarContract(
        identifier="run-1", timestamp="2026-01-15T15:30:00Z", amount=Decimal("1.20")
    )
    from_integer = _ScalarContract(
        identifier="run-1", timestamp="2026-01-15T15:30:00Z", amount=7
    )

    assert value.amount == Decimal("1.20")
    assert from_decimal.amount == Decimal("1.20")
    assert from_integer.amount == Decimal("7")
    assert value.model_dump(mode="json")["amount"] == "1.20"
    assert from_decimal.model_dump_json().find('"amount":"1.20"') >= 0
