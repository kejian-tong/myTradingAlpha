"""PIT-02 contract tests for exchange sessions and point-in-time daily bars."""

from __future__ import annotations

import base64
import hashlib
import importlib
import inspect
import json
import socket
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter, ValidationError

import mytradingalpha.data.bars as bars_module
import mytradingalpha.data.calendar as calendar_module
from mytradingalpha.contracts.redaction import validate_artifact_text
from mytradingalpha.data.bars import (
    AdjustmentBasis,
    BarFutureError,
    BarMissingError,
    BarQueryError,
    BarRepository,
    BarRepositoryError,
    BarStaleError,
    DailyBar,
)
from mytradingalpha.data.calendar import (
    CalendarCoverageError,
    CalendarError,
    CalendarSessionNotFoundError,
    SessionType,
    TradingCalendar,
    TradingSession,
)
from mytradingalpha.data.capture import CaptureClient
from mytradingalpha.data.provenance import SourceManifest

FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "pit" / "xnys_bars_calendar_v1.json"
)


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _calendar(**overrides: object) -> TradingCalendar:
    fixture = _fixture()
    fields: dict[str, object] = {
        "schema_version": fixture["schema_version"],
        "calendar_id": fixture["calendar_id"],
        "timezone": fixture["timezone"],
        "coverage_start": fixture["coverage_start"],
        "coverage_end": fixture["coverage_end"],
        "schedule": tuple(TradingSession.model_validate(row) for row in fixture["sessions"]),
    }
    if "coverage_ranges" in TradingCalendar.model_fields:
        fields["coverage_ranges"] = tuple(
            calendar_module.CalendarCoverageRange.model_validate(row)
            for row in fixture["coverage_ranges"]
        )
        fields["closures"] = tuple(
            calendar_module.CalendarClosure.model_validate(row)
            for row in fixture["closures"]
        )
    fields.update(overrides)
    return TradingCalendar(**fields)


def _manifest(
    session: TradingSession,
    *,
    source: str = "synthetic-bars",
    revision: int = 0,
    event_time: object | None = None,
    available_at: object | None = None,
    fetched_at: object | None = None,
    ingested_at: object | None = None,
) -> SourceManifest:
    event = session.close_at if event_time is None else event_time
    available = session.close_at + timedelta(minutes=revision + 1)
    if available_at is not None:
        available = available_at  # type: ignore[assignment]
    fetched = available + timedelta(minutes=1) if fetched_at is None else fetched_at
    ingested = fetched + timedelta(minutes=1) if ingested_at is None else ingested_at
    payload = f"{source}:{session.session_date}:r{revision}".encode()
    return CaptureClient().capture(
        payload,
        schema_version="v1",
        manifest_id=f"{source}-{session.session_date}-r{revision}",
        source=source,
        source_locator=f"fixture://bars/{source}/{session.session_date}/r{revision}",
        fetched_at=fetched,
        event_time=event,
        published_at=None,
        available_at=available,
        ingested_at=ingested,
        terms="synthetic-fixture-v1",
        revision=revision,
    ).manifest


def _bar(
    calendar: TradingCalendar,
    session_date: str = "2024-11-27",
    *,
    instrument_id: str = "AAPL",
    source: str = "synthetic-bars",
    revision: int = 0,
    adjustment_basis: AdjustmentBasis | str = AdjustmentBasis.UNADJUSTED,
    adjustment_version: str | None = None,
    manifest: SourceManifest | None = None,
    **overrides: object,
) -> DailyBar:
    session = calendar.session(session_date)
    fields: dict[str, object] = {
        "schema_version": "v1",
        "bar_id": (
            f"bar-{instrument_id}-{session_date}-{source}-"
            f"{adjustment_basis}-{adjustment_version or 'none'}-r{revision}"
        ),
        "instrument_id": instrument_id,
        "calendar_id": calendar.calendar_id,
        "session_date": session_date,
        "interval": "1d",
        "open": "100.00",
        "high": "105.00",
        "low": "98.00",
        "close": "103.00",
        "volume": 1_000_000,
        "adjustment_basis": adjustment_basis,
        "adjustment_version": adjustment_version,
        "manifest": manifest
        or _manifest(session, source=source, revision=revision),
    }
    if "finality" in DailyBar.model_fields:
        fields["finality"] = bars_module.BarFinality.FINAL
    fields.update(overrides)
    return DailyBar(**fields)


def _repository(
    calendar: TradingCalendar,
    bars: tuple[DailyBar, ...],
) -> BarRepository:
    return BarRepository(schema_version="v1", calendar=calendar, bars=bars)


def _calendar_with_replay_evidence(calendar: TradingCalendar) -> TradingCalendar:
    capture = getattr(calendar_module, "capture_calendar_replay_evidence", None)
    assert callable(capture), "SIG-03 calendar replay capture API is missing"
    evidence = capture(calendar)
    return TradingCalendar.model_validate(
        {**calendar.model_dump(mode="python"), "replay_evidence": evidence}
    )


def _replay_evidence_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "content_hash"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(
        b"mytradingalpha:calendar-replay-evidence:v1\0" + canonical
    ).hexdigest()


def _unsupported_witnessed_timezone_names() -> tuple[str, ...]:
    secret = "sk-proj-CALENDAR-CANARY"
    standard_encoded = base64.b64encode((secret + chr(0x1003E)).encode()).decode()
    assert "+" in standard_encoded
    nested = secret
    for _ in range(3):
        nested = base64.urlsafe_b64encode(nested.encode()).decode().rstrip("=")
    return (
        "America/" + standard_encoded,
        "America/" + nested,
        "America/" + base64.b64encode(b"sk-").decode().rstrip("="),
        "America/" + base64.b32encode(b"sk-").decode().rstrip("="),
        "America/Not_A_Real_Zone_2026",
    )


def test_witnessed_timezone_catalog_is_frozen_to_reviewed_iana_source() -> None:
    try:
        catalog = importlib.import_module("mytradingalpha.data.timezone_catalog")
    except ModuleNotFoundError:
        catalog = None
    assert catalog is not None, "SIG-03 witnessed timezone catalog is missing"
    version = getattr(catalog, "CATALOG_VERSION", None)
    names = getattr(catalog, "SUPPORTED_TIMEZONE_NAMES", None)
    assert version == "2026e"
    assert type(names) is tuple
    assert len(names) == 553
    assert all(type(name) is str for name in names)
    assert names == tuple(sorted(set(names)))
    assert hashlib.sha256(("\n".join(names) + "\n").encode("utf-8")).hexdigest() == (
        "bab362935dbe8fceb73682327aa5a8773917e07406d4cbd0b986808a9fff39d6"
    )
    for alias in ("US/Eastern", "Canada/Central", "Etc/UTC", "Etc/GMT+4"):
        assert alias in names
    for candidate in _unsupported_witnessed_timezone_names():
        assert candidate not in names


