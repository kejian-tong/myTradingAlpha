"""First-use SIG-03 shared wire contracts for deterministic quant signals."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from contextlib import suppress
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
_CANONICAL_CHECKSUM = re.compile(r"sha256:[0-9a-f]{64}")
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
MAX_FEATURES = 32
MAX_IDENTIFIER_LENGTH = 128
MAX_CANONICAL_BYTES = 1_048_576
MAX_NESTING_DEPTH = 64
_DIRECT_SENSITIVE_WORDS = (
    "api-key",
    "apikey",
    "credential",
    "password",
    "secret",
    "token",
    "private-key",
    "privatekey",
)
_DECODED_SENSITIVE_WORDS = (
    *_DIRECT_SENSITIVE_WORDS,
    "api-secret",
    "access-token",
    "bearer",
    "authorization",
    "auth-token",
    "aws-access-key-id",
    "aws-secret-access-key",
    "broker-account-id",
    "brokeraccountid",
    "client-secret",
    "consumer-secret",
    "account-number",
    "account-id",
    "refresh-token",
    "session-token",
    "source-locator",
    "terms",
)
_AWS_ACCESS_KEY = re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")
_SK_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{8,}")
_BASE64 = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")
_HEX = re.compile(r"[0-9A-Fa-f]+")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")
_PERCENT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2}){5,}")
_UNICODE_RUN = re.compile(r"(?:\\u[0-9A-Fa-f]{4}){5,}")
_HEX_RUN = re.compile(r"[0-9A-Fa-f]{10,}")
_MAX_DECODE_CANDIDATES = 100_000
_MAX_IDENTIFIER_DECODE_ATTEMPTS = 6_000
_MAX_PREVALIDATION_DECODE_ATTEMPTS = 4_096


class _DecodeBudget:
    __slots__ = ("attempts", "limit", "memo")

    def __init__(self, limit: int) -> None:
        self.attempts = 0
        self.limit = limit
        self.memo: dict[str, bool] = {}

    def consume(self) -> None:
        if self.attempts >= self.limit:
            raise ValueError("identifier decode work exceeds bound")
        self.attempts += 1


def _new_sensitive_prevalidation_budget() -> _DecodeBudget:
    return _DecodeBudget(_MAX_PREVALIDATION_DECODE_ATTEMPTS)


def _compact_text_is_sensitive(
    value: str,
    *,
    markers: tuple[str, ...] = _DIRECT_SENSITIVE_WORDS,
) -> bool:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    parts = tuple(re.findall(r"[a-z0-9]+", normalized))
    for marker in markers:
        marker_parts = tuple(re.findall(r"[a-z0-9]+", marker.casefold()))
        if marker_parts and any(
            parts[index : index + len(marker_parts)] == marker_parts
            for index in range(len(parts) - len(marker_parts) + 1)
        ):
            return True
    return False


def _artifact_text_is_sensitive(value: str) -> bool:
    try:
        if validate_artifact_text(value) != value:
            return True
    except (TypeError, ValueError):
        return True
    if _AWS_ACCESS_KEY.search(value):
        return True
    return _compact_text_is_sensitive(value)


def _decoded_artifact_is_sensitive(value: str) -> bool:
    redaction_rejected = False
    try:
        redaction_rejected = validate_artifact_text(value) != value
    except (TypeError, ValueError):
        redaction_rejected = True
    return redaction_rejected and (
        _AWS_ACCESS_KEY.search(value) is not None
        or _SK_TOKEN.search(value) is not None
        or _compact_text_is_sensitive(value, markers=_DECODED_SENSITIVE_WORDS)
    )


def _decoded_candidate_is_relevant(value: str) -> bool:
    if not value or not value.isprintable():
        return False
    if _AWS_ACCESS_KEY.search(value) or _compact_text_is_sensitive(
        value, markers=_DECODED_SENSITIVE_WORDS
    ):
        return True
    if re.fullmatch(r"[a-z][a-z0-9]*(?:[-._:][a-z0-9]+)+", value):
        return False
    return bool(
        (len(value) >= 7 and _BASE64.fullmatch(value))
        or _PERCENT_RUN.fullmatch(value)
        or _UNICODE_RUN.fullmatch(value)
        or _HEX_RUN.fullmatch(value)
    )


def _decoded_text_is_candidate(value: str) -> bool:
    if not value or not value.isascii() or not value.isprintable():
        return False
    normalized = unicodedata.normalize("NFKC", value)
    if any(character in normalized for character in '{}[]"'):
        try:
            json.loads(normalized)
        except (TypeError, ValueError):
            return False
    return True


def _decoded_identifier_candidates(
    value: str,
    budget: _DecodeBudget,
) -> tuple[str, ...]:
    candidates: list[str] = []

    def append_if_relevant(decoded: str) -> bool:
        if not decoded or not decoded.isprintable():
            return False
        if _decoded_artifact_is_sensitive(decoded):
            candidates.append(decoded)
            return True
        if not _decoded_text_is_candidate(decoded):
            return False
        if _decoded_candidate_is_relevant(decoded):
            candidates.append(decoded)
        return False

    for match in _PERCENT_RUN.finditer(value):
        encoded = match.group(0)
        budget.consume()
        with suppress(UnicodeDecodeError, ValueError):
            decoded = bytes(
                    int(encoded[index + 1 : index + 3], 16)
                    for index in range(0, len(encoded), 3)
                ).decode("utf-8")
            if append_if_relevant(decoded):
                return tuple(dict.fromkeys(candidates))
    for match in _UNICODE_RUN.finditer(value):
        encoded = match.group(0)
        budget.consume()
        with suppress(ValueError):
            decoded = "".join(
                    chr(int(encoded[index + 2 : index + 6], 16))
                    for index in range(0, len(encoded), 6)
                )
            if append_if_relevant(decoded):
                return tuple(dict.fromkeys(candidates))
    for match in _BASE64_RUN.finditer(value):
        run = match.group(0).rstrip("=")
        if re.fullmatch(r"[a-z][a-z0-9_-]*", run):
            continue
        if len(run) >= 7 and len(run) % 4 != 1:
            budget.consume()
            padded_run = run + "=" * (-len(run) % 4)
            try:
                decoded_run = base64.b64decode(
                    padded_run.encode("ascii"), altchars=b"-_", validate=True
                ).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                decoded_run = None
            if decoded_run is not None:
                candidate_count = len(candidates)
                if append_if_relevant(decoded_run):
                    return tuple(dict.fromkeys(candidates))
                if len(candidates) > candidate_count:
                    return tuple(dict.fromkeys(candidates))
                if (
                    _decoded_text_is_candidate(decoded_run)
                    and not _decoded_candidate_is_relevant(decoded_run)
                ):
                    continue
        for start in range(len(run)):
            for end in range(start + 7, len(run) + 1):
                if start == 0 and end == len(run):
                    continue
                encoded = run[start:end]
                if len(encoded) % 4 == 1 or _BASE64.fullmatch(encoded) is None:
                    continue
                budget.consume()
                padded = encoded + "=" * (-len(encoded) % 4)
                with suppress(UnicodeDecodeError, ValueError):
                    decoded = base64.b64decode(
                            padded.encode("ascii"), altchars=b"-_", validate=True
                        ).decode("utf-8")
                    if append_if_relevant(decoded):
                        return tuple(dict.fromkeys(candidates))
    for match in _HEX_RUN.finditer(value):
        run = match.group(0)
        if len(run) % 2 == 0:
            budget.consume()
            try:
                decoded_run = bytes.fromhex(run).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                decoded_run = None
            if decoded_run is not None:
                candidate_count = len(candidates)
                if append_if_relevant(decoded_run):
                    return tuple(dict.fromkeys(candidates))
                if len(candidates) > candidate_count:
                    return tuple(dict.fromkeys(candidates))
                if (
                    _decoded_text_is_candidate(decoded_run)
                    and not _decoded_candidate_is_relevant(decoded_run)
                ):
                    continue
        for start in range(len(run)):
            for end in range(start + 10, len(run) + 1):
                if start == 0 and end == len(run):
                    continue
                encoded = run[start:end]
                if len(encoded) % 2 != 0 or _HEX.fullmatch(encoded) is None:
                    continue
                budget.consume()
                with suppress(UnicodeDecodeError, ValueError):
                    decoded = bytes.fromhex(encoded).decode("utf-8")
                    if append_if_relevant(decoded):
                        return tuple(dict.fromkeys(candidates))
    return tuple(dict.fromkeys(candidates))


def _identifier_contains_sensitive_candidate(
    value: str,
    budget: _DecodeBudget,
) -> bool:
    try:
        if validate_artifact_text(value) != value:
            return True
    except (TypeError, ValueError):
        return True
    if _SIGNAL_ID.fullmatch(value) or _CANONICAL_CHECKSUM.fullmatch(value):
        return False
    pending = [value]
    seen: set[str] = set()
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        if len(seen) > _MAX_DECODE_CANDIDATES:
            return True
        if _artifact_text_is_sensitive(candidate):
            return True
        for decoded in _decoded_identifier_candidates(candidate, budget):
            if _artifact_text_is_sensitive(decoded):
                return True
            try:
                encoded = decoded.encode("utf-8", "strict")
            except UnicodeError:
                continue
            if (
                not encoded
                or len(encoded) > MAX_IDENTIFIER_LENGTH
                or decoded == candidate
                or len(decoded) >= len(candidate)
            ):
                continue
            pending.append(decoded)
    return False


def validate_sig03_identifier(
    value: object,
    *,
    _decode_budget: _DecodeBudget | None = None,
) -> str:
    """Validate one bounded identifier without echoing hostile or secret input."""

    if type(value) is not str:
        raise ValueError("identifier requires an exact string")
    if not value or len(value) > MAX_IDENTIFIER_LENGTH:
        raise ValueError("identifier exceeds SIG-03 bound")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("identifier is not artifact-safe") from exc
    if len(encoded) > MAX_IDENTIFIER_LENGTH:
        raise ValueError("identifier exceeds SIG-03 bound")
    budget = _decode_budget or _DecodeBudget(_MAX_IDENTIFIER_DECODE_ATTEMPTS)
    cached = budget.memo.get(value)
    if cached is None:
        cached = _identifier_contains_sensitive_candidate(value, budget)
        budget.memo[value] = cached
    if cached:
        raise ValueError("identifier is not artifact-safe")
    return value


def _validation_error(model_name: str) -> ValidationError:
    return ValidationError.from_exception_data(
        model_name,
        [
            {
                "type": "value_error",
                "loc": (),
                "input": None,
                "ctx": {"error": ValueError("artifact input is invalid")},
            }
        ],
    )


def _plain_mapping(
    value: object,
    *,
    model_name: str,
    allowed_fields: tuple[str, ...],
) -> dict[str, object]:
    if type(value) is not dict:
        raise _validation_error(model_name)
    keys = tuple(dict.keys(value))
    if len(keys) > len(allowed_fields) or any(type(key) is not str for key in keys):
        raise _validation_error(model_name)
    allowed = set(allowed_fields)
    if any(key not in allowed for key in keys):
        raise _validation_error(model_name)
    return {key: dict.__getitem__(value, key) for key in keys}


def _prevalidate_sensitive(value: object, model_name: str) -> None:
    seen: set[int] = set()
    budget = _new_sensitive_prevalidation_budget()

    def walk(item: object, depth: int = 0) -> None:
        if depth > MAX_NESTING_DEPTH:
            raise ValueError
        if type(item) is str:
            validate_sig03_identifier(item, _decode_budget=budget)
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
                    keys = tuple(dict.keys(item))
                    if len(keys) > 64 or any(type(key) is not str for key in keys):
                        raise ValueError
                    for key in keys:
                        walk(key, depth + 1)
                        walk(dict.__getitem__(item, key), depth + 1)
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
        raise _validation_error(model_name) from exc


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
    if len(value) > MAX_FEATURES:
        raise ValueError("signal collection exceeds SIG-03 bound")
    return tuple(value)


def _fixed_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("signal score must be a finite Decimal")
    if value.as_tuple().exponent != -12:
        raise ValueError("signal score must use exactly twelve decimal places")
    if not Decimal("-1.000000000000") <= value <= Decimal("1.000000000000"):
        raise ValueError("signal score exceeds fixed range")
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
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> QuantSignal:
        if type(obj) not in (dict, cls):
            raise ValueError("QuantSignal requires exact plain data")
        return super().model_validate(obj, *args, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def require_bounded_plain_data(cls, value: object) -> object:
        if type(value) is cls:
            storage = object.__getattribute__(value, "__dict__")
            if type(storage) is not dict:
                raise ValueError("QuantSignal storage must be plain data")
            value = storage
        plain = _plain_mapping(
            value,
            model_name=cls.__name__,
            allowed_fields=tuple(cls.model_fields),
        )
        for field in (
            "feature_ids",
            "missing_required_feature_ids",
            "missing_optional_feature_ids",
            "reason_codes",
        ):
            if field in plain:
                collection = dict.__getitem__(plain, field)
                if type(collection) not in (tuple, list) or len(collection) > MAX_FEATURES:
                    raise _validation_error(cls.__name__)
        _prevalidate_sensitive(plain, cls.__name__)
        return plain

    @field_validator(
        "feature_ids",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        mode="before",
    )
    @classmethod
    def validate_id_sequences(cls, value: object) -> tuple[object, ...]:
        return _exact_tuple(value)

    @field_validator(
        "feature_ids",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
    )
    @classmethod
    def validate_bounded_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_sig03_identifier(item) for item in value)

    @field_validator("run_id", "bundle_id", "instrument_id", "model_id", "model_version")
    @classmethod
    def validate_scalar_ids(cls, value: str) -> str:
        return validate_sig03_identifier(value)

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
        feature_ids = set(self.feature_ids)
        missing_required = set(self.missing_required_feature_ids)
        missing_optional = set(self.missing_optional_feature_ids)
        if not missing_required.issubset(feature_ids) or not missing_optional.issubset(
            feature_ids
        ):
            raise ValueError("missing feature identifiers must belong to feature_ids")
        if missing_required & missing_optional:
            raise ValueError("required and optional missing feature sets must be disjoint")
        reason_values = tuple(item.value for item in self.reason_codes)
        if reason_values != tuple(sorted(reason_values, key=_REASON_ORDER.index)):
            raise ValueError("reason_codes must use stable canonical ordering")
        if len(set(reason_values)) != len(reason_values):
            raise ValueError("reason_codes must be unique")
        has_required_reason = (
            QuantSignalReasonCode.REQUIRED_FEATURE_MISSING in self.reason_codes
        )
        has_optional_reason = (
            QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING in self.reason_codes
        )
        if bool(missing_required) is not has_required_reason:
            raise ValueError("required missingness reason does not match missing set")
        if bool(missing_optional) is not has_optional_reason:
            raise ValueError("optional missingness reason does not match missing set")
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
                or self.reason_codes
                != (QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING,)
            ):
                raise ValueError("degraded signals require optional missingness")
        else:
            if self.score is not None or not self.reason_codes:
                raise ValueError("invalid signals require a reason and no score")
            global_invalid_reasons = {
                QuantSignalReasonCode.INSTRUMENT_NOT_IN_BUNDLE,
                QuantSignalReasonCode.INSTRUMENT_INACTIVE_AS_OF,
                QuantSignalReasonCode.INSTRUMENT_NOT_IN_UNIVERSE,
                QuantSignalReasonCode.AMBIGUOUS_UNIVERSE_MEMBERSHIP,
                QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
            }
            feature_invalid_reasons = {
                QuantSignalReasonCode.BAR_SERIES_AMBIGUOUS,
                QuantSignalReasonCode.EXACT_SESSION_BAR_MISSING,
                QuantSignalReasonCode.INSUFFICIENT_LOOKBACK,
            }
            has_global_invalid_reason = bool(
                global_invalid_reasons.intersection(self.reason_codes)
            )
            if (
                missing_optional
                and not missing_required
                and not has_global_invalid_reason
            ):
                raise ValueError("optional-only missingness cannot invalidate a signal")
            if (
                feature_invalid_reasons.intersection(self.reason_codes)
                and not (missing_required or missing_optional)
            ):
                raise ValueError(
                    "feature-level invalid reasons require required missingness"
                )
        payload = self.model_dump(mode="json")
        payload.pop("signal_id", None)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(HASH_DOMAIN_QUANT_SIGNAL.encode("utf-8") + encoded) > MAX_CANONICAL_BYTES:
            raise ValueError("canonical signal bytes exceed bound")
        expected_id = f"quant-signal:{hashlib.sha256(HASH_DOMAIN_QUANT_SIGNAL.encode() + encoded).hexdigest()}"
        if self.signal_id != expected_id:
            raise ValueError("signal_id does not match canonical signal payload")
        return self


__all__ = [
    "HASH_DOMAIN_QUANT_SIGNAL",
    "MAX_CANONICAL_BYTES",
    "MAX_FEATURES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_NESTING_DEPTH",
    "QuantSignal",
    "QuantSignalReasonCode",
    "QuantSignalStatus",
    "validate_sig03_identifier",
]
