"""Fail-closed zero-egress guard for historical bundle replay."""

from __future__ import annotations

import re

from pydantic import ValidationError

from mytradingalpha.contracts.schemas import Mode, RunContext

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


class HistoricalDataGuardError(ValueError):
    """Base class for public historical replay guard failures."""


class HistoricalReplayDeniedError(HistoricalDataGuardError):
    """Raised when a context is invalid or not strictly zero-egress historical."""


class HistoricalReplayMismatchError(HistoricalDataGuardError):
    """Raised when a context does not bind the exact requested sealed bundle."""


def _validated_context(context: object) -> RunContext:
    try:
        payload = (
            context.model_dump(mode="python")
            if isinstance(context, RunContext)
            else context
        )
        validated = RunContext.model_validate(payload)
    except (TypeError, ValidationError, ValueError) as exc:
        raise HistoricalReplayDeniedError("invalid historical RunContext") from exc

    if _CANONICAL_HASH.fullmatch(validated.bundle_hash) is None:
        raise HistoricalReplayDeniedError(
            "historical RunContext requires a canonical bundle hash"
        )
    return validated


class HistoricalDataGuard:
    """Concrete RunContext validator and exact sealed-bundle replay boundary."""

    @staticmethod
    def assert_network_denied(context: RunContext) -> None:
        """Require historical mode with every component-scoped egress flag false."""

        validated = _validated_context(context)
        if validated.mode is not Mode.HISTORICAL or any(
            getattr(validated.network_policy, component)
            for component in _NETWORK_COMPONENTS
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

        validated_context = _validated_context(context)
        HistoricalDataGuard.assert_network_denied(validated_context)
        if not isinstance(repository, EvidenceRepository):
            raise HistoricalReplayDeniedError(
                "historical replay requires an in-memory EvidenceRepository"
            )

        bundle = repository.get(bundle_id)
        if validated_context.bundle_id != bundle_id or bundle.bundle_id != bundle_id:
            raise HistoricalReplayMismatchError("historical bundle ID mismatch")
        if validated_context.bundle_hash != bundle.bundle_hash:
            raise HistoricalReplayMismatchError("historical bundle hash mismatch")
        if validated_context.knowledge_cutoff != bundle.knowledge_cutoff:
            raise HistoricalReplayMismatchError("historical knowledge cutoff mismatch")
        if validated_context.calendar_id != bundle.calendar.calendar_id:
            raise HistoricalReplayMismatchError("historical calendar mismatch")
        return bundle


__all__ = [
    "HistoricalDataGuard",
    "HistoricalDataGuardError",
    "HistoricalReplayDeniedError",
    "HistoricalReplayMismatchError",
]
