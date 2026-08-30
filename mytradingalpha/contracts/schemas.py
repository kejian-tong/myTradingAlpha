"""Versioned Pydantic contracts owned by the production namespace."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .common import StableId, UtcDateTime
from .versions import CURRENT_SCHEMA_VERSION

_NETWORK_COMPONENTS = (
    "data_capture_egress",
    "model_provider_egress",
    "research_tool_egress",
    "paper_broker_egress",
    "live_broker_egress",
)


class ContractModel(BaseModel):
    """Immutable contract base that rejects fields outside the declared schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Mode(str, Enum):
    """Execution/replay modes with stable wire values."""

    HISTORICAL = "historical"
    FORWARD_PAPER = "forward_paper"
    LIVE_PILOT = "live_pilot"


class NetworkPolicy(ContractModel):
    """Component-scoped network egress policy, denied by default."""

    data_capture_egress: StrictBool = False
    model_provider_egress: StrictBool = False
    research_tool_egress: StrictBool = False
    paper_broker_egress: StrictBool = False
    live_broker_egress: StrictBool = False


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
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)

    @model_validator(mode="after")
    def validate_time_order(self) -> RunContext:
        if self.mode is Mode.HISTORICAL and any(
            getattr(self.network_policy, component) for component in _NETWORK_COMPONENTS
        ):
            raise ValueError("historical mode requires every network component to be disabled")

        if self.mode is Mode.FORWARD_PAPER and (
            self.network_policy.research_tool_egress
            or self.network_policy.live_broker_egress
        ):
            raise ValueError(
                "forward paper mode cannot enable research-tool or live-broker egress"
            )

        if self.mode is Mode.LIVE_PILOT and (
            self.network_policy.research_tool_egress
            or self.network_policy.paper_broker_egress
            or self.network_policy.live_broker_egress
        ):
            raise ValueError(
                "live pilot read-only mode cannot enable research, paper, or live-broker egress"
            )

        if self.knowledge_cutoff > self.decision_time:
            raise ValueError(
                "invalid_time_order: knowledge_cutoff must be at or before decision_time"
            )
        if self.decision_time >= self.earliest_execution_time:
            raise ValueError(
                "invalid_time_order: decision_time must be before earliest_execution_time"
            )
        return self


__all__ = ["ContractModel", "Mode", "NetworkPolicy", "RunContext"]
