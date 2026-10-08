"""First-use SIG-03 shared wire contracts for deterministic quant signals."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from contextlib import suppress
from decimal import (
    ROUND_HALF_EVEN,
    Context as _DecimalContext,
    Decimal,
    Inexact,
    Rounded,
    localcontext,
)
from enum import Enum
from typing import Literal

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    ValidationInfo,
    field_serializer,
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
from .research import (
    EvidenceCitation,
    EvidenceReference,
    ResearchNote,
    ResearchProvenance,
    ResearchSourceFields,
)
from .schemas import ContractModel, Mode, NetworkPolicy, RunContext
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
HASH_DOMAIN_LLM_OVERLAY = "mytradingalpha:sig04:llm-overlay:v1\0"
HASH_DOMAIN_SIGNAL_VARIANT = "mytradingalpha:sig05:signal-variant:v1\0"
HASH_DOMAIN_SIGNAL_ENVELOPE = "mytradingalpha:sig05:signal-envelope:v1\0"
MAX_FEATURES = 32
MAX_IDENTIFIER_LENGTH = 128
MAX_CANONICAL_BYTES = 1_048_576
MAX_NESTING_DEPTH = 64
MAX_LLM_OVERLAY_BYTES = 65_536
MAX_LLM_OVERLAY_EVIDENCE_IDS = 32
MAX_LLM_OVERLAY_RATIONALE_BYTES = 8_192
MAX_SIG05_CANONICAL_BYTES = 6_291_456
MAX_SIG05_DEPTH = 16
MAX_SIG05_NODES = 4_096
MAX_SIG05_SEQUENCE_ITEMS = 256
MAX_SIG05_TEXT_BYTES = 1_048_576
MAX_SIG05_INTEGER_BITS = 63
_LLM_OVERLAY_ID = re.compile(r"overlay:[0-9a-f]{64}")
_LLM_OVERLAY_DECIMAL = re.compile(r"(?:0|1|0\.(?:[0-9]{0,11}[1-9]))")
_SIG05_ENVELOPE_ID = re.compile(r"signal-envelope:[0-9a-f]{64}")
_SIG05_FIXED_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{24}")
_SIG05_SCALE = Decimal("0." + "0" * 23 + "1")
_SIG05_FIXED_ZERO = Decimal("0." + "0" * 24)
_SIG05_DECIMAL_QUANTA = tuple(Decimal(f"1E{exponent}") for exponent in range(-24, 1))
_SIG05_ZERO_REPRESENTATIONS = tuple(
    Decimal(f"{sign}0E{exponent}")
    for exponent in range(-24, 1)
    for sign in ("", "-")
)
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
_MAX_PREVALIDATION_DECODE_ATTEMPTS = 6_000
_VALIDATION_BUDGET_KEY = "sig03_decode_budget"
_VALIDATION_CONTEXT_MARKER = object()


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


def _is_internal_validation_context(context: object) -> bool:
    return (
        type(context) is dict
        and dict.get(context, _VALIDATION_CONTEXT_MARKER)
        is _VALIDATION_CONTEXT_MARKER
        and type(dict.get(context, _VALIDATION_BUDGET_KEY)) is _DecodeBudget
    )


def _new_sig03_validation_context(
    _caller_context: object = None,
) -> dict[object, object]:
    context: dict[object, object] = {}
    dict.__setitem__(
        context,
        _VALIDATION_CONTEXT_MARKER,
        _VALIDATION_CONTEXT_MARKER,
    )
    dict.__setitem__(
        context,
        _VALIDATION_BUDGET_KEY,
        _new_sensitive_prevalidation_budget(),
    )
    return context


def _decode_budget_from_context(context: object) -> _DecodeBudget:
    if _is_internal_validation_context(context):
        budget = dict.get(context, _VALIDATION_BUDGET_KEY)
        assert type(budget) is _DecodeBudget
        return budget
    return _new_sensitive_prevalidation_budget()


def _initialize_sig03_model(instance: object, data: dict[str, object]) -> None:
    type(instance).__pydantic_validator__.validate_python(  # type: ignore[attr-defined]
        data,
        self_instance=instance,
        context=_new_sig03_validation_context(),
    )


def _validate_sig03_model(
    model: type[object],
    value: object,
    *,
    strict: bool | None = None,
    extra: object = None,
    from_attributes: bool | None = None,
    context: object = None,
    by_alias: bool | None = None,
    by_name: bool | None = None,
) -> object:
    """Validate one public request without trusting or mutating caller context."""

    return _validate_sig03_model_with_context(
        model,
        value,
        strict=strict,
        extra=extra,
        from_attributes=from_attributes,
        context=_new_sig03_validation_context(context),
        by_alias=by_alias,
        by_name=by_name,
    )


def _validate_sig03_nested_model(
    model: type[object],
    value: object,
    *,
    context: object,
) -> object:
    """Reuse only a validation context created inside the current request."""

    if not _is_internal_validation_context(context):
        raise ValueError("nested SIG-03 validation requires private request context")
    return _validate_sig03_model_with_context(
        model,
        value,
        context=context,
    )


def _validate_sig03_model_with_context(
    model: type[object],
    value: object,
    *,
    strict: bool | None = None,
    extra: object = None,
    from_attributes: bool | None = None,
    context: object,
    by_alias: bool | None = None,
    by_name: bool | None = None,
) -> object:
    """Run the Pydantic validator with an already isolated request context."""

    if type(value) is model:
        storage = object.__getattribute__(value, "__dict__")
        if type(storage) is not dict:
            raise ValueError("SIG-03 model storage must be exact plain data")
        fields = tuple(model.model_fields)  # type: ignore[attr-defined]
        if dict.__len__(storage) != len(fields):
            raise ValueError("SIG-03 model storage must be exact plain data")
        keys = tuple(dict.keys(storage))
        if any(type(key) is not str for key in keys) or set(keys) != set(fields):
            raise ValueError("SIG-03 model storage must be exact plain data")
        value = {key: dict.__getitem__(storage, key) for key in keys}
    instance = object.__new__(model)
    return model.__pydantic_validator__.validate_python(  # type: ignore[attr-defined]
        value,
        strict=strict,
        extra=extra,
        from_attributes=from_attributes,
        context=context,
        by_alias=by_alias,
        by_name=by_name,
        self_instance=instance,
    )


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
    if dict.__len__(value) > len(allowed_fields):
        raise _validation_error(model_name)
    keys = tuple(dict.keys(value))
    if any(type(key) is not str for key in keys):
        raise _validation_error(model_name)
    allowed = set(allowed_fields)
    if any(key not in allowed for key in keys):
        raise _validation_error(model_name)
    return {key: dict.__getitem__(value, key) for key in keys}


def _prevalidate_sensitive(
    value: object,
    model_name: str,
    budget: _DecodeBudget,
) -> None:
    seen: set[int] = set()

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
                    if dict.__len__(item) > 64:
                        raise ValueError
                    keys = tuple(dict.keys(item))
                    if any(type(key) is not str for key in keys):
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

    def __init__(self, **data: object) -> None:
        _initialize_sig03_model(self, data)

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> QuantSignal:
        if type(obj) not in (dict, cls):
            raise ValueError("QuantSignal requires exact plain data")
        if args:
            raise TypeError("model_validate options must be keyword arguments")
        return _validate_sig03_model(cls, obj, **kwargs)  # type: ignore[return-value]

    @model_validator(mode="before")
    @classmethod
    def require_bounded_plain_data(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
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
        _prevalidate_sensitive(
            plain,
            cls.__name__,
            _decode_budget_from_context(info.context),
        )
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
    def validate_bounded_ids(
        cls,
        value: tuple[str, ...],
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        budget = _decode_budget_from_context(info.context)
        return tuple(
            validate_sig03_identifier(item, _decode_budget=budget) for item in value
        )

    @field_validator("run_id", "bundle_id", "instrument_id", "model_id", "model_version")
    @classmethod
    def validate_scalar_ids(cls, value: str, info: ValidationInfo) -> str:
        return validate_sig03_identifier(
            value,
            _decode_budget=_decode_budget_from_context(info.context),
        )

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


_LLM_OVERLAY_FIELDS = (
    "schema_version",
    "overlay_id",
    "note_id",
    "note_hash",
    "quant_signal_id",
    "run_id",
    "bundle_id",
    "bundle_hash",
    "instrument_id",
    "action",
    "abstain",
    "multiplier",
    "evidence_ids",
    "rationale",
    "model_id",
    "generated_at",
)
_LLM_OVERLAY_IDENTIFIER_FIELDS = (
    "overlay_id",
    "note_id",
    "quant_signal_id",
    "run_id",
    "bundle_id",
    "instrument_id",
    "model_id",
)
_LLM_OVERLAY_CHECKSUM_FIELDS = ("note_hash", "bundle_hash")


def _overlay_text(value: object, *, maximum: int) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise ValueError("overlay text is invalid")
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("overlay text is invalid") from exc
    if len(encoded) > maximum:
        raise ValueError("overlay text exceeds its bound")
    return value


def _overlay_plain_fields(value: object, model: type[object]) -> dict[str, object]:
    if type(value) is model:
        storage = object.__getattribute__(value, "__dict__")
    elif type(value) is dict:
        storage = value
    else:
        raise _validation_error(model.__name__)
    if type(storage) is not dict or dict.__len__(storage) != len(_LLM_OVERLAY_FIELDS):
        raise _validation_error(model.__name__)
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(_LLM_OVERLAY_FIELDS):
        raise _validation_error(model.__name__)
    plain = {field: dict.__getitem__(storage, field) for field in _LLM_OVERLAY_FIELDS}

    model_input = type(value) is model
    string_limits = {
        "schema_version": 16,
        "overlay_id": 72,
        "note_id": MAX_IDENTIFIER_LENGTH,
        "note_hash": 71,
        "quant_signal_id": MAX_IDENTIFIER_LENGTH,
        "run_id": MAX_IDENTIFIER_LENGTH,
        "bundle_id": MAX_IDENTIFIER_LENGTH,
        "bundle_hash": 71,
        "instrument_id": MAX_IDENTIFIER_LENGTH,
        "model_id": MAX_IDENTIFIER_LENGTH,
        "rationale": MAX_LLM_OVERLAY_RATIONALE_BYTES,
    }
    for field, maximum in string_limits.items():
        _overlay_text(plain[field], maximum=maximum)

    action = plain["action"]
    if action is not None and type(action) is not str:
        raise ValueError("overlay action is invalid")
    if action is not None and action not in {"attenuate", "veto"}:
        raise ValueError("overlay action is invalid")
    if type(plain["abstain"]) is not bool:
        raise ValueError("overlay abstain flag is invalid")

    multiplier = plain["multiplier"]
    if model_input:
        if type(multiplier) is not Decimal or not multiplier.is_finite():
            raise ValueError("overlay multiplier is invalid")
        multiplier_text = str(multiplier)
    else:
        multiplier_text = _overlay_text(multiplier, maximum=32)
    if _LLM_OVERLAY_DECIMAL.fullmatch(multiplier_text) is None:
        raise ValueError("overlay multiplier is not canonical")
    if not Decimal("0") <= Decimal(multiplier_text) <= Decimal("1"):
        raise ValueError("overlay multiplier is outside its bound")

    evidence_ids = plain["evidence_ids"]
    if type(evidence_ids) not in (list, tuple):
        raise ValueError("overlay evidence identifiers are invalid")
    if len(evidence_ids) > MAX_LLM_OVERLAY_EVIDENCE_IDS:
        raise ValueError("overlay evidence identifiers exceed their bound")
    safe_evidence_ids = tuple(
        _overlay_text(item, maximum=256) for item in evidence_ids
    )
    if tuple(sorted(safe_evidence_ids)) != safe_evidence_ids:
        raise ValueError("overlay evidence identifiers are not canonical")
    if len(set(safe_evidence_ids)) != len(safe_evidence_ids):
        raise ValueError("overlay evidence identifiers are duplicated")
    plain["evidence_ids"] = safe_evidence_ids if model_input else list(safe_evidence_ids)

    generated_at = plain["generated_at"]
    if model_input:
        if (
            type(generated_at) is not _DateTime
            or object.__getattribute__(generated_at, "tzinfo") is not _Timezone.utc
        ):
            raise ValueError("overlay timestamp is invalid")
        plain["generated_at"] = generated_at.isoformat().replace("+00:00", "Z")
    else:
        _overlay_text(generated_at, maximum=40)

    budget = _new_sensitive_prevalidation_budget()
    for field in _LLM_OVERLAY_IDENTIFIER_FIELDS:
        identifier = plain[field]
        if field == "overlay_id" and _LLM_OVERLAY_ID.fullmatch(identifier) is None:
            raise ValueError("overlay identifier is invalid")
        validate_sig03_identifier(identifier, _decode_budget=budget)
    for field in _LLM_OVERLAY_CHECKSUM_FIELDS:
        validate_sig03_identifier(plain[field], _decode_budget=budget)

    rationale = plain["rationale"]
    if _identifier_contains_sensitive_candidate(rationale, budget):
        raise ValueError("overlay rationale is not artifact safe")

    canonical_fields = dict(plain)
    canonical_fields["multiplier"] = multiplier_text
    canonical_fields["evidence_ids"] = list(safe_evidence_ids)
    try:
        encoded = json.dumps(
            canonical_fields,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise ValueError("overlay canonical bytes are invalid") from exc
    if len(HASH_DOMAIN_LLM_OVERLAY.encode("utf-8") + encoded) > MAX_LLM_OVERLAY_BYTES:
        raise ValueError("overlay canonical bytes exceed their bound")
    return plain


class LLMOverlay(ContractModel):
    """Immutable SIG-04 wire for one bounded, caller-supplied overlay candidate."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    overlay_id: StableId
    note_id: StableId
    note_hash: CanonicalChecksum
    quant_signal_id: StableId
    run_id: StableId
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    instrument_id: StableId
    action: Literal["attenuate", "veto"] | None
    abstain: StrictBool
    multiplier: Decimal
    evidence_ids: tuple[StableId, ...]
    rationale: str
    model_id: StableId
    generated_at: UtcDateTime
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @classmethod
    def model_validate_json(
        cls,
        json_data: object,
        *args: object,
        **kwargs: object,
    ) -> LLMOverlay:
        """Reject JSON before parsing; SIG-04 accepts only bounded plain mappings."""

        del json_data, args, kwargs
        raise ValueError("LLMOverlay accepts plain dictionary input only")

    @model_validator(mode="before")
    @classmethod
    def require_bounded_plain_data(cls, value: object) -> object:
        try:
            return _overlay_plain_fields(value, cls)
        except ValidationError:
            raise ValueError("overlay input is invalid") from None
        except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
            raise _validation_error(cls.__name__) from exc

    @field_validator(
        "schema_version",
        "overlay_id",
        "note_id",
        "note_hash",
        "quant_signal_id",
        "run_id",
        "bundle_id",
        "bundle_hash",
        "instrument_id",
        "model_id",
        "rationale",
        mode="before",
    )
    @classmethod
    def validate_exact_overlay_text(cls, value: object) -> str:
        if type(value) is not str:
            raise ValueError("overlay text requires an exact string")
        return value

    @field_validator("multiplier", mode="before")
    @classmethod
    def validate_exact_multiplier(cls, value: object) -> Decimal:
        if type(value) is Decimal:
            text = str(value)
        elif type(value) is str:
            text = value
        else:
            raise ValueError("overlay multiplier requires a canonical decimal string")
        if len(text) > 32 or _LLM_OVERLAY_DECIMAL.fullmatch(text) is None:
            raise ValueError("overlay multiplier is not canonical")
        return Decimal(text)

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def validate_evidence_sequence(cls, value: object) -> tuple[object, ...]:
        if type(value) not in (tuple, list) or len(value) > MAX_LLM_OVERLAY_EVIDENCE_IDS:
            raise ValueError("overlay evidence identifiers are invalid")
        result = tuple(value)
        if any(type(item) is not str for item in result):
            raise ValueError("overlay evidence identifiers require exact strings")
        return result

    @field_validator("generated_at", mode="before")
    @classmethod
    def validate_wire_timestamp(cls, value: object) -> object:
        if type(value) is str:
            return value
        if type(value) is _DateTime and object.__getattribute__(value, "tzinfo") is _Timezone.utc:
            return value
        raise ValueError("overlay timestamp requires an exact UTC value")

    @model_validator(mode="after")
    def validate_overlay(self) -> LLMOverlay:
        if len(self.evidence_ids) == 0:
            raise ValueError("overlay evidence identifiers cannot be empty")
        if tuple(self.evidence_ids) != tuple(sorted(self.evidence_ids)):
            raise ValueError("overlay evidence identifiers are not canonical")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("overlay evidence identifiers are duplicated")
        if self.action is None:
            if self.abstain is not True:
                raise ValueError("an overlay without an action must abstain")
        elif self.abstain is True:
            raise ValueError("an abstaining overlay cannot carry an action")
        if self.abstain is True and self.multiplier != Decimal("0"):
            raise ValueError("an abstaining overlay must have zero multiplier")
        if self.action == "veto" and self.multiplier != Decimal("0"):
            raise ValueError("a veto overlay must have zero multiplier")

        payload = self.model_dump(mode="json")
        supplied_id = payload.pop("overlay_id")
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8", "strict")
        except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
            raise ValueError("overlay canonical bytes are invalid") from exc
        preimage = HASH_DOMAIN_LLM_OVERLAY.encode("utf-8") + encoded
        if len(preimage) > MAX_LLM_OVERLAY_BYTES:
            raise ValueError("overlay canonical bytes exceed their bound")
        expected_id = f"overlay:{hashlib.sha256(preimage).hexdigest()}"
        if supplied_id != expected_id:
            raise ValueError("overlay identifier does not match canonical content")
        return self