@pytest.mark.parametrize("timezone_name", _unsupported_witnessed_timezone_names())
@pytest.mark.parametrize("entrypoint", ("python", "json", "type_adapter"))
def test_rehashed_witness_rejects_unknown_or_encoded_timezone_without_echo(
    timezone_name: str,
    entrypoint: str,
) -> None:
    decoded = "sk-proj-CALENDAR-CANARY"
    payload = _calendar_with_replay_evidence(_calendar()).model_dump(mode="json")
    evidence = dict(payload["replay_evidence"])
    payload["timezone"] = timezone_name
    evidence["timezone"] = timezone_name
    evidence["content_hash"] = _replay_evidence_hash(evidence)
    payload["replay_evidence"] = evidence
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "python":
            TradingCalendar.model_validate(payload)
        elif entrypoint == "json":
            TradingCalendar.model_validate_json(json.dumps(payload, sort_keys=True))
        else:
            TypeAdapter(TradingCalendar).validate_python(payload)
    error = str(exc_info.value)
    assert timezone_name not in error
    assert decoded not in error
    assert "CALENDAR-CANARY" not in error


def test_legacy_v1_calendar_serialization_omits_replay_evidence() -> None:
    calendar = _calendar()
    for mode in ("python", "json"):
        payload = calendar.model_dump(mode=mode)
        assert "replay_evidence" not in payload
        assert TradingCalendar.model_validate(payload).model_dump(mode=mode) == payload


def test_captured_replay_days_bind_local_dates_to_utc_half_open_intervals() -> None:
    calendar = _calendar_with_replay_evidence(_calendar())
    evidence = calendar.replay_evidence
    assert evidence is not None
    assert evidence.schema_version == "v1"
    assert evidence.timezone == calendar.timezone
    assert evidence.coverage_ranges == calendar.coverage_ranges
    assert evidence.content_hash.startswith("sha256:")
    assert len(evidence.content_hash) == 71
    assert evidence.content_hash == _replay_evidence_hash(
        evidence.model_dump(mode="json")
    )
    days = {day.local_date.isoformat(): day for day in evidence.days}
    assert tuple(days) == tuple(sorted(days))
    assert days["2024-03-10"].start_utc == datetime(2024, 3, 10, 5, tzinfo=timezone.utc)
    assert days["2024-03-10"].end_utc == datetime(2024, 3, 11, 4, tzinfo=timezone.utc)
    assert days["2024-07-02"].start_utc == datetime(2024, 7, 2, 4, tzinfo=timezone.utc)
    assert days["2024-07-02"].end_utc == datetime(2024, 7, 3, 4, tzinfo=timezone.utc)
    assert days["2024-07-03"].start_utc == days["2024-07-02"].end_utc
    assert days["2024-07-03"].start_utc <= datetime(2024, 7, 3, 4, tzinfo=timezone.utc)
    assert days["2024-07-02"].start_utc <= datetime(2024, 7, 3, 0, 30, tzinfo=timezone.utc) < days["2024-07-02"].end_utc
    assert calendar.session("2024-07-03").session_type is SessionType.EARLY_CLOSE
    assert calendar.session("2024-07-03").close_at < days["2024-07-03"].end_utc
    assert not any(day.local_date == date(2024, 7, 6) for day in evidence.days)


def test_captured_replay_day_includes_fall_dst_25_hour_date() -> None:
    calendar = TradingCalendar.model_validate(
        {
            "schema_version": "v1",
            "calendar_id": "XNYS.synthetic.v1",
            "timezone": "America/New_York",
            "coverage_start": "2024-11-02",
            "coverage_end": "2024-11-04",
            "coverage_ranges": ({"start": "2024-11-02", "end": "2024-11-04"},),
            "closures": (
                {"schema_version": "v1", "calendar_id": "XNYS.synthetic.v1", "date": "2024-11-02", "reason": "weekend"},
                {"schema_version": "v1", "calendar_id": "XNYS.synthetic.v1", "date": "2024-11-03", "reason": "weekend"},
            ),
            "schedule": (
                {
                    "schema_version": "v1",
                    "calendar_id": "XNYS.synthetic.v1",
                    "session_date": "2024-11-04",
                    "open_at": "2024-11-04T14:30:00Z",
                    "close_at": "2024-11-04T21:00:00Z",
                    "session_type": "regular",
                },
            ),
        }
    )
    days = _calendar_with_replay_evidence(calendar).replay_evidence.days
    fall_day = next(day for day in days if day.local_date == date(2024, 11, 3))
    assert fall_day.start_utc == datetime(2024, 11, 3, 4, tzinfo=timezone.utc)
    assert fall_day.end_utc == datetime(2024, 11, 4, 5, tzinfo=timezone.utc)
    assert fall_day.end_utc - fall_day.start_utc == timedelta(hours=25)


@pytest.mark.parametrize("defect", ("missing", "duplicate", "reversed", "overlap", "hash", "version"))
def test_replay_evidence_rejects_corrupt_or_noncanonical_day_claim(defect: str) -> None:
    calendar = _calendar_with_replay_evidence(_calendar())
    payload = calendar.model_dump(mode="json")
    evidence = dict(payload["replay_evidence"])
    days = list(evidence["days"])
    if defect == "missing":
        days.pop(1)
    elif defect == "duplicate":
        days.insert(1, days[0])
    elif defect == "reversed":
        days[0], days[1] = days[1], days[0]
    elif defect == "overlap":
        days[1] = {**days[1], "start_utc": days[0]["start_utc"]}
    elif defect == "hash":
        evidence["content_hash"] = "sha256:" + "0" * 64
    else:
        evidence["schema_version"] = "v2"
    evidence["days"] = days
    if defect != "hash":
        evidence["content_hash"] = _replay_evidence_hash(evidence)
    payload["replay_evidence"] = evidence
    with pytest.raises(ValidationError):
        TradingCalendar.model_validate(payload)


def test_replay_evidence_day_count_cap_rejects_cap_plus_one() -> None:
    max_days = getattr(calendar_module, "MAX_CALENDAR_REPLAY_DAYS", None)
    assert type(max_days) is int and 1 <= max_days <= 4096
    calendar = _calendar_with_replay_evidence(_calendar())
    payload = calendar.model_dump(mode="python")
    evidence = dict(payload["replay_evidence"])
    evidence["days"] = [evidence["days"][0]] * (max_days + 1)
    payload["replay_evidence"] = evidence
    with pytest.raises(ValidationError):
        TradingCalendar.model_validate(payload)


def test_replay_evidence_rejects_hostile_day_without_callback_or_payload_echo() -> None:
    class HostileDay:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("HOSTILE-REPLAY-DAY-CANARY")

        def __str__(self) -> str:
            raise AssertionError("HOSTILE-REPLAY-DAY-CANARY")

    calendar = _calendar_with_replay_evidence(_calendar())
    payload = calendar.model_dump(mode="python")
    evidence = dict(payload["replay_evidence"])
    days = list(evidence["days"])
    days[0] = HostileDay()
    evidence["days"] = days
    payload["replay_evidence"] = evidence
    with pytest.raises(ValidationError) as exc_info:
        TradingCalendar.model_validate(payload)
    assert "HOSTILE-REPLAY-DAY-CANARY" not in str(exc_info.value)


