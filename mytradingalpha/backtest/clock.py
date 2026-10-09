"""Witnessed, immutable session bindings for the offline BT-01 runner."""

from __future__ import annotations

import hashlib
import json
import types
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from itertools import islice
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from mytradingalpha.contracts.research import (
    EvidenceCitation,
    EvidenceReference,
    ResearchNote,
    ResearchProvenance,
    ResearchSourceFields,
)
from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext
from mytradingalpha.contracts.signals import (
    LLMOverlay,
    QuantSignal,
    QuantSignalReasonCode,
    QuantSignalStatus,
    SignalEnvelope,
    SignalEnvelopeReasonCode,
    SignalVariant,
)
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
    CalendarReplayDay,
    CalendarReplayEvidence,
    SessionType,
    TradingCalendar,
    TradingSession,
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
from mytradingalpha.data.universe import (
    AssetClass,
    Instrument,
    SymbolAlias,
    UniverseMembership,
)

_BINDING_DOMAIN = b"mytradingalpha:bt01:binding:v1\0"
_STORAGE_DOMAIN = b"mytradingalpha:bt01:storage:v1\0"
_DECIMAL_QUANTA = tuple(Decimal((0, (1,), exponent)) for exponent in range(-64, 65))
_MAX_BINDINGS = 256
_MAX_EVENTS = 512
_MAX_SOURCE_NODES = 100_000
_MAX_RUN_NODES = 1_000_000
_MAX_DEPTH = 64
_MAX_COLLECTION_ITEMS = 4096
_MAX_MAPPING_FIELDS = 64
_MAX_TEXT_BYTES = 65_536
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_RUN_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_SEQUENCE = (1 << 63) - 1


_MODEL_TYPES: tuple[type[Any], ...] = (
    RunContext,
    NetworkPolicy,
    EvidenceBundle,
    EvidenceRequirement,
    MissingEvidence,
    TradingCalendar,
    TradingSession,
    CalendarCoverageRange,
    CalendarClosure,
    CalendarReplayDay,
    CalendarReplayEvidence,
    Instrument,
    SymbolAlias,
    UniverseMembership,
    SourceManifest,
    TickerChangeAction,
    SplitAction,
    DividendAction,
    DelistingAction,
    DailyBar,
    FinancialFact,
    FinancialFiling,
    NewsEvent,
    SocialPost,
    MacroObservation,
    SignalEnvelope,
    SignalVariant,
    QuantSignal,
    LLMOverlay,
    ResearchNote,
    ResearchSourceFields,
    ResearchProvenance,
    EvidenceReference,
    EvidenceCitation,
)

_ENUM_TYPES: tuple[type[Enum], ...] = (
    Mode,
    BundleReplayPolicy,
    EvidenceDomain,
    SessionType,
    AssetClass,
    ActionType,
    AdjustmentBasis,
    BarFinality,
    StatementType,
    ReportingPeriod,
    UnitScale,
    EventKind,
    ReplayPolicy,
    SocialPlatform,
    MacroFrequency,
    QuantSignalStatus,
    QuantSignalReasonCode,
    SignalEnvelopeReasonCode,
)

_REASON_CODES = (
    "input_invalid",
    "resource_limit",
    "source_changed",
    "source_invalid",
    "binding_mismatch",
    "witness_missing",
    "session_unavailable",
    "decision_not_close",
    "cutoff_invalid",
    "execution_too_early",
    "duplicate_decision_slot",
    "duplicate_event_id",
    "event_invalid",
    "sequence_invalid",
)


class BacktestInputError(ValueError):
    """Stable, bounded error raised when a BT-01 input cannot be proved safe."""

    def __init__(self, reason_code: str) -> None:
        if type(reason_code) is not str or not any(
            reason_code == known for known in _REASON_CODES
        ):
            reason_code = "input_invalid"
        self.reason_code = reason_code
        super().__init__("BT-01 input rejected")


@dataclass(slots=True)
class _CaptureBudget:
    run_nodes: int = 0
    source_nodes: int = 0
    escaped_bytes: int = 0
    stack: set[int] | None = None

    def begin_source(self) -> None:
        self.source_nodes = 0
        self.escaped_bytes = 0
        self.stack = set()


def _is_model_type(value_type: type[object]) -> bool:
    return any(value_type is known for known in _MODEL_TYPES)


def _is_enum_type(value_type: type[object]) -> bool:
    return any(value_type is known for known in _ENUM_TYPES)


def _source_error(reason: str = "source_invalid") -> None:
    raise BacktestInputError(reason) from None


