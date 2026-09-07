"""Strict wire contracts for cited historical research evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from mytradingalpha.data.provenance import CanonicalChecksum

from .common import StableId, UtcDateTime
from .redaction import validate_artifact_text
from .schemas import ContractModel
from .versions import CURRENT_SCHEMA_VERSION

CitableDomain = Literal[
    "instruments",
    "aliases",
    "memberships",
    "actions",
    "bars",
    "filings",
    "events",
    "social",
    "macro",
]
ResearchClaim = Literal["thesis", "risks"]
ResearchSourceAgent = Literal[
    "market_analyst",
    "sentiment_analyst",
    "news_analyst",
    "fundamentals_analyst",
    "bull_researcher",
    "bear_researcher",
    "research_manager",
    "trader",
    "aggressive_analyst",
    "neutral_analyst",
    "conservative_analyst",
    "portfolio_manager",
]
MAX_RESEARCH_NOTE_BYTES = 4_194_304


class ResearchNoteSerializationError(ValueError):
    """Raised when a note cannot be represented within its canonical bounds."""


class _ResearchContractModel(ContractModel):
    """Strict nested research model with defensive instance revalidation."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class ResearchSourceFields(_ResearchContractModel):
    """Exact cached-response fields selected for thesis and risks."""

    thesis: StrictStr
    risks: StrictStr

    @field_validator("thesis", "risks")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("research source field names must be non-empty and trimmed")
        return value


class ResearchProvenance(_ResearchContractModel):
    """Redacted SourceManifest projection retaining an exact-manifest hash."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    manifest_id: StableId
    source: StableId
    source_locator: StrictStr
    fetched_at: UtcDateTime
    event_time: UtcDateTime | None
    published_at: UtcDateTime | None
    available_at: UtcDateTime
    ingested_at: UtcDateTime
    checksum: CanonicalChecksum
    terms: StrictStr
    revision: StrictInt = Field(ge=0)
    manifest_hash: CanonicalChecksum

    @model_validator(mode="after")
    def validate_redacted_fields(self) -> ResearchProvenance:
        if self.source_locator != "[REDACTED]" or self.terms != "[REDACTED]":
            raise ValueError("research provenance requires redacted projection fields")
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("research provenance publication follows availability")
        if self.available_at > self.fetched_at:
            raise ValueError("research provenance availability follows fetch")
        if self.fetched_at > self.ingested_at:
            raise ValueError("research provenance fetch follows ingestion")
        return self


class EvidenceReference(_ResearchContractModel):
    """A domain-qualified reference to exactly one bundle record."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    bundle_id: StableId
    domain: CitableDomain
    record_id: StableId


class EvidenceCitation(_ResearchContractModel):
    """One validated citation whose semantic support remains unassessed."""

    claim: ResearchClaim
    reference: EvidenceReference
    provenance: ResearchProvenance
    semantic_support: Literal["unassessed"] = "unassessed"


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise ResearchNoteSerializationError("research note is not canonical JSON data") from exc


