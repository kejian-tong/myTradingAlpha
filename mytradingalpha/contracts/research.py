"""Strict wire contracts for cited historical research evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import StrictStr, field_validator

from mytradingalpha.data.provenance import CanonicalChecksum, SourceManifest

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


class _FrozenDict(dict[str, str]):
    """Small immutable mapping used for the note's source-field binding."""

    def _blocked(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("research note mappings are immutable")

    __delitem__ = __setitem__ = clear = pop = popitem = setdefault = update = _blocked


class EvidenceReference(ContractModel):
    """A domain-qualified reference to exactly one bundle record."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    bundle_id: StableId
    domain: CitableDomain
    record_id: StableId


class EvidenceCitation(ContractModel):
    """One validated citation whose semantic support remains unassessed."""

    claim: ResearchClaim
    reference: EvidenceReference
    provenance: SourceManifest
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
        raise TypeError("research note is not canonical JSON data") from exc


class ResearchNote(ContractModel):
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
    capture_manifest: SourceManifest
    source_agent: StrictStr
    source_fields: dict[ResearchClaim, StrictStr]
    thesis: StrictStr
    risks: tuple[StrictStr, ...]
    citations: tuple[EvidenceCitation, ...]

    @field_validator("source_fields", mode="after")
    @classmethod
    def validate_source_fields(
        cls, value: dict[ResearchClaim, StrictStr]
    ) -> dict[ResearchClaim, StrictStr]:
        if set(value) != {"thesis", "risks"}:
            raise ValueError("research note source fields must name thesis and risks")
        return _FrozenDict(value)

    @field_validator("risks", mode="before")
    @classmethod
    def normalize_risks(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("research note risks require a sequence")
        return tuple(value)  # type: ignore[arg-type]

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
    "ResearchNoteSerializationError",
]
