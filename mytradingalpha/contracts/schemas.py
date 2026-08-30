"""Versioned Pydantic contracts owned by the production namespace."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import StableId, UtcDateTime
from .versions import CURRENT_SCHEMA_VERSION


class ContractModel(BaseModel):
    """Immutable contract base that rejects fields outside the declared schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Mode(str, Enum):
    """Execution/replay modes with stable wire values."""

    HISTORICAL = "historical"
    FORWARD_PAPER = "forward_paper"
    LIVE_PILOT = "live_pilot"


class RunContext(ContractModel):
    """Immutable, versioned context delimiting one production run."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    run_id: StableId
    mode: Mode
    variant_id: StableId
    decision_time: UtcDateTime
    knowledge_cutoff: UtcDateTime
    earliest_execution_time: UtcDateTime
    bundle_id: StableId
    bundle_hash: StableId
    calendar_id: StableId
    base_currency: StableId = Field(default="USD", validate_default=True)

    @model_validator(mode="after")
    def validate_time_order(self) -> RunContext:
        if self.knowledge_cutoff > self.decision_time:
            raise ValueError(
                "invalid_time_order: knowledge_cutoff must be at or before decision_time"
            )
        if self.decision_time >= self.earliest_execution_time:
            raise ValueError(
                "invalid_time_order: decision_time must be before earliest_execution_time"
            )
        return self


__all__ = ["ContractModel", "Mode", "RunContext"]
