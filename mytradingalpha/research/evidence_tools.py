"""Read-only access to cited records in one sealed EvidenceBundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from mytradingalpha.contracts.research import EvidenceReference
from mytradingalpha.data.actions import (
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.bars import DailyBar
from mytradingalpha.data.bundle import BundleReplayPolicy, EvidenceBundle
from mytradingalpha.data.events import NewsEvent
from mytradingalpha.data.fundamentals import FinancialFiling
from mytradingalpha.data.macro import MacroObservation
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.data.social import SocialPost
from mytradingalpha.data.universe import Instrument, SymbolAlias, UniverseMembership
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
    if type(value) is not EvidenceReference:
        raise MalformedEvidenceReferenceError(
            "evidence reference must be an exact structured EvidenceReference"
        )
    try:
        return EvidenceReference.model_validate(
            EvidenceReference.model_dump(value, mode="python")
        )
    except (TypeError, ValueError) as exc:
        raise MalformedEvidenceReferenceError("evidence reference is invalid") from exc


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
        if type(bundle) is not EvidenceBundle:
            raise EvidenceToolError("evidence toolset requires an exact EvidenceBundle")
        try:
            payload = EvidenceBundle.model_dump(bundle, mode="python")
            self._bundle = EvidenceBundle.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise EvidenceToolError("evidence bundle failed defensive validation") from exc

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
