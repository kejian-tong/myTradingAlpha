"""Read-only access to cited records in one sealed EvidenceBundle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType

from mytradingalpha.contracts.research import EvidenceReference
from mytradingalpha.data.bundle import BundleReplayPolicy, EvidenceBundle
from mytradingalpha.ops.logging import redact_text


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


_DOMAIN_FIELDS: tuple[tuple[str, str, str], ...] = (
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
_DOMAIN_BY_NAME = {domain: (field, id_field) for domain, field, id_field in _DOMAIN_FIELDS}


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
    return value


def _record_payload(record: object) -> tuple[dict[str, object], dict[str, object]]:
    try:
        payload = record.model_dump(mode="json")  # type: ignore[attr-defined]
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
            payload = bundle.model_dump(mode="python")
            self._bundle = EvidenceBundle.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise EvidenceToolError("evidence bundle failed defensive validation") from exc

    @property
    def bundle_id(self) -> str:
        return self._bundle.bundle_id

    def list_citations(self) -> tuple[EvidenceReference, ...]:
        """Enumerate every citable record in deterministic order."""

        references = [
            EvidenceReference(
                schema_version="v1",
                bundle_id=self._bundle.bundle_id,
                domain=domain,
                record_id=getattr(record, id_field),
            )
            for domain, field, id_field in _DOMAIN_FIELDS
            for record in getattr(self._bundle, field)
        ]
        return tuple(sorted(references, key=lambda item: (item.domain, item.record_id)))

    def _find(self, reference: EvidenceReference) -> object:
        field_and_id = _DOMAIN_BY_NAME.get(reference.domain)
        if field_and_id is None:
            raise MalformedEvidenceReferenceError(
                f"evidence domain is not citable: {reference.domain}"
            )
        field, id_field = field_and_id
        matches = tuple(
            record
            for record in getattr(self._bundle, field)
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
        if manifest is None or manifest.available_at > self._bundle.knowledge_cutoff:
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
            "reference": _unfreeze(item.reference.model_dump(mode="json")),
            "content": _unfreeze(item.content),
            "provenance": _unfreeze(item.provenance),
        }
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return redact_text(
            "--- BEGIN UNTRUSTED EVIDENCE ---\n"
            + raw
            + "\n--- END UNTRUSTED EVIDENCE ---"
        )


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