class SignalEnvelopeReasonCode(str, Enum):
    """Static SIG-05 outcome and sanitized input reason wires."""

    QUANT_ONLY = "quant_only"
    OVERLAY_APPLIED = "overlay_applied"
    QUANT_INVALID = "quant_invalid"
    QUANT_ZERO = "quant_zero"
    NOTE_UNAVAILABLE = "note_unavailable"
    NOTE_INVALID = "note_invalid"
    OVERLAY_UNAVAILABLE = "overlay_unavailable"
    OVERLAY_INVALID = "overlay_invalid"
    OVERLAY_VETOED = "overlay_vetoed"
    OVERLAY_ABSTAINED = "overlay_abstained"
    OVERLAY_ZERO_MULTIPLIER = "overlay_zero_multiplier"
    INPUT_INVALID = "input_invalid"
    CONTEXT_INVALID = "context_invalid"
    CONTEXT_MISMATCH = "context_mismatch"
    VARIANT_INVALID = "variant_invalid"
    UNEXPECTED_RESEARCH = "unexpected_research"


class SignalEnvelopeError(ValueError):
    """Sanitized fail-closed error for SIG-05 composition and registry inputs."""

    def __init__(
        self,
        reason_code: SignalEnvelopeReasonCode = SignalEnvelopeReasonCode.INPUT_INVALID,
    ) -> None:
        if type(reason_code) is not SignalEnvelopeReasonCode:
            reason_code = SignalEnvelopeReasonCode.INPUT_INVALID
        self.reason_code = reason_code
        self.no_trade = True
        super().__init__(f"signal envelope rejected: {reason_code.value}")