def test_mutated_exact_replay_day_date_is_rejected_before_comparison_callback() -> None:
    calls: list[str] = []

    class ArmedDate(date):
        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            raise AssertionError("REPLAY-DAY-DATE-CALLBACK")

        def __ne__(self, other: object) -> bool:
            calls.append("ne")
            raise AssertionError("REPLAY-DAY-DATE-CALLBACK")

    evidence = _calendar_with_replay_evidence(_calendar()).replay_evidence
    payload = evidence.model_dump(mode="python")
    day = evidence.days[0].model_copy()
    object.__setattr__(day, "local_date", ArmedDate(2024, 3, 8))
    payload["days"] = (day, *payload["days"][1:])
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        calendar_module.CalendarReplayEvidence.model_validate(payload)
    assert calls == []
    assert "REPLAY-DAY-DATE-CALLBACK" not in str(exc_info.value)


def test_mutated_exact_replay_coverage_is_rejected_before_date_callback() -> None:
    calls: list[str] = []

    class ArmedDate(date):
        def toordinal(self) -> int:
            calls.append("toordinal")
            raise AssertionError("REPLAY-COVERAGE-DATE-CALLBACK")

    evidence = _calendar_with_replay_evidence(_calendar()).replay_evidence
    payload = evidence.model_dump(mode="python")
    coverage = evidence.coverage_ranges[0].model_copy()
    object.__setattr__(coverage, "start", ArmedDate(2024, 3, 8))
    payload["coverage_ranges"] = (coverage, *payload["coverage_ranges"][1:])
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        calendar_module.CalendarReplayEvidence.model_validate(payload)
    assert calls == []
    assert "REPLAY-COVERAGE-DATE-CALLBACK" not in str(exc_info.value)


def test_witnessed_calendar_rejects_str_subclass_child_key_before_equality() -> None:
    calls: list[str] = []

    class ArmedKey(str):
        __hash__ = str.__hash__

        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            raise AssertionError("REPLAY-CHILD-KEY-CALLBACK")

    payload = _calendar_with_replay_evidence(_calendar()).model_dump(mode="python")
    evidence = dict(payload["replay_evidence"])
    days = list(evidence["days"])
    day = dict(days[0])
    original_date = day.pop("local_date")
    day[ArmedKey("local_date")] = original_date
    days[0] = day
    evidence["days"] = days
    payload["replay_evidence"] = evidence
    calls.clear()
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        TradingCalendar.model_validate(payload)
    assert calls == []
    assert "REPLAY-CHILD-KEY-CALLBACK" not in str(exc_info.value)


@pytest.mark.parametrize(
    "timezone_name",
    ("America/sk-proj-CALENDAR-CANARY", "America/sk-proj-%43ALENDAR-CANARY"),
)
def test_witnessed_calendar_rejects_sensitive_timezone_without_echo(
    timezone_name: str,
) -> None:
    with pytest.raises(ValueError):
        validate_artifact_text(timezone_name)
    payload = _calendar_with_replay_evidence(_calendar()).model_dump(mode="json")
    evidence = dict(payload["replay_evidence"])
    payload["timezone"] = timezone_name
    evidence["timezone"] = timezone_name
    evidence["content_hash"] = _replay_evidence_hash(evidence)
    payload["replay_evidence"] = evidence
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        TradingCalendar.model_validate(payload)
    assert timezone_name not in str(exc_info.value)
    assert "CALENDAR-CANARY" not in str(exc_info.value)


@pytest.mark.parametrize("field", ("local_date", "end_utc"))
@pytest.mark.parametrize("entrypoint", ("model_validate", "type_adapter"))
def test_direct_replay_day_rejects_mutated_exact_instance_without_callbacks(
    field: str,
    entrypoint: str,
) -> None:
    calls: list[str] = []

    class ArmedDate(date):
        def __eq__(self, other: object) -> bool:
            calls.append("date_eq")
            raise AssertionError("DIRECT-REPLAY-DATE-CALLBACK")

    class ArmedDateTime(datetime):
        def __sub__(self, other: object) -> timedelta:
            calls.append("datetime_sub")
            raise AssertionError("DIRECT-REPLAY-TIME-CALLBACK")

    day = _calendar_with_replay_evidence(_calendar()).replay_evidence.days[0].model_copy()
    if field == "local_date":
        object.__setattr__(day, field, ArmedDate(2024, 3, 8))
    else:
        end = day.end_utc
        object.__setattr__(
            day,
            field,
            ArmedDateTime(end.year, end.month, end.day, end.hour, tzinfo=timezone.utc),
        )
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "model_validate":
            calendar_module.CalendarReplayDay.model_validate(day)
        else:
            TypeAdapter(calendar_module.CalendarReplayDay).validate_python(day)
    assert calls == []
    assert "DIRECT-REPLAY-" not in str(exc_info.value)


@pytest.mark.parametrize("entrypoint", ("constructor", "model_validate", "type_adapter"))
def test_replay_day_rejects_raw_datetime_subclass_before_utcoffset_callback(
    entrypoint: str,
) -> None:
    calls: list[str] = []

    class ArmedDateTime(datetime):
        def utcoffset(self) -> timedelta:
            calls.append("utcoffset")
            raise AssertionError("RAW-REPLAY-UTC-OFFSET-CALLBACK")

    payload = _calendar_with_replay_evidence(_calendar()).replay_evidence.days[0].model_dump(
        mode="python"
    )
    payload["start_utc"] = ArmedDateTime(2024, 3, 8, 5, tzinfo=timezone.utc)
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "constructor":
            calendar_module.CalendarReplayDay(**payload)
        elif entrypoint == "model_validate":
            calendar_module.CalendarReplayDay.model_validate(payload)
        else:
            TypeAdapter(calendar_module.CalendarReplayDay).validate_python(payload)
    assert calls == []
    assert "RAW-REPLAY-UTC-OFFSET-CALLBACK" not in str(exc_info.value)


@pytest.mark.parametrize("entrypoint", ("model_validate", "type_adapter"))
def test_direct_coverage_range_rejects_mutated_exact_instance_without_callbacks(
    entrypoint: str,
) -> None:
    calls: list[str] = []

    class ArmedDate(date):
        def __gt__(self, other: object) -> bool:
            calls.append("date_gt")
            raise AssertionError("DIRECT-COVERAGE-DATE-CALLBACK")

    coverage = _calendar_with_replay_evidence(_calendar()).coverage_ranges[0].model_copy()
    object.__setattr__(coverage, "start", ArmedDate(2024, 3, 8))
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "model_validate":
            calendar_module.CalendarCoverageRange.model_validate(coverage)
        else:
            TypeAdapter(calendar_module.CalendarCoverageRange).validate_python(coverage)
    assert calls == []
    assert "DIRECT-COVERAGE-DATE-CALLBACK" not in str(exc_info.value)


