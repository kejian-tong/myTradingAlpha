"""Pure, point-in-time deterministic feature calculation for SIG-03."""

from __future__ import annotations

import hashlib
import json
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Rounded,
    localcontext,
)
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import (
    CanonicalChecksum,
    StableId,
    UtcDateTime,
    datetime as _DateTime,
    timezone as _Timezone,
)
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.signals import (
    QuantSignalReasonCode,
    _decode_budget_from_context,
    _initialize_sig03_model,
    _new_sig03_validation_context,
    _validate_sig03_model,
    _validate_sig03_nested_model,
    validate_sig03_identifier,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION
from mytradingalpha.data.actions import (
    ActionType,
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, DailyBar
from mytradingalpha.data.bundle import (
    BundleReplayPolicy,
    EvidenceBundle,
    EvidenceDomain,
    EvidenceRequirement,
    MissingEvidence,
)
from mytradingalpha.data.calendar import (
    CalendarClosure,
    CalendarCoverageRange,
    CalendarError,
    SessionType,
    TradingCalendar,
    TradingSession,
    date as _Date,
)
from mytradingalpha.data.events import EventKind, NewsEvent, ReplayPolicy
from mytradingalpha.data.fundamentals import (
    FinancialFact,
    FinancialFiling,
    ReportingPeriod,
    StatementType,
    UnitScale,
)
from mytradingalpha.data.macro import MacroFrequency, MacroObservation
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.social import SocialPlatform, SocialPost
from mytradingalpha.data.universe import AssetClass, Instrument, SymbolAlias, UniverseMembership

MAX_FEATURES = 32
MAX_LOOKBACK_SESSIONS = 252
MAX_PROVENANCE_ITEMS = MAX_LOOKBACK_SESSIONS + 1
MAX_HORIZON_SESSIONS = 252
MAX_BARS = 4096
MAX_BUNDLE_WALK_NODES = 100_000
MAX_NESTING_DEPTH = 64
MAX_IDENTIFIER_LENGTH = 128
MAX_CANONICAL_BYTES = 1_048_576
DECIMAL_PLACES = 12
DECIMAL_PRECISION = 64
DECIMAL_ROUNDING = ROUND_HALF_EVEN

HASH_DOMAIN_FEATURE_CONFIGURATION = "mytradingalpha:sig03:feature-configuration:v1\0"
HASH_DOMAIN_FEATURE_SCHEMA = "mytradingalpha:sig03:feature-schema:v1\0"
HASH_DOMAIN_FEATURE_SET = "mytradingalpha:sig03:feature-set:v1\0"

_REASON_ORDER = {item.value: index for index, item in enumerate(QuantSignalReasonCode)}
_GLOBAL_FAILURE_REASONS = frozenset(
    {
        QuantSignalReasonCode.INSTRUMENT_NOT_IN_BUNDLE,
        QuantSignalReasonCode.INSTRUMENT_INACTIVE_AS_OF,
        QuantSignalReasonCode.INSTRUMENT_NOT_IN_UNIVERSE,
        QuantSignalReasonCode.AMBIGUOUS_UNIVERSE_MEMBERSHIP,
        QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
    }
)
_MISSINGNESS_REASONS = frozenset(
    {
        QuantSignalReasonCode.REQUIRED_FEATURE_MISSING,
        QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING,
    }
)


class QuantInputError(ValueError):
    """Raised when a quant input is malformed, tampered, or outside fixed bounds."""


def _plain_model_input(model: type[object], value: object) -> dict[str, object]:
    if type(value) is model:
        try:
            value = object.__getattribute__(value, "__dict__")
        except (AttributeError, TypeError) as exc:
            raise _sensitive_validation_error(model.__name__) from exc
    if type(value) is not dict:
        raise _sensitive_validation_error(model.__name__)
    fields = tuple(model.model_fields)  # type: ignore[attr-defined]
    if dict.__len__(value) > len(fields):
        raise _sensitive_validation_error(model.__name__)
    keys = tuple(dict.keys(value))
    if any(type(key) is not str for key in keys):
        raise _sensitive_validation_error(model.__name__)
    allowed = set(fields)
    if any(key not in allowed for key in keys):
        raise _sensitive_validation_error(model.__name__)
    return {key: dict.__getitem__(value, key) for key in keys}


def _fixed_decimal_context() -> Context:
    context = Context(prec=DECIMAL_PRECISION, rounding=DECIMAL_ROUNDING)
    context.traps[Inexact] = False
    context.traps[Rounded] = False
    return context


class FeatureSpec(ContractModel):
    """One close-return selector and its bounded lookback policy."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    feature_id: StableId
    feature_version: StableId
    kind: Literal["close_return"]
    bar_source: StableId
    interval: Literal["1d"]
    adjustment_basis: AdjustmentBasis
    adjustment_version: StableId | None
    lookback_sessions: StrictInt = Field(ge=1, le=MAX_LOOKBACK_SESSIONS)
    required: StrictBool
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="never", hide_input_in_errors=True
    )

    def __init__(self, **data: object) -> None:
        _initialize_sig03_model(self, data)

    @classmethod
    def model_validate(cls, obj: object, *args: Any, **kwargs: Any) -> FeatureSpec:
        if type(obj) not in (dict, cls):
            raise ValueError("FeatureSpec requires exact plain data")
        if args:
            raise TypeError("model_validate options must be keyword arguments")
        return _validate_sig03_model(cls, obj, **kwargs)  # type: ignore[return-value]

    @model_validator(mode="before")
    @classmethod
    def require_plain_data(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        plain = _plain_model_input(cls, value)
        _prevalidate_sensitive(
            cls, plain, _decode_budget_from_context(info.context)
        )
        return plain

    @field_validator("feature_id", "feature_version", "bar_source")
    @classmethod
    def validate_safe_selector(cls, value: str, info: ValidationInfo) -> str:
        return _safe_identifier(value, context=info.context)

    @field_validator("adjustment_version")
    @classmethod
    def validate_safe_adjustment_version(
        cls,
        value: str | None,
        info: ValidationInfo,
    ) -> str | None:
        return None if value is None else _safe_identifier(value, context=info.context)

    @model_validator(mode="after")
    def validate_adjustment_policy(self) -> FeatureSpec:
        if (self.adjustment_basis is AdjustmentBasis.UNADJUSTED) != (self.adjustment_version is None):
            raise ValueError("unadjusted bars require no version; adjusted bars require a version")
        return self


class FeatureConfiguration(ContractModel):
    """Immutable canonical feature configuration bound to one universe/calendar."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    configuration_id: StableId
    configuration_version: StableId
    universe_id: StableId
    calendar_id: StableId
    horizon_sessions: StrictInt = Field(ge=1, le=MAX_HORIZON_SESSIONS)
    features: tuple[FeatureSpec, ...]
    content_hash: CanonicalChecksum
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    def __init__(self, **data: object) -> None:
        _initialize_sig03_model(self, data)

    @classmethod
    def model_validate(cls, obj: object, *args: Any, **kwargs: Any) -> FeatureConfiguration:
        if type(obj) not in (dict, cls):
            raise ValueError("FeatureConfiguration requires exact plain data")
        if args:
            raise TypeError("model_validate options must be keyword arguments")
        return _validate_sig03_model(cls, obj, **kwargs)  # type: ignore[return-value]

    @model_validator(mode="before")
    @classmethod
    def require_plain_data(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> object:
        plain = _plain_model_input(cls, value)
        if "features" in plain:
            features = dict.__getitem__(plain, "features")
            if (
                type(features) not in (tuple, list)
                or len(features) == 0
                or len(features) > MAX_FEATURES
            ):
                raise ValueError("feature count exceeds SIG-03 bound")
        _prevalidate_sensitive(
            cls, plain, _decode_budget_from_context(info.context)
        )
        return plain

    @field_validator("configuration_id", "configuration_version", "universe_id", "calendar_id")
    @classmethod
    def validate_ids(cls, value: str, info: ValidationInfo) -> str:
        return _safe_identifier(value, context=info.context)

    @field_validator("features", mode="before")
    @classmethod
    def validate_features(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> tuple[FeatureSpec, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("features require a plain sequence")
        if len(value) == 0 or len(value) > MAX_FEATURES:
            raise ValueError("feature count exceeds SIG-03 bound")
        specs = tuple(
            _validate_sig03_nested_model(
                FeatureSpec,
                item,
                context=info.context,
            )
            for item in value
        )
        ordered = tuple(sorted(specs, key=lambda item: item.feature_id))
        if tuple(item.feature_id for item in ordered) != tuple(item.feature_id for item in specs):
            raise ValueError("features must be supplied in canonical order")
        if len({item.feature_id for item in specs}) != len(specs):
            raise ValueError("feature identifiers must be unique")
        return specs

    @model_validator(mode="after")
    def validate_hash(self, info: ValidationInfo) -> FeatureConfiguration:
        expected = (
            _feature_configuration_hash(self, context=info.context)
            if type(self) is FeatureConfiguration
            else _hash_json(
                HASH_DOMAIN_FEATURE_CONFIGURATION,
                _configuration_payload(self),
            )
        )
        if self.content_hash != expected:
            raise ValueError("feature configuration content hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        configuration_id: str,
        configuration_version: str,
        universe_id: str,
        calendar_id: str,
        horizon_sessions: int,
        features: tuple[FeatureSpec, ...] | list[FeatureSpec],
    ) -> FeatureConfiguration:
        if type(features) not in (tuple, list):
            raise QuantInputError("feature configuration features require a plain sequence")
        if len(features) == 0 or len(features) > MAX_FEATURES:
            raise QuantInputError("feature count exceeds SIG-03 bound")
        context = _new_sig03_validation_context()
        specs = tuple(
            _validate_sig03_nested_model(
                FeatureSpec,
                item,
                context=context,
            )
            for item in features
        )
        payload = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "configuration_id": configuration_id,
            "configuration_version": configuration_version,
            "universe_id": universe_id,
            "calendar_id": calendar_id,
            "horizon_sessions": horizon_sessions,
            "features": tuple(sorted(specs, key=lambda item: item.feature_id)),
        }
        payload["content_hash"] = _hash_json(
            HASH_DOMAIN_FEATURE_CONFIGURATION,
            _configuration_payload(payload),
        )
        return _validate_sig03_nested_model(cls, payload, context=context)  # type: ignore[return-value]


class FeatureObservation(ContractModel):
    """One feature value with exact temporal and source-bar provenance."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    feature_id: StableId
    feature_version: StableId
    value: Decimal | None
    required: StrictBool
    status: Literal["available", "missing"]
    reason_code: QuantSignalReasonCode | None
    as_of: UtcDateTime
    anchor_session: str | None
    lookback_sessions: StrictInt = Field(ge=1, le=MAX_LOOKBACK_SESSIONS)
    lookback_session: str | None
    latest_available_at: UtcDateTime | None
    source_bar_ids: tuple[StableId, ...]
    source_manifest_ids: tuple[StableId, ...]
    source_revisions: tuple[StrictInt, ...]
    source_session_dates: tuple[str, ...]
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="never", hide_input_in_errors=True
    )

    def __init__(self, **data: object) -> None:
        _initialize_sig03_model(self, data)

    @field_validator("feature_id", "feature_version")
    @classmethod
    def validate_feature_ids(cls, value: str, info: ValidationInfo) -> str:
        return _safe_identifier(value, context=info.context)

    @classmethod
    def model_validate(cls, obj: object, *args: Any, **kwargs: Any) -> FeatureObservation:
        if type(obj) not in (dict, cls):
            raise ValueError("FeatureObservation requires exact plain data")
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
        plain = _plain_model_input(cls, value)
        required_fields = {
            "lookback_sessions",
            "status",
            "source_bar_ids",
            "source_manifest_ids",
            "source_revisions",
            "source_session_dates",
        }
        if not required_fields.issubset(plain):
            raise _sensitive_validation_error(cls.__name__)
        lookback = dict.__getitem__(plain, "lookback_sessions")
        status = dict.__getitem__(plain, "status")
        if (
            type(lookback) is not int
            or not 1 <= lookback <= MAX_LOOKBACK_SESSIONS
            or type(status) is not str
            or status not in {"available", "missing"}
        ):
            raise _sensitive_validation_error(cls.__name__)
        lengths: list[int] = []
        for field in (
            "source_bar_ids",
            "source_manifest_ids",
            "source_revisions",
            "source_session_dates",
        ):
            collection = dict.__getitem__(plain, field)
            if (
                type(collection) not in (tuple, list)
                or len(collection) > MAX_PROVENANCE_ITEMS
            ):
                raise _sensitive_validation_error(cls.__name__)
            lengths.append(len(collection))
        expected_length = lookback + 1 if status == "available" else 0
        if len(set(lengths)) != 1 or lengths[0] != expected_length:
            raise _sensitive_validation_error(cls.__name__)
        _prevalidate_sensitive(
            cls, plain, _decode_budget_from_context(info.context)
        )
        return plain

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        if type(value) not in (Decimal, str):
            raise ValueError("feature value requires an exact Decimal or string")
        try:
            decimal = value if type(value) is Decimal else Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("feature value is invalid") from exc
        parts = decimal.as_tuple()
        if (
            not decimal.is_finite()
            or parts.exponent != -DECIMAL_PLACES
            or len(parts.digits) > DECIMAL_PRECISION
        ):
            raise ValueError("feature value must be a bounded twelve-place decimal")
        if decimal == 0:
            with localcontext(_fixed_decimal_context()):
                return Decimal(0).quantize(Decimal(1).scaleb(-DECIMAL_PLACES))
        return decimal

    @field_validator("anchor_session", "lookback_session", mode="before")
    @classmethod
    def validate_session_dates(cls, value: object) -> str | None:
        if value is None:
            return None
        if type(value) is not str:
            raise ValueError("feature sessions require canonical ISO dates")
        try:
            parsed = _Date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("feature sessions require canonical ISO dates") from exc
        if parsed.isoformat() != value:
            raise ValueError("feature sessions require canonical ISO dates")
        return value

    @field_validator("source_bar_ids", "source_manifest_ids", mode="before")
    @classmethod
    def validate_provenance_ids(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> tuple[str, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("feature provenance requires plain sequences")
        if len(value) > MAX_PROVENANCE_ITEMS:
            raise ValueError("feature provenance exceeds SIG-03 bound")
        return tuple(_safe_identifier(item, context=info.context) for item in value)

    @field_validator("source_revisions", mode="before")
    @classmethod
    def validate_source_revisions(cls, value: object) -> tuple[int, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("feature provenance requires plain sequences")
        if len(value) > MAX_PROVENANCE_ITEMS:
            raise ValueError("feature provenance exceeds SIG-03 bound")
        if any(type(item) is not int or item < 0 for item in value):
            raise ValueError("feature revisions require nonnegative exact integers")
        return tuple(value)

    @field_validator("source_session_dates", mode="before")
    @classmethod
    def validate_source_session_dates(cls, value: object) -> tuple[str, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("feature provenance requires plain sequences")
        if len(value) > MAX_PROVENANCE_ITEMS:
            raise ValueError("feature provenance exceeds SIG-03 bound")
        parsed: list[str] = []
        for item in value:
            if type(item) is not str:
                raise ValueError("source sessions require canonical ISO dates")
            try:
                session_date = _Date.fromisoformat(item)
            except ValueError as exc:
                raise ValueError("source sessions require canonical ISO dates") from exc
            if session_date.isoformat() != item:
                raise ValueError("source sessions require canonical ISO dates")
            parsed.append(item)
        return tuple(parsed)

    @model_validator(mode="after")
    def validate_provenance(self) -> FeatureObservation:
        if not (
            len(self.source_bar_ids)
            == len(self.source_manifest_ids)
            == len(self.source_revisions)
            == len(self.source_session_dates)
        ):
            raise ValueError("parallel feature provenance lengths must match")
        if self.status == "available":
            if (
                self.value is None
                or self.reason_code is not None
                or self.anchor_session is None
                or self.lookback_session is None
                or self.latest_available_at is None
                or len(self.source_bar_ids) != self.lookback_sessions + 1
                or len(self.source_manifest_ids) != self.lookback_sessions + 1
                or len(self.source_revisions) != self.lookback_sessions + 1
                or len(self.source_session_dates) != self.lookback_sessions + 1
            ):
                raise ValueError(
                    "available observations require exact lookback provenance"
                )
            anchor = _Date.fromisoformat(self.anchor_session)
            lookback = _Date.fromisoformat(self.lookback_session)
            source_sessions = tuple(
                _Date.fromisoformat(item) for item in self.source_session_dates
            )
            if (
                not lookback < anchor
                or anchor != self.as_of.date()
                or source_sessions[0] != lookback
                or source_sessions[-1] != anchor
                or any(
                    left >= right
                    for left, right in zip(
                        source_sessions, source_sessions[1:], strict=False
                    )
                )
                or len(set(source_sessions)) != len(source_sessions)
            ):
                raise ValueError("feature session chronology is invalid")
            if len(set(self.source_bar_ids)) != len(self.source_bar_ids):
                raise ValueError("source bar identifiers must be unique")
            if len(set(self.source_manifest_ids)) != len(self.source_manifest_ids):
                raise ValueError("source manifest identifiers must be unique")
        elif (
            self.value is not None
            or self.reason_code is None
            or self.lookback_session is not None
            or self.latest_available_at is not None
            or len(self.source_bar_ids) != 0
            or len(self.source_manifest_ids) != 0
            or len(self.source_revisions) != 0
            or len(self.source_session_dates) != 0
        ):
            raise ValueError("missing observations require only an explicit reason")
        return self


class FeatureSet(ContractModel):
    """Immutable feature calculation result bound to one sealed bundle."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    instrument_id: StableId
    as_of: UtcDateTime
    knowledge_cutoff: UtcDateTime
    horizon_sessions: StrictInt = Field(ge=1, le=MAX_HORIZON_SESSIONS)
    configuration_id: StableId
    configuration_version: StableId
    feature_config_hash: CanonicalChecksum
    feature_schema_hash: CanonicalChecksum
    feature_hash: CanonicalChecksum
    observations: tuple[FeatureObservation, ...]
    missing_required_feature_ids: tuple[StableId, ...]
    missing_optional_feature_ids: tuple[StableId, ...]
    status: Literal["valid", "degraded", "invalid"]
    reason_codes: tuple[QuantSignalReasonCode, ...]
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    def __init__(self, **data: object) -> None:
        _initialize_sig03_model(self, data)

    @field_validator(
        "bundle_id",
        "instrument_id",
        "configuration_id",
        "configuration_version",
    )
    @classmethod
    def validate_scalar_ids(cls, value: str, info: ValidationInfo) -> str:
        return _safe_identifier(value, context=info.context)

    @classmethod
    def model_validate(cls, obj: object, *args: Any, **kwargs: Any) -> FeatureSet:
        if type(obj) not in (dict, cls):
            raise ValueError("FeatureSet requires exact plain data")
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
        plain = _plain_model_input(cls, value)
        for field in (
            "observations",
            "missing_required_feature_ids",
            "missing_optional_feature_ids",
            "reason_codes",
        ):
            if field not in plain:
                continue
            collection = dict.__getitem__(plain, field)
            if type(collection) not in (tuple, list) or len(collection) > MAX_FEATURES:
                raise ValueError("feature set collection exceeds SIG-03 bound")
        _prevalidate_sensitive(
            cls, plain, _decode_budget_from_context(info.context)
        )
        return plain

    @field_validator("observations", mode="before")
    @classmethod
    def validate_observations(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> tuple[FeatureObservation, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("observations require a plain sequence")
        if len(value) > MAX_FEATURES:
            raise ValueError("observation count exceeds SIG-03 bound")
        observations = tuple(
            _validate_sig03_nested_model(
                FeatureObservation,
                item,
                context=info.context,
            )
            for item in value
        )
        return observations

    @field_validator("missing_required_feature_ids", "missing_optional_feature_ids", mode="before")
    @classmethod
    def validate_missing_ids(
        cls,
        value: object,
        info: ValidationInfo,
    ) -> tuple[object, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("missing feature IDs require a plain sequence")
        if len(value) > MAX_FEATURES:
            raise ValueError("missing feature IDs exceed SIG-03 bound")
        return tuple(_safe_identifier(item, context=info.context) for item in value)

    @field_validator("reason_codes", mode="before")
    @classmethod
    def validate_reason_codes(cls, value: object) -> tuple[object, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("reason codes require a plain sequence")
        if len(value) > MAX_FEATURES:
            raise ValueError("reason codes exceed SIG-03 bound")
        return tuple(value)

    @model_validator(mode="after")
    def validate_hash_and_status(self, info: ValidationInfo) -> FeatureSet:
        expected_hash = (
            _feature_set_hash(self, context=info.context)
            if type(self) is FeatureSet
            else _hash_json(HASH_DOMAIN_FEATURE_SET, _feature_set_payload(self))
        )
        if self.feature_hash != expected_hash:
            raise QuantInputError("feature set hash mismatch")
        if self.as_of > self.knowledge_cutoff:
            raise ValueError("feature set as_of exceeds knowledge cutoff")
        for observation in self.observations:
            if observation.as_of != self.as_of:
                raise ValueError("observation as_of does not match feature set")
            if (
                observation.status == "available"
                and observation.latest_available_at is not None
                and observation.latest_available_at > self.knowledge_cutoff
            ):
                raise ValueError("feature availability exceeds knowledge cutoff")
        observation_ids = tuple(item.feature_id for item in self.observations)
        if observation_ids != tuple(sorted(observation_ids)) or len(set(observation_ids)) != len(observation_ids):
            raise ValueError("feature observations must be sorted and unique")
        expected_required = tuple(sorted(item.feature_id for item in self.observations if item.required and item.value is None))
        expected_optional = tuple(sorted(item.feature_id for item in self.observations if not item.required and item.value is None))
        if self.missing_required_feature_ids != expected_required or self.missing_optional_feature_ids != expected_optional:
            raise ValueError("feature missing IDs do not match observations")
        reason_values = tuple(item.value for item in self.reason_codes)
        if len(reason_values) != len(set(reason_values)) or reason_values != tuple(
            sorted(reason_values, key=lambda item: _REASON_ORDER[item])
        ):
            raise ValueError("reason codes must be canonical and unique")
        reasons = frozenset(self.reason_codes)
        observation_reasons = frozenset(
            item.reason_code
            for item in self.observations
            if item.reason_code is not None
        )
        if not observation_reasons.issubset(reasons):
            raise ValueError("observation reasons must be preserved")
        global_reasons = reasons.intersection(_GLOBAL_FAILURE_REASONS)
        feature_reasons = reasons.difference(
            _GLOBAL_FAILURE_REASONS | _MISSINGNESS_REASONS
        )
        if not feature_reasons.issubset(observation_reasons):
            raise ValueError("feature reasons must be explained by observations")
        has_required_missing = bool(self.missing_required_feature_ids)
        has_optional_missing = bool(self.missing_optional_feature_ids)
        has_required_reason = QuantSignalReasonCode.REQUIRED_FEATURE_MISSING in reasons
        has_optional_reason = QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING in reasons
        if has_required_reason != has_required_missing:
            raise ValueError("required missingness reason does not match feature IDs")
        expected_optional_reason = (
            has_optional_missing
            and not has_required_missing
            and not global_reasons
        )
        if has_optional_reason != expected_optional_reason:
            raise ValueError("optional missingness reason does not match feature IDs")
        if feature_reasons and not (has_required_missing or has_optional_missing):
            raise ValueError("feature reasons require missing feature IDs")
        if self.status == "valid" and (
            has_required_missing or has_optional_missing or reasons
        ):
            raise ValueError("valid feature set cannot have missingness or reasons")
        if self.status == "degraded" and (
            has_required_missing
            or not has_optional_missing
            or global_reasons
            or has_required_reason
            or not has_optional_reason
        ):
            raise ValueError("degraded feature set requires optional missingness only")
        if self.status == "invalid" and not (
            global_reasons or has_required_missing
        ):
            raise ValueError("invalid feature set requires global or required failure")
        return self

    @classmethod
    def compute(
        cls,
        *,
        bundle: EvidenceBundle,
        configuration: FeatureConfiguration,
        instrument_id: str,
    ) -> FeatureSet:
        validated_bundle = _validated_bundle(bundle)
        if type(configuration) is not FeatureConfiguration:
            raise QuantInputError("feature configuration must be exact")
        validated_configuration = _copy_feature_configuration(configuration)
        instrument_id = _safe_identifier(instrument_id)
        as_of, anchor_session, calendar_reason = _anchor(validated_bundle)
        reasons: set[QuantSignalReasonCode] = set()
        if calendar_reason is not None:
            reasons.add(calendar_reason)
        if validated_configuration.calendar_id != validated_bundle.calendar.calendar_id:
            reasons.add(QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE)

        instrument = next(
            (item for item in validated_bundle.instruments if item.instrument_id == instrument_id),
            None,
        )
        if instrument is None:
            reasons.add(QuantSignalReasonCode.INSTRUMENT_NOT_IN_BUNDLE)
        elif anchor_session is not None and not (
            instrument.active_from <= anchor_session.session_date
            and (instrument.active_to is None or anchor_session.session_date < instrument.active_to)
        ):
            reasons.add(QuantSignalReasonCode.INSTRUMENT_INACTIVE_AS_OF)
        memberships = tuple(
            item
            for item in validated_bundle.memberships
            if item.instrument_id == instrument_id
            and item.universe_id == validated_configuration.universe_id
            and anchor_session is not None
            and item.valid_from <= anchor_session.session_date
            and (item.valid_to is None or anchor_session.session_date < item.valid_to)
        )
        if instrument is not None and anchor_session is not None and not memberships:
            reasons.add(QuantSignalReasonCode.INSTRUMENT_NOT_IN_UNIVERSE)
        elif len(memberships) > 1:
            reasons.add(QuantSignalReasonCode.AMBIGUOUS_UNIVERSE_MEMBERSHIP)

        observations: list[FeatureObservation] = []
        for spec in validated_configuration.features:
            observation = _compute_observation(
                validated_bundle,
                spec,
                instrument_id=instrument_id,
                anchor_session=anchor_session,
                as_of=as_of,
            )
            observations.append(observation)
            if observation.reason_code is not None:
                reasons.add(observation.reason_code)

        missing_required = tuple(
            sorted(item.feature_id for item in observations if item.required and item.value is None)
        )
        missing_optional = tuple(
            sorted(item.feature_id for item in observations if not item.required and item.value is None)
        )
        if missing_required:
            reasons.add(QuantSignalReasonCode.REQUIRED_FEATURE_MISSING)
        if missing_optional and not missing_required and not any(
            reason
            in {
                QuantSignalReasonCode.INSTRUMENT_NOT_IN_BUNDLE,
                QuantSignalReasonCode.INSTRUMENT_INACTIVE_AS_OF,
                QuantSignalReasonCode.INSTRUMENT_NOT_IN_UNIVERSE,
                QuantSignalReasonCode.AMBIGUOUS_UNIVERSE_MEMBERSHIP,
                QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
            }
            for reason in reasons
        ):
            reasons.add(QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING)
        required_feature_failure = any(
            item.required and item.value is None and item.reason_code is not None
            for item in observations
        )
        status = "invalid" if missing_required or reasons.intersection(_GLOBAL_FAILURE_REASONS) or required_feature_failure else (
            "degraded" if missing_optional else "valid"
        )
        reason_codes = tuple(sorted(reasons, key=lambda item: _REASON_ORDER[item.value]))
        payload: dict[str, Any] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "bundle_id": validated_bundle.bundle_id,
            "bundle_hash": validated_bundle.bundle_hash,
            "instrument_id": instrument_id,
            "as_of": as_of,
            "knowledge_cutoff": validated_bundle.knowledge_cutoff,
            "horizon_sessions": validated_configuration.horizon_sessions,
            "configuration_id": validated_configuration.configuration_id,
            "configuration_version": validated_configuration.configuration_version,
            "feature_config_hash": validated_configuration.content_hash,
            "feature_schema_hash": feature_schema_hash(validated_configuration.features),
            "observations": tuple(observations),
            "missing_required_feature_ids": missing_required,
            "missing_optional_feature_ids": missing_optional,
            "status": status,
            "reason_codes": reason_codes,
        }
        payload["feature_hash"] = _hash_json(HASH_DOMAIN_FEATURE_SET, _feature_set_payload(payload))
        return cls.model_validate(payload)


def _safe_identifier(value: object, *, context: object = None) -> str:
    if context is None:
        return validate_sig03_identifier(value)
    return validate_sig03_identifier(
        value,
        _decode_budget=_decode_budget_from_context(context),
    )


def _sensitive_validation_error(model_name: str) -> ValidationError:
    return ValidationError.from_exception_data(
        model_name,
        [
            {
                "type": "value_error",
                "loc": (),
                "input": None,
                "ctx": {"error": ValueError("artifact text is not safe")},
            }
        ],
    )


def _scan_sensitive_plain(
    value: object,
    *,
    seen: set[int],
    budget: Any,
    depth: int = 0,
) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise ValueError("artifact text is not safe")
    if type(value) is str:
        try:
            validate_sig03_identifier(value, _decode_budget=budget)
        except (TypeError, ValueError) as exc:
            raise ValueError("artifact text is not safe") from exc
        return
    if type(value) in (int, bool, type(None), Decimal, _Date) or type(value) in _SAFE_ENUM_TYPES or type(value) is QuantSignalReasonCode:
        return
    if type(value) is _DateTime:
        if object.__getattribute__(value, "tzinfo") is not _Timezone.utc:
            raise ValueError("artifact text is not safe")
        return
    if type(value) in (dict, list, tuple):
        identity = id(value)
        if identity in seen:
            raise ValueError("artifact text is not safe")
        seen.add(identity)
        try:
            if type(value) is dict:
                if dict.__len__(value) > 64:
                    raise ValueError("artifact text is not safe")
                keys = tuple(dict.keys(value))
                if any(type(key) is not str for key in keys):
                    raise ValueError("artifact text is not safe")
                for key in keys:
                    _scan_sensitive_plain(
                        key, seen=seen, budget=budget, depth=depth + 1
                    )
                    _scan_sensitive_plain(
                        dict.__getitem__(value, key),
                        seen=seen,
                        budget=budget,
                        depth=depth + 1,
                    )
            else:
                for item in value:
                    _scan_sensitive_plain(
                        item, seen=seen, budget=budget, depth=depth + 1
                    )
        finally:
            seen.remove(identity)
        return
    local_types = tuple(
        item
        for item in (
            globals().get("FeatureSpec"),
            globals().get("FeatureConfiguration"),
            globals().get("FeatureObservation"),
            globals().get("FeatureSet"),
        )
        if isinstance(item, type)
    )
    if type(value) in local_types:
        storage = object.__getattribute__(value, "__dict__")
        if type(storage) is not dict:
            raise ValueError("artifact text is not safe")
        _scan_sensitive_plain(
            storage, seen=seen, budget=budget, depth=depth + 1
        )
        return
    raise ValueError("artifact text is not safe")


def _prevalidate_sensitive(
    model: type[object],
    value: object,
    budget: Any,
) -> None:
    try:
        _scan_sensitive_plain(
            value,
            seen=set(),
            budget=budget,
        )
    except (TypeError, ValueError) as exc:
        raise _sensitive_validation_error(model.__name__) from exc


def _decimal(value: object, *, places: int = DECIMAL_PLACES) -> Decimal:
    if type(value) in (bool, float) or not (type(value) is Decimal or type(value) in (int, str)):
        raise QuantInputError("decimal inputs require exact integer/string/Decimal values")
    try:
        decimal = value if type(value) is Decimal else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise QuantInputError("invalid decimal input") from exc
    if not decimal.is_finite() or abs(decimal.as_tuple().exponent) > 64 or len(decimal.as_tuple().digits) > 64:
        raise QuantInputError("decimal input exceeds SIG-03 bound")
    with localcontext(_fixed_decimal_context()):
        try:
            result = decimal.quantize(Decimal(1).scaleb(-places))
        except InvalidOperation as exc:
            raise QuantInputError("decimal input exceeds SIG-03 precision") from exc
    return Decimal("0").quantize(Decimal(1).scaleb(-places)) if result == 0 else result


def _hash_json(domain: str, payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise QuantInputError("canonical quant bytes are invalid") from exc
    canonical = domain.encode("utf-8") + encoded
    if len(canonical) > MAX_CANONICAL_BYTES:
        raise QuantInputError("canonical quant bytes exceed bound")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _spec_payload(spec: FeatureSpec) -> dict[str, object]:
    return {
        "schema_version": spec.schema_version,
        "feature_id": spec.feature_id,
        "feature_version": spec.feature_version,
        "kind": spec.kind,
        "bar_source": spec.bar_source,
        "interval": spec.interval,
        "adjustment_basis": spec.adjustment_basis.value,
        "adjustment_version": spec.adjustment_version,
        "lookback_sessions": spec.lookback_sessions,
        "required": spec.required,
    }


def _configuration_payload(value: FeatureConfiguration | dict[str, object]) -> dict[str, object]:
    if isinstance(value, FeatureConfiguration):
        fields: dict[str, object] = {
            "schema_version": value.schema_version,
            "configuration_id": value.configuration_id,
            "configuration_version": value.configuration_version,
            "universe_id": value.universe_id,
            "calendar_id": value.calendar_id,
            "horizon_sessions": value.horizon_sessions,
            "features": [_spec_payload(item) for item in value.features],
        }
    else:
        fields = {
            key: value[key]
            for key in (
                "schema_version",
                "configuration_id",
                "configuration_version",
                "universe_id",
                "calendar_id",
                "horizon_sessions",
            )
        }
        fields["features"] = [
            _spec_payload(item) if isinstance(item, FeatureSpec) else item
            for item in value["features"]  # type: ignore[index]
        ]
    for key in ("as_of", "knowledge_cutoff"):
        value = fields.get(key)
        if hasattr(value, "isoformat"):
            fields[key] = value.isoformat().replace("+00:00", "Z")
    return fields


def _feature_configuration_hash(
    value: object,
    *,
    context: object,
) -> str:
    fields = _copy_local_model(
        value,
        FeatureConfiguration,
        tuple(FeatureConfiguration.model_fields),
    )
    features = fields["features"]
    if (
        type(features) is not tuple
        or len(features) == 0
        or len(features) > MAX_FEATURES
    ):
        raise QuantInputError("feature configuration features exceed bound")
    if any(
        type(item) is not FeatureSpec for item in features
    ):
        raise QuantInputError("feature configuration features are not canonical")
    _prevalidate_sensitive(
        FeatureConfiguration,
        fields,
        _decode_budget_from_context(context),
    )
    fields["features"] = tuple(
        _copy_feature_spec(item, context=context) for item in features
    )
    return _hash_json(
        HASH_DOMAIN_FEATURE_CONFIGURATION,
        _configuration_payload(fields),
    )


def feature_configuration_hash(value: FeatureConfiguration) -> str:
    return _feature_configuration_hash(
        value,
        context=_new_sig03_validation_context(),
    )


def feature_schema_hash(features: tuple[FeatureSpec, ...] | list[FeatureSpec]) -> str:
    if (
        type(features) not in (tuple, list)
        or len(features) == 0
        or len(features) > MAX_FEATURES
    ):
        raise QuantInputError("feature schema exceeds bound")
    context = _new_sig03_validation_context()
    copied = tuple(_copy_feature_spec(item, context=context) for item in features)
    return _hash_json(
        HASH_DOMAIN_FEATURE_SCHEMA,
        [_spec_payload(item) for item in sorted(copied, key=lambda item: item.feature_id)],
    )


def _observation_payload(value: FeatureObservation) -> dict[str, object]:
    return value.model_dump(mode="json")


def _feature_set_payload(value: FeatureSet | dict[str, object]) -> dict[str, object]:
    if isinstance(value, FeatureSet):
        fields = value.model_dump(mode="json")
    else:
        fields = {
            key: value[key]
            for key in (
                "schema_version",
                "bundle_id",
                "bundle_hash",
                "instrument_id",
                "as_of",
                "knowledge_cutoff",
                "horizon_sessions",
                "configuration_id",
                "configuration_version",
                "feature_config_hash",
                "feature_schema_hash",
                "observations",
                "missing_required_feature_ids",
                "missing_optional_feature_ids",
                "status",
                "reason_codes",
            )
        }
    fields.pop("feature_hash", None)
    for key in ("as_of", "knowledge_cutoff"):
        field_value = fields.get(key)
        if hasattr(field_value, "isoformat"):
            fields[key] = field_value.isoformat().replace("+00:00", "Z")
    fields["observations"] = [
        _observation_payload(item) if isinstance(item, FeatureObservation) else item
        for item in fields["observations"]
    ]
    fields["reason_codes"] = [
        item.value if isinstance(item, QuantSignalReasonCode) else item
        for item in fields["reason_codes"]
    ]
    return fields


def _feature_set_hash(value: object, *, context: object) -> str:
    fields = _copy_local_model(value, FeatureSet, tuple(FeatureSet.model_fields))
    for field in (
        "observations",
        "missing_required_feature_ids",
        "missing_optional_feature_ids",
        "reason_codes",
    ):
        collection = fields[field]
        if type(collection) is not tuple or len(collection) > MAX_FEATURES:
            raise QuantInputError("feature set collection exceeds bound")
    observations = fields["observations"]
    if any(
        type(item) is not FeatureObservation for item in observations
    ):
        raise QuantInputError("feature set observations are not canonical")
    _prevalidate_sensitive(
        FeatureSet,
        fields,
        _decode_budget_from_context(context),
    )
    fields["observations"] = tuple(
        FeatureObservation.model_construct(
            **_copy_local_model(
                item,
                FeatureObservation,
                tuple(FeatureObservation.model_fields),
            )
        )
        for item in observations
    )
    return _hash_json(HASH_DOMAIN_FEATURE_SET, _feature_set_payload(fields))


def feature_set_hash(value: FeatureSet) -> str:
    return _feature_set_hash(value, context=_new_sig03_validation_context())


_MAX_BUNDLE_WALK_NODES = 100_000
_MODEL_FIELDS: dict[type[object], tuple[str, ...]] = {
    cls: tuple(cls.model_fields)
    for cls in (
        EvidenceBundle,
        EvidenceRequirement,
        MissingEvidence,
        TradingCalendar,
        CalendarCoverageRange,
        CalendarClosure,
        TradingSession,
        Instrument,
        SymbolAlias,
        UniverseMembership,
        TickerChangeAction,
        SplitAction,
        DividendAction,
        DelistingAction,
        DailyBar,
        FinancialFiling,
        FinancialFact,
        NewsEvent,
        SocialPost,
        MacroObservation,
        SourceManifest,
    )
}
_SAFE_ENUM_TYPES = (
    ActionType,
    AdjustmentBasis,
    AssetClass,
    BarFinality,
    BundleReplayPolicy,
    EvidenceDomain,
    EventKind,
    MacroFrequency,
    ReplayPolicy,
    ReportingPeriod,
    SessionType,
    SocialPlatform,
    StatementType,
    UnitScale,
)


def _raw_fields(value: object, expected: type[object]) -> dict[str, object]:
    if type(value) is not expected:
        raise QuantInputError("quant input contains an unexpected contract type")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise QuantInputError("quant input storage is unavailable") from exc
    if type(storage) is not dict:
        raise QuantInputError("quant input storage is not plain data")
    fields = _MODEL_FIELDS[expected]
    if dict.__len__(storage) != len(fields):
        raise QuantInputError("quant input fields are not canonical")
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(fields):
        raise QuantInputError("quant input fields are not canonical")
    return {field: dict.__getitem__(storage, field) for field in fields}


def _safe_bundle_value(
    value: object,
    *,
    seen: set[int],
    depth: int,
    nodes: list[int],
) -> object:
    nodes[0] += 1
    if nodes[0] > _MAX_BUNDLE_WALK_NODES or depth > MAX_NESTING_DEPTH:
        raise QuantInputError("quant evidence exceeds structural bounds")
    value_type = type(value)
    if value_type is str:
        if len(value) > MAX_IDENTIFIER_LENGTH * 32:
            raise QuantInputError("quant text exceeds structural bounds")
        try:
            encoded = value.encode("utf-8", "strict")
        except UnicodeError as exc:
            raise QuantInputError("quant text is not valid UTF-8") from exc
        if len(encoded) > MAX_IDENTIFIER_LENGTH * 32:
            raise QuantInputError("quant text exceeds structural bounds")
        return value
    if value_type in (int, bool, type(None)):
        return value
    if value_type is Decimal:
        if (
            not value.is_finite()
            or abs(value.as_tuple().exponent) > 64
            or len(value.as_tuple().digits) > 64
        ):
            raise QuantInputError("quant decimal exceeds structural bounds")
        return value
    if value_type is float:
        raise QuantInputError("quant evidence does not accept float values")
    if value_type is _DateTime:
        if object.__getattribute__(value, "tzinfo") is not _Timezone.utc:
            raise QuantInputError("quant timestamps require exact UTC")
        return value
    if value_type is _Date:
        return value
    if value_type in _SAFE_ENUM_TYPES:
        return value
    if value_type in _MODEL_FIELDS:
        identity = id(value)
        if identity in seen:
            raise QuantInputError("quant evidence contains a cycle")
        seen.add(identity)
        try:
            fields = _raw_fields(value, value_type)
            return {
                key: _safe_bundle_value(item, seen=seen, depth=depth + 1, nodes=nodes)
                for key, item in fields.items()
            }
        finally:
            seen.remove(identity)
    if value_type in (tuple, list):
        identity = id(value)
        if identity in seen:
            raise QuantInputError("quant evidence contains a cycle")
        seen.add(identity)
        try:
            copied = tuple(
                _safe_bundle_value(item, seen=seen, depth=depth + 1, nodes=nodes)
                for item in value
            )
            return copied if value_type is tuple else list(copied)
        finally:
            seen.remove(identity)
    if value_type is dict:
        if dict.__len__(value) > (_MAX_BUNDLE_WALK_NODES - nodes[0]) // 2:
            raise QuantInputError("quant evidence exceeds structural bounds")
        identity = id(value)
        if identity in seen:
            raise QuantInputError("quant evidence contains a cycle")
        seen.add(identity)
        try:
            keys = tuple(dict.keys(value))
            if any(type(key) is not str for key in keys):
                raise QuantInputError("quant mappings require exact string keys")
            result: dict[str, object] = {}
            for key in keys:
                result[key] = _safe_bundle_value(
                    dict.__getitem__(value, key),
                    seen=seen,
                    depth=depth + 1,
                    nodes=nodes,
                )
            return result
        finally:
            seen.remove(identity)
    raise QuantInputError("quant evidence contains an unsupported object")


def _validated_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    if type(bundle) is not EvidenceBundle:
        raise QuantInputError("evidence bundle requires exact sealed type")
    root_fields = _raw_fields(bundle, EvidenceBundle)
    payload = _safe_bundle_value(root_fields, seen=set(), depth=0, nodes=[0])
    if type(payload) is not dict:
        raise QuantInputError("evidence bundle did not normalize to an object")
    if type(payload.get("bars")) is not tuple or len(payload["bars"]) > MAX_BARS:
        raise QuantInputError("bar count exceeds SIG-03 bound")
    try:
        validated = EvidenceBundle.model_validate(payload)
    except QuantInputError:
        raise
    except Exception as exc:
        raise QuantInputError("sealed evidence bundle failed defensive validation") from exc
    if validated.bundle_hash != root_fields["bundle_hash"]:
        raise QuantInputError("sealed evidence bundle hash changed")
    return validated


def _copy_local_model(value: object, expected: type[object], fields: tuple[str, ...]) -> dict[str, object]:
    if type(value) is not expected:
        raise QuantInputError("quant input contains a hostile model instance")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise QuantInputError("quant model storage is unavailable") from exc
    if type(storage) is not dict or dict.__len__(storage) != len(fields):
        raise QuantInputError("quant model storage is not canonical")
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(fields):
        raise QuantInputError("quant model storage is not canonical")
    return {field: dict.__getitem__(storage, field) for field in fields}


def _copy_feature_spec(value: object, *, context: object = None) -> FeatureSpec:
    fields = _copy_local_model(value, FeatureSpec, tuple(FeatureSpec.model_fields))
    return _validate_sig03_nested_model(  # type: ignore[return-value]
        FeatureSpec,
        fields,
        context=context,
    )


def _copy_feature_configuration(value: object) -> FeatureConfiguration:
    context = _new_sig03_validation_context()
    fields = _copy_local_model(value, FeatureConfiguration, tuple(FeatureConfiguration.model_fields))
    features = fields["features"]
    if (
        type(features) is not tuple
        or len(features) == 0
        or len(features) > MAX_FEATURES
    ):
        raise QuantInputError("feature configuration features exceed bound")
    fields["features"] = tuple(
        _copy_feature_spec(item, context=context) for item in features
    )
    try:
        return _validate_sig03_nested_model(  # type: ignore[return-value]
            FeatureConfiguration,
            fields,
            context=context,
        )
    except QuantInputError:
        raise
    except Exception as exc:
        raise QuantInputError("feature configuration failed defensive validation") from exc


def _copy_feature_observation(
    value: object,
    *,
    context: object = None,
) -> FeatureObservation:
    fields = _copy_local_model(value, FeatureObservation, tuple(FeatureObservation.model_fields))
    return _validate_sig03_nested_model(  # type: ignore[return-value]
        FeatureObservation,
        fields,
        context=context,
    )


def _copy_feature_set(value: object) -> FeatureSet:
    context = _new_sig03_validation_context()
    fields = _copy_local_model(value, FeatureSet, tuple(FeatureSet.model_fields))
    observations = fields["observations"]
    if type(observations) is not tuple or len(observations) > MAX_FEATURES:
        raise QuantInputError("feature set observations exceed bound")
    try:
        fields["observations"] = tuple(
            _copy_feature_observation(item, context=context) for item in observations
        )
        return _validate_sig03_nested_model(  # type: ignore[return-value]
            FeatureSet,
            fields,
            context=context,
        )
    except QuantInputError:
        raise
    except Exception as exc:
        raise QuantInputError("feature set failed defensive validation") from exc


def _anchor(bundle: EvidenceBundle) -> tuple[Any | None, Any | None, QuantSignalReasonCode | None]:
    calendar = bundle.calendar
    try:
        cutoff_date = bundle.knowledge_cutoff.astimezone(
            ZoneInfo(calendar.timezone)
        ).date()
    except (ValueError, ZoneInfoNotFoundError):
        return (
            bundle.knowledge_cutoff,
            None,
            QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
        )
    coverage_range = next(
        (
            item
            for item in calendar.coverage_ranges
            if item.start <= cutoff_date <= item.end
        ),
        None,
    )
    if coverage_range is None:
        return (
            bundle.knowledge_cutoff,
            None,
            QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
        )
    try:
        eligible = tuple(
            session
            for session in calendar.sessions(coverage_range.start, cutoff_date)
            if session.close_at <= bundle.knowledge_cutoff
        )
    except CalendarError:
        eligible = ()
    if not eligible:
        return (
            bundle.knowledge_cutoff,
            None,
            QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
        )
    return eligible[-1].close_at, eligible[-1], None


def _compute_observation(
    bundle: EvidenceBundle,
    spec: FeatureSpec,
    *,
    instrument_id: str,
    anchor_session: Any | None,
    as_of: Any,
) -> FeatureObservation:
    if anchor_session is None:
        return _missing_observation(
            spec,
            as_of=as_of,
            anchor_session=None,
            reason=QuantSignalReasonCode.CALENDAR_SESSION_UNAVAILABLE,
        )
    sessions = bundle.calendar.schedule
    try:
        anchor_index = next(
            index for index, session in enumerate(sessions) if session.session_date == anchor_session.session_date
        )
    except StopIteration as exc:
        raise QuantInputError("anchor session is not in the sealed calendar") from exc
    lag_index = anchor_index - spec.lookback_sessions
    if lag_index < 0:
        return _missing_observation(
            spec,
            as_of=as_of,
            anchor_session=anchor_session.session_date.isoformat(),
            reason=QuantSignalReasonCode.INSUFFICIENT_LOOKBACK,
        )
    lag_session = sessions[lag_index]
    try:
        distance = bundle.calendar.session_distance(
            lag_session.session_date,
            anchor_session.session_date,
        )
        selected_sessions = bundle.calendar.sessions(
            lag_session.session_date,
            anchor_session.session_date,
        )
    except CalendarError:
        distance = -1
        selected_sessions = ()
    if distance != spec.lookback_sessions:
        return _missing_observation(
            spec,
            as_of=as_of,
            anchor_session=anchor_session.session_date.isoformat(),
            reason=QuantSignalReasonCode.INSUFFICIENT_LOOKBACK,
        )
    candidates = tuple(
        bar
        for bar in bundle.bars
        if bar.instrument_id == instrument_id
        and bar.calendar_id == bundle.calendar.calendar_id
        and bar.manifest.source == spec.bar_source
        and bar.interval == spec.interval
        and bar.adjustment_basis is spec.adjustment_basis
        and bar.adjustment_version == spec.adjustment_version
        and bar.session_date in {item.session_date for item in selected_sessions}
    )
    by_date: dict[Any, list[DailyBar]] = {}
    for bar in candidates:
        by_date.setdefault(bar.session_date, []).append(bar)
    if len(by_date.get(anchor_session.session_date, ())) != 1:
        return _missing_observation(
            spec,
            as_of=as_of,
            anchor_session=anchor_session.session_date.isoformat(),
            reason=QuantSignalReasonCode.EXACT_SESSION_BAR_MISSING,
        )
    if any(len(by_date.get(item.session_date, ())) != 1 for item in selected_sessions):
        return _missing_observation(
            spec,
            as_of=as_of,
            anchor_session=anchor_session.session_date.isoformat(),
            reason=QuantSignalReasonCode.INSUFFICIENT_LOOKBACK,
        )
    selected = tuple(by_date[item.session_date][0] for item in selected_sessions)
    lag = selected[0]
    anchor = selected[-1]
    try:
        with localcontext(_fixed_decimal_context()):
            value = _decimal((anchor.close / lag.close) - Decimal(1))
    except DecimalException as exc:
        raise QuantInputError("feature arithmetic is invalid") from exc
    return FeatureObservation(
        schema_version=CURRENT_SCHEMA_VERSION,
        feature_id=spec.feature_id,
        feature_version=spec.feature_version,
        value=value,
        required=spec.required,
        status="available",
        reason_code=None,
        as_of=as_of,
        anchor_session=anchor_session.session_date.isoformat(),
        lookback_sessions=spec.lookback_sessions,
        lookback_session=lag_session.session_date.isoformat(),
        latest_available_at=max(item.manifest.available_at for item in selected),
        source_bar_ids=tuple(item.bar_id for item in selected),
        source_manifest_ids=tuple(item.manifest.manifest_id for item in selected),
        source_revisions=tuple(item.manifest.revision for item in selected),
        source_session_dates=tuple(item.session_date.isoformat() for item in selected),
    )


def _missing_observation(
    spec: FeatureSpec,
    *,
    as_of: Any,
    anchor_session: str | None,
    reason: QuantSignalReasonCode,
) -> FeatureObservation:
    return FeatureObservation(
        schema_version=CURRENT_SCHEMA_VERSION,
        feature_id=spec.feature_id,
        feature_version=spec.feature_version,
        value=None,
        required=spec.required,
        status="missing",
        reason_code=reason,
        as_of=as_of,
        anchor_session=anchor_session,
        lookback_sessions=spec.lookback_sessions,
        lookback_session=None,
        latest_available_at=None,
        source_bar_ids=(),
        source_manifest_ids=(),
        source_revisions=(),
        source_session_dates=(),
    )


__all__ = [
    "DECIMAL_PLACES",
    "FeatureConfiguration",
    "FeatureObservation",
    "FeatureSet",
    "FeatureSpec",
    "HASH_DOMAIN_FEATURE_CONFIGURATION",
    "HASH_DOMAIN_FEATURE_SCHEMA",
    "HASH_DOMAIN_FEATURE_SET",
    "MAX_BARS",
    "MAX_CANONICAL_BYTES",
    "MAX_FEATURES",
    "MAX_HORIZON_SESSIONS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_LOOKBACK_SESSIONS",
    "MAX_PROVENANCE_ITEMS",
    "MAX_NESTING_DEPTH",
    "QuantInputError",
    "_copy_feature_configuration",
    "_copy_feature_set",
    "feature_configuration_hash",
    "feature_schema_hash",
    "feature_set_hash",
]