class ResearchNote(_ResearchContractModel):
    """Immutable, provenance-bound note derived from sealed research output."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    note_id: StableId
    run_id: StableId
    variant_id: StableId
    instrument_id: StableId
    bundle_id: StableId
    bundle_hash: CanonicalChecksum
    knowledge_cutoff: UtcDateTime
    calendar_id: StableId
    replay_policy: Literal["availability", "archive_realistic"]
    response_id: StableId
    response_hash: CanonicalChecksum
    output_hash: CanonicalChecksum
    graph_artifact_id: StableId
    graph_artifact_hash: CanonicalChecksum
    model_artifact_id: StableId
    model_artifact_hash: CanonicalChecksum
    runtime_manifest_id: StableId
    runtime_manifest_hash: CanonicalChecksum
    capture_manifest: ResearchProvenance
    source_agent: ResearchSourceAgent
    source_fields: ResearchSourceFields
    thesis: StrictStr
    risks: tuple[StrictStr, ...]
    citations: tuple[EvidenceCitation, ...]

    @field_validator("source_agent", mode="before")
    @classmethod
    def validate_source_agent_type(cls, value: object) -> object:
        if type(value) is not str:
            raise ValueError("source_agent requires an exact built-in string")
        return value

    @field_validator("source_fields", mode="before")
    @classmethod
    def validate_source_fields(cls, value: object) -> object:
        if type(value) not in (dict, ResearchSourceFields):
            raise ValueError("research note source fields require plain data")
        return value

    @field_validator("risks", mode="before")
    @classmethod
    def normalize_risks(cls, value: object) -> tuple[str, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("research note risks require a sequence")
        return tuple(value)  # type: ignore[arg-type]

    @field_validator("thesis")
    @classmethod
    def validate_thesis_text(cls, value: str) -> str:
        return validate_artifact_text(value)

    @field_validator("risks")
    @classmethod
    def validate_risk_texts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(validate_artifact_text(item) for item in value)

    @field_validator("citations", mode="before")
    @classmethod
    def normalize_citations(cls, value: object) -> tuple[object, ...]:
        if type(value) not in (tuple, list):
            raise ValueError("research note citations require a sequence")
        for item in value:  # type: ignore[union-attr]
            if type(item) not in (dict, EvidenceCitation):
                raise ValueError("research note citations require plain data")
        return tuple(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_citation_integrity(self) -> ResearchNote:
        if not self.citations:
            raise ValueError("research note requires at least one citation")
        if self.capture_manifest.checksum != self.output_hash:
            raise ValueError("research note capture checksum does not match output hash")
        manifests = (self.capture_manifest, *(citation.provenance for citation in self.citations))
        for manifest in manifests:
            if manifest.available_at > self.knowledge_cutoff:
                raise ValueError("research note evidence is unavailable at cutoff")
            if (
                self.replay_policy == "archive_realistic"
                and manifest.ingested_at > self.knowledge_cutoff
            ):
                raise ValueError("research note evidence is not archived at cutoff")
        seen: set[tuple[str, str]] = set()
        claims: set[str] = set()
        for citation in self.citations:
            reference_key = (citation.reference.domain, citation.reference.record_id)
            if citation.reference.bundle_id != self.bundle_id:
                raise ValueError("research citation targets another bundle")
            if reference_key in seen:
                raise ValueError("research note contains duplicate citation")
            seen.add(reference_key)
            claims.add(citation.claim)
        if claims != {"thesis", "risks"}:
            raise ValueError("research note must cite both thesis and risks")
        return self

    def canonical_bytes(self) -> bytes:
        """Return bounded canonical UTF-8 JSON for this note."""

        raw = _canonical_note_bytes(self)
        if len(raw) > MAX_RESEARCH_NOTE_BYTES:
            raise ResearchNoteSerializationError(
                "research note exceeds maximum canonical byte size"
            )
        return raw

    @property
    def note_hash(self) -> str:
        """Return the deterministic content hash for canonical note bytes."""

        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


_NOTE_MODEL_FIELDS: dict[type[object], tuple[str, ...]] = {
    ResearchNote: (
        "schema_version",
        "note_id",
        "run_id",
        "variant_id",
        "instrument_id",
        "bundle_id",
        "bundle_hash",
        "knowledge_cutoff",
        "calendar_id",
        "replay_policy",
        "response_id",
        "response_hash",
        "output_hash",
        "graph_artifact_id",
        "graph_artifact_hash",
        "model_artifact_id",
        "model_artifact_hash",
        "runtime_manifest_id",
        "runtime_manifest_hash",
        "capture_manifest",
        "source_agent",
        "source_fields",
        "thesis",
        "risks",
        "citations",
    ),
    ResearchSourceFields: ("thesis", "risks"),
    ResearchProvenance: (
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
        "manifest_hash",
    ),
    EvidenceCitation: ("claim", "reference", "provenance", "semantic_support"),
    EvidenceReference: ("schema_version", "bundle_id", "domain", "record_id"),
}
_NOTE_FIELD_TYPES: dict[tuple[type[object], str], tuple[type[object], ...]] = {
    (ResearchNote, "knowledge_cutoff"): (datetime,),
    (ResearchNote, "capture_manifest"): (ResearchProvenance,),
    (ResearchNote, "source_fields"): (ResearchSourceFields,),
    (ResearchNote, "risks"): (tuple,),
    (ResearchNote, "citations"): (tuple,),
    (ResearchSourceFields, "thesis"): (str,),
    (ResearchSourceFields, "risks"): (str,),
    (ResearchProvenance, "source_locator"): (str,),
    (ResearchProvenance, "fetched_at"): (datetime,),
    (ResearchProvenance, "event_time"): (datetime, type(None)),
    (ResearchProvenance, "published_at"): (datetime, type(None)),
    (ResearchProvenance, "available_at"): (datetime,),
    (ResearchProvenance, "ingested_at"): (datetime,),
    (ResearchProvenance, "terms"): (str,),
    (EvidenceCitation, "reference"): (EvidenceReference,),
    (EvidenceCitation, "provenance"): (ResearchProvenance,),
}


def _raw_note_fields(value: object, expected_type: type[object]) -> dict[str, object]:
    fields = _NOTE_MODEL_FIELDS[expected_type]
    try:
        storage = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError) as exc:
        raise ResearchNoteSerializationError("research note storage is unavailable") from exc
    if type(storage) is not dict:
        raise ResearchNoteSerializationError("research note storage must be an exact dictionary")
    keys = tuple(dict.keys(storage))
    if any(type(key) is not str for key in keys) or set(keys) != set(fields):
        raise ResearchNoteSerializationError("research note fields are not canonical")
    return {field: dict.__getitem__(storage, field) for field in fields}


def _safe_note_value(value: object, *, seen: set[int], depth: int) -> object:
    if depth > 64:
        raise ResearchNoteSerializationError("research note exceeds maximum nesting depth")
    value_type = type(value)
    if value_type in (str, int, bool, type(None)):
        return value
    if value_type is datetime:
        if object.__getattribute__(value, "tzinfo") is not timezone.utc:
            raise ResearchNoteSerializationError(
                "research note timestamps require the exact UTC timezone"
            )
        return value.isoformat().replace("+00:00", "Z")
    if value_type is tuple:
        identity = id(value)
        if identity in seen:
            raise ResearchNoteSerializationError("research note contains a cycle")
        seen.add(identity)
        try:
            return [
                _safe_note_value(item, seen=seen, depth=depth + 1)
                for item in value
            ]
        finally:
            seen.remove(identity)
    if value_type is dict:
        identity = id(value)
        if identity in seen:
            raise ResearchNoteSerializationError("research note contains a cycle")
        seen.add(identity)
        try:
            result: dict[str, object] = {}
            for key, item in value.items():
                if type(key) is not str:
                    raise ResearchNoteSerializationError(
                        "research note object keys must be exact strings"
                    )
                result[key] = _safe_note_value(item, seen=seen, depth=depth + 1)
            return result
        finally:
            seen.remove(identity)
    if value_type not in _NOTE_MODEL_FIELDS:
        raise ResearchNoteSerializationError("research note contains an unsupported object")
    identity = id(value)
    if identity in seen:
        raise ResearchNoteSerializationError("research note contains a cycle")
    seen.add(identity)
    try:
        fields = _raw_note_fields(value, value_type)
        safe: dict[str, object] = {}
        for field, item in fields.items():
            allowed = _NOTE_FIELD_TYPES.get((value_type, field))
            if allowed is not None and type(item) not in allowed:
                raise ResearchNoteSerializationError(
                    "research note contains a value of the wrong exact type"
                )
            safe[field] = _safe_note_value(item, seen=seen, depth=depth + 1)
        return safe
    finally:
        seen.remove(identity)


def _safe_note_payload(note: ResearchNote) -> dict[str, object]:
    if type(note) is not ResearchNote:
        raise ResearchNoteSerializationError("canonicalization requires an exact ResearchNote")
    payload = _safe_note_value(note, seen=set(), depth=0)
    if type(payload) is not dict:
        raise ResearchNoteSerializationError("research note did not normalize to an object")
    return payload


def _derive_note_id_from_payload(payload: dict[str, object]) -> str:
    preimage = dict(payload)
    preimage["note_id"] = "note-pending"
    return f"note-{hashlib.sha256(_canonical_json(preimage)).hexdigest()}"


def derive_research_note_id(note: ResearchNote) -> str:
    """Derive the deterministic note ID from a safe canonical preimage."""

    return _derive_note_id_from_payload(_safe_note_payload(note))


def _canonical_note_bytes(note: ResearchNote) -> bytes:
    payload = _safe_note_payload(note)
    if payload.get("note_id") != _derive_note_id_from_payload(payload):
        raise ResearchNoteSerializationError("research note ID does not match canonical content")
    try:
        rebuilt = ResearchNote.model_validate(payload)
        rebuilt_payload = _safe_note_payload(rebuilt)
        return _canonical_json(rebuilt_payload)
    except ResearchNoteSerializationError:
        raise
    except (TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise ResearchNoteSerializationError(
            "research note failed safe canonical validation"
        ) from exc


__all__ = [
    "CitableDomain",
    "EvidenceCitation",
    "EvidenceReference",
    "MAX_RESEARCH_NOTE_BYTES",
    "ResearchClaim",
    "ResearchNote",
    "ResearchProvenance",
    "ResearchSourceAgent",
    "ResearchSourceFields",
    "ResearchNoteSerializationError",
    "derive_research_note_id",
]
