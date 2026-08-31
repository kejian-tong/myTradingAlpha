"""Immutable provenance contracts for PIT-01 raw captures."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, StrictInt, StrictStr, model_validator

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

_CHECKSUM_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _validate_required_reference(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid_reference: expected a non-empty trimmed string")
    return value


RequiredReference = Annotated[
    StrictStr,
    BeforeValidator(_validate_required_reference),
]


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
    checksum: StrictStr = Field(pattern=_CHECKSUM_PATTERN.pattern)
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


__all__ = ["SourceManifest"]