class _Sig05WalkBudget:
    __slots__ = ("nodes", "json_bytes", "active")

    def __init__(self) -> None:
        self.nodes = 0
        self.json_bytes = 0
        self.active: set[int] = set()

    def visit(self, depth: int) -> None:
        if depth > MAX_SIG05_DEPTH or self.nodes >= MAX_SIG05_NODES:
            raise ValueError("SIG-05 source exceeds its structural bound")
        self.nodes += 1
        self.json_bytes += 2
        if self.json_bytes > MAX_SIG05_CANONICAL_BYTES:
            raise ValueError("SIG-05 canonical source exceeds its bound")

    def add_string(self, value: str) -> None:
        if len(value) > MAX_SIG05_TEXT_BYTES:
            raise ValueError("SIG-05 string exceeds its bound")
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError:
            raise ValueError("SIG-05 string is not valid UTF-8") from None
        if len(encoded) > MAX_SIG05_TEXT_BYTES:
            raise ValueError("SIG-05 string exceeds its bound")
        escaped_bytes = sum(char in ('"', "\\") for char in value)
        escaped_bytes += 5 * sum(ord(char) < 0x20 for char in value)
        self.json_bytes += len(encoded) + escaped_bytes + 2
        if self.json_bytes > MAX_SIG05_CANONICAL_BYTES:
            raise ValueError("SIG-05 canonical source exceeds its bound")


