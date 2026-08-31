"""Captured event contracts and point-in-time historical selection."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BeforeValidator,
    StrictStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)


def _validate_required_text(value: object) -> object:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("invalid_text: expected a non-empty trimmed string")
    return value


RequiredText = Annotated[StrictStr, BeforeValidator(_validate_required_text)]


class EventRepositoryError(ValueError):
    """Base class for public historical event query failures."""


class EventMissingError(EventRepositoryError):
    """Raised when no event matches every explicit selector and event-time bound."""


class EventFutureError(EventRepositoryError):
    """Raised when matching events exist but none is available by the cutoff."""


class HistoricalReplayBlockedError(EventRepositoryError):
    """Raised when live-now-only event evidence is requested historically."""


class EventQueryError(EventRepositoryError):
    """Raised when an event query or repository state is invalid."""


class ReplayPolicy(str, Enum):
    """Whether captured evidence is eligible for historical replay."""

    ARCHIVED = "archived"
    LIVE_NOW_ONLY = "live_now_only"


class EventKind(str, Enum):
    """Stable event classifications owned by PIT-04."""

    NEWS = "news"
    PREDICTION_MARKET = "prediction_market"


class NewsEvent(ContractModel):
    """One immutable captured news or prediction-market event revision."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    event_id: StableId
    instrument_id: StableId | None
    kind: EventKind
    title: RequiredText
    body: RequiredText
    publisher: RequiredText
    url: RequiredText | None
    replay_policy: ReplayPolicy
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return SourceManifest.model_validate(
            value.model_dump(mode="python") if isinstance(value, SourceManifest) else value
        )

    @model_validator(mode="after")
    def validate_event_times(self) -> NewsEvent:
        if self.manifest.event_time is None:
            raise ValueError("event_time_required")
        if self.manifest.published_at is None:
            raise ValueError("event_publication_required")
        return self


def _event_series_key(event: NewsEvent) -> tuple[object, ...]:
    return (
        event.event_id,
        event.instrument_id,
        event.kind,
        event.manifest.source,
        event.manifest.event_time,
        event.replay_policy,
    )


def _event_sort_key(event: NewsEvent) -> tuple[object, ...]:
    return (
        event.manifest.event_time,
        event.event_id,
        event.manifest.revision,
        event.manifest.source,
    )


def _query_timestamp(value: object, *, field: str) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise EventQueryError(f"invalid_{field}: expected an aware ISO timestamp") from exc


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise EventQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_instrument_id(value: object) -> str | None:
    if value is None:
        return None
    return _query_stable_id(value, field="instrument_id")


def _query_event_kind(value: object) -> EventKind:
    if isinstance(value, EventKind):
        return value
    if isinstance(value, str):
        try:
            return EventKind(value)
        except ValueError as exc:
            raise EventQueryError("invalid_event_kind") from exc
    raise EventQueryError("invalid_event_kind")


class EventRepository(ContractModel):
    """A frozen, canonical collection of captured event revisions."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    events: tuple[NewsEvent, ...]

    @field_validator("events", mode="before")
    @classmethod
    def revalidate_and_sort_events(cls, value: object) -> tuple[NewsEvent, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_events: expected an event sequence")
        events = tuple(
            NewsEvent.model_validate(
                item.model_dump(mode="python") if isinstance(item, NewsEvent) else item
            )
            for item in value
        )
        return tuple(sorted(events, key=_event_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> EventRepository:
        business_revisions: set[tuple[str, int]] = set()
        by_event_id: dict[str, list[NewsEvent]] = {}
        for event in self.events:
            business_revision = (event.event_id, event.manifest.revision)
            if business_revision in business_revisions:
                raise ValueError("duplicate_event_id_revision")
            business_revisions.add(business_revision)
            by_event_id.setdefault(event.event_id, []).append(event)

        for series in by_event_id.values():
            first_key = _event_series_key(series[0])
            previous: NewsEvent | None = None
            for event in sorted(series, key=lambda item: item.manifest.revision):
                if _event_series_key(event) != first_key:
                    raise ValueError("event_revision_series_mismatch")
                if previous is not None and (
                    event.manifest.published_at < previous.manifest.published_at
                    or event.manifest.available_at < previous.manifest.available_at
                ):
                    raise ValueError("event_revision_chronology_regressed")
                previous = event
        return self

    def as_of(
        self,
        start_time: datetime | str,
        end_time: datetime | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        event_kind: EventKind | str,
        instrument_id: str | None,
    ) -> tuple[NewsEvent, ...]:
        """Return deterministic archived event revisions in ``[start_time, end_time)``."""

        repository = self._revalidate_for_query()
        return repository._select_as_of(
            start_time,
            end_time,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            event_kind=event_kind,
            instrument_id=instrument_id,
        )

    def _revalidate_for_query(self) -> EventRepository:
        try:
            return EventRepository.model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise EventQueryError("invalid_event_repository_state") from exc

    def _select_as_of(
        self,
        start_time: object,
        end_time: object,
        *,
        knowledge_cutoff: object,
        source: object,
        event_kind: object,
        instrument_id: object,
    ) -> tuple[NewsEvent, ...]:
        start = _query_timestamp(start_time, field="start_time")
        end = _query_timestamp(end_time, field="end_time")
        cutoff = _query_timestamp(knowledge_cutoff, field="knowledge_cutoff")
        query_source = _query_stable_id(source, field="source")
        query_kind = _query_event_kind(event_kind)
        query_instrument = _query_instrument_id(instrument_id)
        if start >= end:
            raise EventQueryError("invalid_event_window: start_time must precede end_time")

        matching = tuple(
            event
            for event in self.events
            if event.manifest.source == query_source
            and event.kind is query_kind
            and event.instrument_id == query_instrument
            and start <= event.manifest.event_time < end
        )
        if not matching:
            raise EventMissingError("no events match the exact query")
        if any(event.replay_policy is ReplayPolicy.LIVE_NOW_ONLY for event in matching):
            raise HistoricalReplayBlockedError(
                "live-now-only event cannot be replayed historically"
            )

        eligible = tuple(event for event in matching if event.manifest.available_at <= cutoff)
        if not eligible:
            raise EventFutureError("matching events exist but are unavailable at the cutoff")

        selected_by_id: dict[str, NewsEvent] = {}
        for event in eligible:
            selected = selected_by_id.get(event.event_id)
            if selected is None or event.manifest.revision > selected.manifest.revision:
                selected_by_id[event.event_id] = event
        return tuple(
            sorted(
                selected_by_id.values(),
                key=lambda event: (event.manifest.event_time, event.event_id),
            )
        )


__all__ = [
    "EventFutureError",
    "EventKind",
    "EventMissingError",
    "EventQueryError",
    "EventRepository",
    "EventRepositoryError",
    "HistoricalReplayBlockedError",
    "NewsEvent",
    "ReplayPolicy",
]
