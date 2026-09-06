"""Strict wire contracts for cited historical research evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from mytradingalpha.data.provenance import CanonicalChecksum

from .common import StableId, UtcDateTime
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
    source_agent: StrictStr
    source_fields: ResearchSourceFields
    thesis: StrictStr
    risks: tuple[StrictStr, ...]
    citations: tuple[EvidenceCitation, ...]

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

        raw = _canonical_json(self.model_dump(mode="json"))
        if len(raw) > MAX_RESEARCH_NOTE_BYTES:
            raise ResearchNoteSerializationError(
                "research note exceeds maximum canonical byte size"
            )
        return raw

    @property
    def note_hash(self) -> str:
        """Return the deterministic content hash for canonical note bytes."""

        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


__all__ = [
    "CitableDomain",
    "EvidenceCitation",
    "EvidenceReference",
    "MAX_RESEARCH_NOTE_BYTES",
    "ResearchClaim",
    "ResearchNote",
    "ResearchProvenance",
    "ResearchSourceFields",
    "ResearchNoteSerializationError",
]
