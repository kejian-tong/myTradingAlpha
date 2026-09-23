"""Plain-data deterministic model artifacts for SIG-03."""

from __future__ import annotations

import hashlib
import json
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    Rounded,
    localcontext,
)
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

from mytradingalpha.contracts.common import CanonicalChecksum, StableId
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.signals import (
    _new_sensitive_prevalidation_budget,
    validate_sig03_identifier,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION
from mytradingalpha.data.bars import AdjustmentBasis

from .features import (
    DECIMAL_PLACES,
    HASH_DOMAIN_FEATURE_SCHEMA,
    MAX_CANONICAL_BYTES,
    MAX_FEATURES,
    MAX_HORIZON_SESSIONS,
    MAX_IDENTIFIER_LENGTH,
    MAX_NESTING_DEPTH,
    QuantInputError,
    _plain_model_input,
    _sensitive_validation_error,
)

HASH_DOMAIN_MODEL_ARTIFACT = "mytradingalpha:sig03:model-artifact:v1\0"
_LOWER_HEX = frozenset("0123456789abcdef")


def _safe_identifier(value: object) -> str:
    return validate_sig03_identifier(value)


def _exact_canonical_checksum(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or value[:7] != "sha256:"
        or any(character not in _LOWER_HEX for character in value[7:])
    ):
        raise QuantInputError("model artifact checksum input is invalid")
    return value


def _fixed_decimal_context() -> Context:
    context = Context(prec=64, rounding=ROUND_HALF_EVEN)
    context.traps[Inexact] = False
    context.traps[Rounded] = False
    return context


def _prevalidate_model_sensitive(model: type[object], value: object) -> None:
    seen: set[int] = set()
    budget = _new_sensitive_prevalidation_budget()

    def walk(item: object, depth: int = 0) -> None:
        if depth > MAX_NESTING_DEPTH:
            raise ValueError
        if type(item) is str:
            validate_sig03_identifier(item, _decode_budget=budget)
            return
        if type(item) in (int, bool, type(None), Decimal, AdjustmentBasis):
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
        if type(item) in (ModelFeature, ModelArtifact):
            storage = object.__getattribute__(item, "__dict__")
            if type(storage) is not dict:
                raise ValueError
            walk(storage, depth + 1)
            return
        raise ValueError

    try:
        walk(value)
    except (TypeError, ValueError) as exc:
        raise _sensitive_validation_error(model.__name__) from exc


def _decimal(value: object, *, fixed: bool = True) -> Decimal:
    if type(value) in (bool, float) or not (type(value) is Decimal or type(value) in (int, str)):
        raise ValueError("model decimals require exact integer/string/Decimal values")
    try:
        decimal = value if type(value) is Decimal else Decimal(value)
    except Exception as exc:
        raise ValueError("invalid model decimal") from exc
    if not decimal.is_finite() or abs(decimal.as_tuple().exponent) > 64 or len(decimal.as_tuple().digits) > 64:
        raise ValueError("model decimal exceeds SIG-03 bound")
    with localcontext(_fixed_decimal_context()):
        try:
            result = decimal.quantize(Decimal(1).scaleb(-DECIMAL_PLACES))
            return Decimal(0).quantize(Decimal(1).scaleb(-DECIMAL_PLACES)) if result == 0 else result
        except InvalidOperation as exc:
            raise ValueError("model decimal exceeds SIG-03 precision") from exc


def _decimal_needs_normalization(value: object) -> bool:
    if type(value) is Decimal:
        return value.as_tuple().exponent != -DECIMAL_PLACES
    if type(value) is str:
        try:
            parsed = Decimal(value)
        except Exception:
            return False
        return parsed.is_finite() and parsed.as_tuple().exponent != -DECIMAL_PLACES
    return False


def _validate_raw_decimal(value: object, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if type(value) in (bool, float) or not (type(value) is Decimal or type(value) in (int, str)):
        raise QuantInputError("model decimal input is not an exact scalar")
    if type(value) is Decimal:
        decimal = value
    else:
        try:
            decimal = Decimal(value)
        except Exception as exc:
            raise QuantInputError("model decimal input is invalid") from exc
    if not decimal.is_finite() or abs(decimal.as_tuple().exponent) > 64 or len(decimal.as_tuple().digits) > 64:
        raise QuantInputError("model decimal input exceeds bound")


def _json_hash(domain: str, payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise QuantInputError("canonical model bytes are invalid") from exc
    canonical = domain.encode("utf-8") + encoded
    if len(canonical) > MAX_CANONICAL_BYTES:
        raise QuantInputError("canonical model bytes exceed bound")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


class ModelFeature(ContractModel):
    """A model's complete, repeated feature selector plus coefficient/default."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    feature_id: StableId
    feature_version: StableId
    kind: Literal["close_return"]
    bar_source: StableId
    interval: Literal["1d"]
    adjustment_basis: AdjustmentBasis
    adjustment_version: StableId | None
    lookback_sessions: StrictInt = Field(ge=1, le=252)
    required: StrictBool
    weight: Decimal
    missing_value: Decimal | None = None
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> ModelFeature:
        if type(obj) not in (dict, cls):
            raise ValueError("ModelFeature requires exact plain data")
        plain = _plain_model_input(cls, obj)
        _prevalidate_model_sensitive(cls, plain)
        return super().model_validate(plain, *args, **kwargs)

    @model_validator(mode="before")
    @classmethod
    def require_plain_data(cls, value: object) -> object:
        if type(value) is cls:
            storage = object.__getattribute__(value, "__dict__")
            if type(storage) is not dict:
                raise ValueError("ModelFeature storage must be plain data")
            return dict(storage)
        if type(value) is not dict:
            raise ValueError("ModelFeature requires exact plain data")
        return value

    @field_validator("feature_id", "feature_version", "bar_source")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _safe_identifier(value)

    @field_validator("adjustment_version")
    @classmethod
    def validate_adjustment_version(cls, value: str | None) -> str | None:
        return None if value is None else _safe_identifier(value)

    @field_validator("weight", "missing_value", mode="before")
    @classmethod
    def validate_decimal_inputs(cls, value: object) -> object:
        if value is None:
            return None
        return _decimal(value)

    @model_validator(mode="after")
    def validate_missing_value_policy(self) -> ModelFeature:
        if (self.adjustment_basis is AdjustmentBasis.UNADJUSTED) != (self.adjustment_version is None):
            raise ValueError("unadjusted bars require no version; adjusted bars require a version")
        if self.required and self.missing_value is not None:
            raise ValueError("required model features cannot have missing values")
        if not self.required and self.missing_value is None:
            raise ValueError("optional model features require an explicit default")
        return self


class ModelArtifact(ContractModel):
    """Immutable plain-data model artifact with a reproducible content hash."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    model_id: StableId
    model_version: StableId
    horizon_sessions: StrictInt = Field(ge=1, le=MAX_HORIZON_SESSIONS)
    decimal_places: Literal[12]
    score_min: Decimal
    score_max: Decimal
    feature_config_hash: CanonicalChecksum
    feature_schema_hash: CanonicalChecksum
    features: tuple[ModelFeature, ...]
    intercept: Decimal
    content_hash: CanonicalChecksum
    model_config = ConfigDict(
        extra="forbid", frozen=True, revalidate_instances="always", hide_input_in_errors=True
    )

    @classmethod
    def model_validate(cls, obj: object, *args: object, **kwargs: object) -> ModelArtifact:
        if type(obj) not in (dict, cls):
            raise ValueError("ModelArtifact requires exact plain data")
        plain = _plain_model_input(cls, obj)
        for field in ("feature_config_hash", "feature_schema_hash"):
            if field in plain:
                plain[field] = _exact_canonical_checksum(dict.__getitem__(plain, field))
        if (
            "feature_config_hash" in plain
            and dict.__getitem__(plain, "feature_config_hash") == "sha256:" + "0" * 64
        ):
            raise QuantInputError("model configuration hash is not bound")
        for field in ("score_min", "score_max", "intercept"):
            if field in plain:
                _validate_raw_decimal(dict.__getitem__(plain, field))
        if "features" in plain:
            features = dict.__getitem__(plain, "features")
            if type(features) not in (tuple, list):
                raise ValueError("model features require a plain sequence")
            if len(features) == 0 or len(features) > MAX_FEATURES:
                raise ValueError("model feature count exceeds SIG-03 bound")
            for feature in features:
                if type(feature) is ModelFeature:
                    storage = object.__getattribute__(feature, "__dict__")
                    if type(storage) is not dict:
                        raise QuantInputError("model feature storage is not plain data")
                    _validate_raw_decimal(dict.__getitem__(storage, "weight"))
                    _validate_raw_decimal(dict.__getitem__(storage, "missing_value"), allow_none=True)
                elif type(feature) is dict:
                    feature_plain = _plain_model_input(ModelFeature, feature)
                    if "weight" in feature_plain:
                        _validate_raw_decimal(dict.__getitem__(feature_plain, "weight"))
                    if "missing_value" in feature_plain:
                        _validate_raw_decimal(
                            dict.__getitem__(feature_plain, "missing_value"),
                            allow_none=True,
                        )
                else:
                    raise QuantInputError("model feature input is not exact plain data")
        _prevalidate_model_sensitive(cls, plain)
        try:
            return super().model_validate(plain, *args, **kwargs)
        except ValidationError as exc:
            errors = exc.errors(include_input=False)
            if len(errors) == 1 and errors[0].get("loc") == () and any(
                marker in str(errors[0].get("msg", ""))
                for marker in ("model artifact content hash mismatch", "model feature schema hash mismatch")
            ):
                raise QuantInputError("model artifact integrity mismatch") from exc
            raise

    @model_validator(mode="before")
    @classmethod
    def require_plain_data(cls, value: object) -> object:
        if type(value) is cls:
            storage = object.__getattribute__(value, "__dict__")
            if type(storage) is not dict:
                raise ValueError("ModelArtifact storage must be plain data")
            return dict(storage)
        if type(value) is not dict:
            raise ValueError("ModelArtifact requires exact plain data")
        return value

    @field_validator("model_id", "model_version")
    @classmethod
    def validate_model_ids(cls, value: str) -> str:
        return _safe_identifier(value)

    @field_validator("score_min", "score_max", mode="before")
    @classmethod
    def validate_model_decimals(cls, value: object) -> object:
        return _decimal(value, fixed=False)

    @field_validator("intercept", mode="before")
    @classmethod
    def validate_intercept(cls, value: object) -> object:
        return _decimal(value, fixed=True)

    @field_validator("features", mode="before")
    @classmethod
    def validate_model_features(cls, value: object) -> tuple[ModelFeature, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("model features require a plain sequence")
        if len(value) == 0 or len(value) > MAX_FEATURES:
            raise ValueError("model feature count exceeds SIG-03 bound")
        features = tuple(ModelFeature.model_validate(item) for item in value)
        if tuple(item.feature_id for item in features) != tuple(
            sorted(item.feature_id for item in features)
        ):
            raise ValueError("model features must be canonical and sorted")
        if len({item.feature_id for item in features}) != len(features):
            raise ValueError("model feature identifiers must be unique")
        return features

    @model_validator(mode="after")
    def validate_artifact(self) -> ModelArtifact:
        if self.score_min != Decimal("-1") or self.score_max != Decimal("1"):
            raise ValueError("SIG-03 score range is fixed to [-1, 1]")
        if self.score_min >= self.score_max:
            raise ValueError("invalid model score range")
        expected_schema = _model_feature_schema_hash(self.features)
        if self.feature_schema_hash != expected_schema:
            raise QuantInputError("model feature schema hash mismatch")
        expected = model_artifact_hash(self)
        if self.content_hash != expected:
            raise QuantInputError("model artifact content hash mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        model_id: str,
        model_version: str,
        horizon_sessions: int,
        decimal_places: int,
        score_min: Decimal,
        score_max: Decimal,
        feature_config_hash: str,
        feature_schema_hash: str,
        features: tuple[ModelFeature, ...] | list[ModelFeature],
        intercept: Decimal,
    ) -> ModelArtifact:
        if type(features) not in (tuple, list):
            raise QuantInputError("model artifact features require a plain sequence")
        if len(features) == 0 or len(features) > MAX_FEATURES:
            raise QuantInputError("model feature count exceeds SIG-03 bound")
        try:
            validated_model_id = _safe_identifier(model_id)
            validated_model_version = _safe_identifier(model_version)
        except (TypeError, ValueError) as exc:
            raise QuantInputError("model artifact identifier is invalid") from exc
        validated_features = tuple(ModelFeature.model_validate(item) for item in features)
        _validate_raw_decimal(score_min)
        _validate_raw_decimal(score_max)
        _validate_raw_decimal(intercept)
        normalized_score_min = _decimal(score_min, fixed=False)
        normalized_score_max = _decimal(score_max, fixed=False)
        normalized_intercept = _decimal(intercept, fixed=True)
        validated_feature_config_hash = _exact_canonical_checksum(feature_config_hash)
        validated_feature_schema_hash = _exact_canonical_checksum(feature_schema_hash)
        fields: dict[str, object] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "model_id": validated_model_id,
            "model_version": validated_model_version,
            "horizon_sessions": horizon_sessions,
            "decimal_places": decimal_places,
            "score_min": normalized_score_min,
            "score_max": normalized_score_max,
            "feature_config_hash": validated_feature_config_hash,
            "feature_schema_hash": validated_feature_schema_hash,
            "features": tuple(
                sorted(validated_features, key=lambda item: item.feature_id)
            ),
            "intercept": normalized_intercept,
        }
        fields["content_hash"] = _json_hash(HASH_DOMAIN_MODEL_ARTIFACT, _artifact_payload(fields))
        return cls.model_validate(fields)


def _model_feature_payload(feature: ModelFeature) -> dict[str, object]:
    return {
        "schema_version": feature.schema_version,
        "feature_id": feature.feature_id,
        "feature_version": feature.feature_version,
        "kind": feature.kind,
        "bar_source": feature.bar_source,
        "interval": feature.interval,
        "adjustment_basis": feature.adjustment_basis,
        "adjustment_version": feature.adjustment_version,
        "lookback_sessions": feature.lookback_sessions,
        "required": feature.required,
        "weight": format(feature.weight, ".12f"),
        **(
            {"missing_value": format(feature.missing_value, ".12f")}
            if feature.missing_value is not None
            else {}
        ),
    }


def _model_feature_schema_hash(features: tuple[ModelFeature, ...]) -> str:
    payload = [
        {
            key: value
            for key, value in _model_feature_payload(feature).items()
            if key not in {"weight", "missing_value"}
        }
        for feature in features
    ]
    return _json_hash(HASH_DOMAIN_FEATURE_SCHEMA, payload)


def _artifact_payload(value: ModelArtifact | dict[str, object]) -> dict[str, object]:
    if isinstance(value, ModelArtifact):
        return {
            "schema_version": value.schema_version,
            "model_id": value.model_id,
            "model_version": value.model_version,
            "horizon_sessions": value.horizon_sessions,
            "decimal_places": value.decimal_places,
            "score_min": str(value.score_min.normalize()),
            "score_max": str(value.score_max.normalize()),
            "feature_config_hash": value.feature_config_hash,
            "feature_schema_hash": value.feature_schema_hash,
            "features": [_model_feature_payload(item) for item in value.features],
            "intercept": format(value.intercept, ".12f"),
        }
    features = value["features"]
    normalized_features = [
        _model_feature_payload(item) if isinstance(item, ModelFeature) else item
        for item in features  # type: ignore[union-attr]
    ]
    score_min = value["score_min"]
    score_max = value["score_max"]
    intercept = value["intercept"]
    return {
        "schema_version": value["schema_version"],
        "model_id": value["model_id"],
        "model_version": value["model_version"],
        "horizon_sessions": value["horizon_sessions"],
        "decimal_places": value["decimal_places"],
        "score_min": str(score_min.normalize()) if type(score_min) is Decimal else str(score_min),
        "score_max": str(score_max.normalize()) if type(score_max) is Decimal else str(score_max),
        "feature_config_hash": value["feature_config_hash"],
        "feature_schema_hash": value["feature_schema_hash"],
        "features": normalized_features,
        "intercept": format(intercept, ".12f") if type(intercept) is Decimal else str(intercept),
    }


def model_artifact_hash(value: ModelArtifact) -> str:
    return _json_hash(HASH_DOMAIN_MODEL_ARTIFACT, _artifact_payload(value))


def _copy_model_feature(value: object) -> ModelFeature:
    if type(value) is not ModelFeature:
        raise QuantInputError("model feature requires exact type")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise QuantInputError("model feature storage is unavailable") from exc
    fields = tuple(ModelFeature.model_fields)
    keys = tuple(dict.keys(storage)) if type(storage) is dict else ()
    if type(storage) is not dict or any(type(key) is not str for key in keys) or set(keys) != set(fields):
        raise QuantInputError("model feature storage is not canonical")
    return ModelFeature.model_validate({field: dict.__getitem__(storage, field) for field in fields})


def _copy_model_artifact(value: object) -> ModelArtifact:
    if type(value) is not ModelArtifact:
        raise QuantInputError("model artifact requires exact type")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise QuantInputError("model artifact storage is unavailable") from exc
    fields = tuple(ModelArtifact.model_fields)
    keys = tuple(dict.keys(storage)) if type(storage) is dict else ()
    if type(storage) is not dict or any(type(key) is not str for key in keys) or set(keys) != set(fields):
        raise QuantInputError("model artifact storage is not canonical")
    payload = {field: dict.__getitem__(storage, field) for field in fields}
    features = payload["features"]
    if type(features) is not tuple:
        raise QuantInputError("model artifact features are not canonical")
    payload["features"] = tuple(_copy_model_feature(item) for item in features)
    original_hash = payload["content_hash"]
    try:
        validated = ModelArtifact.model_validate(payload)
    except QuantInputError:
        raise
    except Exception as exc:
        raise QuantInputError("model artifact failed defensive validation") from exc
    if original_hash != model_artifact_hash(validated):
        raise QuantInputError("model artifact hash changed after validation")
    return validated


__all__ = [
    "HASH_DOMAIN_MODEL_ARTIFACT",
    "MAX_CANONICAL_BYTES",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_NESTING_DEPTH",
    "ModelArtifact",
    "ModelFeature",
    "_copy_model_artifact",
    "model_artifact_hash",
]
