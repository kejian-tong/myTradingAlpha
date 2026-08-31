"""Append-only in-memory repository for sealed evidence bundles."""

from __future__ import annotations

from threading import RLock

from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import StableId

from .bundle import EvidenceBundle


class EvidenceRepositoryError(ValueError):
    """Base class for public sealed-bundle repository failures."""


class EvidenceBundleConflictError(EvidenceRepositoryError):
    """Raised when a bundle ID is reused for different semantics."""


class EvidenceBundleNotFoundError(EvidenceRepositoryError):
    """Raised when a sealed bundle ID is absent."""


class EvidenceBundleCorruptionError(EvidenceRepositoryError):
    """Raised when a bundle fails concrete validation or hash verification."""


def _bundle_copy(bundle: object) -> EvidenceBundle:
    try:
        payload = (
            bundle.model_dump(mode="python")
            if isinstance(bundle, EvidenceBundle)
            else bundle
        )
        return EvidenceBundle.model_validate(payload)
    except (TypeError, ValidationError, ValueError) as exc:
        raise EvidenceBundleCorruptionError(
            "evidence bundle failed validation or semantic hash verification"
        ) from exc


def _bundle_id(value: object) -> str:
    try:
        return TypeAdapter(StableId).validate_python(value)
    except ValidationError as exc:
        raise EvidenceRepositoryError("invalid_bundle_id") from exc


class EvidenceRepository:
    """Thread-safe append-only storage with defensive boundary copies."""

    def __init__(self) -> None:
        self._bundles: dict[str, EvidenceBundle] = {}
        self._lock = RLock()

    def seal(self, bundle: EvidenceBundle) -> EvidenceBundle:
        """Seal one bundle idempotently, rejecting ID/hash conflicts."""

        validated = _bundle_copy(bundle)
        with self._lock:
            existing = self._bundles.get(validated.bundle_id)
            if existing is not None:
                checked_existing = _bundle_copy(existing)
                if checked_existing.bundle_hash != validated.bundle_hash:
                    raise EvidenceBundleConflictError(
                        "bundle ID is already sealed with a different semantic hash"
                    )
                return _bundle_copy(checked_existing)
            self._bundles[validated.bundle_id] = validated
            return _bundle_copy(validated)

    def get(self, bundle_id: str) -> EvidenceBundle:
        """Return a validated defensive copy of one sealed bundle."""

        validated_id = _bundle_id(bundle_id)
        with self._lock:
            bundle = self._bundles.get(validated_id)
            if bundle is None:
                raise EvidenceBundleNotFoundError(
                    f"sealed evidence bundle not found: {validated_id}"
                )
            return _bundle_copy(bundle)


__all__ = [
    "EvidenceBundleConflictError",
    "EvidenceBundleCorruptionError",
    "EvidenceBundleNotFoundError",
    "EvidenceRepository",
    "EvidenceRepositoryError",
]
