"""Stateless deterministic QuantSignal scoring for SIG-03."""

from __future__ import annotations

import hashlib
import json
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    Rounded,
    localcontext,
)

from mytradingalpha.contracts.signals import (
    QuantSignal,
    QuantSignalReasonCode,
    QuantSignalStatus,
    _new_sensitive_prevalidation_budget,
    validate_sig03_identifier,
)
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION
from mytradingalpha.data.bundle import EvidenceBundle

from .features import (
    DECIMAL_PLACES,
    MAX_CANONICAL_BYTES,
    MAX_FEATURES,
    MAX_HORIZON_SESSIONS,
    MAX_IDENTIFIER_LENGTH,
    MAX_NESTING_DEPTH,
    FeatureConfiguration,
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


def _fixed_decimal_context() -> Context:
    context = Context(prec=64, rounding=ROUND_HALF_EVEN)
    context.traps[Inexact] = False
    context.traps[Rounded] = False
    return context


def _prevalidate_signal_sensitive(model: type[object], value: object) -> None:
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
    try:
        return validate_sig03_identifier(value)
    except (TypeError, ValueError) as exc:
        raise QuantInputError("run_id is not artifact-safe") from exc


class QuantSignalModel:
    """Pure scoring object; it stores no mutable run or provider state."""

    __slots__ = ("_artifact",)

    def __init__(self, model_artifact: ModelArtifact) -> None:
        if type(model_artifact) is not ModelArtifact:
            raise QuantInputError("model artifact requires exact type")
        self._artifact = _copy_model_artifact(model_artifact)

    def score(
        self,
        feature_set: FeatureSet,
        *,
        run_id: str,
        bundle: EvidenceBundle,
        configuration: FeatureConfiguration,
    ) -> QuantSignal:
        if type(feature_set) is not FeatureSet:
            raise QuantInputError("feature set requires exact type")
        run_id = _safe_run_id(run_id)
        features = _copy_feature_set(feature_set)
        try:
            expected_features = FeatureSet.compute(
                bundle=bundle,
                configuration=configuration,
                instrument_id=features.instrument_id,
            )
        except Exception as exc:
            raise QuantInputError("scoring provenance is invalid") from exc
        if (
            features.feature_hash != expected_features.feature_hash
            or features.model_dump(mode="json")
            != expected_features.model_dump(mode="json")
        ):
            raise QuantInputError("scoring provenance does not match sealed inputs")
        artifact = _copy_model_artifact(self._artifact)
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
        for model_feature, observation in zip(
            artifact.features, features.observations, strict=True
        ):
            if (
                model_feature.feature_id != observation.feature_id
                or model_feature.feature_version != observation.feature_version
                or model_feature.required is not observation.required
                or model_feature.lookback_sessions != observation.lookback_sessions
            ):
                raise QuantInputError("model/feature schema mismatch")
        missing_required = tuple(features.missing_required_feature_ids)
        missing_optional = tuple(features.missing_optional_feature_ids)
        reasons = set(features.reason_codes)
        score: Decimal | None
        if features.status == "invalid" or missing_required:
            score = None
            if missing_required:
                reasons.add(QuantSignalReasonCode.REQUIRED_FEATURE_MISSING)
        else:
            try:
                with localcontext(_fixed_decimal_context()):
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
            except DecimalException as exc:
                raise QuantInputError("quant score decimal input is invalid") from exc
        if missing_optional:
            reasons.add(QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING)
        reason_codes = tuple(sorted(reasons, key=lambda item: _REASON_ORDER[item]))
        if score is None:
            status = QuantSignalStatus.INVALID
        elif missing_optional:
            status = QuantSignalStatus.DEGRADED
        else:
            status = QuantSignalStatus.VALID
        if status is QuantSignalStatus.DEGRADED:
            reason_codes = (QuantSignalReasonCode.OPTIONAL_FEATURE_MISSING,)
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
