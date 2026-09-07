"""Immutable provenance contracts for PIT-01 raw captures."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictInt, model_validator

from mytradingalpha.contracts.common import (
    CanonicalChecksum,
    RequiredReference,
    StableId,
    UtcDateTime,
)
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION


class SourceManifest(ContractModel):
    """Versioned provenance for one immutable provider payload."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    manifest_id: StableId
    source: StableId
    source_locator: RequiredReference
    fetched_at: UtcDateTime
    event_time: UtcDateTime | None
    published_at: UtcDateTime | None
    available_at: UtcDateTime
    ingested_at: UtcDateTime
    checksum: CanonicalChecksum
    terms: RequiredReference
    revision: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_provenance_chronology(self) -> SourceManifest:
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("invalid_time_order: published_at must be at or before available_at")
        if self.available_at > self.fetched_at:
            raise ValueError("invalid_time_order: available_at must be at or before fetched_at")
        if self.fetched_at > self.ingested_at:
            raise ValueError("invalid_time_order: fetched_at must be at or before ingested_at")
        return self


__all__ = ["CanonicalChecksum", "RequiredReference", "SourceManifest"]