def _sig05_decimal_is_bounded(value: Decimal) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("SIG-05 decimal is invalid")
    if not any(value.same_quantum(quantum) for quantum in _SIG05_DECIMAL_QUANTA):
        raise ValueError("SIG-05 decimal exceeds its exponent bound")
    if value < Decimal("-1") or value > Decimal("1"):
        raise ValueError("SIG-05 decimal exceeds its numeric range")
    if value.is_zero():
        if not any(
            value.compare_total(zero) == 0 for zero in _SIG05_ZERO_REPRESENTATIONS
        ):
            raise ValueError("SIG-05 zero representation exceeds its bound")
        return
    if len(value.as_tuple().digits) > 25:
        raise ValueError("SIG-05 decimal coefficient exceeds its bound")


def _sig05_walk(value: object, budget: _Sig05WalkBudget, depth: int = 0) -> object:
    budget.visit(depth)
    value_type = type(value)

    model_type: type[object] | None = None
    model_fields: tuple[str, ...] = ()
    for allowed_type, allowed_fields in _SIG05_MODEL_FIELDS.items():
        if value_type is allowed_type:
            model_type = allowed_type
            model_fields = allowed_fields
            break
    if model_type is not None:
        try:
            storage = object.__getattribute__(value, "__dict__")
        except (AttributeError, TypeError) as exc:
            raise ValueError("SIG-05 model storage is invalid") from exc
        if type(storage) is not dict:
            raise ValueError("SIG-05 model storage is invalid")
        keys = tuple(dict.keys(storage))
        if (
            len(keys) != len(model_fields)
            or any(type(key) is not str for key in keys)
            or set(keys) != set(model_fields)
        ):
            raise ValueError("SIG-05 model fields are invalid")
        identity = id(value)
        if identity in budget.active:
            raise ValueError("SIG-05 source contains a cycle")
        budget.active.add(identity)
        try:
            payload: dict[str, object] = {}
            for field in model_fields:
                budget.add_string(field)
                payload[field] = _sig05_walk(
                    dict.__getitem__(storage, field), budget, depth + 1
                )
        finally:
            budget.active.remove(identity)
        if model_type is LLMOverlay:
            multiplier = dict.__getitem__(storage, "multiplier")
            _sig05_decimal_is_bounded(multiplier)
            payload["multiplier"] = str(multiplier)
            evidence_ids = payload["evidence_ids"]
            if type(evidence_ids) is tuple:
                payload["evidence_ids"] = list(evidence_ids)
            generated_at = dict.__getitem__(storage, "generated_at")
            if (
                type(generated_at) is not _DateTime
                or object.__getattribute__(generated_at, "tzinfo") is not _Timezone.utc
            ):
                raise ValueError("SIG-05 overlay timestamp is invalid")
            payload["generated_at"] = generated_at.isoformat().replace("+00:00", "Z")
        return payload

    if value_type is str:
        budget.add_string(value)
        return value
    if value_type is bool or value_type is type(None):
        return value
    if value_type is int:
        if value.bit_length() > MAX_SIG05_INTEGER_BITS:
            raise ValueError("SIG-05 integer exceeds its numeric bound")
        return value
    if value_type is Decimal:
        _sig05_decimal_is_bounded(value)
        return value
    if value_type is _DateTime:
        if object.__getattribute__(value, "tzinfo") is not _Timezone.utc:
            raise ValueError("SIG-05 timestamp must be exact UTC")
        return value
    if any(value_type is enum_type for enum_type in _SIG05_ENUM_TYPES):
        return value
    if value_type is dict:
        if dict.__len__(value) > MAX_SIG05_SEQUENCE_ITEMS:
            raise ValueError("SIG-05 mapping exceeds its cardinality bound")
        identity = id(value)
        if identity in budget.active:
            raise ValueError("SIG-05 source contains a cycle")
        budget.active.add(identity)
        try:
            result: dict[str, object] = {}
            for key in dict.keys(value):
                if type(key) is not str:
                    raise ValueError("SIG-05 mapping keys must be exact strings")
                budget.add_string(key)
                result[key] = _sig05_walk(dict.__getitem__(value, key), budget, depth + 1)
            return result
        finally:
            budget.active.remove(identity)
    if value_type is tuple or value_type is list:
        if len(value) > MAX_SIG05_SEQUENCE_ITEMS:
            raise ValueError("SIG-05 sequence exceeds its cardinality bound")
        identity = id(value)
        if identity in budget.active:
            raise ValueError("SIG-05 source contains a cycle")
        budget.active.add(identity)
        try:
            copied = [_sig05_walk(child, budget, depth + 1) for child in value]
        finally:
            budget.active.remove(identity)
        return tuple(copied) if value_type is tuple else copied
    raise ValueError("SIG-05 source contains an unsupported value")


