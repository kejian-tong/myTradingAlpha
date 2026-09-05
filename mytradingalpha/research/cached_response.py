"""Canonical, exact-ID cached graph responses for SIG-01 closed replay."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from math import isfinite
from threading import RLock
from typing import Literal

from pydantic import ConfigDict, TypeAdapter, ValidationError, model_validator

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
_SOURCE_MANIFEST_FIELDS = (
    "schema_version",
    "manifest_id",
    "source",
    "source_locator",
    "fetched_at",
    "event_time",
    "published_at",
    "available_at",
    "ingested_at",
    "checksum",
    "terms",
    "revision",
)
_SOURCE_MANIFEST_STRING_FIELDS = (
    "schema_version",
    "manifest_id",
    "source",
    "source_locator",
    "checksum",
    "terms",
)
_SOURCE_MANIFEST_TIME_FIELDS = ("fetched_at", "available_at", "ingested_at")
_SOURCE_MANIFEST_OPTIONAL_TIME_FIELDS = ("event_time", "published_at")
_RESPONSE_STRING_FIELDS = (
    "schema_version",
    "response_id",
    "response_hash",
    "bundle_id",
    "bundle_hash",
    "calendar_id",
    "variant_id",
    "trade_date",
    "ticker",
    "instrument_id",
    "asset_type",
    "instrument_context",
    "graph_artifact_id",
    "graph_artifact_hash",
    "model_artifact_id",
    "model_artifact_hash",
    "runtime_manifest_id",
    "runtime_manifest_hash",
    "output_hash",
)
_CACHED_SELECTION_FIELDS = (
    "response_id",
    "expected_response_hash",
    "graph_artifact_id",
    "graph_artifact_hash",
    "model_artifact_id",
    "model_artifact_hash",
    "runtime_manifest_id",
    "runtime_manifest_hash",
)


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

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

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

    @model_validator(mode="before")
    @classmethod
    def validate_raw_contract_input(cls, value: object) -> dict[str, object]:
        return _safe_response_input(value)


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


def _exact_dict_fields(
    value: dict[object, object], expected: tuple[str, ...], *, label: str
) -> dict[str, object]:
    raw_keys = tuple(dict.keys(value))
    if any(type(key) is not str for key in raw_keys):
        raise CachedGraphResponseCorruptionError(f"{label} keys must be exact strings")
    if set(raw_keys) != set(expected):
        raise CachedGraphResponseCorruptionError(f"{label} field set is invalid")
    return {key: dict.__getitem__(value, key) for key in expected}


def _is_exact_utc_datetime(value: object) -> bool:
    return type(value) is datetime and object.__getattribute__(value, "tzinfo") is timezone.utc


def _validate_manifest_python_fields(fields: dict[str, object]) -> None:
    if any(type(fields[field]) is not str for field in _SOURCE_MANIFEST_STRING_FIELDS):
        raise CachedGraphResponseCorruptionError(
            "capture manifest string fields require exact strings"
        )
    if any(not _is_exact_utc_datetime(fields[field]) for field in _SOURCE_MANIFEST_TIME_FIELDS):
        raise CachedGraphResponseCorruptionError(
            "capture manifest timestamps require exact UTC datetime values"
        )
    if any(
        value is not None and not _is_exact_utc_datetime(value)
        for value in (fields[field] for field in _SOURCE_MANIFEST_OPTIONAL_TIME_FIELDS)
    ):
        raise CachedGraphResponseCorruptionError(
            "capture manifest optional timestamps require exact UTC datetime or None"
        )
    if type(fields["revision"]) is not int:
        raise CachedGraphResponseCorruptionError(
            "capture manifest revision requires an exact integer"
        )


def _safe_source_manifest(value: object) -> SourceManifest:
    if type(value) is SourceManifest:
        raw = object.__getattribute__(value, "__dict__")
        if type(raw) is not dict:
            raise CachedGraphResponseCorruptionError(
                "capture manifest storage requires an exact dictionary"
            )
        fields = _exact_dict_fields(raw, _SOURCE_MANIFEST_FIELDS, label="capture manifest")
        _validate_manifest_python_fields(fields)
    elif type(value) is dict:
        fields = _exact_dict_fields(value, _SOURCE_MANIFEST_FIELDS, label="capture manifest")
        if any(type(fields[field]) is not str for field in _SOURCE_MANIFEST_STRING_FIELDS):
            raise CachedGraphResponseCorruptionError(
                "capture manifest string fields require exact strings"
            )
        if any(
            type(fields[field]) is not str and not _is_exact_utc_datetime(fields[field])
            for field in _SOURCE_MANIFEST_TIME_FIELDS
        ):
            raise CachedGraphResponseCorruptionError(
                "capture manifest timestamps require exact strings or UTC datetimes"
            )
        if any(
            value is not None and type(value) is not str and not _is_exact_utc_datetime(value)
            for value in (fields[field] for field in _SOURCE_MANIFEST_OPTIONAL_TIME_FIELDS)
        ):
            raise CachedGraphResponseCorruptionError(
                "capture manifest optional timestamps require exact strings, UTC datetimes, or None"
            )
        if type(fields["revision"]) is not int:
            raise CachedGraphResponseCorruptionError(
                "capture manifest revision requires an exact integer"
            )
        if all(type(item) is not datetime for item in fields.values()):
            _bounded_plain(fields)
    else:
        raise CachedGraphResponseCorruptionError(
            "cached response requires an exact SourceManifest or dictionary"
        )

    try:
        manifest = SourceManifest.model_validate(dict(fields))
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError("capture manifest validation failed") from exc
    if type(manifest) is not SourceManifest:
        raise CachedGraphResponseCorruptionError(
            "capture manifest validation returned a non-exact type"
        )
    safe_storage = object.__getattribute__(manifest, "__dict__")
    if type(safe_storage) is not dict:
        raise CachedGraphResponseCorruptionError(
            "capture manifest storage requires an exact dictionary"
        )
    safe_fields = _exact_dict_fields(
        safe_storage, _SOURCE_MANIFEST_FIELDS, label="capture manifest"
    )
    _validate_manifest_python_fields(safe_fields)
    return manifest


def _safe_response_input(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise CachedGraphResponseCorruptionError(
            "cached response public validation requires an exact dictionary"
        )
    expected = tuple(_CachedGraphResponseFields.model_fields)
    fields = _exact_dict_fields(value, expected, label="cached response")
    if any(type(fields[field]) is not str for field in _RESPONSE_STRING_FIELDS):
        raise CachedGraphResponseCorruptionError("cached response fields require exact strings")
    if type(fields["knowledge_cutoff"]) is not str and not _is_exact_utc_datetime(
        fields["knowledge_cutoff"]
    ):
        raise CachedGraphResponseCorruptionError(
            "cached response cutoff requires an exact string or UTC datetime"
        )
    if type(fields["replay_policy"]) not in (str, BundleReplayPolicy):
        raise CachedGraphResponseCorruptionError(
            "cached response policy requires an exact string or BundleReplayPolicy"
        )
    if type(fields["output"]) is not dict:
        raise CachedGraphResponseCorruptionError(
            "cached response output requires an exact dictionary"
        )
    fields["output"] = _bounded_plain(fields["output"])
    fields["capture_manifest"] = _safe_source_manifest(fields["capture_manifest"])
    return fields


def _safe_cached_selection(value: object) -> CachedGraphSelection:
    if type(value) is not CachedGraphSelection:
        raise CachedGraphResponseMismatchError("cached response requires exact selection type")
    raw = object.__getattribute__(value, "__dict__")
    if type(raw) is not dict:
        raise CachedGraphResponseMismatchError("invalid cached response selection storage")
    try:
        fields = _exact_dict_fields(
            raw, _CACHED_SELECTION_FIELDS, label="cached response selection"
        )
    except CachedGraphResponseCorruptionError as exc:
        raise CachedGraphResponseMismatchError("invalid cached response selection fields") from exc
    if any(type(fields[field]) is not str for field in _CACHED_SELECTION_FIELDS):
        raise CachedGraphResponseMismatchError(
            "cached response selection requires exact string fields"
        )
    try:
        selection = CachedGraphSelection.model_validate(dict(fields))
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseMismatchError("invalid cached response selection") from exc
    if type(selection) is not CachedGraphSelection:
        raise CachedGraphResponseMismatchError(
            "cached response selection did not normalize to an exact type"
        )
    safe_storage = object.__getattribute__(selection, "__dict__")
    if type(safe_storage) is not dict:
        raise CachedGraphResponseMismatchError("invalid cached response selection storage")
    try:
        safe_fields = _exact_dict_fields(
            safe_storage, _CACHED_SELECTION_FIELDS, label="cached response selection"
        )
    except CachedGraphResponseCorruptionError as exc:
        raise CachedGraphResponseMismatchError(
            "invalid canonical cached response selection fields"
        ) from exc
    if any(type(safe_fields[field]) is not str for field in _CACHED_SELECTION_FIELDS):
        raise CachedGraphResponseMismatchError("cached response selection fields did not normalize")
    return selection


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
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, OverflowError, RecursionError) as exc:
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
    capture_manifest: SourceManifest | dict[str, object],
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
    if type(knowledge_cutoff) is not str and not _is_exact_utc_datetime(knowledge_cutoff):
        raise CachedGraphResponseCorruptionError(
            "cached response knowledge cutoff requires an exact string or UTC datetime"
        )
    if type(replay_policy) is not BundleReplayPolicy:
        raise CachedGraphResponseCorruptionError(
            "cached response requires exact BundleReplayPolicy"
        )
    safe_capture_manifest = _safe_source_manifest(capture_manifest)
    normalised_output = _bounded_plain(output)
    if type(normalised_output) is not dict:
        raise CachedGraphResponseCorruptionError("cached response output must be an object")
    try:
        cutoff = _UTC_ADAPTER.validate_python(knowledge_cutoff)
    except (TypeError, ValidationError, ValueError) as exc:
        raise CachedGraphResponseCorruptionError(
            "invalid cached response knowledge cutoff"
        ) from exc
    if not _is_exact_utc_datetime(cutoff):
        raise CachedGraphResponseCorruptionError(
            "cached response cutoff did not normalize to an exact UTC datetime"
        )
    _validate_trade_date(trade_date, cutoff)
    validate_historical_response(
        normalised_output,
        company_name=ticker,
        trade_date=trade_date,
        asset_type=asset_type,
        instrument_context=instrument_context,
    )
    output_hash = _sha256(_canonical_bytes(normalised_output))
    if safe_capture_manifest.checksum != output_hash:
        raise CachedGraphResponseCorruptionError(
            "capture manifest checksum does not bind cached output"
        )
    if safe_capture_manifest.available_at > cutoff:
        raise CachedGraphResponseUnavailableError(
            "cached response was unavailable at knowledge cutoff"
        )
    if (
        replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
        and safe_capture_manifest.ingested_at > cutoff
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
        "capture_manifest": safe_capture_manifest.model_dump(mode="json"),
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
        checked_selection = _safe_cached_selection(selection)
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
        if not _is_exact_utc_datetime(knowledge_cutoff):
            raise CachedGraphResponseMismatchError(
                "cached response replay requires exact UTC cutoff type"
            )
        if type(replay_policy) is not BundleReplayPolicy:
            raise CachedGraphResponseMismatchError(
                "cached response replay requires exact policy type"
            )
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