def _exact_utc_datetime(value: object) -> bool:
    if type(value) is not datetime:
        return False
    zone = object.__getattribute__(value, "tzinfo")
    if type(zone) is not timezone:
        return False
    try:
        offset = timezone.utcoffset(zone, value)
    except (TypeError, ValueError, OverflowError):
        return False
    return type(offset) is timedelta and offset == timedelta(0)


@dataclass(frozen=True, slots=True)
class _CapturedModel:
    """Owned typed storage, captured before any model copy or serializer."""

    model_type: type[Any]
    fields: dict[str, object]
    fields_set: tuple[str, ...]


def _annotation_storage_matches(
    value: object,
    annotation: object,
    budget: _CaptureBudget,
    depth: int = 0,
) -> bool:
    """Check exact declared storage types, including collection members."""

    budget.run_nodes += 1
    budget.source_nodes += 1
    if budget.run_nodes > _MAX_RUN_NODES or budget.source_nodes > _MAX_SOURCE_NODES:
        _source_error("resource_limit")
    if depth > _MAX_DEPTH:
        _source_error("resource_limit")
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return _annotation_storage_matches(value, args[0], budget, depth + 1)
    if origin is types.UnionType or origin is Union:
        return any(
            _annotation_storage_matches(value, item, budget, depth + 1)
            for item in args
        )
    if origin is Literal:
        if type(value) is str or type(value) is int or type(value) is bool:
            return any(type(value) is type(item) and value == item for item in args)
        if _is_enum_type(type(value)):
            return any(value is item for item in args)
        return False
    if origin is tuple or origin is list:
        expected_type = tuple if origin is tuple else list
        if type(value) is not expected_type:
            return False
        if len(value) > _MAX_COLLECTION_ITEMS:
            _source_error("resource_limit")
        if origin is list or (len(args) == 2 and args[1] is Ellipsis):
            return len(args) >= 1 and all(
                _annotation_storage_matches(item, args[0], budget, depth + 1)
                for item in value
            )
        return len(value) == len(args) and all(
            _annotation_storage_matches(item, expected, budget, depth + 1)
            for item, expected in zip(value, args, strict=True)
        )
    if origin is dict:
        if type(value) is not dict or len(args) != 2:
            return False
        if dict.__len__(value) > _MAX_MAPPING_FIELDS:
            _source_error("resource_limit")
        return all(
            _annotation_storage_matches(key, args[0], budget, depth + 1)
            and _annotation_storage_matches(item, args[1], budget, depth + 1)
            for key, item in dict.items(value)
        )
    if annotation is type(None):
        return value is None
    if any(annotation is known for known in (str, bool, int, Decimal, date, datetime)):
        return type(value) is annotation
    if _is_model_type(annotation) or _is_enum_type(annotation):
        return type(value) is annotation
    return False


def _capture_string(value: str, budget: _CaptureBudget) -> str:
    if len(value) > _MAX_TEXT_BYTES:
        _source_error("resource_limit")
    try:
        raw = value.encode("utf-8", "strict")
        escaped = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        escaped_size = len(escaped.encode("utf-8", "strict"))
    except (UnicodeError, ValueError, OverflowError):
        _source_error()
    if len(raw) > _MAX_TEXT_BYTES:
        _source_error("resource_limit")
    budget.escaped_bytes += escaped_size
    if budget.escaped_bytes > _MAX_SOURCE_BYTES:
        _source_error("resource_limit")
    return value


