"""Pydantic-compatible scalar types shared by production contracts."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, TypeAdapter, WithJsonSchema

_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._:-]*[A-Za-z0-9])?$")
_DATETIME_ADAPTER = TypeAdapter(datetime)


def _validate_stable_id(value: Any) -> str:
    if not isinstance(value, str) or not _STABLE_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid_identifier: expected a non-whitespace stable token")
    return value


def _validate_utc_datetime(value: Any) -> datetime:
    if not isinstance(value, (datetime, str)):
        raise ValueError("invalid_timestamp: expected an aware datetime or ISO timestamp")

    try:
        parsed = _DATETIME_ADAPTER.validate_python(value)
    except Exception as exc:
        raise ValueError("invalid_timestamp: expected an aware datetime or ISO timestamp") from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_timestamp: naive datetimes are not supported")
    return parsed.astimezone(timezone.utc)


def _serialize_utc_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TypeError("cannot serialize a naive datetime as UtcDateTime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_decimal_string(value: Any) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError("invalid_decimal: float and bool inputs are not exact decimals")

    if isinstance(value, Decimal):
        decimal_value = value
    elif isinstance(value, int):
        decimal_value = Decimal(value)
    elif isinstance(value, str):
        if not value or value != value.strip():
            raise ValueError("invalid_decimal: expected a non-empty decimal string")
        try:
            decimal_value = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid_decimal: malformed decimal string") from exc
    else:
        raise ValueError("invalid_decimal: expected a string, integer, or Decimal")

    if not decimal_value.is_finite():
        raise ValueError("invalid_decimal: non-finite decimals are not supported")
    return decimal_value


def _serialize_decimal_string(value: Decimal) -> str:
    return str(value)


StableId = Annotated[
    str,
    BeforeValidator(_validate_stable_id),
    WithJsonSchema({"type": "string", "pattern": _STABLE_ID_PATTERN.pattern}),
]
"""A non-empty, whitespace-free identifier suitable for persisted keys."""

UtcDateTime = Annotated[
    datetime,
    BeforeValidator(_validate_utc_datetime),
    PlainSerializer(_serialize_utc_datetime, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time"}),
]
"""A timezone-aware datetime normalized to :data:`datetime.timezone.utc`."""

DecimalString = Annotated[
    Decimal,
    BeforeValidator(_validate_decimal_string),
    PlainSerializer(_serialize_decimal_string, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string"}),
]
"""A finite :class:`~decimal.Decimal` serialized as its decimal string."""


__all__ = ["DecimalString", "StableId", "UtcDateTime"]