def _sig05_model_payload(value: object, model: type[object]) -> dict[str, object]:
    value_type = type(value)
    if value_type is not dict and value_type is not model:
        raise ValueError("SIG-05 requires exact model or plain dictionary input")
    storage = object.__getattribute__(value, "__dict__") if value_type is model else value
    fields = _SIG05_MODEL_FIELDS[model]
    if type(storage) is not dict:
        raise ValueError("SIG-05 model storage is invalid")
    keys = tuple(dict.keys(storage))
    if (
        len(keys) != len(fields)
        or any(type(key) is not str for key in keys)
        or set(keys) != set(fields)
    ):
        raise ValueError("SIG-05 model fields are invalid")
    budget = _Sig05WalkBudget()
    budget.visit(0)
    payload: dict[str, object] = {}
    for field in fields:
        budget.add_string(field)
        payload[field] = _sig05_walk(dict.__getitem__(storage, field), budget, 1)
    if model is LLMOverlay:
        multiplier = dict.__getitem__(storage, "multiplier")
        _sig05_decimal_is_bounded(multiplier)
        payload["multiplier"] = str(multiplier)
        evidence_ids = payload["evidence_ids"]
        if type(evidence_ids) is tuple:
            payload["evidence_ids"] = list(evidence_ids)
        generated_at = dict.__getitem__(storage, "generated_at")
        if (
            type(generated_at) is not _DateTime
            or object.__getattribute__(generated_at, "tzinfo") is not _Timezone.utc
        ):
            raise ValueError("SIG-05 overlay timestamp is invalid")
        payload["generated_at"] = generated_at.isoformat().replace("+00:00", "Z")
    return payload