def _capture_value(value: object, budget: _CaptureBudget, depth: int = 0) -> object:
    budget.run_nodes += 1
    budget.source_nodes += 1
    if budget.run_nodes > _MAX_RUN_NODES or budget.source_nodes > _MAX_SOURCE_NODES:
        _source_error("resource_limit")
    if depth > _MAX_DEPTH:
        _source_error("resource_limit")

    value_type = type(value)
    if value is None or value_type is bool:
        return value
    if value_type is str:
        return _capture_string(value, budget)
    if value_type is int:
        if value.bit_length() > 256:
            _source_error("resource_limit")
        return value
    if value_type is Decimal:
        if not value.is_finite():
            _source_error()
        exponent = None
        for candidate_exponent, quantum in enumerate(_DECIMAL_QUANTA, start=-64):
            if value.same_quantum(quantum):
                exponent = candidate_exponent
                break
        if type(exponent) is not int:
            _source_error("resource_limit")
        if not value.is_zero():
            digit_count = value.adjusted() - exponent + 1
            if not 1 <= digit_count <= 64:
                _source_error("resource_limit")
        _, digits, stored_exponent = value.as_tuple()
        if len(digits) > 64 or stored_exponent != exponent:
            _source_error("resource_limit")
        return value
    if value_type is datetime:
        if not _exact_utc_datetime(value):
            _source_error()
        return value
    if value_type is date:
        return value
    if (
        value_type is tuple
        or value_type is list
        or value_type is dict
        or _is_model_type(value_type)
    ):
        identity = id(value)
        if budget.stack is None:
            budget.stack = set()
        if identity in budget.stack:
            _source_error()
        budget.stack.add(identity)
        try:
            if value_type is tuple or value_type is list:
                if len(value) > _MAX_COLLECTION_ITEMS:  # type: ignore[arg-type]
                    _source_error("resource_limit")
                captured = tuple(
                    _capture_value(item, budget, depth + 1) for item in value  # type: ignore[union-attr]
                )
                return captured if value_type is tuple else list(captured)
            if value_type is dict:
                if dict.__len__(value) > _MAX_MAPPING_FIELDS:  # type: ignore[arg-type]
                    _source_error("resource_limit")
                pairs = tuple(islice(dict.items(value), _MAX_MAPPING_FIELDS + 1))  # type: ignore[arg-type]
                if len(pairs) > _MAX_MAPPING_FIELDS:
                    _source_error("resource_limit")
                result: dict[str, object] = {}
                for key, item in pairs:
                    if type(key) is not str:
                        _source_error()
                    safe_key = _capture_string(key, budget)
                    result[safe_key] = _capture_value(item, budget, depth + 1)
                return result
            if not _is_model_type(value_type):
                _source_error()
            storage = object.__getattribute__(value, "__dict__")
            extra = object.__getattribute__(value, "__pydantic_extra__")
            private = object.__getattribute__(value, "__pydantic_private__")
            fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
            fields = tuple(value_type.model_fields)
            if (
                type(storage) is not dict
                or extra is not None
                or private is not None
                or dict.__len__(storage) != len(fields)
                or type(fields_set) is not set
            ):
                _source_error()
            if set.__len__(fields_set) > _MAX_MAPPING_FIELDS:
                _source_error("resource_limit")
            captured_fields_set = tuple(islice(set.__iter__(fields_set), _MAX_MAPPING_FIELDS + 1))
            if len(captured_fields_set) > _MAX_MAPPING_FIELDS:
                _source_error("resource_limit")
            for field_name in captured_fields_set:
                if type(field_name) is not str:
                    _source_error()
                if not any(field_name == declared for declared in fields):
                    _source_error()
            if dict.__len__(storage) > _MAX_MAPPING_FIELDS:
                _source_error("resource_limit")
            pairs = tuple(islice(dict.items(storage), _MAX_MAPPING_FIELDS + 1))
            if len(pairs) > _MAX_MAPPING_FIELDS:
                _source_error("resource_limit")
            if len(pairs) != len(fields):
                _source_error()
            if any(type(key) is not str for key, _ in pairs):
                _source_error()
            if any(not any(key == field for field in fields) for key, _ in pairs):
                _source_error()
            owned_storage = dict(pairs)
            result = {}
            for field_name in fields:
                try:
                    field_value = dict.__getitem__(owned_storage, field_name)
                except KeyError:
                    _source_error()
                annotation = value_type.model_fields[field_name].annotation
                if not _annotation_storage_matches(field_value, annotation, budget):
                    _source_error()
                result[field_name] = _capture_value(field_value, budget, depth + 1)
            return _CapturedModel(value_type, result, tuple(sorted(captured_fields_set)))
        except BacktestInputError:
            raise
        except Exception:
            _source_error()
        finally:
            budget.stack.remove(identity)
    if _is_enum_type(value_type):
        if not any(value is member for member in value_type.__members__.values()):
            _source_error()
        enum_value = object.__getattribute__(value, "_value_")
        enum_value_type = type(enum_value)
        if enum_value_type is str:
            _capture_string(enum_value, budget)
        elif enum_value_type is int:
            if enum_value.bit_length() > 256:
                _source_error("resource_limit")
        elif enum_value_type is not bool:
            _source_error()
        return value
    _source_error()


def _canonical_json(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, OverflowError, UnicodeError):
        _source_error()