def test_exact_instance_type_adapters_reject_nested_mutation_without_callbacks() -> None:
    calls: list[str] = []

    class ArmedDate(date):
        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            raise AssertionError("NESTED-REPLAY-DATE-CALLBACK")

        def __ne__(self, other: object) -> bool:
            calls.append("ne")
            raise AssertionError("NESTED-REPLAY-DATE-CALLBACK")

    calendar = _calendar_with_replay_evidence(_calendar())
    evidence = calendar.replay_evidence.model_copy(deep=True)
    day = evidence.days[0].model_copy()
    object.__setattr__(day, "local_date", ArmedDate(2024, 3, 8))
    object.__setattr__(evidence, "days", (day, *evidence.days[1:]))
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        TypeAdapter(calendar_module.CalendarReplayEvidence).validate_python(evidence)
    assert calls == []
    assert "NESTED-REPLAY-DATE-CALLBACK" not in str(exc_info.value)

    coverage = calendar.coverage_ranges[0].model_copy()
    object.__setattr__(coverage, "start", ArmedDate(2024, 3, 8))
    object.__setattr__(calendar, "coverage_ranges", (coverage, *calendar.coverage_ranges[1:]))
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        TypeAdapter(TradingCalendar).validate_python(calendar)
    assert calls == []
    assert "NESTED-REPLAY-DATE-CALLBACK" not in str(exc_info.value)


@pytest.mark.parametrize("entrypoint", ("python", "json"))
@pytest.mark.parametrize(
    "timezone_name",
    (
        "America/sk-proj-CALENDAR-CANARY",
        "America/c2stcHJvai1DQUxFTkRBUi1DQU5BUlk",
        "America/hex736b2d70726f6a2d43414c454e4441522d43414e415259",
        "America/sk-proj-%43ALENDAR-CANARY",
    ),
)
def test_witnessed_timezone_secret_encodings_reject_without_echo(
    timezone_name: str,
    entrypoint: str,
) -> None:
    decoded = "sk-proj-CALENDAR-CANARY"
    payload = _calendar_with_replay_evidence(_calendar()).model_dump(mode="json")
    evidence = dict(payload["replay_evidence"])
    payload["timezone"] = timezone_name
    evidence["timezone"] = timezone_name
    evidence["content_hash"] = _replay_evidence_hash(evidence)
    payload["replay_evidence"] = evidence
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "python":
            TradingCalendar.model_validate(payload)
        else:
            TradingCalendar.model_validate_json(json.dumps(payload, sort_keys=True))
    assert timezone_name not in str(exc_info.value)
    assert decoded not in str(exc_info.value)


@pytest.mark.parametrize("encoding", ("double_base64", "base64_of_hex"))
@pytest.mark.parametrize("entrypoint", ("python", "json"))
def test_nested_timezone_secret_encoding_is_bounded_and_rejected_without_echo(
    encoding: str,
    entrypoint: str,
) -> None:
    decoded = "sk-proj-CALENDAR-CANARY"
    if encoding == "double_base64":
        inner = base64.urlsafe_b64encode(decoded.encode()).decode().rstrip("=")
    else:
        inner = "hex" + decoded.encode().hex()
    segment = base64.urlsafe_b64encode(inner.encode()).decode().rstrip("=")
    timezone_name = "America/" + segment
    payload = _calendar_with_replay_evidence(_calendar()).model_dump(mode="json")
    evidence = dict(payload["replay_evidence"])
    payload["timezone"] = timezone_name
    evidence["timezone"] = timezone_name
    evidence["content_hash"] = _replay_evidence_hash(evidence)
    payload["replay_evidence"] = evidence
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        if entrypoint == "python":
            TradingCalendar.model_validate(payload)
        else:
            TradingCalendar.model_validate_json(json.dumps(payload, sort_keys=True))
    assert timezone_name not in str(exc_info.value)
    assert decoded not in str(exc_info.value)


@pytest.mark.parametrize("timezone_name", ("America/New_York", "Pacific/Honolulu"))
def test_safe_iana_timezones_remain_valid_without_changing_legacy_wire(
    timezone_name: str,
) -> None:
    payload = _calendar().model_dump(mode="json")
    assert "replay_evidence" not in payload
    payload["timezone"] = timezone_name
    calendar = TradingCalendar.model_validate(payload)
    assert calendar.timezone == timezone_name
    assert "replay_evidence" not in calendar.model_dump(mode="json")


def test_calendar_fixture_is_versioned_sorted_and_immutable() -> None:
    calendar = _calendar()

    assert calendar.schema_version == "v1"
    assert calendar.calendar_id == "XNYS.synthetic.v1"
    assert calendar.timezone == "America/New_York"
    assert calendar.coverage_start == date(2024, 3, 8)
    assert calendar.coverage_end == date(2024, 11, 29)
    assert isinstance(calendar.schedule, tuple)
    assert isinstance(calendar.coverage_ranges, tuple)
    assert isinstance(calendar.closures, tuple)
    assert [(item.start, item.end) for item in calendar.coverage_ranges] == [
        (date(2024, 3, 8), date(2024, 3, 11)),
        (date(2024, 7, 2), date(2024, 7, 5)),
        (date(2024, 11, 27), date(2024, 11, 29)),
    ]
    assert tuple(item.session_date for item in calendar.schedule) == tuple(
        sorted(item.session_date for item in calendar.schedule)
    )
    with pytest.raises(ValidationError):
        calendar.timezone = "UTC"
    with pytest.raises(ValidationError):
        calendar.schedule[0].close_at = calendar.schedule[0].open_at
    with pytest.raises(ValidationError):
        calendar.coverage_ranges[0].end = date(2024, 3, 12)
    with pytest.raises(ValidationError):
        calendar.closures[0].reason = "changed"


def test_session_and_adjustment_enums_have_stable_wire_values() -> None:
    assert {item.value for item in SessionType} == {"regular", "early_close"}
    assert {item.value for item in AdjustmentBasis} == {
        "unadjusted",
        "provider_adjusted",
    }
    assert {item.value for item in bars_module.BarFinality} == {"preliminary", "final"}


def test_calendar_preserves_dst_transition_and_actual_early_close() -> None:
    calendar = _calendar()
    eastern = ZoneInfo(calendar.timezone)
    winter = calendar.session("2024-11-27")
    summer = calendar.session("2024-07-02")
    before_transition = calendar.session("2024-03-08")
    after_transition = calendar.session("2024-03-11")
    early_close = calendar.session("2024-11-29")

    assert winter.open_at == datetime(2024, 11, 27, 14, 30, tzinfo=timezone.utc)
    assert summer.open_at == datetime(2024, 7, 2, 13, 30, tzinfo=timezone.utc)
    assert winter.open_at.astimezone(eastern).hour == 9
    assert summer.open_at.astimezone(eastern).hour == 9
    assert before_transition.open_at.hour == 14
    assert after_transition.open_at.hour == 13
    assert winter.open_at.astimezone(eastern).utcoffset() == timedelta(hours=-5)
    assert summer.open_at.astimezone(eastern).utcoffset() == timedelta(hours=-4)
    assert early_close.session_type is SessionType.EARLY_CLOSE
    assert early_close.close_at == datetime(2024, 11, 29, 18, 0, tzinfo=timezone.utc)
    assert early_close.close_at.astimezone(eastern) == datetime(
        2024,
        11,
        29,
        13,
        0,
        tzinfo=eastern,
    )


