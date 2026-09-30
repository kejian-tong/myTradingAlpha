"""Versioned exchange-session contracts for point-in-time data."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
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

from mytradingalpha.contracts.common import CanonicalChecksum, StableId, UtcDateTime
from mytradingalpha.contracts.schemas import ContractModel
from mytradingalpha.contracts.versions import CURRENT_SCHEMA_VERSION

_ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIMEZONE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z][A-Za-z0-9_+-]*)+")
_REPLAY_HASH_DOMAIN = b"mytradingalpha:calendar-replay-evidence:v1\0"
MAX_CALENDAR_REPLAY_DAYS = 4096
_MAX_REPLAY_CANONICAL_BYTES = 1_048_576


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
    if (
        type(value) is not str
        or len(value.encode("utf-8", "strict")) > 128
        or _TIMEZONE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("invalid_timezone: expected an explicit IANA region name")
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


class CalendarReplayDay(ContractModel):
    """A captured exchange-local date and its exact half-open UTC interval."""

    local_date: ExactDate
    start_utc: UtcDateTime
    end_utc: UtcDateTime

    @model_validator(mode="after")
    def validate_interval(self) -> CalendarReplayDay:
        if not timedelta(hours=22) <= self.end_utc - self.start_utc <= timedelta(hours=26):
            raise ValueError("invalid_replay_day: UTC interval duration is invalid")
        if self.local_date == date.max:
            raise ValueError("invalid_replay_day: date exceeds supported bound")
        nominal_start = datetime.combine(self.local_date, time.min, tzinfo=timezone.utc)
        nominal_end = nominal_start + timedelta(days=1)
        if (
            abs(self.start_utc - nominal_start) > timedelta(hours=14)
            or abs(self.end_utc - nominal_end) > timedelta(hours=14)
        ):
            raise ValueError("invalid_replay_day: UTC bounds do not match local midnight")
        return self


def _replay_evidence_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(canonical) > _MAX_REPLAY_CANONICAL_BYTES:
        raise ValueError("invalid_replay_evidence: canonical bytes exceed bound")
    return "sha256:" + hashlib.sha256(_REPLAY_HASH_DOMAIN + canonical).hexdigest()


class CalendarReplayEvidence(ContractModel):
    """Versioned captured local-date classification, independent of replay TZDB."""

    schema_version: Literal["v1"]
    calendar_id: StableId
    timezone: IanaTimezone
    coverage_ranges: tuple[CalendarCoverageRange, ...]
    days: tuple[CalendarReplayDay, ...]
    content_hash: CanonicalChecksum

    @field_validator("coverage_ranges", mode="before")
    @classmethod
    def bound_coverage_ranges(cls, value: object) -> object:
        if type(value) not in (tuple, list) or len(value) > MAX_CALENDAR_REPLAY_DAYS:
            raise ValueError("invalid_replay_evidence: sequence exceeds bound")
        if any(type(item) not in (dict, CalendarCoverageRange) for item in value):
            raise ValueError("invalid_replay_evidence: coverage contains non-data")
        return value

    @field_validator("days", mode="before")
    @classmethod
    def bound_days(cls, value: object) -> object:
        if type(value) not in (tuple, list) or len(value) > MAX_CALENDAR_REPLAY_DAYS:
            raise ValueError("invalid_replay_evidence: sequence exceeds bound")
        if any(type(item) not in (dict, CalendarReplayDay) for item in value):
            raise ValueError("invalid_replay_evidence: day contains non-data")
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> CalendarReplayEvidence:
        if not self.coverage_ranges or not self.days:
            raise ValueError("invalid_replay_evidence: coverage and days are required")
        expected_dates: list[date] = []
        prior_range_end: date | None = None
        for coverage_range in self.coverage_ranges:
            if prior_range_end is not None and (coverage_range.start - prior_range_end).days <= 1:
                raise ValueError("invalid_replay_evidence: coverage ranges are not canonical")
            span = coverage_range.end.toordinal() - coverage_range.start.toordinal() + 1
            if len(expected_dates) + span > MAX_CALENDAR_REPLAY_DAYS:
                raise ValueError("invalid_replay_evidence: covered days exceed bound")
            expected_dates.extend(
                date.fromordinal(coverage_range.start.toordinal() + offset)
                for offset in range(span)
            )
            prior_range_end = coverage_range.end
        if len(self.days) != len(expected_dates):
            raise ValueError("invalid_replay_evidence: day count does not match coverage")
        previous_day: CalendarReplayDay | None = None
        for day, expected_date in zip(self.days, expected_dates, strict=True):
            if day.local_date != expected_date:
                raise ValueError("invalid_replay_evidence: local dates are not canonical")
            if previous_day is not None:
                consecutive = (day.local_date - previous_day.local_date).days == 1
                if consecutive and previous_day.end_utc != day.start_utc:
                    raise ValueError("invalid_replay_evidence: UTC days are discontinuous")
                if not consecutive and previous_day.end_utc >= day.start_utc:
                    raise ValueError("invalid_replay_evidence: coverage gap is not preserved")
            previous_day = day
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if self.content_hash != _replay_evidence_hash(payload):
            raise ValueError("invalid_replay_evidence: content hash mismatch")
        return self


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
    replay_evidence: CalendarReplayEvidence | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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

    @field_validator("replay_evidence", mode="before")
    @classmethod
    def revalidate_replay_evidence(cls, value: object) -> object:
        if value is None:
            return None
        if type(value) is CalendarReplayEvidence:
            value = value.model_dump(mode="python")
        if type(value) is not dict:
            raise ValueError("invalid_replay_evidence: expected plain evidence")
        return CalendarReplayEvidence.model_validate(value)

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

        evidence = self.replay_evidence
        if evidence is None:
            try:
                zone = ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("invalid_timezone: unknown IANA region name") from exc
            day_by_date: dict[date, CalendarReplayDay] = {}
        else:
            zone = None
            if (
                evidence.calendar_id != self.calendar_id
                or evidence.timezone != self.timezone
                or evidence.coverage_ranges != self.coverage_ranges
            ):
                raise ValueError("invalid_replay_evidence: calendar binding mismatch")
            if len(evidence.days) != classified_day_count:
                raise ValueError("invalid_replay_evidence: incomplete covered dates")
            day_by_date = {day.local_date: day for day in evidence.days}
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
            if zone is None:
                replay_day = day_by_date[session.session_date]
                if not (
                    replay_day.start_utc <= session.open_at < replay_day.end_utc
                    and replay_day.start_utc <= session.close_at < replay_day.end_utc
                ):
                    raise ValueError("invalid_schedule: session lies outside sealed local date")
            else:
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


def _capture_calendar_plain(
    value: object, *, seen: set[int], nodes: list[int], depth: int = 0
) -> object:
    nodes[0] += 1
    if nodes[0] > 20_000 or depth > 16:
        raise ValueError("invalid_replay_capture: calendar exceeds bounds")
    value_type = type(value)
    if value_type is str:
        if len(value) > 4096 or len(value.encode("utf-8", "strict")) > 4096:
            raise ValueError("invalid_replay_capture: calendar text exceeds bound")
        return value
    if value_type in (date, datetime, SessionType, type(None)):
        if value_type is datetime and value.tzinfo is not timezone.utc:
            raise ValueError("invalid_replay_capture: calendar timestamp is not UTC")
        return value
    if value_type is tuple:
        if len(value) > MAX_CALENDAR_REPLAY_DAYS:
            raise ValueError("invalid_replay_capture: calendar sequence exceeds bound")
        identity = id(value)
        if identity in seen:
            raise ValueError("invalid_replay_capture: calendar contains a cycle")
        seen.add(identity)
        try:
            return tuple(
                _capture_calendar_plain(item, seen=seen, nodes=nodes, depth=depth + 1)
                for item in value
            )
        finally:
            seen.remove(identity)
    if value_type in (TradingCalendar, CalendarCoverageRange, CalendarClosure, TradingSession):
        identity = id(value)
        if identity in seen:
            raise ValueError("invalid_replay_capture: calendar contains a cycle")
        seen.add(identity)
        try:
            storage = object.__getattribute__(value, "__dict__")
            fields = tuple(value_type.model_fields)
            if (
                type(storage) is not dict
                or dict.__len__(storage) != len(fields)
                or set(dict.keys(storage)) != set(fields)
                or any(type(key) is not str for key in dict.keys(storage))
            ):
                raise ValueError("invalid_replay_capture: calendar storage is not canonical")
            return {
                field: _capture_calendar_plain(
                    dict.__getitem__(storage, field),
                    seen=seen,
                    nodes=nodes,
                    depth=depth + 1,
                )
                for field in fields
            }
        finally:
            seen.remove(identity)
    raise ValueError("invalid_replay_capture: calendar contains non-data")


def capture_calendar_replay_evidence(calendar: TradingCalendar) -> CalendarReplayEvidence:
    """Capture a bounded timezone classification once, before offline replay."""

    if type(calendar) is not TradingCalendar or calendar.replay_evidence is not None:
        raise ValueError("invalid_replay_capture: expected an unwitnessed exact calendar")
    try:
        snapshot = _capture_calendar_plain(calendar, seen=set(), nodes=[0])
        calendar = TradingCalendar.model_validate(snapshot)
    except Exception:
        raise ValueError("invalid_replay_capture: calendar is invalid") from None
    try:
        zone = ZoneInfo(calendar.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid_replay_capture: timezone is unavailable") from exc
    days: list[CalendarReplayDay] = []
    for coverage_range in calendar.coverage_ranges:
        span = coverage_range.end.toordinal() - coverage_range.start.toordinal() + 1
        if len(days) + span > MAX_CALENDAR_REPLAY_DAYS:
            raise ValueError("invalid_replay_capture: covered days exceed bound")
        for offset in range(span):
            local_date = date.fromordinal(coverage_range.start.toordinal() + offset)
            if local_date == date.max:
                raise ValueError("invalid_replay_capture: date exceeds supported bound")
            start_local = datetime.combine(local_date, time.min, tzinfo=zone)
            end_local = datetime.combine(
                date.fromordinal(local_date.toordinal() + 1), time.min, tzinfo=zone
            )
            days.append(
                CalendarReplayDay(
                    local_date=local_date,
                    start_utc=start_local.astimezone(timezone.utc),
                    end_utc=end_local.astimezone(timezone.utc),
                )
            )
    payload: dict[str, object] = {
        "schema_version": "v1",
        "calendar_id": calendar.calendar_id,
        "timezone": calendar.timezone,
        "coverage_ranges": [item.model_dump(mode="json") for item in calendar.coverage_ranges],
        "days": [item.model_dump(mode="json") for item in days],
    }
    return CalendarReplayEvidence.model_validate(
        {**payload, "content_hash": _replay_evidence_hash(payload)}
    )


__all__ = [
    "CalendarReplayDay",
    "CalendarReplayEvidence",
    "CalendarClosure",
    "CalendarCoverageError",
    "CalendarCoverageRange",
    "CalendarError",
    "CalendarSessionNotFoundError",
    "SessionType",
    "TradingCalendar",
    "TradingSession",
    "MAX_CALENDAR_REPLAY_DAYS",
    "capture_calendar_replay_evidence",
]