def _storage_projection(value: object) -> object:
    """Seal exact typed storage; this private seal never changes v1 source bytes."""

    value_type = type(value)
    if value is None or value_type is bool or value_type is int or value_type is str:
        return value
    if value_type is Decimal:
        return ["Decimal", str(value)]
    if value_type is datetime:
        return ["datetime", value.isoformat()]
    if value_type is date:
        return ["date", value.isoformat()]
    if _is_enum_type(value_type):
        return [
            "enum",
            value_type.__name__,
            _storage_projection(object.__getattribute__(value, "_value_")),
        ]
    if value_type is _CapturedModel:
        return [
            "model",
            value.model_type.__name__,
            _storage_projection(value.fields),
            list(value.fields_set),
        ]
    if value_type is tuple or value_type is list:
        return [
            "tuple" if value_type is tuple else "list",
            [_storage_projection(item) for item in value],
        ]
    if value_type is dict:
        return {key: _storage_projection(item) for key, item in dict.items(value)}
    _source_error()


def _captured_payload(value: object, *, construct: bool) -> Any:
    """Build only from the checked graph, never reread a mutable source root.

    Construction on refresh carries forward the constructor's semantic validation
    only after the exact typed storage seal matches. It is not validation itself.
    """

    value_type = type(value)
    if value_type is _CapturedModel:
        fields = {
            key: _captured_payload(item, construct=construct)
            for key, item in dict.items(value.fields)
        }
        if construct:
            return value.model_type.model_construct(
                _fields_set=set(value.fields_set), **fields
            )
        return fields
    if value_type is tuple:
        return tuple(_captured_payload(item, construct=construct) for item in value)
    if value_type is list:
        return [_captured_payload(item, construct=construct) for item in value]
    if value_type is dict:
        return {
            key: _captured_payload(item, construct=construct)
            for key, item in dict.items(value)
        }
    return value


def _storage_bytes(*values: object) -> bytes:
    return _STORAGE_DOMAIN + _canonical_json(
        [_storage_projection(value) for value in values]
    )


def _model_payload(model: object) -> dict[str, object]:
    value_type = type(model)
    if not _is_model_type(value_type):
        _source_error()
    try:
        payload = model.model_dump(mode="json")  # type: ignore[attr-defined]
    except Exception:
        _source_error()
    if type(payload) is not dict:
        _source_error()
    return payload


def _source_json(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: SignalEnvelope,
) -> bytes:
    return _canonical_json(
        {
            "context": _model_payload(context),
            "bundle": _model_payload(bundle),
            "envelope": _model_payload(envelope),
        }
    )


def _raw_model_field(model: object, field_name: str) -> object:
    storage = object.__getattribute__(model, "__dict__")
    if type(storage) is not dict or dict.__len__(storage) > _MAX_MAPPING_FIELDS:
        _source_error()
    pairs = tuple(islice(dict.items(storage), _MAX_MAPPING_FIELDS + 1))
    if len(pairs) > _MAX_MAPPING_FIELDS or any(type(key) is not str for key, _ in pairs):
        _source_error()
    # Compare only checked strings and read only the captured snapshot.
    for key, value in pairs:
        if key == field_name:
            return value
    _source_error()


def _require_presealed_witness(bundle: EvidenceBundle) -> None:
    calendar = _raw_model_field(bundle, "calendar")
    if type(calendar) is not TradingCalendar:
        _source_error()
    witness = _raw_model_field(calendar, "replay_evidence")
    if witness is None:
        _source_error("witness_missing")
    if type(witness) is not CalendarReplayEvidence:
        _source_error()


def _capture_root(value: object, budget: _CaptureBudget) -> object:
    budget.begin_source()
    return _capture_value(value, budget)


def _revalidate_sources(
    context: object,
    bundle: object,
    envelope: object,
    budget: _CaptureBudget,
) -> tuple[RunContext, EvidenceBundle, SignalEnvelope, bytes, str]:
    if type(context) is not RunContext or type(bundle) is not EvidenceBundle or type(envelope) is not SignalEnvelope:
        _source_error("input_invalid")
    _require_presealed_witness(bundle)
    try:
        # Finish capture of every root before any inherited validation runs.
        context_capture = _capture_root(context, budget)
        bundle_capture = _capture_root(bundle, budget)
        envelope_capture = _capture_root(envelope, budget)
        context_data = _captured_payload(context_capture, construct=False)
        bundle_data = _captured_payload(bundle_capture, construct=False)
        envelope_data = _captured_payload(envelope_capture, construct=False)
        overlay_data = envelope_data.get("overlay") if type(envelope_data) is dict else None
        if overlay_data is not None:
            if type(overlay_data) is not dict:
                _source_error()
            overlay_wire = dict(overlay_data)
            multiplier = overlay_wire.get("multiplier")
            generated_at = overlay_wire.get("generated_at")
            if type(multiplier) is Decimal:
                overlay_wire["multiplier"] = str(multiplier)
            if type(generated_at) is datetime:
                overlay_wire["generated_at"] = generated_at.astimezone(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                )
            envelope_data["overlay"] = LLMOverlay.model_validate(overlay_wire)
        copied_context = RunContext.model_validate(context_data)
        copied_bundle = EvidenceBundle.model_validate(bundle_data)
        copied_envelope = SignalEnvelope.model_validate(envelope_data)
    except BacktestInputError:
        raise
    except Exception:
        _source_error()
    if (
        type(copied_context) is not RunContext
        or type(copied_bundle) is not EvidenceBundle
        or type(copied_envelope) is not SignalEnvelope
    ):
        _source_error()
    payload = _source_json(copied_context, copied_bundle, copied_envelope)
    source_size = len(_BINDING_DOMAIN) + len(payload)
    if source_size > _MAX_SOURCE_BYTES:
        _source_error("resource_limit")
    fingerprint = "sha256:" + hashlib.sha256(_BINDING_DOMAIN + payload).hexdigest()
    return (
        copied_context,
        copied_bundle,
        copied_envelope,
        payload,
        fingerprint,
    )