def test_calendar_holidays_are_omitted_and_never_inferred() -> None:
    calendar = _calendar()

    with pytest.raises(CalendarSessionNotFoundError):
        calendar.session("2024-07-04")
    with pytest.raises(CalendarSessionNotFoundError):
        calendar.session("2024-11-28")


def test_calendar_ranges_are_inclusive_and_next_session_is_strictly_later() -> None:
    calendar = _calendar()

    assert [
        item.session_date
        for item in calendar.sessions("2024-07-02", "2024-07-04")
    ] == [date(2024, 7, 2), date(2024, 7, 3)]
    assert calendar.sessions("2024-07-03", "2024-07-03") == (
        calendar.session("2024-07-03"),
    )
    assert calendar.next_session("2024-07-02").session_date == date(2024, 7, 3)
    assert calendar.next_session(date(2024, 7, 4)).session_date == date(2024, 7, 5)


def test_calendar_never_crosses_an_unverified_coverage_gap() -> None:
    calendar = _calendar()

    for value in ("2024-03-12", "2024-06-01", "2024-07-06", "2024-11-26"):
        with pytest.raises(CalendarCoverageError):
            calendar.session(value)
        with pytest.raises(CalendarCoverageError):
            calendar.next_session(value)
    with pytest.raises(CalendarCoverageError):
        calendar.sessions("2024-07-05", "2024-11-27")
    with pytest.raises(CalendarCoverageError):
        calendar.next_session("2024-07-05")


def test_calendar_session_distance_uses_verified_session_transitions_only() -> None:
    calendar = _calendar()

    assert calendar.session_distance("2024-11-27", "2024-11-29") == 1
    assert calendar.session_distance("2024-07-02", "2024-07-05") == 2
    assert calendar.session_distance("2024-07-03", "2024-07-03") == 0
    with pytest.raises(CalendarSessionNotFoundError):
        calendar.session_distance("2024-07-03", "2024-07-04")
    with pytest.raises(CalendarCoverageError):
        calendar.session_distance("2024-07-05", "2024-11-27")


def test_calendar_fails_closed_outside_coverage_and_at_schedule_exhaustion() -> None:
    calendar = _calendar()

    for value in ("2024-03-07", "2024-11-30"):
        with pytest.raises(CalendarCoverageError):
            calendar.session(value)
    with pytest.raises(CalendarCoverageError):
        calendar.sessions("2024-07-02", "2024-11-30")
    with pytest.raises(CalendarCoverageError):
        calendar.next_session("2024-11-29")


@pytest.mark.parametrize(
    "value",
    [
        datetime(2024, 7, 2, tzinfo=timezone.utc),
        20240702,
        2024.0702,
        " 2024-07-02",
        "2024-07-02 ",
        "2024-7-2",
        "2024-07-02T00:00:00Z",
        "not-a-date",
    ],
)
def test_calendar_methods_require_exact_date_or_iso_date_inputs(value: object) -> None:
    calendar = _calendar()

    with pytest.raises(CalendarError):
        calendar.session(value)  # type: ignore[arg-type]
    with pytest.raises(CalendarError):
        calendar.sessions(value, date(2024, 11, 29))  # type: ignore[arg-type]
    with pytest.raises(CalendarError):
        calendar.next_session(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("timezone_name", ["", "EST", "+05:00", "Mars/Olympus"])
def test_calendar_requires_an_iana_timezone(timezone_name: str) -> None:
    with pytest.raises(ValidationError):
        _calendar(timezone=timezone_name)


def test_trading_session_requires_utc_instants_and_open_before_close() -> None:
    fields = _fixture()["sessions"][0]
    for override in (
        {"open_at": "2024-03-08T09:30:00"},
        {"close_at": "2024-03-08"},
        {"open_at": 1_709_908_200},
        {"open_at": "2024-03-08T21:00:00Z"},
    ):
        with pytest.raises(ValidationError):
            TradingSession.model_validate({**fields, **override})


def test_calendar_rejects_duplicate_unsorted_conflicting_and_outside_sessions() -> None:
    schedule = _calendar().schedule
    conflicting = schedule[0].model_copy(update={"calendar_id": "OTHER"})
    outside = schedule[0].model_copy(update={"session_date": date(2024, 3, 7)})

    for invalid_schedule in (
        (schedule[0], schedule[0]),
        tuple(reversed(schedule)),
        (conflicting, *schedule[1:]),
        (outside, *schedule[1:]),
    ):
        with pytest.raises(ValidationError):
            _calendar(schedule=invalid_schedule)


def test_calendar_rejects_overlap_and_local_date_mismatch() -> None:
    calendar = _calendar()
    first, second = calendar.schedule[:2]
    overlapping = TradingSession.model_construct(
        schema_version="v1",
        calendar_id=calendar.calendar_id,
        session_date=second.session_date,
        open_at=first.open_at + timedelta(hours=1),
        close_at=first.close_at + timedelta(hours=1),
        session_type=SessionType.REGULAR,
    )
    local_mismatch = first.model_copy(
        update={
            "open_at": datetime(2024, 3, 9, 14, 30, tzinfo=timezone.utc),
            "close_at": datetime(2024, 3, 9, 21, 0, tzinfo=timezone.utc),
        }
    )

    with pytest.raises(ValidationError):
        _calendar(schedule=(first, overlapping, *calendar.schedule[2:]))
    with pytest.raises(ValidationError):
        _calendar(schedule=(local_mismatch, *calendar.schedule[1:]))


def test_calendar_requires_exact_dates_and_valid_coverage_order() -> None:
    for overrides in (
        {"coverage_start": datetime(2024, 3, 8, tzinfo=timezone.utc)},
        {"coverage_end": 20241129},
        {"coverage_start": " 2024-03-08"},
        {"coverage_start": "2024-11-30"},
    ):
        with pytest.raises(ValidationError):
            _calendar(**overrides)


def test_coverage_and_closure_models_are_public_exact_and_required() -> None:
    assert set(calendar_module.CalendarCoverageRange.model_fields) == {"start", "end"}
    assert set(calendar_module.CalendarClosure.model_fields) == {
        "schema_version",
        "calendar_id",
        "date",
        "reason",
    }
    assert TradingCalendar.model_fields["coverage_ranges"].is_required()
    assert TradingCalendar.model_fields["closures"].is_required()

    fixture = _fixture()
    for missing in ("coverage_ranges", "closures"):
        fields = {
            "schema_version": fixture["schema_version"],
            "calendar_id": fixture["calendar_id"],
            "timezone": fixture["timezone"],
            "coverage_start": fixture["coverage_start"],
            "coverage_end": fixture["coverage_end"],
            "schedule": fixture["sessions"],
            "coverage_ranges": fixture["coverage_ranges"],
            "closures": fixture["closures"],
        }
        fields.pop(missing)
        with pytest.raises(ValidationError):
            TradingCalendar.model_validate(fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"start": "2024-03-12", "end": "2024-03-11"},
        {"start": " 2024-03-08", "end": "2024-03-11"},
        {"start": datetime(2024, 3, 8, tzinfo=timezone.utc), "end": "2024-03-11"},
    ],
)
def test_coverage_range_requires_exact_ordered_dates(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        calendar_module.CalendarCoverageRange.model_validate(fields)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": "v2"},
        {"calendar_id": "OTHER"},
        {"date": " 2024-07-04"},
        {"reason": ""},
        {"reason": "not stable"},
    ],
)
def test_calendar_closure_is_strict_versioned_and_calendar_bound(
    overrides: dict[str, object],
) -> None:
    closure = {
        "schema_version": "v1",
        "calendar_id": "XNYS.synthetic.v1",
        "date": "2024-07-04",
        "reason": "exchange_holiday",
    }
    closure.update(overrides)
    if overrides == {"calendar_id": "OTHER"}:
        invalid = calendar_module.CalendarClosure.model_validate(closure)
        with pytest.raises(ValidationError):
            _calendar(closures=(invalid, *_calendar().closures))
    else:
        with pytest.raises(ValidationError):
            calendar_module.CalendarClosure.model_validate(closure)


