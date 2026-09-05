"""Regression contracts for audit A01/A02; no service or credential access."""

from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import UtcDateTime
from mytradingalpha.ops.logging import configure_logging


@pytest.mark.parametrize("managed_first", [False, True])
def test_external_handler_is_rejected_before_configuration_changes(managed_first: bool) -> None:
    logger = logging.Logger("audit-ownership")
    if managed_first:
        configure_logging(logger=logger, stream=io.StringIO())
    external_stream = io.StringIO()
    external = logging.StreamHandler(external_stream)
    logger.addHandler(external)
    before = (list(logger.handlers), logger.level, logger.propagate)
    destination = io.StringIO()

    with pytest.raises(ValueError, match="dedicated logger"):
        configure_logging(logger=logger, stream=destination)

    assert (logger.handlers, logger.level, logger.propagate) == before
    assert external_stream.getvalue() == destination.getvalue() == ""
    assert not any(handler._closed for handler in logger.handlers)


def test_dedicated_logger_reconfiguration_remains_idempotent_and_redacted() -> None:
    logger = logging.Logger("audit-dedicated")
    first, second = io.StringIO(), io.StringIO()
    configure_logging(logger=logger, stream=first)
    old = logger.handlers[0]
    configure_logging(logger=logger, stream=second)
    logger.info("api_key=%s count=%d", "AUDIT_CANARY_NOT_A_SECRET", 2)

    assert old._closed
    assert len(logger.handlers) == 1
    assert first.getvalue() == ""
    assert "AUDIT_CANARY_NOT_A_SECRET" not in second.getvalue()
    assert json.loads(second.getvalue())["message"] == "api_key=[REDACTED] count=2"
    assert logger.propagate is False


@pytest.mark.parametrize("fraction", ["0000009", "1234567", "12345678", "123456789", "0000000"])
@pytest.mark.parametrize("offset", ["Z", "+00:00", "-05:00"])
def test_timestamp_rejects_more_than_six_fractional_digits(fraction: str, offset: str) -> None:
    # Even extra zero digits are outside the explicitly microsecond wire grammar.
    with pytest.raises(ValidationError, match="invalid_timestamp"):
        TypeAdapter(UtcDateTime).validate_python(f"2024-06-30T23:59:59.{fraction}{offset}")


@pytest.mark.parametrize("fraction", ["", ".1", ".12", ".123", ".1234", ".12345", ".123456"])
def test_supported_timestamp_precision_round_trips_without_loss(fraction: str) -> None:
    adapter = TypeAdapter(UtcDateTime)
    parsed = adapter.validate_python(f"2024-06-30T18:59:59{fraction}-05:00")
    microseconds = int(fraction.removeprefix(".").ljust(6, "0"))
    assert parsed == datetime(2024, 6, 30, 23, 59, 59, microseconds, tzinfo=timezone.utc)
    assert parsed.tzinfo is timezone.utc
    assert adapter.validate_json(adapter.dump_json(parsed)) == parsed


def test_microsecond_cutoff_order_is_preserved() -> None:
    adapter = TypeAdapter(UtcDateTime)
    cutoff = adapter.validate_python("2024-06-30T23:59:59.000001Z")
    assert adapter.validate_python("2024-06-30T23:59:59Z") < cutoff
    assert adapter.validate_python("2024-06-30T23:59:59.000001+00:00") == cutoff
    assert adapter.validate_python("2024-06-30T23:59:59.000002Z") > cutoff
