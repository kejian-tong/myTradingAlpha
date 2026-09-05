"""Canonical, exact-ID cached graph responses for SIG-01 closed replay."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from math import isfinite
from threading import RLock
from typing import Literal

from pydantic import TypeAdapter, ValidationError, model_validator

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.data.bundle import BundleReplayPolicy
from mytradingalpha.data.provenance import CanonicalChecksum, RequiredReference, SourceManifest
from tradingagents.graph.historical import (
    HistoricalRuntimeOutputError,
    validate_historical_response,
)

CACHED_RESPONSE_SCHEMA_VERSION = "v1"
MAX_CACHED_RESPONSE_BYTES = 4_194_304
MAX_CACHED_RESPONSE_DEPTH = 64
MAX_CACHED_RESPONSE_NODES = 100_000
MAX_CACHED_RESPONSE_STRING_BYTES = 1_048_576
_RESPONSE_HASH_DOMAIN = b"mytradingalpha.cached_graph_response.v1\x00"
_UTC_ADAPTER = TypeAdapter(UtcDateTime)


class CachedGraphResponseError(ValueError):
    """Base class for cached graph-response failures."""


class CachedGraphResponseUnavailableError(CachedGraphResponseError):
    """Raised when an exact response is absent or unavailable at the cutoff."""


class CachedGraphResponseCorruptionError(CachedGraphResponseError):
    """Raised when bytes, schema, limits, or hashes are invalid."""


class CachedGraphResponseConflictError(CachedGraphResponseError):
    """Raised when a response ID is reused for different immutable bytes."""


class CachedGraphResponseMismatchError(CachedGraphResponseError):
    """Raised when an exact selection or replay binding disagrees."""


class CachedGraphSelection(ContractModel):
    """Immutable exact response and artifact selection."""

    response_id: StableId
    expected_response_hash: CanonicalChecksum
    graph_artifact_id: StableId
    graph_artifact_hash: CanonicalChecksum
    model_artifact_id: StableId
    model_artifact_hash: CanonicalChecksum
    runtime_manifest_id: StableId
    runtime_manifest_hash: CanonicalChecksum


class _CachedGraphResponseFields(ContractModel):
    """Shared response fields used for typed preflight without error reclassification."""

    schema_version: Literal["v1"]
    response_id: StableId
    response_hash: CanonicalChecksum
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    knowledge_cutoff: UtcDateTime
    calendar_id: StableId
    replay_policy: BundleReplayPolicy
    variant_id: StableId
    trade_date: str
    ticker: StableId
    instrument_id: StableId
    asset_type: StableId
    instrument_context: RequiredReference
    graph_artifact_id: StableId
    graph_artifact_hash: CanonicalChecksum
    model_artifact_id: StableId
    model_artifact_hash: CanonicalChecksum
    runtime_manifest_id: StableId
    runtime_manifest_hash: CanonicalChecksum
    capture_manifest: SourceManifest
    output: dict[str, object]
    output_hash: CanonicalChecksum


class CachedGraphResponse(_CachedGraphResponseFields):
    """One immutable, cutoff-eligible cached Research Graph response."""

    @model_validator(mode="after")
    def validate_public_contract(self) -> CachedGraphResponse:
        _validate_intrinsic_record(self)
        _validate_availability(self)
        return self


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response is not canonical JSON data"
        ) from exc


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response strings must be valid UTF-8"
        ) from exc


def _normalise_plain(value: object, *, seen: set[int], depth: int, counter: list[int]) -> object:
    if depth > MAX_CACHED_RESPONSE_DEPTH:
        raise CachedGraphResponseCorruptionError("cached response exceeds maximum depth")
    counter[0] += 1
    if counter[0] > MAX_CACHED_RESPONSE_NODES:
        raise CachedGraphResponseCorruptionError("cached response exceeds maximum node count")
    value_type = type(value)
    if value_type is str:
        if _utf8_size(value) > MAX_CACHED_RESPONSE_STRING_BYTES:
            raise CachedGraphResponseCorruptionError("cached response string exceeds maximum size")
        return value
    if value_type is float:
        if not isfinite(value):
            raise CachedGraphResponseCorruptionError("cached response requires finite floats")
        return value
    if value_type in (int, bool, type(None)):
        return value
    if value_type not in (dict, list, tuple):
        raise CachedGraphResponseCorruptionError(
            "cached response accepts exact built-in JSON data only"
        )
    identity = id(value)
    if identity in seen:
        raise CachedGraphResponseCorruptionError("cached response contains a cycle")
    seen.add(identity)
    try:
        if value_type is dict:
            result: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise CachedGraphResponseCorruptionError(
                        "cached response object keys must be strings"
                    )
                if _utf8_size(key) > MAX_CACHED_RESPONSE_STRING_BYTES:
                    raise CachedGraphResponseCorruptionError(
                        "cached response key exceeds maximum string size"
                    )
                result[key] = _normalise_plain(item, seen=seen, depth=depth + 1, counter=counter)
            return result
        return [
            _normalise_plain(item, seen=seen, depth=depth + 1, counter=counter) for item in value
        ]
    finally:
        seen.remove(identity)


def _bounded_plain(value: object) -> object:
    return _normalise_plain(value, seen=set(), depth=1, counter=[0])


def _duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate cached response member")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite cached response number")


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("overflowed cached response number")
    return parsed


def _response_payload(record: _CachedGraphResponseFields) -> dict[str, object]:
    return record.model_dump(mode="json", exclude={"response_hash"})


def _expected_response_hash(record: _CachedGraphResponseFields) -> str:
    return _sha256(_RESPONSE_HASH_DOMAIN + _canonical_bytes(_response_payload(record)))


def _validate_trade_date(trade_date: object, cutoff: datetime) -> None:
    if type(trade_date) is not str:
        raise CachedGraphResponseMismatchError(
            "cached response trade date must be exact YYYY-MM-DD"
        )
    try:
        parsed = date.fromisoformat(trade_date)
    except (TypeError, ValueError) as exc:
        raise CachedGraphResponseMismatchError(
            "cached response trade date must be exact YYYY-MM-DD"
        ) from exc
    if parsed.isoformat() != trade_date or trade_date != cutoff.date().isoformat():
        raise CachedGraphResponseMismatchError(
            "cached response trade date does not equal UTC cutoff date"
        )


def _validate_intrinsic_record(record: _CachedGraphResponseFields) -> None:
    if type(record.capture_manifest) is not SourceManifest:
        raise CachedGraphResponseCorruptionError("cached response requires exact SourceManifest")
    normalised_output = _bounded_plain(record.output)
    if type(record.output) is not dict or normalised_output != record.output:
        raise CachedGraphResponseCorruptionError(
            "cached response contract requires canonical plain output"
        )
    output_bytes = _canonical_bytes(record.output)
    if record.output_hash != _sha256(output_bytes):
        raise CachedGraphResponseCorruptionError("cached response output hash mismatch")
    if record.capture_manifest.checksum != record.output_hash:
        raise CachedGraphResponseCorruptionError(
            "capture manifest checksum does not bind cached output"
        )
    if record.response_hash != _expected_response_hash(record):
        raise CachedGraphResponseCorruptionError("cached response hash mismatch")
    _validate_trade_date(record.trade_date, record.knowledge_cutoff)
    validate_historical_response(
        record.output,
        company_name=record.ticker,
        trade_date=record.trade_date,
        asset_type=record.asset_type,
        instrument_context=record.instrument_context,
    )


def _validate_availability(record: _CachedGraphResponseFields) -> None:
    if record.capture_manifest.available_at > record.knowledge_cutoff:
        raise CachedGraphResponseUnavailableError(
            "cached response was unavailable at knowledge cutoff"
        )
    if (
        record.replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
        and record.capture_manifest.ingested_at > record.knowledge_cutoff
    ):
        raise CachedGraphResponseUnavailableError(
            "cached response was not archived at knowledge cutoff"
        )


def parse_cached_graph_response(raw_record: bytes) -> CachedGraphResponse:
    """Parse exact bounded canonical UTF-8 JSON bytes and verify all hashes."""

    if type(raw_record) is not bytes:
        raise CachedGraphResponseCorruptionError("cached response parser requires exact bytes")
    if len(raw_record) > MAX_CACHED_RESPONSE_BYTES:
        raise CachedGraphResponseCorruptionError("cached response exceeds maximum record size")
    try:
        text = raw_record.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_constant,
            parse_float=_parse_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError) as exc:
        raise CachedGraphResponseCorruptionError(
            "invalid cached response encoding or JSON"
        ) from exc
    canonical_payload = _bounded_plain(payload)
    if type(canonical_payload) is not dict:
        raise CachedGraphResponseCorruptionError("cached response record must be an object")
    if _canonical_bytes(canonical_payload) != raw_record:
        raise CachedGraphResponseCorruptionError("cached response bytes are not canonical")
    try:
        fields = _CachedGraphResponseFields.model_validate(canonical_payload)
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response schema validation failed"
        ) from exc
    try:
        _validate_intrinsic_record(fields)
    except HistoricalRuntimeOutputError as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response output validation failed"
        ) from exc
    _validate_availability(fields)
    try:
        return CachedGraphResponse.model_validate(fields.model_dump(mode="python"))
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response public contract validation failed"
        ) from exc


def build_cached_graph_response(
    *,
    schema_version: Literal["v1"],
    response_id: str,
    bundle_id: str,
    bundle_hash: str,
    knowledge_cutoff: object,
    calendar_id: str,
    replay_policy: BundleReplayPolicy,
    variant_id: str,
    trade_date: str,
    ticker: str,
    instrument_id: str,
    asset_type: str,
    instrument_context: str,
    graph_artifact_id: str,
    graph_artifact_hash: str,
    model_artifact_id: str,
    model_artifact_hash: str,
    runtime_manifest_id: str,
    runtime_manifest_hash: str,
    capture_manifest: SourceManifest,
    output: dict[str, object],
) -> bytes:
    """Validate and seal one graph response as canonical UTF-8 JSON bytes."""

    if type(schema_version) is not str or schema_version != CACHED_RESPONSE_SCHEMA_VERSION:
        raise CachedGraphResponseCorruptionError("unsupported cached response schema")
    string_fields = (
        response_id,
        bundle_id,
        bundle_hash,
        calendar_id,
        variant_id,
        trade_date,
        ticker,
        instrument_id,
        asset_type,
        instrument_context,
        graph_artifact_id,
        graph_artifact_hash,
        model_artifact_id,
        model_artifact_hash,
        runtime_manifest_id,
        runtime_manifest_hash,
    )
    if any(type(value) is not str for value in string_fields):
        raise CachedGraphResponseCorruptionError("cached response metadata requires exact strings")
    if type(knowledge_cutoff) not in (str, datetime):
        raise CachedGraphResponseCorruptionError(
            "cached response knowledge cutoff requires a plain timestamp"
        )
    if type(replay_policy) is not BundleReplayPolicy:
        raise CachedGraphResponseCorruptionError(
            "cached response requires exact BundleReplayPolicy"
        )
    if type(capture_manifest) is not SourceManifest:
        raise CachedGraphResponseCorruptionError("cached response requires exact SourceManifest")
    normalised_output = _bounded_plain(output)
    if type(normalised_output) is not dict:
        raise CachedGraphResponseCorruptionError("cached response output must be an object")
    try:
        cutoff = _UTC_ADAPTER.validate_python(knowledge_cutoff)
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "invalid cached response knowledge cutoff"
        ) from exc
    _validate_trade_date(trade_date, cutoff)
    validate_historical_response(
        normalised_output,
        company_name=ticker,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    output_hash = _sha256(_canonical_bytes(normalised_output))
    if capture_manifest.checksum != output_hash:
        raise CachedGraphResponseCorruptionError(
            "capture manifest checksum does not bind cached output"
        )
    if capture_manifest.available_at > cutoff:
        raise CachedGraphResponseUnavailableError(
            "cached response was unavailable at knowledge cutoff"
        )
    if (
        replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
        and capture_manifest.ingested_at > cutoff
    ):
        raise CachedGraphResponseUnavailableError(
            "cached response was not archived at knowledge cutoff"
        )
    hash_payload: dict[str, object] = {
        "schema_version": schema_version,
        "response_id": response_id,
        "bundle_id": bundle_id,
        "bundle_hash": bundle_hash,
        "knowledge_cutoff": _UTC_ADAPTER.dump_python(cutoff, mode="json"),
        "calendar_id": calendar_id,
        "replay_policy": replay_policy.value,
        "variant_id": variant_id,
        "trade_date": trade_date,
        "ticker": ticker,
        "instrument_id": instrument_id,
        "asset_type": asset_type,
        "instrument_context": instrument_context,
        "graph_artifact_id": graph_artifact_id,
        "graph_artifact_hash": graph_artifact_hash,
        "model_artifact_id": model_artifact_id,
        "model_artifact_hash": model_artifact_hash,
        "runtime_manifest_id": runtime_manifest_id,
        "runtime_manifest_hash": runtime_manifest_hash,
        "capture_manifest": capture_manifest.model_dump(mode="json"),
        "output": normalised_output,
        "output_hash": output_hash,
    }
    payload = {
        **hash_payload,
        "response_hash": _sha256(_RESPONSE_HASH_DOMAIN + _canonical_bytes(hash_payload)),
    }
    try:
        fields = _CachedGraphResponseFields.model_validate(payload)
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response schema validation failed"
        ) from exc
    _validate_intrinsic_record(fields)
    _validate_availability(fields)
    try:
        record = CachedGraphResponse.model_validate(fields.model_dump(mode="python"))
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "cached response public contract validation failed"
        ) from exc
    raw = _canonical_bytes(record.model_dump(mode="json"))
    if len(raw) > MAX_CACHED_RESPONSE_BYTES:
        raise CachedGraphResponseCorruptionError("cached response exceeds maximum record size")
    parse_cached_graph_response(raw)
    return raw


class CachedGraphResponseRepository:
    """Thread-safe append-only in-memory storage of canonical response bytes."""

    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}
        self._lock = RLock()

    def seal(self, raw_record: bytes) -> CachedGraphResponse:
        record = parse_cached_graph_response(raw_record)
        with self._lock:
            existing = self._records.get(record.response_id)
            if existing is not None:
                checked = parse_cached_graph_response(existing)
                if checked.response_hash != record.response_hash or existing != raw_record:
                    raise CachedGraphResponseConflictError(
                        "response ID is already sealed with different bytes"
                    )
                return parse_cached_graph_response(existing)
            self._records[record.response_id] = raw_record
            return parse_cached_graph_response(raw_record)

    def get_bound(
        self,
        selection: CachedGraphSelection,
        *,
        bundle_id: str,
        bundle_hash: str,
        knowledge_cutoff: datetime,
        calendar_id: str,
        replay_policy: BundleReplayPolicy,
        variant_id: str,
        trade_date: str,
        ticker: str,
        instrument_id: str,
        asset_type: str,
        instrument_context: str,
    ) -> CachedGraphResponse:
        if type(selection) is not CachedGraphSelection:
            raise CachedGraphResponseMismatchError("cached response requires exact selection type")
        string_bindings = (
            bundle_id,
            bundle_hash,
            calendar_id,
            variant_id,
            trade_date,
            ticker,
            instrument_id,
            asset_type,
            instrument_context,
        )
        if any(type(value) is not str for value in string_bindings):
            raise CachedGraphResponseMismatchError(
                "cached response replay bindings require exact strings"
            )
        if type(knowledge_cutoff) is not datetime:
            raise CachedGraphResponseMismatchError(
                "cached response replay requires exact UTC cutoff type"
            )
        if type(replay_policy) is not BundleReplayPolicy:
            raise CachedGraphResponseMismatchError(
                "cached response replay requires exact policy type"
            )
        try:
            checked_selection = CachedGraphSelection.model_validate(
                selection.model_dump(mode="python")
            )
        except (TypeError, ValidationError, ValueError) as exc:
            raise CachedGraphResponseMismatchError("invalid cached response selection") from exc
        with self._lock:
            raw = self._records.get(checked_selection.response_id)
            if raw is None:
                raise CachedGraphResponseUnavailableError(
                    f"cached graph response not found: {checked_selection.response_id}"
                )
            record = parse_cached_graph_response(raw)
        for field in (
            "graph_artifact_id",
            "graph_artifact_hash",
            "model_artifact_id",
            "model_artifact_hash",
            "runtime_manifest_id",
            "runtime_manifest_hash",
        ):
            if getattr(checked_selection, field) != getattr(record, field):
                raise CachedGraphResponseMismatchError(
                    f"cached response selection mismatch: {field}"
                )
        if checked_selection.expected_response_hash != record.response_hash:
            raise CachedGraphResponseMismatchError("cached response selection hash mismatch")
        bindings = {
            "bundle_id": bundle_id,
            "bundle_hash": bundle_hash,
            "knowledge_cutoff": knowledge_cutoff,
            "calendar_id": calendar_id,
            "replay_policy": replay_policy,
            "variant_id": variant_id,
            "trade_date": trade_date,
            "ticker": ticker,
            "instrument_id": instrument_id,
            "asset_type": asset_type,
            "instrument_context": instrument_context,
        }
        for field, value in bindings.items():
            if getattr(record, field) != value:
                raise CachedGraphResponseMismatchError(f"cached response replay mismatch: {field}")
        return parse_cached_graph_response(raw)


__all__ = [
    "CACHED_RESPONSE_SCHEMA_VERSION",
    "MAX_CACHED_RESPONSE_BYTES",
    "MAX_CACHED_RESPONSE_DEPTH",
    "MAX_CACHED_RESPONSE_NODES",
    "MAX_CACHED_RESPONSE_STRING_BYTES",
    "CachedGraphResponse",
    "CachedGraphResponseConflictError",
    "CachedGraphResponseCorruptionError",
    "CachedGraphResponseError",
    "CachedGraphResponseMismatchError",
    "CachedGraphResponseRepository",
    "CachedGraphResponseUnavailableError",
    "CachedGraphSelection",
    "build_cached_graph_response",
    "parse_cached_graph_response",
]
