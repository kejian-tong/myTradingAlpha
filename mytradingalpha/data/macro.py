"""Captured macroeconomic contracts and point-in-time vintage selection."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import TypeAdapter, ValidationError, field_validator, model_validator

from mytradingalpha.contracts.common import DecimalString, StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .calendar import ExactDate
from .events import HistoricalReplayBlockedError, ReplayPolicy
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_EXACT_DATE_ADAPTER = TypeAdapter(ExactDate)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)


class MacroRepositoryError(ValueError):
    """Base class for public historical macro query failures."""


class MacroMissingError(MacroRepositoryError):
    """Raised when no macro series matches every explicit selector."""


class MacroFutureError(MacroRepositoryError):
    """Raised when matching macro observations are unavailable at the cutoff."""


class MacroHistoricalReplayBlockedError(
    MacroRepositoryError,
    HistoricalReplayBlockedError,
):
    """Raised when a current-only macro observation is requested historically."""


class MacroQueryError(MacroRepositoryError):
    """Raised when a macro query or repository state is invalid."""


class MacroFrequency(str, Enum):
    """Stable macroeconomic observation frequencies."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class MacroObservation(ContractModel):
    """One immutable captured macroeconomic observation revision."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    observation_id: StableId
    series_id: StableId
    observation_date: ExactDate
    value: DecimalString
    units: StableId
    frequency: MacroFrequency
    replay_policy: ReplayPolicy
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return SourceManifest.model_validate(
            value.model_dump(mode="python") if isinstance(value, SourceManifest) else value
        )

    @model_validator(mode="after")
    def validate_observation_times(self) -> MacroObservation:
        if self.manifest.event_time is None:
            raise ValueError("macro_event_time_required")
        if self.manifest.event_time.date() != self.observation_date:
            raise ValueError("macro_event_date_must_equal_observation_date")
        if self.manifest.published_at is None:
            raise ValueError("macro_publication_required")
        if self.manifest.event_time > self.manifest.published_at:
            raise ValueError("macro_publication_cannot_precede_event_time")
        return self


def _macro_vintage_key(observation: MacroObservation) -> tuple[object, ...]:
    return (
        observation.series_id,
        observation.observation_date,
        observation.manifest.source,
        observation.units,
        observation.frequency,
    )


def _macro_series_key(observation: MacroObservation) -> tuple[object, ...]:
    return (
        observation.observation_id,
        *_macro_vintage_key(observation),
        observation.replay_policy,
        observation.manifest.event_time,
    )


def _macro_sort_key(observation: MacroObservation) -> tuple[object, ...]:
    return (
        observation.series_id,
        observation.observation_date,
        observation.manifest.source,
        observation.units,
        observation.frequency.value,
        observation.observation_id,
        observation.manifest.revision,
    )


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise MacroQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_date(value: object) -> date:
    try:
        return _EXACT_DATE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise MacroQueryError("invalid_observation_date: expected an exact ISO date") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise MacroQueryError("invalid_knowledge_cutoff: expected an aware ISO timestamp") from exc


def _query_frequency(value: object) -> MacroFrequency:
    if isinstance(value, MacroFrequency):
        return value
    if isinstance(value, str):
        try:
            return MacroFrequency(value)
        except ValueError as exc:
            raise MacroQueryError("invalid_frequency") from exc
    raise MacroQueryError("invalid_frequency")


class MacroRepository(ContractModel):
    """A frozen, canonical collection of captured macro observation revisions."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    observations: tuple[MacroObservation, ...]

    @field_validator("observations", mode="before")
    @classmethod
    def revalidate_and_sort_observations(cls, value: object) -> tuple[MacroObservation, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_observations: expected a macro observation sequence")
        observations = tuple(
            MacroObservation.model_validate(
                item.model_dump(mode="python") if isinstance(item, MacroObservation) else item
            )
            for item in value
        )
        return tuple(sorted(observations, key=_macro_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> MacroRepository:
        business_revisions: set[tuple[str, int]] = set()
        by_observation_id: dict[str, list[MacroObservation]] = {}
        observation_id_by_vintage: dict[tuple[object, ...], str] = {}
        for observation in self.observations:
            business_revision = (
                observation.observation_id,
                observation.manifest.revision,
            )
            if business_revision in business_revisions:
                raise ValueError("duplicate_macro_observation_id_revision")
            business_revisions.add(business_revision)
            by_observation_id.setdefault(observation.observation_id, []).append(observation)

            vintage_key = _macro_vintage_key(observation)
            existing_id = observation_id_by_vintage.setdefault(
                vintage_key,
                observation.observation_id,
            )
            if existing_id != observation.observation_id:
                raise ValueError("macro_vintage_has_multiple_observation_ids")

        for series in by_observation_id.values():
            first_key = _macro_series_key(series[0])
            previous: MacroObservation | None = None
            for observation in sorted(series, key=lambda item: item.manifest.revision):
                if _macro_series_key(observation) != first_key:
                    raise ValueError("macro_revision_series_mismatch")
                if previous is not None and (
                    observation.manifest.published_at < previous.manifest.published_at
                    or observation.manifest.available_at < previous.manifest.available_at
                ):
                    raise ValueError("macro_revision_chronology_regressed")
                previous = observation
        return self

    def as_of(
        self,
        series_id: str,
        observation_date: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        units: str,
        frequency: MacroFrequency | str,
    ) -> MacroObservation:
        """Return the highest archived revision in one exact macro vintage."""

        repository = self._revalidate_for_query()
        return repository._select_as_of(
            series_id,
            observation_date,
            knowledge_cutoff=knowledge_cutoff,
            source=source,
            units=units,
            frequency=frequency,
        )

    def _revalidate_for_query(self) -> MacroRepository:
        try:
            return MacroRepository.model_validate(self.model_dump(mode="python"))
        except (TypeError, ValidationError, ValueError) as exc:
            raise MacroQueryError("invalid_macro_repository_state") from exc

    def _select_as_of(
        self,
        series_id: object,
        observation_date: object,
        *,
        knowledge_cutoff: object,
        source: object,
        units: object,
        frequency: object,
    ) -> MacroObservation:
        query_series = _query_stable_id(series_id, field="series_id")
        query_date = _query_date(observation_date)
        cutoff = _query_cutoff(knowledge_cutoff)
        query_source = _query_stable_id(source, field="source")
        query_units = _query_stable_id(units, field="units")
        query_frequency = _query_frequency(frequency)

        matching = tuple(
            observation
            for observation in self.observations
            if observation.series_id == query_series
            and observation.observation_date == query_date
            and observation.manifest.source == query_source
            and observation.units == query_units
            and observation.frequency is query_frequency
        )
        if not matching:
            raise MacroMissingError("no macro observations match the exact query")
        if any(observation.replay_policy is ReplayPolicy.LIVE_NOW_ONLY for observation in matching):
            raise MacroHistoricalReplayBlockedError(
                "live-now-only macro evidence cannot be replayed historically"
            )

        eligible = tuple(
            observation for observation in matching if observation.manifest.available_at <= cutoff
        )
        if not eligible:
            raise MacroFutureError("matching macro observations are unavailable at the cutoff")
        return max(eligible, key=lambda observation: observation.manifest.revision)


__all__ = [
    "MacroFrequency",
    "MacroFutureError",
    "MacroHistoricalReplayBlockedError",
    "MacroMissingError",
    "MacroObservation",
    "MacroQueryError",
    "MacroRepository",
    "MacroRepositoryError",
]
