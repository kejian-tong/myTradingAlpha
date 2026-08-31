"""Versioned exchange-session contracts for point-in-time data."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BeforeValidator,
    Field,
    PlainSerializer,
    StrictStr,
    field_validator,
    model_validator,
)

from mytradingalpha.contracts.common import StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

_ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class CalendarError(ValueError):
    """Base class for public calendar query failures."""


class CalendarCoverageError(CalendarError):
    """Raised when a query is outside the injected calendar coverage."""


class CalendarSessionNotFoundError(CalendarError):
    """Raised when a covered date is not an injected trading session."""


class SessionType(str, Enum):
    """Stable session-type wire values."""

    REGULAR = "regular"
    EARLY_CLOSE = "early_close"


def _validate_exact_date(value: object) -> date:
    if type(value) is date:
        return value
    if not isinstance(value, str) or _ISO_DATE_PATTERN.fullmatch(value) is None:
        raise ValueError("invalid_date: expected a date or exact ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid_date: expected a valid ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError("invalid_date: expected a zero-padded ISO date")
    return parsed


def _serialize_exact_date(value: date) -> str:
    return value.isoformat()


ExactDate = Annotated[
    date,
    BeforeValidator(_validate_exact_date),
    PlainSerializer(_serialize_exact_date, return_type=str, when_used="json"),
]


def _validate_timezone(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "/" not in value:
        raise ValueError("invalid_timezone: expected an explicit IANA region name")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid_timezone: unknown IANA region name") from exc
    return value


IanaTimezone = Annotated[
    StrictStr,
    BeforeValidator(_validate_timezone),
]


def _query_date(value: object) -> date:
    try:
        return _validate_exact_date(value)
    except (TypeError, ValueError) as exc:
        raise CalendarError(str(exc)) from exc


class TradingSession(ContractModel):
    """One immutable exchange session expressed as UTC instants."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    calendar_id: StableId
    session_date: ExactDate
    open_at: UtcDateTime
    close_at: UtcDateTime
    session_type: SessionType

    @model_validator(mode="after")
    def validate_session_bounds(self) -> TradingSession:
        if self.open_at >= self.close_at:
            raise ValueError("invalid_session: open_at must be before close_at")
        return self


class TradingCalendar(ContractModel):
    """An immutable, bounded, injected exchange schedule."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    calendar_id: StableId
    timezone: IanaTimezone
    coverage_start: ExactDate
    coverage_end: ExactDate
    schedule: tuple[TradingSession, ...] = Field(default_factory=tuple)

    @field_validator("schedule", mode="before")
    @classmethod
    def revalidate_schedule(cls, value: object) -> tuple[TradingSession, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_schedule: expected a session sequence")
        return tuple(
            TradingSession.model_validate(
                item.model_dump() if isinstance(item, TradingSession) else item
            )
            for item in value
        )

    @model_validator(mode="after")
    def validate_calendar(self) -> TradingCalendar:
        if self.coverage_start > self.coverage_end:
            raise ValueError("invalid_coverage: coverage_start must not exceed coverage_end")

        zone = ZoneInfo(self.timezone)
        previous_date: date | None = None
        previous_close: datetime | None = None
        for session in self.schedule:
            if session.calendar_id != self.calendar_id:
                raise ValueError("invalid_schedule: session calendar_id does not match")
            if not self.coverage_start <= session.session_date <= self.coverage_end:
                raise ValueError("invalid_schedule: session is outside calendar coverage")
            if previous_date is not None and session.session_date <= previous_date:
                raise ValueError("invalid_schedule: sessions must be unique and sorted")
            if previous_close is not None and session.open_at < previous_close:
                raise ValueError("invalid_schedule: sessions must not overlap")
            if session.open_at.astimezone(zone).date() != session.session_date:
                raise ValueError("invalid_schedule: session open maps to another local date")
            if session.close_at.astimezone(zone).date() != session.session_date:
                raise ValueError("invalid_schedule: session close maps to another local date")
            previous_date = session.session_date
            previous_close = session.close_at
        return self

    def _require_coverage(self, value: date) -> None:
        if not self.coverage_start <= value <= self.coverage_end:
            raise CalendarCoverageError(
                f"calendar coverage does not include {value.isoformat()}"
            )

    def session(self, session_date: date | str) -> TradingSession:
        """Return the exact injected session; never infer a missing date."""

        requested = _query_date(session_date)
        self._require_coverage(requested)
        for session in self.schedule:
            if session.session_date == requested:
                return session
        raise CalendarSessionNotFoundError(
            f"calendar has no session on {requested.isoformat()}"
        )

    def sessions(self, start: date | str, end: date | str) -> tuple[TradingSession, ...]:
        """Return injected sessions in the inclusive covered date range."""

        first = _query_date(start)
        last = _query_date(end)
        self._require_coverage(first)
        self._require_coverage(last)
        if first > last:
            raise CalendarError("invalid_range: start must not exceed end")
        return tuple(
            session for session in self.schedule if first <= session.session_date <= last
        )

    def next_session(self, after: date | str) -> TradingSession:
        """Return the first injected session strictly later than a covered date."""

        requested = _query_date(after)
        self._require_coverage(requested)
        for session in self.schedule:
            if session.session_date > requested:
                return session
        raise CalendarCoverageError(
            f"calendar coverage contains no session after {requested.isoformat()}"
        )


__all__ = [
    "CalendarCoverageError",
    "CalendarError",
    "CalendarSessionNotFoundError",
    "SessionType",
    "TradingCalendar",
    "TradingSession",
]