def _manifest_bytes(manifest: SourceManifest) -> bytes:
    return _canonical_json(_model_payload(manifest))


_CITABLE_RECORDS: tuple[tuple[str, str, str], ...] = (
    ("instruments", "instruments", "instrument_id"),
    ("aliases", "aliases", "alias_id"),
    ("memberships", "memberships", "membership_id"),
    ("actions", "actions", "action_id"),
    ("bars", "bars", "bar_id"),
    ("filings", "filings", "filing_id"),
    ("events", "events", "event_id"),
    ("social", "social_posts", "post_id"),
    ("macro", "macro_observations", "observation_id"),
)


def _find_cited_record(bundle: EvidenceBundle, domain: str, record_id: str) -> object:
    for candidate_domain, records_field, id_field in _CITABLE_RECORDS:
        if domain != candidate_domain:
            continue
        records = object.__getattribute__(bundle, records_field)
        matches = tuple(
            record
            for record in records
            if object.__getattribute__(record, id_field) == record_id
        )
        if len(matches) != 1:
            _source_error("binding_mismatch")
        return matches[0]
    _source_error("binding_mismatch")


def _validate_research_sources(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: SignalEnvelope,
) -> None:
    note = object.__getattribute__(envelope, "note")
    if note is None:
        return
    if type(note) is not ResearchNote:
        _source_error("binding_mismatch")
    policy = object.__getattribute__(bundle, "replay_policy").value
    cutoff = object.__getattribute__(context, "knowledge_cutoff")
    if (
        object.__getattribute__(note, "run_id") != object.__getattribute__(context, "run_id")
        or object.__getattribute__(note, "variant_id") != object.__getattribute__(context, "variant_id")
        or object.__getattribute__(note, "bundle_id") != object.__getattribute__(bundle, "bundle_id")
        or object.__getattribute__(note, "bundle_hash") != object.__getattribute__(bundle, "bundle_hash")
        or object.__getattribute__(note, "knowledge_cutoff") != cutoff
        or object.__getattribute__(note, "calendar_id") != object.__getattribute__(context, "calendar_id")
        or object.__getattribute__(note, "instrument_id") != object.__getattribute__(envelope.quant, "instrument_id")
        or object.__getattribute__(note, "replay_policy") != policy
    ):
        _source_error("binding_mismatch")

    manifests = (object.__getattribute__(note, "capture_manifest"),) + tuple(
        object.__getattribute__(citation, "provenance")
        for citation in object.__getattribute__(note, "citations")
    )
    for provenance in manifests:
        if type(provenance) is not ResearchProvenance:
            _source_error("binding_mismatch")
        available_at = object.__getattribute__(provenance, "available_at")
        ingested_at = object.__getattribute__(provenance, "ingested_at")
        if available_at > cutoff:
            _source_error("binding_mismatch")
        if policy == BundleReplayPolicy.ARCHIVE_REALISTIC.value and ingested_at > cutoff:
            _source_error("binding_mismatch")

    for citation in object.__getattribute__(note, "citations"):
        reference = object.__getattribute__(citation, "reference")
        supplied = object.__getattribute__(citation, "provenance")
        if type(reference) is not EvidenceReference or type(supplied) is not ResearchProvenance:
            _source_error("binding_mismatch")
        domain = object.__getattribute__(reference, "domain")
        record_id = object.__getattribute__(reference, "record_id")
        if (
            type(domain) is not str
            or object.__getattribute__(reference, "bundle_id") != object.__getattribute__(bundle, "bundle_id")
        ):
            _source_error("binding_mismatch")
        record = _find_cited_record(bundle, domain, record_id)
        manifest = object.__getattribute__(record, "manifest")
        if type(manifest) is not SourceManifest:
            _source_error("binding_mismatch")
        try:
            expected_hash = "sha256:" + hashlib.sha256(_manifest_bytes(manifest)).hexdigest()
        except BacktestInputError:
            _source_error("binding_mismatch")
        if object.__getattribute__(supplied, "manifest_hash") != expected_hash:
            _source_error("binding_mismatch")
        for name in (
            "schema_version",
            "manifest_id",
            "source",
            "fetched_at",
            "event_time",
            "published_at",
            "available_at",
            "ingested_at",
            "checksum",
            "revision",
        ):
            if object.__getattribute__(manifest, name) != object.__getattribute__(supplied, name):
                _source_error("binding_mismatch")


