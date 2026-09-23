"""Stateless deterministic QuantSignal scoring for SIG-03."""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from mytradingalpha.contracts.redaction import validate_artifact_text
from mytradingalpha.contracts.signals import (
    QuantSignal,
    QuantSignalReasonCode,
    QuantSignalStatus,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .features import (
    DECIMAL_PLACES,
    MAX_CANONICAL_BYTES,
    MAX_FEATURES,
    MAX_HORIZON_SESSIONS,
    MAX_IDENTIFIER_LENGTH,
    MAX_NESTING_DEPTH,
    FeatureSet,
    QuantInputError,
    _copy_feature_set,
    _sensitive_validation_error,
)
from .models import (
    ModelArtifact,
    _copy_model_artifact,
    model_artifact_hash,
)

HASH_DOMAIN_QUANT_SIGNAL = "mytradingalpha:sig03:quant-signal:v1\0"
_REASON_ORDER = {item: index for index, item in enumerate(QuantSignalReasonCode)}


def _prevalidate_signal_sensitive(model: type[object], value: object) -> None:
    seen: set[int] = set()

    def walk(item: object, depth: int = 0) -> None:
        if depth > MAX_NESTING_DEPTH:
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
        raise _sensitive_validation_error(model.__name__) from exc


def _canonical_hash(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise QuantInputError("canonical signal bytes are invalid") from exc
    canonical = HASH_DOMAIN_QUANT_SIGNAL.encode("utf-8") + encoded
    if len(canonical) > MAX_CANONICAL_BYTES:
        raise QuantInputError("canonical signal bytes exceed bound")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _safe_run_id(value: object) -> str:
    if type(value) is not str:
        raise QuantInputError("run_id exceeds SIG-03 bound")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise QuantInputError("run_id contains a surrogate")
    if not value or len(value.encode("utf-8")) > MAX_IDENTIFIER_LENGTH:
        raise QuantInputError("run_id exceeds SIG-03 bound")
    if any(word in value.casefold() for word in ("api-key", "apikey", "credential", "password", "secret", "token")):
        raise QuantInputError("run_id is not artifact-safe")
    return value


class QuantSignalModel:
    """Pure scoring object; it stores no mutable run or provider state."""

    __slots__ = ("_artifact",)

    def __init__(self, model_artifact: ModelArtifact) -> None:
        if type(model_artifact) is not ModelArtifact:
            raise QuantInputError("model artifact requires exact type")
        self._artifact = _copy_model_artifact(model_artifact)

    def score(self, feature_set: FeatureSet, *, run_id: str) -> QuantSignal:
        if type(feature_set) is not FeatureSet:
            raise QuantInputError("feature set requires exact type")
        run_id = _safe_run_id(run_id)
        features = _copy_feature_set(feature_set)
        artifact = self._artifact
        if artifact.feature_config_hash != features.feature_config_hash:
            raise QuantInputError("model/configuration hash mismatch")
        if artifact.feature_schema_hash != features.feature_schema_hash:
            raise QuantInputError("model/schema hash mismatch")
        if artifact.horizon_sessions != features.horizon_sessions:
            raise QuantInputError("model/feature horizon mismatch")
        observations = {item.feature_id: item for item in features.observations}
        artifact_ids = tuple(item.feature_id for item in artifact.features)
        feature_ids = tuple(item.feature_id for item in features.observations)
        if artifact_ids != feature_ids:
            raise QuantInputError("model/feature identifiers mismatch")
        missing_required = tuple(features.missing_required_feature_ids)
        missing_optional = tuple(features.missing_optional_feature_ids)
        reasons = set(features.reason_codes)
        score: Decimal | None
        if features.status == "invalid" or missing_required:
            score = None
            if missing_required:
                reasons.add(QuantSignalReasonCode.REQUIRED_FEATURE_MISSING)
        else:
            with localcontext() as context:
                context.prec = 64
                context.rounding = ROUND_HALF_EVEN
                total = artifact.intercept
                for feature in artifact.features:
                    observation = observations[feature.feature_id]
                    value = observation.value
                    if value is None:
                        if feature.required:
                            score = None
                            reasons.add(QuantSignalReasonCode.REQUIRED_FEATURE_MISSING)
                            break
                        value = feature.missing_value
                        reasons.add(QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING)
                    total += value * feature.weight  # type: ignore[operator]
                else:
                    quantum = Decimal(1).scaleb(-DECIMAL_PLACES)
                    score = total.quantize(quantum)
                    score = max(artifact.score_min, min(artifact.score_max, score))
                    score = score.quantize(quantum)
        if missing_optional:
            reasons.add(QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING)
        reason_codes = tuple(sorted(reasons, key=lambda item: _REASON_ORDER[item]))
        if score is None:
            status = QuantSignalStatus.INVALID
        elif missing_optional:
            status = QuantSignalStatus.DEGRADED
        else:
            status = QuantSignalStatus.VALID
        payload: dict[str, object] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "run_id": run_id,
            "bundle_id": features.bundle_id,
            "bundle_hash": features.bundle_hash,
            "instrument_id": features.instrument_id,
            "as_of": features.as_of,
            "horizon_sessions": features.horizon_sessions,
            "score": score,
            "decimal_places": DECIMAL_PLACES,
            "feature_ids": feature_ids,
            "feature_schema_hash": features.feature_schema_hash,
            "feature_config_hash": features.feature_config_hash,
            "feature_hash": features.feature_hash,
            "model_id": artifact.model_id,
            "model_version": artifact.model_version,
            "model_hash": model_artifact_hash(artifact),
            "missing_required_feature_ids": missing_required,
            "missing_optional_feature_ids": missing_optional,
            "status": status,
            "reason_codes": reason_codes,
            "shadow_only": True,
        }
        canonical_payload = dict(payload)
        canonical_payload["as_of"] = features.as_of.isoformat().replace("+00:00", "Z")
        signal_hash = _canonical_hash(
            {
                **canonical_payload,
                "score": None if score is None else str(score),
                "status": status.value,
                "reason_codes": [item.value for item in reason_codes],
            }
        )
        payload["signal_id"] = f"quant-signal:{signal_hash.removeprefix('sha256:')}"
        return QuantSignal.model_validate(payload)


__all__ = [
    "HASH_DOMAIN_QUANT_SIGNAL",
    "MAX_CANONICAL_BYTES",
    "MAX_FEATURES",
    "MAX_HORIZON_SESSIONS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_NESTING_DEPTH",
    "QuantSignalModel",
]
