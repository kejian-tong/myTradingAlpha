"""Fail-closed zero-egress guard for historical bundle replay."""

from __future__ import annotations

import re
from datetime import datetime as _datetime, timezone as _timezone

from pydantic import ValidationError

from mytradingalpha.contracts.schemas import Mode, NetworkPolicy, RunContext

from .bundle import EvidenceBundle
from .repository import EvidenceRepository

_CANONICAL_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_NETWORK_COMPONENTS = (
    "data_capture_egress",
    "model_provider_egress",
    "research_tool_egress",
    "paper_broker_egress",
    "live_broker_egress",
)
_RUN_CONTEXT_FIELDS = (
    "schema_version",
    "run_id",
    "mode",
    "variant_id",
    "decision_time",
    "knowledge_cutoff",
    "earliest_execution_time",
    "bundle_id",
    "bundle_hash",
    "calendar_id",
    "base_currency",
    "network_policy",
)
_RUN_CONTEXT_STRING_FIELDS = (
    "schema_version",
    "run_id",
    "variant_id",
    "bundle_id",
    "bundle_hash",
    "calendar_id",
    "base_currency",
)
_RUN_CONTEXT_TIME_FIELDS = (
    "decision_time",
    "knowledge_cutoff",
    "earliest_execution_time",
)


class HistoricalDataGuardError(ValueError):
    """Base class for public historical replay guard failures."""


class HistoricalReplayDeniedError(HistoricalDataGuardError):
    """Raised when a context is invalid or not strictly zero-egress historical."""


class HistoricalReplayMismatchError(HistoricalDataGuardError):
    """Raised when a context does not bind the exact requested sealed bundle."""


def _exact_fields(
    value: dict[object, object], expected: tuple[str, ...], *, label: str
) -> dict[str, object]:
    keys = tuple(dict.keys(value))
    if any(type(key) is not str for key in keys) or set(keys) != set(expected):
        raise HistoricalReplayDeniedError(f"invalid {label} field set")
    return {field: dict.__getitem__(value, field) for field in expected}


def _is_exact_utc_datetime(value: object) -> bool:
    return type(value) is _datetime and object.__getattribute__(value, "tzinfo") is _timezone.utc


def _safe_network_policy(value: object) -> dict[str, bool]:
    if type(value) is NetworkPolicy:
        raw = object.__getattribute__(value, "__dict__")
        if type(raw) is not dict:
            raise HistoricalReplayDeniedError("invalid historical NetworkPolicy storage")
        fields = _exact_fields(raw, _NETWORK_COMPONENTS, label="historical NetworkPolicy")
    elif type(value) is dict:
        fields = _exact_fields(value, _NETWORK_COMPONENTS, label="historical NetworkPolicy")
    else:
        raise HistoricalReplayDeniedError(
            "historical replay requires an exact NetworkPolicy or dictionary"
        )
    if any(type(fields[field]) is not bool for field in _NETWORK_COMPONENTS):
        raise HistoricalReplayDeniedError("historical NetworkPolicy requires exact boolean values")
    return {field: fields[field] for field in _NETWORK_COMPONENTS}  # type: ignore[misc]


def _safe_context_fields(context: object) -> dict[str, object]:
    if type(context) is not RunContext:
        raise HistoricalReplayDeniedError(
            "historical replay requires the exact frozen RunContext type"
        )
    raw = object.__getattribute__(context, "__dict__")
    if type(raw) is not dict:
        raise HistoricalReplayDeniedError("invalid historical RunContext storage")
    fields = _exact_fields(raw, _RUN_CONTEXT_FIELDS, label="historical RunContext")
    if any(type(fields[field]) is not str for field in _RUN_CONTEXT_STRING_FIELDS):
        raise HistoricalReplayDeniedError(
            "historical RunContext scalar fields require exact strings"
        )
    if type(fields["mode"]) not in (str, Mode):
        raise HistoricalReplayDeniedError(
            "historical RunContext mode requires an exact string or Mode"
        )
    if any(
        type(fields[field]) is not str and not _is_exact_utc_datetime(fields[field])
        for field in _RUN_CONTEXT_TIME_FIELDS
    ):
        raise HistoricalReplayDeniedError(
            "historical RunContext times require exact strings or UTC datetimes"
        )
    fields["network_policy"] = _safe_network_policy(fields["network_policy"])
    return fields