def _validate_binding_contract(
    context: RunContext,
    bundle: EvidenceBundle,
    envelope: SignalEnvelope,
) -> tuple[TradingSession, TradingSession]:
    try:
        mode = object.__getattribute__(context, "mode")
        network_policy = object.__getattribute__(context, "network_policy")
        if type(mode) is not Mode or mode is not Mode.HISTORICAL:
            _source_error("binding_mismatch")
        if type(network_policy) is not NetworkPolicy or any(
            object.__getattribute__(network_policy, name) is not False
            for name in (
                "data_capture_egress",
                "model_provider_egress",
                "research_tool_egress",
                "paper_broker_egress",
                "live_broker_egress",
            )
        ):
            _source_error("binding_mismatch")

        calendar = object.__getattribute__(bundle, "calendar")
        witness = object.__getattribute__(calendar, "replay_evidence")
        if type(calendar) is not TradingCalendar or type(witness) is not CalendarReplayEvidence:
            _source_error("witness_missing")
        calendar_id = object.__getattribute__(calendar, "calendar_id")
        if (
            object.__getattribute__(context, "bundle_id") != object.__getattribute__(bundle, "bundle_id")
            or object.__getattribute__(context, "bundle_hash") != object.__getattribute__(bundle, "bundle_hash")
            or object.__getattribute__(context, "knowledge_cutoff") != object.__getattribute__(bundle, "knowledge_cutoff")
            or object.__getattribute__(context, "calendar_id") != calendar_id
            or object.__getattribute__(witness, "calendar_id") != calendar_id
        ):
            _source_error("binding_mismatch")
        if object.__getattribute__(context, "knowledge_cutoff") > object.__getattribute__(context, "decision_time"):
            _source_error("cutoff_invalid")

        envelope_context = object.__getattribute__(envelope, "context")
        variant = object.__getattribute__(envelope, "variant")
        quant = object.__getattribute__(envelope, "quant")
        if (
            type(envelope_context) is not RunContext
            or type(variant) is not SignalVariant
            or type(quant) is not QuantSignal
            or envelope_context != context
            or object.__getattribute__(envelope_context, "run_id") != object.__getattribute__(context, "run_id")
            or object.__getattribute__(envelope_context, "variant_id") != object.__getattribute__(context, "variant_id")
            or object.__getattribute__(envelope_context, "bundle_id") != object.__getattribute__(context, "bundle_id")
            or object.__getattribute__(envelope_context, "bundle_hash") != object.__getattribute__(context, "bundle_hash")
            or object.__getattribute__(envelope_context, "decision_time") != object.__getattribute__(context, "decision_time")
            or object.__getattribute__(envelope_context, "knowledge_cutoff") != object.__getattribute__(context, "knowledge_cutoff")
            or object.__getattribute__(envelope_context, "earliest_execution_time") != object.__getattribute__(context, "earliest_execution_time")
            or object.__getattribute__(envelope_context, "calendar_id") != object.__getattribute__(context, "calendar_id")
            or object.__getattribute__(variant, "variant_id") != object.__getattribute__(context, "variant_id")
            or object.__getattribute__(quant, "run_id") != object.__getattribute__(context, "run_id")
            or object.__getattribute__(quant, "bundle_id") != object.__getattribute__(bundle, "bundle_id")
            or object.__getattribute__(quant, "bundle_hash") != object.__getattribute__(bundle, "bundle_hash")
        ):
            _source_error("binding_mismatch")
        if object.__getattribute__(envelope, "shadow_only") is not True:
            _source_error("binding_mismatch")

        evidence_days = object.__getattribute__(witness, "days")
        decision_time = object.__getattribute__(context, "decision_time")
        matches = tuple(
            day
            for day in evidence_days
            if object.__getattribute__(day, "start_utc") <= decision_time
            < object.__getattribute__(day, "end_utc")
        )
        if len(matches) != 1:
            _source_error("witness_missing")
        session_date = object.__getattribute__(matches[0], "local_date")
        try:
            session = calendar.session(session_date)
            next_session = calendar.next_session(session_date)
        except Exception:
            _source_error("session_unavailable")
        if object.__getattribute__(session, "close_at") != decision_time:
            _source_error("decision_not_close")
        if object.__getattribute__(context, "earliest_execution_time") < object.__getattribute__(next_session, "open_at"):
            _source_error("execution_too_early")

        instrument_id = object.__getattribute__(quant, "instrument_id")
        instruments = object.__getattribute__(bundle, "instruments")
        selected_instruments = tuple(
            instrument
            for instrument in instruments
            if object.__getattribute__(instrument, "instrument_id") == instrument_id
        )
        if len(selected_instruments) != 1:
            _source_error("binding_mismatch")
        instrument = selected_instruments[0]
        if (
            object.__getattribute__(instrument, "currency") != object.__getattribute__(context, "base_currency")
            or not object.__getattribute__(instrument, "active_from") <= session_date
            or (
                object.__getattribute__(instrument, "active_to") is not None
                and session_date >= object.__getattribute__(instrument, "active_to")
            )
        ):
            _source_error("binding_mismatch")
        memberships = tuple(
            membership
            for membership in object.__getattribute__(bundle, "memberships")
            if object.__getattribute__(membership, "instrument_id") == instrument_id
            and object.__getattribute__(membership, "valid_from") <= session_date
            and (
                object.__getattribute__(membership, "valid_to") is None
                or session_date < object.__getattribute__(membership, "valid_to")
            )
        )
        if len(memberships) != 1:
            _source_error("binding_mismatch")

        _validate_research_sources(context, bundle, envelope)
        return session, next_session
    except BacktestInputError:
        raise
    except Exception:
        _source_error("source_invalid")


