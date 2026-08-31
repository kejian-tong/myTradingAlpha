"""Pure point-in-time selection for revisioned financial filing vintages."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, TypeVar, cast

from pydantic import TypeAdapter, ValidationError

from mytradingalpha.contracts.common import UtcDateTime

if TYPE_CHECKING:
    from .fundamentals import FinancialFiling

_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)
_FilingT = TypeVar("_FilingT", bound="FinancialFiling")


class VintageSelectionError(ValueError):
    """Base class for public vintage-selection failures."""


class VintageMissingError(VintageSelectionError):
    """Raised when no vintage candidates were supplied."""


class VintageFutureError(VintageSelectionError):
    """Raised when every candidate is unavailable at the knowledge cutoff."""


class VintageConflictError(VintageSelectionError):
    """Raised when candidates do not form one unambiguous revision series."""


def _selection_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise VintageSelectionError(
            "invalid_knowledge_cutoff: expected an aware ISO timestamp"
        ) from exc


def _candidate_attributes(candidate: object) -> tuple[object, int, datetime]:
    try:
        vintage_key = candidate.vintage_key  # type: ignore[attr-defined]
        manifest = candidate.manifest  # type: ignore[attr-defined]
        revision = manifest.revision
        available_at = _UTC_DATETIME_ADAPTER.validate_python(manifest.available_at)
    except (AttributeError, TypeError, ValidationError, ValueError) as exc:
        raise VintageConflictError("invalid_candidate: expected filing vintage attributes") from exc

    if type(revision) is not int or revision < 0:
        raise VintageConflictError("invalid_candidate_revision")
    return vintage_key, revision, available_at


def _normalize_candidate(candidate: _FilingT) -> _FilingT:
    """Revalidate Pydantic candidates without depending on their concrete module."""

    candidate_type = type(candidate)
    model_validate = getattr(candidate_type, "model_validate", None)
    model_dump = getattr(candidate, "model_dump", None)
    if model_validate is None and model_dump is None:
        return candidate
    if not callable(model_validate) or not callable(model_dump):
        raise VintageConflictError("invalid_candidate: incomplete model validation boundary")
    try:
        normalized = model_validate(model_dump(mode="python"))
    except (TypeError, ValidationError, ValueError) as exc:
        raise VintageConflictError("invalid_candidate: filing contract validation failed") from exc
    return cast(_FilingT, normalized)


class VintageSelector:
    """Select the highest revision available at an explicit knowledge cutoff."""

    def select(
        self,
        candidates: Sequence[_FilingT],
        *,
        knowledge_cutoff: object,
    ) -> _FilingT:
        """Return the highest eligible revision from one exact vintage series."""

        items = tuple(candidates)
        if not items:
            raise VintageMissingError("at least one vintage candidate is required")
        cutoff = _selection_cutoff(knowledge_cutoff)

        first_key: object | None = None
        seen_revisions: set[int] = set()
        eligible: list[tuple[int, _FilingT]] = []
        for index, supplied_candidate in enumerate(items):
            candidate = _normalize_candidate(supplied_candidate)
            vintage_key, revision, available_at = _candidate_attributes(candidate)
            if index == 0:
                first_key = vintage_key
            elif vintage_key != first_key:
                raise VintageConflictError("candidate_vintage_key_mismatch")
            if revision in seen_revisions:
                raise VintageConflictError("duplicate_candidate_revision")
            seen_revisions.add(revision)
            if available_at <= cutoff:
                eligible.append((revision, candidate))

        if not eligible:
            raise VintageFutureError("vintage candidates exist but none is available by the cutoff")
        return max(eligible, key=lambda item: item[0])[1]


__all__ = [
    "VintageConflictError",
    "VintageFutureError",
    "VintageMissingError",
    "VintageSelectionError",
    "VintageSelector",
]
