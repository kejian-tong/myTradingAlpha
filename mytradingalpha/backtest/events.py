"""Canonical scalar event records owned by BT-01."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

_EVENT_DOMAIN = b"mytradingalpha:bt01:event:v1\0"
_MAX_EVENT_BYTES = 8192
_MAX_SEQUENCE = (1 << 63) - 1
_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.:-]{0,126}[A-Za-z0-9])?\Z", re.ASCII)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_EVENT_ID = re.compile(r"bt01-event:[0-9a-f]{64}\Z", re.ASCII)
_ENVELOPE_ID = re.compile(r"signal-envelope:[0-9a-f]{64}\Z", re.ASCII)

_COMMON_FIELDS = (
    "schema_version",
    "event_id",
    "sequence",
    "run_id",
    "instrument_id",
    "variant_id",
    "calendar_id",
    "session_date",
    "economic_time",
    "observed_at",
    "decision_time",
    "knowledge_cutoff",
    "bundle_id",
    "bundle_hash",
    "envelope_id",
    "source_fingerprint",
    "shadow_only",
    "no_trade",
)
_OPPORTUNITY_FIELDS = (
    "outcome_start",
    "outcome_end",
    "earliest_execution_time",
    "decision_event_id",
)


def _exact_utc(value: object) -> bool:
    if type(value) is not datetime:
        return False
    zone = object.__getattribute__(value, "tzinfo")
    if type(zone) is not timezone:
        return False
    try:
        offset = timezone.utcoffset(zone, value)
    except (TypeError, ValueError, OverflowError):
        return False
    return type(offset) is timedelta and offset == timedelta(0)


def _token(value: object) -> bool:
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _json_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _event_payload(event: BacktestEvent, *, mode: str) -> dict[str, object]:
    event_type = type(event)
    if event_type is DecisionEvent:
        fields = _COMMON_FIELDS
        stage = "decision"
    elif event_type is OpportunityEvent:
        fields = _COMMON_FIELDS + _OPPORTUNITY_FIELDS
        stage = "opportunity"
    else:
        raise ValueError("unsupported BT-01 event type")
    payload: dict[str, object] = {"stage": stage}
    for name in fields:
        value = object.__getattribute__(event, name)
        if mode == "json" and name in (
            "session_date",
            "economic_time",
            "observed_at",
            "decision_time",
            "knowledge_cutoff",
            "outcome_start",
            "outcome_end",
            "earliest_execution_time",
        ):
            value = value.isoformat() if name == "session_date" else _json_time(value)
        payload[name] = value
    return payload


def _validate_event(event: BacktestEvent) -> None:
    event_type = type(event)
    if event_type is not DecisionEvent and event_type is not OpportunityEvent:
        raise ValueError("unsupported BT-01 event type")

    for name in (
        "schema_version",
        "run_id",
        "instrument_id",
        "variant_id",
        "calendar_id",
        "bundle_id",
        "bundle_hash",
        "envelope_id",
    ):
        if not _token(object.__getattribute__(event, name)):
            raise ValueError("invalid BT-01 event token")
    if object.__getattribute__(event, "schema_version") != "v1":
        raise ValueError("invalid BT-01 event schema")
    event_id = object.__getattribute__(event, "event_id")
    if type(event_id) is not str or _EVENT_ID.fullmatch(event_id) is None:
        raise ValueError("invalid BT-01 event ID")
    bundle_hash = object.__getattribute__(event, "bundle_hash")
    if type(bundle_hash) is not str or _DIGEST.fullmatch(bundle_hash) is None:
        raise ValueError("invalid BT-01 bundle hash")
    envelope_id = object.__getattribute__(event, "envelope_id")
    if type(envelope_id) is not str or _ENVELOPE_ID.fullmatch(envelope_id) is None:
        raise ValueError("invalid BT-01 envelope ID")
    sequence = object.__getattribute__(event, "sequence")
    if type(sequence) is not int or not 0 <= sequence <= _MAX_SEQUENCE:
        raise ValueError("invalid BT-01 event sequence")
    session_date = object.__getattribute__(event, "session_date")
    if type(session_date) is not date:
        raise ValueError("invalid BT-01 event date")
    for name in ("economic_time", "observed_at", "decision_time", "knowledge_cutoff"):
        if not _exact_utc(object.__getattribute__(event, name)):
            raise ValueError("invalid BT-01 event timestamp")
    if object.__getattribute__(event, "knowledge_cutoff") > object.__getattribute__(event, "decision_time"):
        raise ValueError("invalid BT-01 cutoff chronology")
    if object.__getattribute__(event, "shadow_only") is not True:
        raise ValueError("BT-01 events must remain shadow-only")
    if type(object.__getattribute__(event, "no_trade")) is not bool:
        raise ValueError("invalid BT-01 no-trade flag")
    fingerprint = object.__getattribute__(event, "source_fingerprint")
    if type(fingerprint) is not str or _DIGEST.fullmatch(fingerprint) is None:
        raise ValueError("invalid BT-01 source fingerprint")

    if event_type is DecisionEvent:
        if (
            object.__getattribute__(event, "economic_time")
            != object.__getattribute__(event, "decision_time")
            or object.__getattribute__(event, "observed_at")
            != object.__getattribute__(event, "decision_time")
        ):
            raise ValueError("invalid BT-01 decision chronology")
    else:
        for name in ("outcome_start", "outcome_end", "earliest_execution_time"):
            if not _exact_utc(object.__getattribute__(event, name)):
                raise ValueError("invalid BT-01 opportunity timestamp")
        decision_event_id = object.__getattribute__(event, "decision_event_id")
        if type(decision_event_id) is not str or _EVENT_ID.fullmatch(decision_event_id) is None:
            raise ValueError("invalid BT-01 decision reference")
        if (
            object.__getattribute__(event, "economic_time")
            != object.__getattribute__(event, "outcome_start")
            or object.__getattribute__(event, "outcome_start")
            >= object.__getattribute__(event, "outcome_end")
            or object.__getattribute__(event, "observed_at")
            != object.__getattribute__(event, "decision_time")
            or object.__getattribute__(event, "decision_time")
            >= object.__getattribute__(event, "outcome_start")
            or object.__getattribute__(event, "earliest_execution_time")
            < object.__getattribute__(event, "outcome_start")
        ):
            raise ValueError("invalid BT-01 opportunity chronology")

    identity_payload = _event_payload(event, mode="json")
    identity_payload.pop("sequence", None)
    identity_payload.pop("event_id", None)
    expected_id = _make_event_id(identity_payload)
    if expected_id != event_id:
        raise ValueError("BT-01 event ID does not bind its payload")
    raw = _canonical_bytes(_event_payload(event, mode="json"))
    if len(raw) > _MAX_EVENT_BYTES:
        raise ValueError("BT-01 event exceeds byte bound")


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")


def _make_event_id(payload: dict[str, object]) -> str:
    return "bt01-event:" + hashlib.sha256(_EVENT_DOMAIN + _canonical_bytes(payload)).hexdigest()


def _json_projection(payload: dict[str, object]) -> dict[str, object]:
    result = dict(payload)
    for name, value in tuple(result.items()):
        if type(value) is datetime:
            result[name] = _json_time(value)
        elif type(value) is date:
            result[name] = value.isoformat()
    return result


class BacktestEvent:
    """Common narrow scalar serialization facade for BT-01 event records."""

    __slots__ = ()

    @property
    def stage(self) -> str:
        if type(self) is DecisionEvent:
            return "decision"
        if type(self) is OpportunityEvent:
            return "opportunity"
        raise ValueError("unsupported BT-01 event type")

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        if type(mode) is not str or (mode != "python" and mode != "json"):
            raise ValueError("BT-01 event mode must be python or json")
        _validate_event(self)
        return _event_payload(self, mode=mode)

    def canonical_bytes(self) -> bytes:
        _validate_event(self)
        return _canonical_bytes(_event_payload(self, mode="json"))


@dataclass(frozen=True, slots=True)
class DecisionEvent(BacktestEvent):
    schema_version: str
    event_id: str
    sequence: int
    run_id: str
    instrument_id: str
    variant_id: str
    calendar_id: str
    session_date: date
    economic_time: datetime
    observed_at: datetime
    decision_time: datetime
    knowledge_cutoff: datetime
    bundle_id: str
    bundle_hash: str
    envelope_id: str
    source_fingerprint: str
    shadow_only: bool
    no_trade: bool

    def __post_init__(self) -> None:
        _validate_event(self)


@dataclass(frozen=True, slots=True)
class OpportunityEvent(BacktestEvent):
    schema_version: str
    event_id: str
    sequence: int
    run_id: str
    instrument_id: str
    variant_id: str
    calendar_id: str
    session_date: date
    economic_time: datetime
    observed_at: datetime
    decision_time: datetime
    knowledge_cutoff: datetime
    bundle_id: str
    bundle_hash: str
    envelope_id: str
    source_fingerprint: str
    shadow_only: bool
    no_trade: bool
    outcome_start: datetime
    outcome_end: datetime
    earliest_execution_time: datetime
    decision_event_id: str

    def __post_init__(self) -> None:
        _validate_event(self)


def _build_decision_event(
    *,
    context: object,
    bundle: object,
    envelope: object,
    session: object,
    source_fingerprint: str,
    sequence: int,
) -> DecisionEvent:
    decision_time = object.__getattribute__(context, "decision_time")
    payload: dict[str, object] = {
        "schema_version": "v1",
        "stage": "decision",
        "run_id": object.__getattribute__(context, "run_id"),
        "instrument_id": object.__getattribute__(object.__getattribute__(envelope, "quant"), "instrument_id"),
        "variant_id": object.__getattribute__(context, "variant_id"),
        "calendar_id": object.__getattribute__(object.__getattribute__(bundle, "calendar"), "calendar_id"),
        "session_date": object.__getattribute__(session, "session_date"),
        "economic_time": decision_time,
        "observed_at": decision_time,
        "decision_time": decision_time,
        "knowledge_cutoff": object.__getattribute__(context, "knowledge_cutoff"),
        "bundle_id": object.__getattribute__(bundle, "bundle_id"),
        "bundle_hash": object.__getattribute__(bundle, "bundle_hash"),
        "envelope_id": object.__getattribute__(envelope, "envelope_id"),
        "source_fingerprint": source_fingerprint,
        "shadow_only": True,
        "no_trade": object.__getattribute__(envelope, "no_trade"),
    }
    identity_payload = _json_projection(payload)
    event_id = _make_event_id(identity_payload)
    if len(_canonical_bytes(identity_payload)) > _MAX_EVENT_BYTES:
        raise ValueError("BT-01 event exceeds byte bound")
    payload.pop("stage")
    payload["event_id"] = event_id
    payload["sequence"] = sequence
    return DecisionEvent(**payload)  # type: ignore[arg-type]


def _build_opportunity_event(
    *,
    context: object,
    bundle: object,
    envelope: object,
    next_session: object,
    source_fingerprint: str,
    decision_event_id: str,
    sequence: int,
) -> OpportunityEvent:
    decision_time = object.__getattribute__(context, "decision_time")
    open_at = object.__getattribute__(next_session, "open_at")
    close_at = object.__getattribute__(next_session, "close_at")
    payload: dict[str, object] = {
        "schema_version": "v1",
        "stage": "opportunity",
        "run_id": object.__getattribute__(context, "run_id"),
        "instrument_id": object.__getattribute__(object.__getattribute__(envelope, "quant"), "instrument_id"),
        "variant_id": object.__getattribute__(context, "variant_id"),
        "calendar_id": object.__getattribute__(object.__getattribute__(bundle, "calendar"), "calendar_id"),
        "session_date": object.__getattribute__(next_session, "session_date"),
        "economic_time": open_at,
        "observed_at": decision_time,
        "decision_time": decision_time,
        "knowledge_cutoff": object.__getattribute__(context, "knowledge_cutoff"),
        "bundle_id": object.__getattribute__(bundle, "bundle_id"),
        "bundle_hash": object.__getattribute__(bundle, "bundle_hash"),
        "envelope_id": object.__getattribute__(envelope, "envelope_id"),
        "source_fingerprint": source_fingerprint,
        "shadow_only": True,
        "no_trade": object.__getattribute__(envelope, "no_trade"),
        "outcome_start": open_at,
        "outcome_end": close_at,
        "earliest_execution_time": object.__getattribute__(context, "earliest_execution_time"),
        "decision_event_id": decision_event_id,
    }
    identity_payload = _json_projection(payload)
    event_id = _make_event_id(identity_payload)
    if len(_canonical_bytes(identity_payload)) > _MAX_EVENT_BYTES:
        raise ValueError("BT-01 event exceeds byte bound")
    payload.pop("stage")
    payload["event_id"] = event_id
    payload["sequence"] = sequence
    return OpportunityEvent(**payload)  # type: ignore[arg-type]


__all__ = ["BacktestEvent", "DecisionEvent", "OpportunityEvent"]