def test_calendar_requires_complete_disjoint_classification_windows() -> None:
    calendar = _calendar()
    ranges = calendar.coverage_ranges
    closures = calendar.closures
    schedule = calendar.schedule
    duplicate_closure = closures[0].model_copy()
    session_overlap = calendar_module.CalendarClosure(
        schema_version="v1",
        calendar_id=calendar.calendar_id,
        date="2024-07-03",
        reason="unexpected_closure",
    )
    outside_closure = calendar_module.CalendarClosure(
        schema_version="v1",
        calendar_id=calendar.calendar_id,
        date="2024-07-01",
        reason="outside_window",
    )
    overlapping_range = calendar_module.CalendarCoverageRange(
        start="2024-03-11",
        end="2024-07-05",
    )

    invalid_cases = (
        {"coverage_ranges": ()},
        {"coverage_ranges": (ranges[0], ranges[0], *ranges[1:])},
        {"coverage_ranges": (ranges[0], overlapping_range, *ranges[1:])},
        {"closures": closures[1:]},
        {"closures": (duplicate_closure, *closures)},
        {"closures": (*closures, session_overlap)},
        {"closures": (*closures, outside_closure)},
        {"schedule": schedule[1:]},
    )
    for overrides in invalid_cases:
        with pytest.raises(ValidationError):
            _calendar(**overrides)


def test_calendar_rejects_adjacent_coverage_ranges_that_should_be_merged() -> None:
    calendar = _calendar()
    ranges = calendar.coverage_ranges
    july_first = calendar_module.CalendarCoverageRange(
        start="2024-07-02",
        end="2024-07-03",
    )
    july_second = calendar_module.CalendarCoverageRange(
        start="2024-07-04",
        end="2024-07-05",
    )

    assert _calendar().coverage_ranges == ranges
    with pytest.raises(ValidationError):
        _calendar(
            coverage_ranges=(ranges[0], july_first, july_second, ranges[2]),
        )


def test_fixture_classifies_every_date_in_each_coverage_window_once() -> None:
    calendar = _calendar()
    session_dates = {session.session_date for session in calendar.schedule}
    closure_dates = {closure.date for closure in calendar.closures}

    assert session_dates.isdisjoint(closure_dates)
    for coverage_range in calendar.coverage_ranges:
        expected_dates = {
            coverage_range.start + timedelta(days=offset)
            for offset in range((coverage_range.end - coverage_range.start).days + 1)
        }
        assert expected_dates == (session_dates | closure_dates).intersection(expected_dates)


def test_daily_bar_round_trips_exact_decimals_and_nested_manifest() -> None:
    calendar = _calendar()
    bar = _bar(calendar)
    restored = DailyBar.model_validate_json(bar.model_dump_json())

    assert restored == bar
    assert restored.open == Decimal("100.00")
    assert restored.high == Decimal("105.00")
    assert restored.low == Decimal("98.00")
    assert restored.close == Decimal("103.00")
    assert restored.volume == 1_000_000
    assert restored.interval == "1d"
    assert restored.finality is bars_module.BarFinality.FINAL
    assert restored.manifest.source == "synthetic-bars"
    assert restored.model_dump(mode="json")["open"] == "100.00"
    with pytest.raises(ValidationError):
        restored.close = Decimal("1")
    with pytest.raises(ValidationError):
        DailyBar.model_validate({**bar.model_dump(), "provider_timezone": "America/New_York"})


def test_daily_bar_finality_is_required_and_repository_accepts_only_final() -> None:
    assert DailyBar.model_fields["finality"].is_required()
    assert {item.value for item in bars_module.BarFinality} == {"preliminary", "final"}
    calendar = _calendar()
    final = _bar(calendar, finality=bars_module.BarFinality.FINAL)
    preliminary = _bar(calendar, finality=bars_module.BarFinality.PRELIMINARY)
    missing = final.model_dump()
    missing.pop("finality")

    with pytest.raises(ValidationError):
        DailyBar.model_validate(missing)
    assert _repository(calendar, (final,)).bars == (final,)
    with pytest.raises(ValidationError):
        _repository(calendar, (preliminary,))


