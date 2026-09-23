"""First-use SIG-03 shared wire contracts for deterministic quant signals."""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from .common import (
    CanonicalChecksum,
    StableId,
    UtcDateTime,
    datetime as _DateTime,
    timezone as _Timezone,
)
from .redaction import validate_artifact_text
from .schemas import ContractModel
from .versions import CURRENT_SCHEMA_VERSION

_SIGNAL_ID = re.compile(r"quant-signal:[0-9a-f]{64}")
_REASON_ORDER = (
    "instrument_not_in_bundle",
    "instrument_inactive_as_of",
    "instrument_not_in_universe",
    "ambiguous_universe_membership",
    "calendar_session_unavailable",
    "bar_series_ambiguous",
    "exact_session_bar_missing",
    "insufficient_lookback",
    "required_feature_missing",
    "optional_feature_missing",
)
HASH_DOMAIN_QUANT_SIGNAL = "mytradingalpha:sig03:quant-signal:v1\0"


def _prevalidate_sensitive(value: object, model_name: str) -> None:
    seen: set[int] = set()

    def walk(item: object, depth: int = 0) -> None:
        if depth > 64:
            raise ValueError
        if type(item) is str:
            if any(marker in item.casefold() for marker in ("api-key", "apikey", "credential", "password", "secret", "token")):
                raise ValueError
            try:
                if validate_artifact_text(item) != item:
                    raise ValueError
            except (TypeError, ValueError) as exc:
                raise ValueError from exc
            return
        if type(item) in (int, bool, type(None), Decimal):
            return
        if type(item) is _DateTime:
            if object.__getattribute__(item, "tzinfo") is not _Timezone.utc:
                raise ValueError
            return
        if type(item) in (QuantSignalStatus, QuantSignalReasonCode):
            return
        if type(item) in (dict, list, tuple):
            identity = id(item)
            if identity in seen:
                raise ValueError
            seen.add(identity)
            try:
                if type(item) is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            raise ValueError
                        walk(key, depth + 1)
                        walk(child, depth + 1)
                else:
                    for child in item:
                        walk(child, depth + 1)
            finally:
                seen.remove(identity)
            return
        if type(item) is QuantSignal:
            storage = object.__getattribute__(item, "__dict__")
            if type(storage) is not dict:
                raise ValueError
            walk(storage, depth + 1)
            return
        raise ValueError

    try:
        walk(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError.from_exception_data(
            model_name,
            [{"type": "value_error", "loc": (), "input": None, "ctx": {"error": ValueError("artifact text is not safe")}}],
        ) from exc


class QuantSignalStatus(str, Enum):
    """Stable signal outcome values."""

    VALID = "valid"
    DEGRADED = "degraded"
    INVALID = "invalid"


class QuantSignalReasonCode(str, Enum):
    """Stable, bounded SIG-03 reason wires."""

    INSTRUMENT_NOT_IN_BUNDLE = "instrument_not_in_bundle"
    INSTRUMENT_INACTIVE_AS_OF = "instrument_inactive_as_of"
    INSTRUMENT_NOT_IN_UNIVERSE = "instrument_not_in_universe"
    AMBIGUOUS_UNIVERSE_MEMBERSHIP = "ambiguous_universe_membership"
    CALENDAR_SESSION_UNAVAILABLE = "calendar_session_unavailable"
    BAR_SERIES_AMBIGUOUS = "bar_series_ambiguous"
    EXACT_SESSION_BAR_MISSING = "exact_session_bar_missing"
    INSUFFICIENT_LOOKBACK = "insufficient_lookback"
    REQUIRED_FEATURE_MISSING = "required_feature_missing"
    OPTIONAL_FEATURE_MISSING = "optional_feature_missing"


def _exact_tuple(value: object) -> tuple[object, ...]:
    if type(value) not in (tuple, list):
        raise ValueError("signal collections require a plain sequence")
    return tuple(value)


def _fixed_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("signal score must be a finite Decimal")
    if value.as_tuple().exponent != -12:
        raise ValueError("signal score must use exactly twelve decimal places")
    return value


class QuantSignal(ContractModel):
    """Immutable shadow-only deterministic signal wire."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    signal_id: StableId
    run_id: StableId
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    instrument_id: StableId
    as_of: UtcDateTime
    horizon_sessions: StrictInt = Field(ge=1, le=252)
    score: Decimal | None
    decimal_places: Literal[12]
    feature_ids: tuple[StableId, ...]
    feature_schema_hash: CanonicalChecksum
    feature_config_hash: CanonicalChecksum
    feature_hash: CanonicalChecksum
    model_id: StableId
    model_version: StableId
    model_hash: CanonicalChecksum
    missing_required_feature_ids: tuple[StableId, ...]
    missing_optional_feature_ids: tuple[StableId, ...]
    status: QuantSignalStatus
    reason_codes: tuple[QuantSignalReasonCode, ...]
    shadow_only: StrictBool
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> QuantSignal:
        if type(obj) not in (dict, cls):
            raise ValueError("QuantSignal requires exact plain data")
        _prevalidate_sensitive(obj, cls.__name__)
        if type(obj) is cls:
            storage = object.__getattribute__(obj, "__dict__")
            if type(storage) is not dict:
                raise ValueError("QuantSignal storage must be plain data")
            obj = dict(storage)
        return super().model_validate(obj, *args, **kwargs)

    @field_validator(
        "feature_ids",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        mode="before",
    )
    @classmethod
    def validate_id_sequences(cls, value: object) -> tuple[object, ...]:
        return _exact_tuple(value)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def validate_reason_sequence(cls, value: object) -> tuple[object, ...]:
        return _exact_tuple(value)

    @field_validator("signal_id", mode="before")
    @classmethod
    def validate_signal_id(cls, value: object) -> str:
        if type(value) is not str or _SIGNAL_ID.fullmatch(value) is None:
            raise ValueError("signal_id must be quant-signal plus a lowercase SHA-256")
        return value

    @field_validator("score")
    @classmethod
    def validate_score_scale(cls, value: Decimal | None) -> Decimal | None:
        return _fixed_decimal(value)

    @field_validator("score", mode="before")
    @classmethod
    def reject_inexact_score_input(cls, value: object) -> object:
        if value is None:
            return None
        if type(value) in (bool, float) or not (type(value) is Decimal or type(value) in (int, str)):
            raise ValueError("signal score requires an exact decimal input")
        return value

    @model_validator(mode="after")
    def validate_signal(self) -> QuantSignal:
        if self.shadow_only is not True:
            raise ValueError("QuantSignal is shadow-only")
        if tuple(self.feature_ids) != tuple(sorted(self.feature_ids)):
            raise ValueError("feature_ids must be canonical and sorted")
        if len(set(self.feature_ids)) != len(self.feature_ids):
            raise ValueError("feature_ids must be unique")
        for values in (
            self.missing_required_feature_ids,
            self.missing_optional_feature_ids,
        ):
            if tuple(values) != tuple(sorted(values)) or len(set(values)) != len(values):
                raise ValueError("missing feature identifiers must be canonical")
        reason_values = tuple(item.value for item in self.reason_codes)
        if reason_values != tuple(sorted(reason_values, key=_REASON_ORDER.index)):
            raise ValueError("reason_codes must use stable canonical ordering")
        if len(set(reason_values)) != len(reason_values):
            raise ValueError("reason_codes must be unique")
        if self.status is QuantSignalStatus.VALID:
            if (
                self.score is None
                or self.reason_codes
                or self.missing_required_feature_ids
                or self.missing_optional_feature_ids
            ):
                raise ValueError("valid signals require a score and no reasons")
        elif self.status is QuantSignalStatus.DEGRADED:
            if (
                self.score is None
                or not self.missing_optional_feature_ids
                or self.missing_required_feature_ids
                or not self.reason_codes
                or QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING not in self.reason_codes
            ):
                raise ValueError("degraded signals require optional missingness")
        elif self.score is not None or not self.reason_codes:
            raise ValueError("invalid signals require a reason and no score")
        payload = self.model_dump(mode="json")
        payload.pop("signal_id", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        expected_id = f"quant-signal:{hashlib.sha256(HASH_DOMAIN_QUANT_SIGNAL.encode() + encoded).hexdigest()}"
        if self.signal_id != expected_id:
            raise ValueError("signal_id does not match canonical signal payload")
        return self


__all__ = ["HASH_DOMAIN_QUANT_SIGNAL", "QuantSignal", "QuantSignalReasonCode", "QuantSignalStatus"]
