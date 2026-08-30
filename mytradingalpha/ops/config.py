"""Opt-in production configuration and fail-closed mode policy."""

from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, StrictBool, model_validator

from mytradingalpha.contracts import (
    ContractModel,
    Mode,
    NetworkPolicy,
    StableId,
    UtcDateTime,
)

_NETWORK_COMPONENTS = (
    "data_capture_egress",
    "model_provider_egress",
    "research_tool_egress",
    "paper_broker_egress",
    "live_broker_egress",
)
_BOOL_TRUE = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE = frozenset({"false", "0", "no", "off"})


class ModeConfig(ContractModel):
    """Validated ``run`` section for historical and read-only forward modes."""

    mode: Mode = Mode.HISTORICAL
    variant_id: StableId = "quant_only_v1"
    calendar_id: StableId = "XNYS-regular-v1"
    decision_time: UtcDateTime | None = None
    knowledge_cutoff: UtcDateTime | None = None
    earliest_execution_time: UtcDateTime | None = None
    bundle_id: StableId | None = None
    bundle_hash: StableId | None = None
    replay_policy: Literal["availability", "archive_realistic"] = "availability"
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    live_level: StableId | None = None
    required_gate_evidence_ref: StableId | None = None

    @model_validator(mode="after")
    def validate_mode_policy(self) -> ModeConfig:
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

        timestamps = (
            self.decision_time,
            self.knowledge_cutoff,
            self.earliest_execution_time,
        )
        if any(timestamp is not None for timestamp in timestamps) and not all(
            timestamp is not None for timestamp in timestamps
        ):
            raise ValueError(
                "decision_time, knowledge_cutoff, and earliest_execution_time must be provided together"
            )
        if all(timestamp is not None for timestamp in timestamps):
            assert self.decision_time is not None
            assert self.knowledge_cutoff is not None
            assert self.earliest_execution_time is not None
            if self.knowledge_cutoff > self.decision_time:
                raise ValueError(
                    "knowledge_cutoff must be at or before decision_time"
                )
            if self.decision_time >= self.earliest_execution_time:
                raise ValueError(
                    "decision_time must be before earliest_execution_time"
                )
        return self


class BrokerConfig(ContractModel):
    """Opaque execution references and disabled write flags."""

    paper_endpoint_id: StableId | None = None
    broker_endpoint_id: StableId | None = None
    approval_ref: StableId | None = None
    secret_ref: StableId | None = None
    paper_write_enabled: StrictBool = False
    live_write_enabled: StrictBool = False
    human_approval_required: StrictBool = False

    @model_validator(mode="after")
    def reject_live_write(self) -> BrokerConfig:
        if self.live_write_enabled:
            raise ValueError("live writes are disabled before Phase 09")
        return self


class PersistenceConfig(ContractModel):
    """Opaque persistence identities; this slice performs no persistence."""

    bundle_store: StableId = "local-bundle-store"
    manifest_store: StableId = "local-manifest-store"


class ProductionConfig(ContractModel):
    """Immutable, opt-in configuration with explicit foundation sections."""

    run: ModeConfig = Field(default_factory=ModeConfig)
    execution: BrokerConfig = Field(default_factory=BrokerConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)

    @model_validator(mode="after")
    def validate_cross_section_policy(self) -> ProductionConfig:
        if self.run.mode is Mode.HISTORICAL and (
            self.execution.paper_write_enabled or self.execution.live_write_enabled
        ):
            raise ValueError("historical mode cannot enable paper or live writes")

        if self.execution.paper_write_enabled:
            if self.run.mode is not Mode.FORWARD_PAPER:
                raise ValueError("paper writes require forward_paper mode")
            if not self.run.network_policy.paper_broker_egress:
                raise ValueError("paper writes require paper-broker egress")
            if not self.execution.paper_endpoint_id:
                raise ValueError("paper writes require an approved paper endpoint reference")
            if not self.execution.approval_ref:
                raise ValueError("paper writes require an approval reference")
        return self

    @classmethod
    def load(
        cls,
        source: Mapping[str, Any] | str | Path | None = None,
    ) -> ProductionConfig:
        """Load a mapping or safe YAML source, then apply flat env overrides."""

        payload = cls._read_source(source)
        merged = deepcopy(payload)
        cls._apply_environment_overrides(merged)
        return cls.model_validate(merged)

    @staticmethod
    def _read_source(source: Mapping[str, Any] | str | Path | None) -> dict[str, Any]:
        if source is None:
            return {}
        if isinstance(source, Mapping):
            return dict(source)

        if isinstance(source, str):
            source = Path(source)
        if not isinstance(source, Path):
            raise TypeError("configuration source must be a mapping or YAML path")
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"could not read configuration source {source}") from exc
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"malformed YAML configuration in {source}") from exc
        if not isinstance(loaded, Mapping):
            raise ValueError("configuration YAML must contain a top-level mapping")
        return dict(loaded)

    @classmethod
    def _apply_environment_overrides(cls, payload: dict[str, Any]) -> None:
        for environment_name in os.environ:
            if environment_name.startswith("MYTRADINGALPHA_") and environment_name not in _ENV_OVERRIDES:
                raise ValueError(f"unknown production configuration environment variable {environment_name}")

        for environment_name, (path, field_name, kind) in _ENV_OVERRIDES.items():
            raw_value = os.environ.get(environment_name)
            if raw_value is None:
                continue
            if not raw_value.strip():
                raise ValueError(f"empty value for {environment_name}")
            section_payload = payload
            for section in path:
                section_payload = section_payload.setdefault(section, {})
                if not isinstance(section_payload, Mapping):
                    raise ValueError(f"configuration section {section!r} must be a mapping")
                section_payload = dict(section_payload)
            section_payload[field_name] = _coerce_environment_value(raw_value, kind, environment_name)
            parent = payload
            for section in path[:-1]:
                child = dict(parent[section])
                parent[section] = child
                parent = child
            parent[path[-1]] = section_payload


_ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], str, Literal["bool", "str"]]] = {
    "MYTRADINGALPHA_MODE": (("run",), "mode", "str"),
    "MYTRADINGALPHA_VARIANT_ID": (("run",), "variant_id", "str"),
    "MYTRADINGALPHA_CALENDAR_ID": (("run",), "calendar_id", "str"),
    "MYTRADINGALPHA_REPLAY_POLICY": (("run",), "replay_policy", "str"),
    "MYTRADINGALPHA_LIVE_LEVEL": (("run",), "live_level", "str"),
    "MYTRADINGALPHA_REQUIRED_GATE_EVIDENCE_REF": (
        ("run",),
        "required_gate_evidence_ref",
        "str",
    ),
    "MYTRADINGALPHA_DATA_CAPTURE_EGRESS": (
        ("run", "network_policy"),
        "data_capture_egress",
        "bool",
    ),
    "MYTRADINGALPHA_MODEL_PROVIDER_EGRESS": (
        ("run", "network_policy"),
        "model_provider_egress",
        "bool",
    ),
    "MYTRADINGALPHA_RESEARCH_TOOL_EGRESS": (
        ("run", "network_policy"),
        "research_tool_egress",
        "bool",
    ),
    "MYTRADINGALPHA_PAPER_BROKER_EGRESS": (
        ("run", "network_policy"),
        "paper_broker_egress",
        "bool",
    ),
    "MYTRADINGALPHA_LIVE_BROKER_EGRESS": (
        ("run", "network_policy"),
        "live_broker_egress",
        "bool",
    ),
    "MYTRADINGALPHA_PAPER_ENDPOINT_ID": (("execution",), "paper_endpoint_id", "str"),
    "MYTRADINGALPHA_BROKER_ENDPOINT_ID": (("execution",), "broker_endpoint_id", "str"),
    "MYTRADINGALPHA_APPROVAL_REF": (("execution",), "approval_ref", "str"),
    "MYTRADINGALPHA_SECRET_REF": (("execution",), "secret_ref", "str"),
    "MYTRADINGALPHA_PAPER_WRITE_ENABLED": (
        ("execution",),
        "paper_write_enabled",
        "bool",
    ),
    "MYTRADINGALPHA_LIVE_WRITE_ENABLED": (
        ("execution",),
        "live_write_enabled",
        "bool",
    ),
    "MYTRADINGALPHA_HUMAN_APPROVAL_REQUIRED": (
        ("execution",),
        "human_approval_required",
        "bool",
    ),
    "MYTRADINGALPHA_BUNDLE_STORE": (("persistence",), "bundle_store", "str"),
    "MYTRADINGALPHA_MANIFEST_STORE": (("persistence",), "manifest_store", "str"),
}


def _coerce_environment_value(raw_value: str, kind: Literal["bool", "str"], name: str) -> Any:
    if kind == "str":
        return raw_value.strip()
    normalized = raw_value.strip().lower()
    if normalized in _BOOL_TRUE:
        return True
    if normalized in _BOOL_FALSE:
        return False
    raise ValueError(f"invalid boolean value for {name}: {raw_value!r}")


__all__ = [
    "BrokerConfig",
    "ModeConfig",
    "NetworkPolicy",
    "PersistenceConfig",
    "ProductionConfig",
]