def _sig05_json_bytes(payload: dict[str, object], domain: str, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        raise ValueError("SIG-05 canonical payload is invalid") from None
    if len(domain.encode("utf-8") + encoded) > maximum:
        raise ValueError("SIG-05 canonical payload exceeds its bound")
    return encoded


def _sig05_hash(payload: dict[str, object], domain: str, maximum: int) -> str:
    encoded = _sig05_json_bytes(payload, domain, maximum)
    domain_bytes = domain.encode("utf-8")
    return f"sha256:{hashlib.sha256(domain_bytes + encoded).hexdigest()}"


def _sig05_decimal_context() -> _DecimalContext:
    context = _DecimalContext(prec=64, rounding=ROUND_HALF_EVEN, Emin=-100, Emax=100)
    context.traps[Inexact] = False
    context.traps[Rounded] = False
    return context


def _sig05_fixed_decimal(value: object, *, maximum: Decimal) -> Decimal:
    if type(value) is Decimal:
        _sig05_decimal_is_bounded(value)
        decimal_value = value
    elif type(value) is str:
        if len(value) > 32 or _SIG05_FIXED_DECIMAL.fullmatch(value) is None:
            raise ValueError("SIG-05 decimal text is not canonical")
        decimal_value = Decimal(value)
    else:
        raise ValueError("SIG-05 decimal requires an exact decimal value")
    if decimal_value.as_tuple().exponent != -24:
        raise ValueError("SIG-05 decimal requires exactly 24 places")
    if decimal_value.is_zero() and decimal_value.as_tuple().sign:
        raise ValueError("SIG-05 zero must have a positive sign")
    if not -maximum <= decimal_value <= maximum:
        raise ValueError("SIG-05 decimal exceeds its fixed range")
    return decimal_value


class SignalVariant(ContractModel):
    """Immutable, content-addressed identity for one explicit SIG-05 variant."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    variant_id: StableId
    kind: Literal["quant_only", "quant_llm"]
    variant_hash: CanonicalChecksum
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @classmethod
    def model_validate_json(
        cls,
        json_data: object,
        *args: object,
        **kwargs: object,
    ) -> SignalVariant:
        del json_data, args, kwargs
        raise ValueError("SignalVariant accepts plain dictionary input only")

    @model_validator(mode="before")
    @classmethod
    def require_bounded_plain_data(cls, value: object, info: ValidationInfo) -> object:
        if info.mode == "json":
            raise ValueError("SignalVariant JSON input is disabled")
        try:
            return _sig05_model_payload(value, cls)
        except (TypeError, ValueError, OverflowError, UnicodeError):
            raise ValueError("SignalVariant input is invalid") from None

    @field_validator("schema_version", "variant_id", "kind", "variant_hash", mode="before")
    @classmethod
    def validate_exact_variant_strings(cls, value: object) -> str:
        if type(value) is not str:
            raise ValueError("SignalVariant fields require exact strings")
        return value

    @field_validator("variant_id")
    @classmethod
    def validate_variant_identity(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError:
            raise ValueError("variant identity is invalid") from None
        if not encoded or len(encoded) > MAX_IDENTIFIER_LENGTH:
            raise ValueError("variant identity exceeds its bound")
        return validate_sig03_identifier(value)

    @field_validator("variant_hash", mode="before")
    @classmethod
    def validate_variant_hash_wire(cls, value: object) -> str:
        if type(value) is not str or _CANONICAL_CHECKSUM.fullmatch(value) is None:
            raise ValueError("variant hash is invalid")
        return value

    @model_validator(mode="after")
    def validate_variant_hash(self) -> SignalVariant:
        payload = {
            "schema_version": self.schema_version,
            "variant_id": self.variant_id,
            "kind": self.kind,
        }
        expected = _sig05_hash(
            payload,
            HASH_DOMAIN_SIGNAL_VARIANT,
            MAX_SIG05_CANONICAL_BYTES,
        )
        if self.variant_hash != expected:
            raise ValueError("variant hash does not match canonical content")
        return self


def _sig05_validate_context(context: RunContext) -> None:
    if type(context) is not RunContext or context.mode is not Mode.HISTORICAL:
        raise ValueError("SIG-05 requires historical context")
    identifier_budget = _new_sensitive_prevalidation_budget()
    for field in (
        "run_id",
        "variant_id",
        "bundle_id",
        "bundle_hash",
        "calendar_id",
        "base_currency",
    ):
        try:
            validate_sig03_identifier(
                object.__getattribute__(context, field),
                _decode_budget=identifier_budget,
            )
        except (TypeError, ValueError):
            raise ValueError("SIG-05 context identity is invalid") from None
    policy = context.network_policy
    if type(policy) is not NetworkPolicy:
        raise ValueError("SIG-05 requires exact network policy")
    storage = object.__getattribute__(policy, "__dict__")
    for component in (
        "data_capture_egress",
        "model_provider_egress",
        "research_tool_egress",
        "paper_broker_egress",
        "live_broker_egress",
    ):
        if dict.__getitem__(storage, component) is not False:
            raise ValueError("SIG-05 context egress must be disabled")


def _sig05_check_context_quant(
    variant: SignalVariant,
    context: RunContext,
    quant: QuantSignal,
) -> None:
    _sig05_validate_context(context)
    if context.variant_id != variant.variant_id:
        raise ValueError("SIG-05 variant does not match context")
    if (
        context.run_id != quant.run_id
        or context.bundle_id != quant.bundle_id
        or context.bundle_hash != quant.bundle_hash
        or quant.as_of > context.knowledge_cutoff
    ):
        raise ValueError("SIG-05 context does not match QuantSignal")


def _sig05_validate_note_context(
    note: ResearchNote,
    context: RunContext,
    quant: QuantSignal,
) -> None:
    note.canonical_bytes()
    if (
        note.run_id != context.run_id
        or note.variant_id != context.variant_id
        or note.bundle_id != context.bundle_id
        or note.bundle_hash != context.bundle_hash
        or note.calendar_id != context.calendar_id
        or note.knowledge_cutoff != context.knowledge_cutoff
    ):
        raise ValueError("SIG-05 ResearchNote contradicts its context")
    if note.instrument_id != quant.instrument_id:
        raise SignalEnvelopeError(SignalEnvelopeReasonCode.NOTE_INVALID)


def _sig05_validate_overlay_lineage(
    overlay: LLMOverlay,
    note: ResearchNote,
    quant: QuantSignal,
    context: RunContext,
) -> None:
    if (
        overlay.note_id != note.note_id
        or overlay.note_hash != note.note_hash
        or overlay.quant_signal_id != quant.signal_id
        or overlay.run_id != context.run_id
        or overlay.bundle_id != context.bundle_id
        or overlay.bundle_hash != context.bundle_hash
        or overlay.instrument_id != quant.instrument_id
        or overlay.generated_at > context.knowledge_cutoff
    ):
        raise ValueError("SIG-05 overlay lineage is invalid")
    cited = {
        f"{citation.reference.domain}:{citation.reference.record_id}"
        for citation in note.citations
    }
    if not set(overlay.evidence_ids).issubset(cited):
        raise ValueError("SIG-05 overlay evidence is outside its note")


def _sig05_expected_envelope(
    variant: SignalVariant,
    context: RunContext,
    quant: QuantSignal,
    note: ResearchNote | None,
    overlay: LLMOverlay | None,
    *,
    absent_reasons: tuple[SignalEnvelopeReasonCode, ...] | None = None,
) -> tuple[
    Decimal,
    Decimal,
    str,
    bool,
    tuple[SignalEnvelopeReasonCode, ...],
]:
    if type(variant) is not SignalVariant or type(context) is not RunContext:
        raise ValueError("SIG-05 variant and context types are invalid")
    if type(quant) is not QuantSignal:
        raise ValueError("SIG-05 QuantSignal type is invalid")
    _sig05_check_context_quant(variant, context, quant)
    zero = _SIG05_FIXED_ZERO
    invalid_quant = quant.status is QuantSignalStatus.INVALID or quant.score is None

    if variant.kind == "quant_only":
        if note is not None or overlay is not None:
            raise ValueError("quant_only envelope cannot contain research sources")
        if invalid_quant:
            return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.QUANT_INVALID,)
        assert quant.score is not None
        if quant.score.is_zero():
            return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.QUANT_ZERO,)
        return (
            _sig05_effective_score(quant.score, Decimal("1")),
            _sig05_quant_multiplier(Decimal("1")),
            "eligible",
            False,
            (SignalEnvelopeReasonCode.QUANT_ONLY,),
        )

    if invalid_quant:
        if note is not None or overlay is not None:
            raise ValueError("invalid quant envelope must sanitize research sources")
        return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.QUANT_INVALID,)
    if note is None:
        if overlay is not None:
            raise ValueError("overlay cannot be retained without its note")
        if absent_reasons not in (
            (SignalEnvelopeReasonCode.NOTE_UNAVAILABLE,),
            (SignalEnvelopeReasonCode.NOTE_INVALID,),
        ):
            raise ValueError("missing note requires a bounded no-trade reason")
        return zero, zero, "abstain", True, absent_reasons
    if type(note) is not ResearchNote:
        raise ValueError("SIG-05 ResearchNote type is invalid")
    _sig05_validate_note_context(note, context, quant)

    if overlay is None:
        if absent_reasons not in (
            (SignalEnvelopeReasonCode.OVERLAY_UNAVAILABLE,),
            (SignalEnvelopeReasonCode.OVERLAY_INVALID,),
        ):
            raise ValueError("missing overlay requires a bounded no-trade reason")
        return zero, zero, "abstain", True, absent_reasons
    if type(overlay) is not LLMOverlay:
        raise ValueError("SIG-05 overlay type is invalid")
    _sig05_validate_overlay_lineage(overlay, note, quant, context)

    if overlay.action == "veto":
        return zero, zero, "vetoed", True, (SignalEnvelopeReasonCode.OVERLAY_VETOED,)
    if overlay.abstain is True:
        return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.OVERLAY_ABSTAINED,)
    if overlay.action != "attenuate":
        raise ValueError("SIG-05 overlay action is invalid")
    if overlay.multiplier.is_zero():
        return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.OVERLAY_ZERO_MULTIPLIER,)
    assert quant.score is not None
    if quant.score.is_zero():
        return zero, zero, "abstain", True, (SignalEnvelopeReasonCode.QUANT_ZERO,)
    return (
        _sig05_effective_score(quant.score, overlay.multiplier),
        _sig05_quant_multiplier(overlay.multiplier),
        "attenuated",
        False,
        (SignalEnvelopeReasonCode.OVERLAY_APPLIED,),
    )


def _sig05_quant_multiplier(value: Decimal) -> Decimal:
    _sig05_decimal_is_bounded(value)
    with localcontext(_sig05_decimal_context()) as context:
        result = value.quantize(_SIG05_SCALE, context=context)
    return _SIG05_FIXED_ZERO if result.is_zero() else result


def _sig05_effective_score(score: Decimal, multiplier: Decimal) -> Decimal:
    _sig05_decimal_is_bounded(score)
    _sig05_decimal_is_bounded(multiplier)
    with localcontext(_sig05_decimal_context()) as context:
        try:
            result = (score * multiplier).quantize(_SIG05_SCALE, context=context)
        except Exception:
            raise ValueError("SIG-05 score arithmetic failed") from None
    return _SIG05_FIXED_ZERO if result.is_zero() else result


class SignalEnvelope(ContractModel):
    """Full-source, deterministic shadow-only combination of SIG-03 and SIG-04."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    envelope_id: str
    variant: SignalVariant
    context: RunContext
    quant: QuantSignal
    note: ResearchNote | None
    overlay: LLMOverlay | None
    effective_score: Decimal
    effective_multiplier: Decimal
    effective_action: Literal["eligible", "attenuated", "vetoed", "abstain"]
    no_trade: StrictBool
    reason_codes: tuple[SignalEnvelopeReasonCode, ...]
    created_at: UtcDateTime
    shadow_only: StrictBool
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        hide_input_in_errors=True,
    )

    @classmethod
    def model_validate_json(
        cls,
        json_data: object,
        *args: object,
        **kwargs: object,
    ) -> SignalEnvelope:
        del json_data, args, kwargs
        raise ValueError("SignalEnvelope accepts plain dictionary input only")

    @model_validator(mode="before")
    @classmethod
    def require_bounded_plain_data(cls, value: object, info: ValidationInfo) -> object:
        if info.mode == "json":
            raise ValueError("SignalEnvelope JSON input is disabled")
        try:
            return _sig05_model_payload(value, cls)
        except (TypeError, ValueError, OverflowError, UnicodeError):
            raise ValueError("SignalEnvelope input is invalid") from None

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_envelope_schema_version(cls, value: object) -> str:
        if type(value) is not str:
            raise ValueError("envelope schema version requires an exact string")
        return value

    @field_validator("envelope_id", mode="before")
    @classmethod
    def validate_envelope_id(cls, value: object) -> str:
        if type(value) is not str or _SIG05_ENVELOPE_ID.fullmatch(value) is None:
            raise ValueError("envelope ID is invalid")
        return value

    @field_validator("effective_score", mode="before")
    @classmethod
    def validate_effective_score(cls, value: object) -> Decimal:
        return _sig05_fixed_decimal(value, maximum=Decimal("1"))

    @field_validator("effective_multiplier", mode="before")
    @classmethod
    def validate_effective_multiplier(cls, value: object) -> Decimal:
        return _sig05_fixed_decimal(value, maximum=Decimal("1"))

    @field_serializer("effective_score", "effective_multiplier", when_used="json")
    def serialize_fixed_decimals(self, value: Decimal) -> str:
        return format(value, "f")

    @field_validator("reason_codes", mode="before")
    @classmethod
    def validate_reason_sequence(cls, value: object) -> tuple[object, ...]:
        if type(value) not in (tuple, list) or len(value) > 16:
            raise ValueError("envelope reason codes are invalid")
        return tuple(value)

    @model_validator(mode="after")
    def validate_envelope_semantics(self) -> SignalEnvelope:
        if self.shadow_only is not True:
            raise ValueError("SignalEnvelope must remain shadow-only")
        if tuple(self.reason_codes) != tuple(
            sorted(self.reason_codes, key=lambda item: item.value)
        ):
            raise ValueError("envelope reason codes are not canonical")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("envelope reason codes are duplicated")
        try:
            score, multiplier, action, no_trade, reasons = _sig05_expected_envelope(
                self.variant,
                self.context,
                self.quant,
                self.note,
                self.overlay,
                absent_reasons=self.reason_codes,
            )
        except (SignalEnvelopeError, TypeError, ValueError, OverflowError):
            raise ValueError("SignalEnvelope sources or semantics are invalid") from None
        if (
            self.effective_score != score
            or self.effective_multiplier != multiplier
            or self.effective_action != action
            or self.no_trade is not no_trade
            or self.reason_codes != reasons
            or self.created_at != self.context.decision_time
        ):
            raise ValueError("SignalEnvelope outcome does not match its sources")
        payload = self.model_dump(mode="json")
        supplied_id = payload.pop("envelope_id")
        if supplied_id != _sig05_envelope_id(payload):
            raise ValueError("envelope ID does not match canonical content")
        return self

    def canonical_bytes(self) -> bytes:
        """Return bounded canonical JSON after revalidating every stored source."""

        try:
            rebuilt = type(self).model_validate(self)
            payload = rebuilt.model_dump(mode="json")
            return _sig05_json_bytes(
                payload,
                HASH_DOMAIN_SIGNAL_ENVELOPE,
                MAX_SIG05_CANONICAL_BYTES,
            )
        except (ValidationError, SignalEnvelopeError, TypeError, ValueError, OverflowError, UnicodeError):
            raise ValueError("SignalEnvelope failed safe canonical validation") from None


