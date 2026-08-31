"""Immutable daily-bar contracts and point-in-time selection."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    Field,
    StrictInt,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import DecimalString, StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

from .calendar import CalendarError, ExactDate, TradingCalendar
from .provenance import SourceManifest

_STABLE_ID_ADAPTER = TypeAdapter(StableId)
_UTC_DATETIME_ADAPTER = TypeAdapter(UtcDateTime)

PositiveDecimal = Annotated[DecimalString, Field(gt=0)]


class BarRepositoryError(ValueError):
    """Base class for public bar query failures."""


class BarMissingError(BarRepositoryError):
    """Raised when no exact or prior bar matches every selector."""


class BarStaleError(BarRepositoryError):
    """Raised when only earlier matching sessions are available."""

    def __init__(self, message: str, *, prior_matching_session_count: int) -> None:
        super().__init__(message)
        self.prior_matching_session_count = prior_matching_session_count


class BarFutureError(BarRepositoryError):
    """Raised when the exact matching session has only future revisions."""


class BarQueryError(BarRepositoryError):
    """Raised when a bar query is malformed or targets no valid session."""


class AdjustmentBasis(str, Enum):
    """Stable adjustment-policy wire values."""

    UNADJUSTED = "unadjusted"
    PROVIDER_ADJUSTED = "provider_adjusted"


class BarFinality(str, Enum):
    """Whether a daily bar is complete for its exchange session."""

    PRELIMINARY = "preliminary"
    FINAL = "final"


class DailyBar(ContractModel):
    """One immutable daily bar bound to capture provenance."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    bar_id: StableId
    instrument_id: StableId
    calendar_id: StableId
    session_date: ExactDate
    interval: Literal["1d"]
    open: PositiveDecimal
    high: PositiveDecimal
    low: PositiveDecimal
    close: PositiveDecimal
    volume: StrictInt = Field(ge=0)
    adjustment_basis: AdjustmentBasis
    adjustment_version: StableId | None
    finality: BarFinality
    manifest: SourceManifest

    @field_validator("manifest", mode="before")
    @classmethod
    def revalidate_manifest(cls, value: object) -> SourceManifest:
        return SourceManifest.model_validate(
            value.model_dump() if isinstance(value, SourceManifest) else value
        )

    @model_validator(mode="after")
    def validate_bar(self) -> DailyBar:
        if self.high < max(self.open, self.close):
            raise ValueError("invalid_ohlc: high must include open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("invalid_ohlc: low must include open and close")
        if self.low > self.high:
            raise ValueError("invalid_ohlc: low must not exceed high")
        if self.adjustment_basis is AdjustmentBasis.UNADJUSTED:
            if self.adjustment_version is not None:
                raise ValueError("invalid_adjustment: unadjusted bars cannot have a version")
        elif self.adjustment_version is None:
            raise ValueError("invalid_adjustment: provider-adjusted bars require a version")
        return self


def _bar_sort_key(bar: DailyBar) -> tuple[object, ...]:
    return (
        bar.instrument_id,
        bar.session_date,
        bar.manifest.source,
        bar.adjustment_basis.value,
        bar.adjustment_version or "",
        bar.manifest.revision,
        bar.bar_id,
    )


def _business_key(bar: DailyBar) -> tuple[object, ...]:
    return (
        bar.instrument_id,
        bar.session_date,
        bar.manifest.source,
        bar.adjustment_basis,
        bar.adjustment_version,
        bar.manifest.revision,
    )


def _query_stable_id(value: object, *, field: str) -> str:
    try:
        return _STABLE_ID_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise BarQueryError(f"invalid_{field}: expected a stable identifier") from exc


def _query_cutoff(value: object) -> datetime:
    try:
        return _UTC_DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise BarQueryError("invalid_knowledge_cutoff: expected an aware ISO timestamp") from exc


def _query_adjustment_basis(value: object) -> AdjustmentBasis:
    if isinstance(value, AdjustmentBasis):
        return value
    if isinstance(value, str):
        try:
            return AdjustmentBasis(value)
        except ValueError as exc:
            raise BarQueryError("invalid_adjustment_basis") from exc
    raise BarQueryError("invalid_adjustment_basis")


def _query_adjustment_version(
    _basis: AdjustmentBasis,
    value: object,
) -> str | None:
    if value is None:
        return None
    return _query_stable_id(value, field="adjustment_version")


class BarRepository(ContractModel):
    """A frozen in-memory collection supporting deterministic PIT selection."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    calendar: TradingCalendar
    bars: tuple[DailyBar, ...] = Field(default_factory=tuple)

    @field_validator("calendar", mode="before")
    @classmethod
    def revalidate_calendar(cls, value: object) -> TradingCalendar:
        return TradingCalendar.model_validate(
            value.model_dump() if isinstance(value, TradingCalendar) else value
        )

    @field_validator("bars", mode="before")
    @classmethod
    def revalidate_and_sort_bars(cls, value: object) -> tuple[DailyBar, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_bars: expected a bar sequence")
        bars = tuple(
            DailyBar.model_validate(item.model_dump() if isinstance(item, DailyBar) else item)
            for item in value
        )
        return tuple(sorted(bars, key=_bar_sort_key))

    @model_validator(mode="after")
    def validate_repository(self) -> BarRepository:
        bar_ids: set[str] = set()
        business_keys: set[tuple[object, ...]] = set()
        for bar in self.bars:
            if bar.bar_id in bar_ids:
                raise ValueError("duplicate_bar_id")
            bar_ids.add(bar.bar_id)

            business_key = _business_key(bar)
            if business_key in business_keys:
                raise ValueError("duplicate_bar_business_key")
            business_keys.add(business_key)

            if bar.calendar_id != self.calendar.calendar_id:
                raise ValueError("calendar_mismatch")
            if bar.finality is not BarFinality.FINAL:
                raise ValueError("bar_must_be_final")
            try:
                session = self.calendar.session(bar.session_date)
            except CalendarError as exc:
                raise ValueError("bar_session_not_in_calendar") from exc
            if bar.manifest.event_time != session.close_at:
                raise ValueError("bar_event_time_must_equal_session_close")
            if bar.manifest.available_at < session.close_at:
                raise ValueError("bar_available_before_session_close")
        return self

    def as_of(
        self,
        instrument_id: str,
        session_date: date | str,
        *,
        knowledge_cutoff: datetime | str,
        source: str,
        adjustment_basis: AdjustmentBasis | str,
        adjustment_version: str | None,
    ) -> DailyBar:
        """Select the highest exact-session revision available by the cutoff."""

        instrument = _query_stable_id(instrument_id, field="instrument_id")
        source_id = _query_stable_id(source, field="source")
        basis = _query_adjustment_basis(adjustment_basis)
        version = _query_adjustment_version(basis, adjustment_version)
        cutoff = _query_cutoff(knowledge_cutoff)
        try:
            requested_session = self.calendar.session(session_date)
        except CalendarError as exc:
            raise BarQueryError(str(exc)) from exc

        matching = tuple(
            bar
            for bar in self.bars
            if bar.instrument_id == instrument
            and bar.manifest.source == source_id
            and bar.adjustment_basis is basis
            and bar.adjustment_version == version
        )
        exact = tuple(
            bar for bar in matching if bar.session_date == requested_session.session_date
        )
        eligible = tuple(bar for bar in exact if bar.manifest.available_at <= cutoff)
        if eligible:
            return max(eligible, key=lambda bar: bar.manifest.revision)
        if exact:
            raise BarFutureError(
                "matching bar revisions exist but none is available by the cutoff"
            )

        prior_session_dates = {
            bar.session_date
            for bar in matching
            if bar.session_date < requested_session.session_date
            and bar.manifest.available_at <= cutoff
        }
        if prior_session_dates:
            latest_prior = max(prior_session_dates)
            try:
                session_distance = self.calendar.session_distance(
                    latest_prior,
                    requested_session.session_date,
                )
            except CalendarError as exc:
                raise BarMissingError(
                    "prior matching data is separated by unverified calendar coverage"
                ) from exc
            raise BarStaleError(
                "only prior matching sessions are available",
                prior_matching_session_count=session_distance,
            )
        raise BarMissingError("no bar matches every explicit selector")


__all__ = [
    "AdjustmentBasis",
    "BarFinality",
    "BarFutureError",
    "BarMissingError",
    "BarQueryError",
    "BarRepository",
    "BarRepositoryError",
    "BarStaleError",
    "DailyBar",
]
