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


class CalendarCoverageRange(ContractModel):
    """One continuously classified inclusive calendar date range."""

    start: ExactDate
    end: ExactDate

    @model_validator(mode="after")
    def validate_range(self) -> CalendarCoverageRange:
        if self.start > self.end:
            raise ValueError("invalid_coverage_range: start must not exceed end")
        return self


class CalendarClosure(ContractModel):
    """An explicitly classified non-session date within a coverage range."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    calendar_id: StableId
    date: ExactDate
    reason: StableId


class TradingCalendar(ContractModel):
    """An immutable, bounded, injected exchange schedule."""

    schema_version: Literal[CURRENT_SCHEMA_VERSION]
    calendar_id: StableId
    timezone: IanaTimezone
    coverage_start: ExactDate
    coverage_end: ExactDate
    coverage_ranges: tuple[CalendarCoverageRange, ...]
    closures: tuple[CalendarClosure, ...]
    schedule: tuple[TradingSession, ...] = Field(default_factory=tuple)

    @field_validator("coverage_ranges", mode="before")
    @classmethod
    def revalidate_coverage_ranges(
        cls, value: object
    ) -> tuple[CalendarCoverageRange, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_coverage_ranges: expected a range sequence")
        return tuple(
            CalendarCoverageRange.model_validate(
                item.model_dump() if isinstance(item, CalendarCoverageRange) else item
            )
            for item in value
        )

    @field_validator("closures", mode="before")
    @classmethod
    def revalidate_closures(cls, value: object) -> tuple[CalendarClosure, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("invalid_closures: expected a closure sequence")
        return tuple(
            CalendarClosure.model_validate(
                item.model_dump() if isinstance(item, CalendarClosure) else item
            )
            for item in value
        )

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
        if not self.coverage_ranges:
            raise ValueError("invalid_coverage: at least one coverage range is required")
        if self.coverage_ranges[0].start != self.coverage_start:
            raise ValueError("invalid_coverage: first range must start at coverage_start")
        if self.coverage_ranges[-1].end != self.coverage_end:
            raise ValueError("invalid_coverage: last range must end at coverage_end")

        previous_range_end: date | None = None
        classified_day_count = 0
        for coverage_range in self.coverage_ranges:
            if (
                previous_range_end is not None
                and (coverage_range.start - previous_range_end).days <= 1
            ):
                raise ValueError(
                    "invalid_coverage: ranges must be sorted, nonoverlapping, and nonadjacent"
                )
            classified_day_count += (coverage_range.end - coverage_range.start).days + 1
            previous_range_end = coverage_range.end

        zone = ZoneInfo(self.timezone)
        previous_date: date | None = None
        previous_close: datetime | None = None
        for session in self.schedule:
            if session.calendar_id != self.calendar_id:
                raise ValueError("invalid_schedule: session calendar_id does not match")
            if self._find_coverage_range(session.session_date) is None:
                raise ValueError("invalid_schedule: session is outside verified coverage")
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

        previous_closure_date: date | None = None
        closure_dates: set[date] = set()
        for closure in self.closures:
            if closure.calendar_id != self.calendar_id:
                raise ValueError("invalid_closures: closure calendar_id does not match")
            if self._find_coverage_range(closure.date) is None:
                raise ValueError("invalid_closures: closure is outside verified coverage")
            if previous_closure_date is not None and closure.date <= previous_closure_date:
                raise ValueError("invalid_closures: closures must be unique and sorted")
            closure_dates.add(closure.date)
            previous_closure_date = closure.date

        session_dates = {session.session_date for session in self.schedule}
        if session_dates.intersection(closure_dates):
            raise ValueError("invalid_coverage: a date cannot be a session and closure")
        if len(session_dates) + len(closure_dates) != classified_day_count:
            raise ValueError("invalid_coverage: every covered date needs one classification")
        return self

    def _find_coverage_range(self, value: date) -> CalendarCoverageRange | None:
        for coverage_range in self.coverage_ranges:
            if coverage_range.start <= value <= coverage_range.end:
                return coverage_range
        return None

    def _require_coverage(self, value: date) -> CalendarCoverageRange:
        coverage_range = self._find_coverage_range(value)
        if coverage_range is None:
            raise CalendarCoverageError(
                f"verified calendar coverage does not include {value.isoformat()}"
            )
        return coverage_range

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
        if first > last:
            raise CalendarError("invalid_range: start must not exceed end")
        first_range = self._require_coverage(first)
        last_range = self._require_coverage(last)
        if first_range != last_range:
            raise CalendarCoverageError("requested dates cross an unverified coverage gap")
        return tuple(
            session for session in self.schedule if first <= session.session_date <= last
        )

    def next_session(self, after: date | str) -> TradingSession:
        """Return the first injected session strictly later than a covered date."""

        requested = _query_date(after)
        coverage_range = self._require_coverage(requested)
        for session in self.schedule:
            if requested < session.session_date <= coverage_range.end:
                return session
        raise CalendarCoverageError(
            f"verified coverage contains no session after {requested.isoformat()}"
        )

    def session_distance(self, earlier: date | str, later: date | str) -> int:
        """Count trading-session transitions inside one verified coverage range."""

        first_date = _query_date(earlier)
        last_date = _query_date(later)
        if first_date > last_date:
            raise CalendarError("invalid_range: earlier must not exceed later")
        first_range = self._require_coverage(first_date)
        last_range = self._require_coverage(last_date)
        if first_range != last_range:
            raise CalendarCoverageError("session distance crosses an unverified coverage gap")
        self.session(first_date)
        self.session(last_date)
        sessions = tuple(
            session
            for session in self.schedule
            if first_date <= session.session_date <= last_date
        )
        return len(sessions) - 1


__all__ = [
    "CalendarClosure",
    "CalendarCoverageError",
    "CalendarCoverageRange",
    "CalendarError",
    "CalendarSessionNotFoundError",
    "SessionType",
    "TradingCalendar",
    "TradingSession",
]
