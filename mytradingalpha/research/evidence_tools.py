"""Read-only access to cited records in one sealed EvidenceBundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from math import isfinite
from types import MappingProxyType

from mytradingalpha.contracts.research import EvidenceReference
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
from mytradingalpha.data.universe import AssetClass, Instrument, SymbolAlias, UniverseMembership
from mytradingalpha.ops.logging import redact_plain_data


class EvidenceToolError(ValueError):
    """Base class for typed evidence-tool failures."""


class MalformedEvidenceReferenceError(EvidenceToolError):
    """Raised when a reference is not an exact structured reference."""


class MissingEvidenceReferenceError(EvidenceToolError):
    """Raised when a reference ID is absent from the sealed bundle."""


class CrossBundleEvidenceError(EvidenceToolError):
    """Raised when a reference targets another bundle."""


class AmbiguousEvidenceReferenceError(EvidenceToolError):
    """Raised when a reference resolves to more than one record."""


class DuplicateEvidenceReferenceError(EvidenceToolError):
    """Raised when a note repeats one evidence reference."""


class IneligibleEvidenceReferenceError(EvidenceToolError):
    """Raised when a record is not eligible at the bundle cutoff."""


@dataclass(frozen=True)
class EvidenceItem:
    """Immutable derived content and copied provenance for one citation."""

    reference: EvidenceReference
    content: MappingProxyType
    provenance: MappingProxyType


_DOMAIN_FIELDS: tuple[tuple[str, str, str, tuple[type[object], ...]], ...] = (
    ("instruments", "instruments", "instrument_id", (Instrument,)),
    ("aliases", "aliases", "alias_id", (SymbolAlias,)),
    ("memberships", "memberships", "membership_id", (UniverseMembership,)),
    (
        "actions",
        "actions",
        "action_id",
        (TickerChangeAction, SplitAction, DividendAction, DelistingAction),
    ),
    ("bars", "bars", "bar_id", (DailyBar,)),
    ("filings", "filings", "filing_id", (FinancialFiling,)),
    ("events", "events", "event_id", (NewsEvent,)),
    ("social", "social_posts", "post_id", (SocialPost,)),
    ("macro", "macro_observations", "observation_id", (MacroObservation,)),
)
_DOMAIN_BY_NAME = {
    domain: (field, id_field, expected_types)
    for domain, field, id_field, expected_types in _DOMAIN_FIELDS
}

_BUNDLE_FIELDS = (
    "schema_version",
    "bundle_id",
    "bundle_hash",
    "created_at",
    "knowledge_cutoff",
    "replay_policy",
    "requirements",
    "missing_optional",
    "calendar",
    "instruments",
    "aliases",
    "memberships",
    "actions",
    "bars",
    "filings",
    "events",
    "social_posts",
    "macro_observations",
)
_MODEL_FIELDS: dict[type[object], tuple[str, ...]] = {
    EvidenceBundle: _BUNDLE_FIELDS,
    EvidenceRequirement: ("schema_version", "domain", "required"),
    MissingEvidence: ("schema_version", "domain", "reason"),
    TradingCalendar: (
        "schema_version",
        "calendar_id",
        "timezone",
        "coverage_start",
        "coverage_end",
        "coverage_ranges",
        "closures",
        "schedule",
    ),
    CalendarCoverageRange: ("start", "end"),
    CalendarClosure: ("schema_version", "calendar_id", "date", "reason"),
    TradingSession: (
        "schema_version",
        "calendar_id",
        "session_date",
        "open_at",
        "close_at",
        "session_type",
    ),
    Instrument: (
        "schema_version",
        "instrument_id",
        "initial_symbol",
        "asset_class",
        "currency",
        "exchange",
        "active_from",
        "active_to",
        "lot_size",
        "manifest",
    ),
    SymbolAlias: (
        "schema_version",
        "alias_id",
        "instrument_id",
        "symbol",
        "valid_from",
        "valid_to",
        "manifest",
    ),
    UniverseMembership: (
        "schema_version",
        "membership_id",
        "universe_id",
        "instrument_id",
        "valid_from",
        "valid_to",
        "manifest",
    ),
    TickerChangeAction: (
        "schema_version",
        "action_type",
        "action_id",
        "instrument_id",
        "effective_date",
        "old_symbol",
        "new_symbol",
        "manifest",
    ),
    SplitAction: (
        "schema_version",
        "action_type",
        "action_id",
        "instrument_id",
        "effective_date",
        "new_shares_per_old_share",
        "manifest",
    ),
    DividendAction: (
        "schema_version",
        "action_type",
        "action_id",
        "instrument_id",
        "effective_date",
        "amount_per_share",
        "currency",
        "payable_date",
        "manifest",
    ),
    DelistingAction: (
        "schema_version",
        "action_type",
        "action_id",
        "instrument_id",
        "effective_date",
        "reason",
        "manifest",
    ),
    DailyBar: (
        "schema_version",
        "bar_id",
        "instrument_id",
        "calendar_id",
        "session_date",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjustment_basis",
        "adjustment_version",
        "finality",
        "manifest",
    ),
    FinancialFact: ("schema_version", "name", "value"),
    FinancialFiling: (
        "schema_version",
        "filing_id",
        "accession_id",
        "instrument_id",
        "statement_type",
        "reporting_period",
        "form_type",
        "fiscal_period_start",
        "fiscal_period_end",
        "filed_at",
        "currency",
        "unit_scale",
        "facts",
        "manifest",
    ),
    NewsEvent: (
        "schema_version",
        "event_id",
        "instrument_id",
        "kind",
        "title",
        "body",
        "publisher",
        "url",
        "replay_policy",
        "manifest",
    ),
    SocialPost: (
        "schema_version",
        "post_id",
        "instrument_id",
        "platform",
        "text",
        "score",
        "comments",
        "replay_policy",
        "manifest",
    ),
    MacroObservation: (
        "schema_version",
        "observation_id",
        "series_id",
        "observation_date",
        "value",
        "units",
        "frequency",
        "replay_policy",
        "manifest",
    ),
    SourceManifest: (
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
    ),
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
_MAX_BUNDLE_WALK_DEPTH = 64


def _raw_model_fields(
    value: object,
    *,
    expected_type: type[object] | tuple[type[object], ...],
    expected_fields: tuple[str, ...],
) -> dict[str, object]:
    if type(value) not in (
        expected_type if isinstance(expected_type, tuple) else (expected_type,)
    ):
        raise EvidenceToolError("unexpected contract object type")
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise EvidenceToolError("contract object storage is unavailable") from exc
    if type(storage) is not dict:
        raise EvidenceToolError("contract object storage must be an exact dictionary")
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(expected_fields):
        raise EvidenceToolError("contract object fields are not canonical")
    return {field: dict.__getitem__(storage, field) for field in expected_fields}


def _safe_bundle_value(value: object, *, seen: set[int], depth: int) -> object:
    if depth > _MAX_BUNDLE_WALK_DEPTH:
        raise EvidenceToolError("evidence bundle exceeds maximum nesting depth")
    value_type = type(value)
    if value_type in (str, int, bool, type(None)):
        return value
    if value_type is float:
        if not isfinite(value):
            raise EvidenceToolError("evidence bundle requires finite numbers")
        return value
    if value_type is Decimal:
        if not value.is_finite():
            raise EvidenceToolError("evidence bundle requires finite decimals")
        return value
    if value_type is datetime:
        if object.__getattribute__(value, "tzinfo") is not timezone.utc:
            raise EvidenceToolError("evidence bundle timestamps require the exact UTC timezone")
        return value
    if value_type is date:
        return value
    if value_type in _SAFE_ENUM_TYPES:
        return value
    if value_type in _MODEL_FIELDS:
        identity = id(value)
        if identity in seen:
            raise EvidenceToolError("evidence bundle contains a cycle")
        seen.add(identity)
        try:
            fields = _raw_model_fields(
                value,
                expected_type=value_type,
                expected_fields=_MODEL_FIELDS[value_type],
            )
            return {
                key: _safe_bundle_value(item, seen=seen, depth=depth + 1)
                for key, item in fields.items()
            }
        finally:
            seen.remove(identity)
    if value_type is dict:
        identity = id(value)
        if identity in seen:
            raise EvidenceToolError("evidence bundle contains a cycle")
        seen.add(identity)
        try:
            result: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise EvidenceToolError("evidence bundle object keys must be exact strings")
                result[key] = _safe_bundle_value(item, seen=seen, depth=depth + 1)
            return result
        finally:
            seen.remove(identity)
    if value_type in (tuple, list):
        identity = id(value)
        if identity in seen:
            raise EvidenceToolError("evidence bundle contains a cycle")
        seen.add(identity)
        try:
            return value_type(
                _safe_bundle_value(item, seen=seen, depth=depth + 1) for item in value
            )
        finally:
            seen.remove(identity)
    raise EvidenceToolError("evidence bundle contains an unsupported object")


def _copy_bundle(bundle: object) -> EvidenceBundle:
    if type(bundle) is not EvidenceBundle:
        raise EvidenceToolError("evidence toolset requires an exact EvidenceBundle")
    payload = _safe_bundle_value(bundle, seen=set(), depth=0)
    if type(payload) is not dict:
        raise EvidenceToolError("evidence bundle did not normalize to an object")
    try:
        return EvidenceBundle.model_validate(payload)
    except (TypeError, ValueError) as exc:
        raise EvidenceToolError("evidence bundle failed defensive validation") from exc


_REFERENCE_FIELDS = ("schema_version", "bundle_id", "domain", "record_id")


def _copy_reference(value: object) -> EvidenceReference:
    if type(value) is not EvidenceReference:
        raise MalformedEvidenceReferenceError(
            "evidence reference must be an exact structured EvidenceReference"
        )
    try:
        fields = _raw_model_fields(
            value,
            expected_type=EvidenceReference,
            expected_fields=_REFERENCE_FIELDS,
        )
    except EvidenceToolError as exc:
        raise MalformedEvidenceReferenceError("evidence reference storage is malformed") from exc
    if any(type(fields[field]) is not str for field in _REFERENCE_FIELDS):
        raise MalformedEvidenceReferenceError("evidence reference fields must be exact strings")
    try:
        return EvidenceReference.model_validate(fields)
    except (TypeError, ValueError) as exc:
        raise MalformedEvidenceReferenceError("evidence reference is invalid") from exc


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _unfreeze(value: object) -> object:
    if isinstance(value, MappingProxyType):
        return {key: _unfreeze(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_unfreeze(item) for item in value]
    return value


def _validate_reference(value: object) -> EvidenceReference:
    return _copy_reference(value)


def _record_payload(record: object) -> tuple[dict[str, object], dict[str, object]]:
    try:
        payload = type(record).model_dump(record, mode="json")  # type: ignore[attr-defined]
    except (AttributeError, TypeError, ValueError) as exc:
        raise MalformedEvidenceReferenceError("evidence record cannot be rendered") from exc
    manifest = payload.pop("manifest", None)
    if not isinstance(manifest, dict):
        raise MalformedEvidenceReferenceError("evidence record has no provenance manifest")
    return payload, manifest


class EvidenceToolset:
    """Defensively copied, read-only evidence access for one sealed bundle."""

    def __init__(self, bundle: EvidenceBundle) -> None:
        self._bundle = _copy_bundle(bundle)

    @property
    def bundle_id(self) -> str:
        return self._bundle.bundle_id

    def list_citations(self) -> tuple[EvidenceReference, ...]:
        """Enumerate every citable record in deterministic order."""

        references: list[EvidenceReference] = []
        seen: set[tuple[str, str]] = set()
        for domain, field, id_field, expected_types in _DOMAIN_FIELDS:
            records = getattr(self._bundle, field)
            if type(records) is not tuple:
                raise EvidenceToolError(f"evidence domain {domain} is not canonical")
            for record in records:
                if type(record) not in expected_types:
                    raise EvidenceToolError(f"evidence domain {domain} contains a malformed record")
                record_id = getattr(record, id_field)
                if type(record_id) is not str:
                    raise EvidenceToolError(f"evidence domain {domain} contains a malformed ID")
                key = (domain, record_id)
                if key in seen:
                    raise AmbiguousEvidenceReferenceError(
                        f"evidence reference is ambiguous: {domain}/{record_id}"
                    )
                seen.add(key)
                references.append(
                    EvidenceReference(
                        schema_version="v1",
                        bundle_id=self._bundle.bundle_id,
                        domain=domain,
                        record_id=record_id,
                    )
                )
        return tuple(sorted(references, key=lambda item: (item.domain, item.record_id)))

    def _find(self, reference: EvidenceReference) -> object:
        field_and_id = _DOMAIN_BY_NAME.get(reference.domain)
        if field_and_id is None:
            raise MalformedEvidenceReferenceError(
                f"evidence domain is not citable: {reference.domain}"
            )
        field, id_field, expected_types = field_and_id
        records = getattr(self._bundle, field)
        if type(records) is not tuple:
            raise EvidenceToolError(f"evidence domain {reference.domain} is not canonical")
        if any(type(record) not in expected_types for record in records):
            raise EvidenceToolError(f"evidence domain {reference.domain} contains a malformed record")
        if any(type(getattr(record, id_field)) is not str for record in records):
            raise EvidenceToolError(f"evidence domain {reference.domain} contains a malformed ID")
        matches = tuple(
            record
            for record in records
            if getattr(record, id_field) == reference.record_id
        )
        if not matches:
            raise MissingEvidenceReferenceError(
                f"evidence reference is absent: {reference.domain}/{reference.record_id}"
            )
        if len(matches) != 1:
            raise AmbiguousEvidenceReferenceError(
                f"evidence reference is ambiguous: {reference.domain}/{reference.record_id}"
            )
        return matches[0]

    def get(self, reference: EvidenceReference) -> EvidenceItem:
        """Return one immutable derived record and copied source provenance."""

        checked = _validate_reference(reference)
        if checked.bundle_id != self._bundle.bundle_id:
            raise CrossBundleEvidenceError(
                f"evidence reference targets bundle {checked.bundle_id}, expected {self._bundle.bundle_id}"
            )
        record = self._find(checked)
        manifest = getattr(record, "manifest", None)
        if type(manifest) is not SourceManifest:
            raise EvidenceToolError("evidence record provenance is malformed")
        if (
            type(manifest.available_at) is not datetime
            or type(manifest.ingested_at) is not datetime
            or type(self._bundle.knowledge_cutoff) is not datetime
        ):
            raise EvidenceToolError("evidence record provenance timestamps are malformed")
        if manifest.available_at > self._bundle.knowledge_cutoff:
            raise IneligibleEvidenceReferenceError(
                f"evidence reference is unavailable at cutoff: {checked.record_id}"
            )
        if (
            self._bundle.replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC
            and manifest.ingested_at > self._bundle.knowledge_cutoff
        ):
            raise IneligibleEvidenceReferenceError(
                f"evidence reference is not archived at cutoff: {checked.record_id}"
            )
        content, provenance = _record_payload(record)
        frozen_content = _freeze(content)
        frozen_provenance = _freeze(provenance)
        assert isinstance(frozen_content, MappingProxyType)
        assert isinstance(frozen_provenance, MappingProxyType)
        return EvidenceItem(checked, frozen_content, frozen_provenance)

    def render(self, reference: EvidenceReference) -> str:
        """Render one citation as explicitly untrusted, redacted text."""

        item = self.get(reference)
        payload = {
            "reference": _unfreeze(EvidenceReference.model_dump(item.reference, mode="json")),
            "content": _unfreeze(item.content),
            "provenance": _unfreeze(item.provenance),
        }
        redacted = redact_plain_data(payload)
        raw = json.dumps(
            redacted,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return "--- BEGIN UNTRUSTED EVIDENCE ---\n" + raw + "\n--- END UNTRUSTED EVIDENCE ---"


__all__ = [
    "AmbiguousEvidenceReferenceError",
    "CrossBundleEvidenceError",
    "DuplicateEvidenceReferenceError",
    "EvidenceItem",
    "EvidenceToolError",
    "EvidenceToolset",
    "IneligibleEvidenceReferenceError",
    "MalformedEvidenceReferenceError",
    "MissingEvidenceReferenceError",
]