def _prepare_sources(
    context: object,
    bundle: object,
    envelope: object,
    budget: _CaptureBudget,
) -> tuple[RunContext, EvidenceBundle, SignalEnvelope, TradingSession, TradingSession, bytes, str, bytes]:
    if type(context) is not RunContext or type(bundle) is not EvidenceBundle or type(envelope) is not SignalEnvelope:
        _source_error("input_invalid")
    (
        copied_context,
        copied_bundle,
        copied_envelope,
        source_json,
        fingerprint,
    ) = _revalidate_sources(
        context, bundle, envelope, budget
    )
    session, next_session = _validate_binding_contract(copied_context, copied_bundle, copied_envelope)
    # Seal the fully validated private values, including normalized storage and
    # metadata. This fixed pass is not a second charge for caller input.
    seal_budget = _CaptureBudget()
    sealed_storage = _storage_bytes(
        *(
            _capture_root(value, seal_budget)
            for value in (copied_context, copied_bundle, copied_envelope, session, next_session)
        )
    )
    return (
        copied_context,
        copied_bundle,
        copied_envelope,
        session,
        next_session,
        source_json,
        fingerprint,
        sealed_storage,
    )


@dataclass(frozen=True, slots=True, init=False, eq=False, repr=False)
class SessionBinding:
    """Private validated source snapshots with defensive public reads."""

    _context_snapshot: RunContext
    _bundle_snapshot: EvidenceBundle
    _envelope_snapshot: SignalEnvelope
    _session_snapshot: TradingSession
    _next_session_snapshot: TradingSession
    _sealed_source_json: bytes
    _source_fingerprint: str
    _sealed_storage_bytes: bytes

    def __init__(
        self,
        context: RunContext,
        bundle: EvidenceBundle,
        envelope: SignalEnvelope,
    ) -> None:
        prepared = _prepare_sources(context, bundle, envelope, _CaptureBudget())
        copied_context, copied_bundle, copied_envelope, session, next_session, source_json, fingerprint, storage_bytes = prepared
        object.__setattr__(self, "_context_snapshot", copied_context)
        object.__setattr__(self, "_bundle_snapshot", copied_bundle)
        object.__setattr__(self, "_envelope_snapshot", copied_envelope)
        object.__setattr__(self, "_session_snapshot", session)
        object.__setattr__(self, "_next_session_snapshot", next_session)
        object.__setattr__(self, "_sealed_source_json", source_json)
        object.__setattr__(self, "_source_fingerprint", fingerprint)
        object.__setattr__(self, "_sealed_storage_bytes", storage_bytes)

    @property
    def context(self) -> RunContext:
        return _defensive_snapshot(self, "context")

    @property
    def bundle(self) -> EvidenceBundle:
        return _defensive_snapshot(self, "bundle")

    @property
    def envelope(self) -> SignalEnvelope:
        return _defensive_snapshot(self, "envelope")

    @property
    def session(self) -> TradingSession:
        return _defensive_snapshot(self, "session")

    @property
    def next_session(self) -> TradingSession:
        return _defensive_snapshot(self, "next_session")