_SIG05_MODEL_FIELDS: dict[type[object], tuple[str, ...]] = {
    model: tuple(model.model_fields)
    for model in (
        NetworkPolicy,
        RunContext,
        QuantSignal,
        LLMOverlay,
        ResearchProvenance,
        ResearchSourceFields,
        EvidenceReference,
        EvidenceCitation,
        ResearchNote,
        SignalVariant,
        SignalEnvelope,
    )
}
_SIG05_ENUM_TYPES = (
    Mode,
    QuantSignalStatus,
    QuantSignalReasonCode,
    SignalEnvelopeReasonCode,
)


def _sig05_envelope_id(payload: dict[str, object]) -> str:
    encoded = _sig05_json_bytes(
        payload,
        HASH_DOMAIN_SIGNAL_ENVELOPE,
        MAX_SIG05_CANONICAL_BYTES,
    )
    digest = hashlib.sha256(HASH_DOMAIN_SIGNAL_ENVELOPE.encode("utf-8") + encoded).hexdigest()
    return f"signal-envelope:{digest}"


__all__ = [
    "HASH_DOMAIN_LLM_OVERLAY",
    "HASH_DOMAIN_QUANT_SIGNAL",
    "HASH_DOMAIN_SIGNAL_ENVELOPE",
    "HASH_DOMAIN_SIGNAL_VARIANT",
    "LLMOverlay",
    "MAX_LLM_OVERLAY_BYTES",
    "MAX_LLM_OVERLAY_EVIDENCE_IDS",
    "MAX_LLM_OVERLAY_RATIONALE_BYTES",
    "MAX_CANONICAL_BYTES",
    "MAX_FEATURES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_NESTING_DEPTH",
    "QuantSignal",
    "QuantSignalReasonCode",
    "QuantSignalStatus",
    "SignalEnvelope",
    "SignalEnvelopeError",
    "SignalEnvelopeReasonCode",
    "SignalVariant",
    "validate_sig03_identifier",
]