@pytest.mark.parametrize("schema_version", [None, "", "v0", "v2", 1])
def test_calendar_session_bar_and_repository_require_exact_v1(
    schema_version: object,
) -> None:
    calendar = _calendar()
    session_fields = _fixture()["sessions"][0]

    with pytest.raises(ValidationError):
        TradingSession.model_validate({**session_fields, "schema_version": schema_version})
    with pytest.raises(ValidationError):
        _calendar(schema_version=schema_version)
    with pytest.raises(ValidationError):
        _bar(calendar, schema_version=schema_version)
    with pytest.raises(ValidationError):
        BarRepository(schema_version=schema_version, calendar=calendar, bars=())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", "0"),
        ("high", "-1"),
        ("low", 0),
        ("close", -1),
        ("open", 100.0),
        ("close", True),
        ("volume", -1),
        ("volume", True),
        ("volume", 1.0),
        ("volume", "1000"),
        ("interval", "1h"),
    ],
)
def test_daily_bar_rejects_invalid_prices_volume_and_interval(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        _bar(_calendar(), **{field: value})


@pytest.mark.parametrize(
    "overrides",
    [
        {"open": "106", "high": "105"},
        {"close": "106", "high": "105"},
        {"open": "97", "low": "98"},
        {"close": "97", "low": "98"},
        {"high": "97", "low": "98"},
    ],
)
def test_daily_bar_enforces_ohlc_high_low_invariants(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _bar(_calendar(), **overrides)


def test_daily_bar_adjustment_policy_is_explicit_and_versioned() -> None:
    calendar = _calendar()
    adjusted = _bar(
        calendar,
        adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
        adjustment_version="provider-policy-v3",
    )

    assert adjusted.adjustment_version == "provider-policy-v3"
    with pytest.raises(ValidationError):
        _bar(calendar, adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED)
    with pytest.raises(ValidationError):
        _bar(calendar, adjustment_version="unexpected-version")
    with pytest.raises(ValidationError):
        _bar(
            calendar,
            adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
            adjustment_version="",
        )


def test_repository_sorts_bars_deterministically_and_is_frozen_read_only() -> None:
    calendar = _calendar()
    bars = (
        _bar(calendar, revision=2),
        _bar(calendar, session_date="2024-07-03", instrument_id="MSFT"),
        _bar(calendar, revision=0),
        _bar(calendar, revision=1),
    )
    first = _repository(calendar, bars)
    second = _repository(calendar, tuple(reversed(bars)))

    assert isinstance(first.bars, tuple)
    assert first.bars == second.bars
    assert [bar.manifest.revision for bar in first.bars if bar.instrument_id == "AAPL"] == [
        0,
        1,
        2,
    ]
    with pytest.raises(ValidationError):
        first.bars = ()
    assert not {"put", "add", "delete", "update", "refresh"}.intersection(
        vars(BarRepository)
    )


def test_repository_rejects_calendar_mismatch_non_session_and_partial_bar() -> None:
    calendar = _calendar()
    session = calendar.session("2024-11-27")
    out_of_session = _bar(calendar).model_copy(
        update={"session_date": date(2024, 11, 28)}
    )
    for invalid in (
        _bar(calendar, calendar_id="OTHER"),
        out_of_session,
        _bar(calendar, manifest=_manifest(session, event_time=session.open_at)),
        _bar(
            calendar,
            manifest=_manifest(session).model_copy(update={"event_time": None}),
        ),
        _bar(
            calendar,
            manifest=_manifest(
                session,
                available_at=session.close_at - timedelta(microseconds=1),
                fetched_at=session.close_at,
                ingested_at=session.close_at,
            ),
        ),
    ):
        with pytest.raises(ValidationError):
            _repository(calendar, (invalid,))


def test_repository_rejects_duplicate_bar_id_and_duplicate_business_key() -> None:
    calendar = _calendar()
    original = _bar(calendar)
    duplicate_id = _bar(
        calendar,
        session_date="2024-07-03",
        bar_id=original.bar_id,
    )
    duplicate_key_identical = original.model_copy(update={"bar_id": "different-id"})
    duplicate_key_conflicting = original.model_copy(
        update={"bar_id": "conflicting-id", "close": Decimal("104.00")}
    )

    with pytest.raises(ValidationError):
        _repository(calendar, (original, duplicate_id))
    with pytest.raises(ValidationError):
        _repository(calendar, (original, duplicate_key_identical))
    with pytest.raises(ValidationError):
        _repository(calendar, (original, duplicate_key_conflicting))


def test_as_of_signature_requires_every_selector_explicitly() -> None:
    parameters = inspect.signature(BarRepository.as_of).parameters

    assert list(parameters) == [
        "self",
        "instrument_id",
        "session_date",
        "knowledge_cutoff",
        "source",
        "adjustment_basis",
        "adjustment_version",
    ]
    assert parameters["instrument_id"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["session_date"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for name in (
        "knowledge_cutoff",
        "source",
        "adjustment_basis",
        "adjustment_version",
    ):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty


def test_as_of_cutoff_is_inclusive_and_selects_highest_available_revision() -> None:
    calendar = _calendar()
    session = calendar.session("2024-11-27")
    revisions = (
        _bar(
            calendar,
            revision=7,
            manifest=_manifest(
                session,
                revision=7,
                available_at=session.close_at + timedelta(minutes=1),
            ),
        ),
        _bar(
            calendar,
            revision=2,
            manifest=_manifest(
                session,
                revision=2,
                available_at=session.close_at + timedelta(minutes=2),
            ),
        ),
        _bar(
            calendar,
            revision=9,
            manifest=_manifest(
                session,
                revision=9,
                available_at=session.close_at + timedelta(minutes=3),
            ),
        ),
    )
    repository = _repository(calendar, tuple(reversed(revisions)))

    selected = repository.as_of(
        "AAPL",
        "2024-11-27",
        knowledge_cutoff=session.close_at + timedelta(minutes=2),
        source="synthetic-bars",
        adjustment_basis=AdjustmentBasis.UNADJUSTED,
        adjustment_version=None,
    )

    assert selected.manifest.available_at == session.close_at + timedelta(minutes=1)
    assert selected.manifest.revision == 7

    tied_availability = _repository(
        calendar,
        (
            _bar(
                calendar,
                revision=4,
                manifest=_manifest(
                    session,
                    revision=4,
                    available_at=session.close_at + timedelta(minutes=1),
                ),
            ),
            _bar(
                calendar,
                revision=8,
                manifest=_manifest(
                    session,
                    revision=8,
                    available_at=session.close_at + timedelta(minutes=1),
                ),
            ),
        ),
    )
    tied_selected = tied_availability.as_of(
        "AAPL",
        "2024-11-27",
        knowledge_cutoff=session.close_at + timedelta(minutes=1),
        source="synthetic-bars",
        adjustment_basis=AdjustmentBasis.UNADJUSTED,
        adjustment_version=None,
    )
    assert tied_selected.manifest.revision == 8


def test_as_of_never_applies_archive_ingestion_cutoff_before_pit_06() -> None:
    calendar = _calendar()
    session = calendar.session("2024-11-27")
    cutoff = session.close_at + timedelta(minutes=1)
    manifest = _manifest(
        session,
        available_at=cutoff,
        fetched_at=cutoff + timedelta(minutes=1),
        ingested_at=cutoff + timedelta(days=2),
    )
    archived_later = _bar(calendar, manifest=manifest)
    repository = _repository(calendar, (archived_later,))

    selected = repository.as_of(
        "AAPL",
        session.session_date,
        knowledge_cutoff=cutoff,
        source="synthetic-bars",
        adjustment_basis=AdjustmentBasis.UNADJUSTED,
        adjustment_version=None,
    )

    assert selected == archived_later
    assert selected.manifest.ingested_at > cutoff


def test_as_of_isolates_same_source_adjustment_versions_without_fallback() -> None:
    calendar = _calendar()
    session = calendar.session("2024-11-27")
    repository = _repository(
        calendar,
        (
            _bar(calendar),
            _bar(
                calendar,
                adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
                adjustment_version="provider-v1",
            ),
            _bar(
                calendar,
                adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
                adjustment_version="provider-v2",
            ),
        ),
    )
    cutoff = session.close_at + timedelta(hours=1)

    selected = repository.as_of(
        "AAPL",
        session.session_date,
        knowledge_cutoff=cutoff,
        source="synthetic-bars",
        adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
        adjustment_version="provider-v2",
    )
    assert selected.manifest.source == "synthetic-bars"
    assert selected.adjustment_version == "provider-v2"

    selected_v1 = repository.as_of(
        "AAPL",
        session.session_date,
        knowledge_cutoff=cutoff,
        source="synthetic-bars",
        adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
        adjustment_version="provider-v1",
    )
    assert selected_v1.adjustment_version == "provider-v1"

    for selectors in (
        {"source": "unknown-bars"},
        {"adjustment_basis": AdjustmentBasis.PROVIDER_ADJUSTED},
        {
            "adjustment_basis": AdjustmentBasis.PROVIDER_ADJUSTED,
            "adjustment_version": "provider-v3",
        },
    ):
        query: dict[str, object] = {
            "knowledge_cutoff": cutoff,
            "source": "synthetic-bars",
            "adjustment_basis": AdjustmentBasis.UNADJUSTED,
            "adjustment_version": None,
        }
        query.update(selectors)
        with pytest.raises(BarMissingError):
            repository.as_of("AAPL", session.session_date, **query)


def test_as_of_distinguishes_future_stale_and_missing() -> None:
    calendar = _calendar()
    prior = _bar(calendar, session_date="2024-11-27")
    older_history = (
        _bar(calendar, session_date="2024-03-08"),
        _bar(calendar, session_date="2024-07-02"),
        _bar(calendar, session_date="2024-07-03"),
    )
    future_exact = _bar(calendar, session_date="2024-11-29")
    repository = _repository(calendar, (*older_history, prior, future_exact))
    cutoff = calendar.session("2024-11-29").close_at
    query = {
        "knowledge_cutoff": cutoff,
        "source": "synthetic-bars",
        "adjustment_basis": AdjustmentBasis.UNADJUSTED,
        "adjustment_version": None,
    }

    with pytest.raises(BarFutureError):
        repository.as_of("AAPL", "2024-11-29", **query)

    stale_repository = _repository(calendar, (*older_history, prior))
    with pytest.raises(BarStaleError) as stale:
        stale_repository.as_of("AAPL", "2024-11-29", **query)
    assert stale.value.prior_matching_session_count == 1

    with pytest.raises(BarMissingError):
        stale_repository.as_of("MSFT", "2024-11-29", **query)


def test_as_of_does_not_fabricate_stale_distance_across_unverified_gap() -> None:
    calendar = _calendar()
    across_gap = _repository(calendar, (_bar(calendar, session_date="2024-07-05"),))

    with pytest.raises(BarMissingError):
        across_gap.as_of(
            "AAPL",
            "2024-11-29",
            knowledge_cutoff="2024-11-29T19:00:00Z",
            source="synthetic-bars",
            adjustment_basis=AdjustmentBasis.UNADJUSTED,
            adjustment_version=None,
        )


def test_as_of_reports_multiple_verified_session_transitions_from_latest_prior() -> None:
    calendar = _calendar()
    repository = _repository(
        calendar,
        (
            _bar(calendar, session_date="2024-03-08"),
            _bar(calendar, session_date="2024-07-02"),
        ),
    )

    with pytest.raises(BarStaleError) as stale:
        repository.as_of(
            "AAPL",
            "2024-07-05",
            knowledge_cutoff="2024-07-05T21:00:00Z",
            source="synthetic-bars",
            adjustment_basis=AdjustmentBasis.UNADJUSTED,
            adjustment_version=None,
        )
    assert stale.value.prior_matching_session_count == 2


def test_repository_errors_are_public_typed_failures() -> None:
    assert issubclass(BarMissingError, BarRepositoryError)
    assert issubclass(BarStaleError, BarRepositoryError)
    assert issubclass(BarFutureError, BarRepositoryError)
    assert issubclass(BarQueryError, BarRepositoryError)
    assert issubclass(CalendarCoverageError, CalendarError)
    assert issubclass(CalendarSessionNotFoundError, CalendarError)


@pytest.mark.parametrize(
    "session_date",
    [
        datetime(2024, 11, 27, tzinfo=timezone.utc),
        20241127,
        " 2024-11-27",
        "2024-11-27 ",
        "2024-11-27T00:00:00Z",
        "not-a-date",
    ],
)
def test_as_of_rejects_malformed_non_session_and_out_of_coverage_dates(
    session_date: object,
) -> None:
    calendar = _calendar()
    repository = _repository(calendar, (_bar(calendar),))

    with pytest.raises(BarQueryError):
        repository.as_of(
            "AAPL",
            session_date,  # type: ignore[arg-type]
            knowledge_cutoff="2024-11-27T22:00:00Z",
            source="synthetic-bars",
            adjustment_basis=AdjustmentBasis.UNADJUSTED,
            adjustment_version=None,
        )

    for value in ("2024-11-28", "2024-11-30"):
        with pytest.raises(BarQueryError):
            repository.as_of(
                "AAPL",
                value,
                knowledge_cutoff="2024-11-30T22:00:00Z",
                source="synthetic-bars",
                adjustment_basis=AdjustmentBasis.UNADJUSTED,
                adjustment_version=None,
            )


@pytest.mark.parametrize(
    "cutoff",
    [
        datetime(2024, 11, 27, 22, 0),
        1_732_741_200,
        1_732_741_200.0,
        "2024-11-27",
        "2024-11-27T22:00:00",
        " 2024-11-27T22:00:00Z",
        "not-a-time",
    ],
)
def test_as_of_rejects_naive_numeric_date_only_and_malformed_cutoffs(
    cutoff: object,
) -> None:
    calendar = _calendar()
    repository = _repository(calendar, (_bar(calendar),))

    with pytest.raises(BarQueryError):
        repository.as_of(
            "AAPL",
            "2024-11-27",
            knowledge_cutoff=cutoff,  # type: ignore[arg-type]
            source="synthetic-bars",
            adjustment_basis=AdjustmentBasis.UNADJUSTED,
            adjustment_version=None,
        )


def test_repository_selection_is_network_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("PIT bar selection must not open a socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    monkeypatch.setattr(socket, "create_connection", deny_network)
    calendar = _calendar()
    bar = _bar(calendar)
    repository = _repository(calendar, (bar,))

    assert (
        repository.as_of(
            "AAPL",
            "2024-11-27",
            knowledge_cutoff="2024-11-27T22:00:00Z",
            source="synthetic-bars",
            adjustment_basis=AdjustmentBasis.UNADJUSTED,
            adjustment_version=None,
        )
        == bar
    )
