"""Stable reason codes for foundation contract and schema failures."""

from enum import Enum


class FoundationReasonCode(str, Enum):
    """Machine-readable failures shared by the foundation contract boundary."""

    MISSING_SCHEMA_VERSION = "missing_schema_version"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    INVALID_IDENTIFIER = "invalid_identifier"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_TIME_ORDER = "invalid_time_order"
    INVALID_DECIMAL = "invalid_decimal"
    MIGRATION_UNAVAILABLE = "migration_unavailable"


__all__ = ["FoundationReasonCode"]