def _validated_context(context: object) -> RunContext:
    try:
        validated = RunContext.model_validate(_safe_context_fields(context))
    except (TypeError, ValidationError, ValueError) as exc:
        raise HistoricalReplayDeniedError("invalid historical RunContext") from exc

    if type(validated) is not RunContext:
        raise HistoricalReplayDeniedError("invalid canonical historical RunContext type")
    canonical = _safe_context_fields(validated)
    if type(canonical["mode"]) is not Mode:
        raise HistoricalReplayDeniedError("historical RunContext mode did not normalize")
    if any(not _is_exact_utc_datetime(canonical[field]) for field in _RUN_CONTEXT_TIME_FIELDS):
        raise HistoricalReplayDeniedError("historical RunContext times did not normalize to UTC")
    if type(object.__getattribute__(validated, "network_policy")) is not NetworkPolicy:
        raise HistoricalReplayDeniedError("historical NetworkPolicy did not normalize")

    if _CANONICAL_HASH.fullmatch(validated.bundle_hash) is None:
        raise HistoricalReplayDeniedError("historical RunContext requires a canonical bundle hash")
    return validated


class HistoricalDataGuard:
    """Concrete RunContext validator and exact sealed-bundle replay boundary."""

    @staticmethod
    def assert_network_denied(context: RunContext) -> None:
        """Require historical mode with every component-scoped egress flag false."""

        validated = _validated_context(context)
        if validated.mode is not Mode.HISTORICAL or any(
            getattr(validated.network_policy, component) for component in _NETWORK_COMPONENTS
        ):
            raise HistoricalReplayDeniedError(
                "historical replay requires historical mode and zero network egress"
            )

    @staticmethod
    def replay(
        repository: EvidenceRepository,
        bundle_id: str,
        context: RunContext,
    ) -> EvidenceBundle:
        """Return only the sealed bundle exactly named by a zero-egress context."""

        bundle, _ = HistoricalDataGuard.replay_bound(repository, bundle_id, context)
        return bundle

    @staticmethod
    def replay_bound(
        repository: EvidenceRepository,
        bundle_id: str,
        context: RunContext,
    ) -> tuple[EvidenceBundle, RunContext]:
        """Return the sealed bundle and defensive canonical context bound to it."""

        if type(bundle_id) is not str:
            raise HistoricalReplayDeniedError(
                "historical replay requires an exact bundle ID string"
            )
        validated_context = _validated_context(context)
        HistoricalDataGuard.assert_network_denied(validated_context)
        if type(repository) is not EvidenceRepository:
            raise HistoricalReplayDeniedError(
                "historical replay requires the exact in-memory evidence repository"
            )
        if validated_context.bundle_id != bundle_id:
            raise HistoricalReplayMismatchError("historical bundle ID mismatch")

        bundle = repository.get(bundle_id)
        if bundle.bundle_id != bundle_id:
            raise HistoricalReplayMismatchError("historical bundle ID mismatch")
        if validated_context.bundle_hash != bundle.bundle_hash:
            raise HistoricalReplayMismatchError("historical bundle hash mismatch")
        if validated_context.knowledge_cutoff != bundle.knowledge_cutoff:
            raise HistoricalReplayMismatchError("historical knowledge cutoff mismatch")
        if validated_context.calendar_id != bundle.calendar.calendar_id:
            raise HistoricalReplayMismatchError("historical calendar mismatch")
        return bundle, validated_context


__all__ = [
    "HistoricalDataGuard",
    "HistoricalDataGuardError",
    "HistoricalReplayDeniedError",
    "HistoricalReplayMismatchError",
]