def _refresh_binding(
    binding: SessionBinding,
    budget: _CaptureBudget,
) -> tuple[RunContext, EvidenceBundle, SignalEnvelope, TradingSession, TradingSession, bytes, str, bytes]:
    try:
        context = object.__getattribute__(binding, "_context_snapshot")
        bundle = object.__getattribute__(binding, "_bundle_snapshot")
        envelope = object.__getattribute__(binding, "_envelope_snapshot")
        session = object.__getattribute__(binding, "_session_snapshot")
        next_session = object.__getattribute__(binding, "_next_session_snapshot")
        if type(context) is not RunContext or type(bundle) is not EvidenceBundle or type(envelope) is not SignalEnvelope:
            _source_error("source_changed")
        if type(session) is not TradingSession or type(next_session) is not TradingSession:
            _source_error("source_changed")
        _require_presealed_witness(bundle)
        # Capture all storage and metadata first. Copy/serialization cannot see a
        # caller-injected object between the check and construction.
        captures = tuple(
            _capture_root(value, budget)
            for value in (context, bundle, envelope, session, next_session)
        )
        current_storage = _storage_bytes(*captures)
        sealed = object.__getattribute__(binding, "_sealed_source_json")
        expected_fingerprint = object.__getattribute__(binding, "_source_fingerprint")
        sealed_storage = object.__getattribute__(binding, "_sealed_storage_bytes")
        if (
            type(sealed) is not bytes
            or type(sealed_storage) is not bytes
            or current_storage != sealed_storage
            or type(expected_fingerprint) is not str
        ):
            _source_error("source_changed")
        copied_context, copied_bundle, copied_envelope, copied_session, copied_next_session = (
            _captured_payload(capture, construct=True) for capture in captures
        )
        source_json = _source_json(copied_context, copied_bundle, copied_envelope)
        if len(_BINDING_DOMAIN) + len(source_json) > _MAX_SOURCE_BYTES:
            _source_error("resource_limit")
        fingerprint = "sha256:" + hashlib.sha256(_BINDING_DOMAIN + source_json).hexdigest()
        if sealed != source_json or expected_fingerprint != fingerprint:
            _source_error("source_changed")
        derived_session, derived_next_session = _validate_binding_contract(
            copied_context, copied_bundle, copied_envelope
        )
        # The private session slots must also agree with the witnessed calendar.
        session_budget = _CaptureBudget()
        current_sessions = _storage_bytes(
            _capture_root(copied_session, session_budget),
            _capture_root(copied_next_session, session_budget),
        )
        derived_sessions = _storage_bytes(
            _capture_root(derived_session, session_budget),
            _capture_root(derived_next_session, session_budget),
        )
        if current_sessions != derived_sessions:
            _source_error("source_changed")
        return (
            copied_context,
            copied_bundle,
            copied_envelope,
            derived_session,
            derived_next_session,
            source_json,
            fingerprint,
            current_storage,
        )
    except BacktestInputError as error:
        if error.reason_code == "resource_limit":
            raise
        _source_error("source_changed")
    except Exception:
        _source_error("source_changed")


def _defensive_snapshot(binding: SessionBinding, name: str) -> Any:
    prepared = _refresh_binding(binding, _CaptureBudget())
    if name == "context":
        return prepared[0]
    if name == "bundle":
        return prepared[1]
    if name == "envelope":
        return prepared[2]
    if name == "session":
        return prepared[3]
    return prepared[4]


class SessionClock:
    """Bind typed historical inputs to one witnessed exchange close."""

    @staticmethod
    def bind(
        context: RunContext,
        bundle: EvidenceBundle,
        envelope: SignalEnvelope,
    ) -> SessionBinding:
        if type(context) is not RunContext or type(bundle) is not EvidenceBundle or type(envelope) is not SignalEnvelope:
            _source_error("input_invalid")
        return SessionBinding(context, bundle, envelope)


__all__ = ["BacktestInputError", "SessionBinding", "SessionClock"]
