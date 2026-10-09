"""Pure bounded BT-02 fill simulation from precommitted intents and sealed outcomes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import islice
from typing import Literal

from mytradingalpha.contracts.orders import (
    Fill,
    OrderInputError,
    OrderIntent,
    _canonical_json,
    _contract_storage_fingerprint,
    _decimal,
    _decimal_wire,
    _fee_due,
    _fixed_context,
    _raw_payload,
    _safe_date,
    _safe_id_token,
    _safe_string,
    _safe_utc,
    build_fill,
    revalidate_fill,
    revalidate_order_intent,
)
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, DailyBar
from mytradingalpha.data.bundle import BundleReplayPolicy
from mytradingalpha.data.calendar import TradingSession
from mytradingalpha.data.provenance import SourceManifest

from .clock import (
    BacktestInputError,
    SessionBinding,
    _canonical_json as _clock_canonical_json,
    _capture_root,
    _CaptureBudget,
    _refresh_binding,
    _storage_bytes,
)
from .costs import CostModel, CostPolicy, revalidate_cost_policy
from .events import DecisionEvent
from .orders import OrderBook, SimOrder
from .runner import BacktestRunner

_OUTCOME_DOMAIN = b"mytradingalpha:bt02:outcome:v1\0"
_MAX_BINDINGS = 256
_MAX_INTENTS = 256
_MAX_OUTCOMES = 4096
_MAX_SESSIONS = 256
_MAX_ATTEMPTS = 65_536
_MAX_SOURCE_BYTES = 16 * 1024 * 1024
_MAX_CAPTURED_RECORD = 16_384
_MAX_TEXT = 128
_MAX_PRICE = Decimal("1000000000")
_MAX_EXECUTION_PRICE = Decimal("2000000000")
_MAX_QUANTITY = Decimal("1000000000")
_MAX_HOLDINGS = Decimal("1000000000000")
_MAX_MONEY = Decimal("1E24")

_ENUM_MEMBERS: tuple[tuple[type[object], tuple[tuple[str, str, object], ...]], ...] = (
    (
        AdjustmentBasis,
        (
            ("UNADJUSTED", "unadjusted", AdjustmentBasis.UNADJUSTED),
            ("PROVIDER_ADJUSTED", "provider_adjusted", AdjustmentBasis.PROVIDER_ADJUSTED),
        ),
    ),
    (
        BarFinality,
        (
            ("PRELIMINARY", "preliminary", BarFinality.PRELIMINARY),
            ("FINAL", "final", BarFinality.FINAL),
        ),
    ),
    (
        BundleReplayPolicy,
        (
            ("AVAILABILITY", "availability", BundleReplayPolicy.AVAILABILITY),
            ("ARCHIVE_REALISTIC", "archive_realistic", BundleReplayPolicy.ARCHIVE_REALISTIC),
        ),
    ),
)
_ZERO = Decimal("0")


def _reject(reason: str = "input_invalid") -> None:
    raise OrderInputError(reason) from None


def _enum_literal(value: object, enum_type: type[object], reason: str) -> str:
    if type(value) is not enum_type:
        _reject(reason)
    for name, literal, member in next(
        known for known in _ENUM_MEMBERS if known[0] is enum_type
    )[1]:
        if value is member:
            try:
                actual_name = object.__getattribute__(value, "_name_")
                actual_value = object.__getattribute__(value, "_value_")
            except Exception:
                _reject(reason)
            if type(actual_name) is str and type(actual_value) is str and actual_name == name and actual_value == literal:
                return literal
    _reject(reason)
    raise AssertionError("unreachable")


def _decimal_value(value: object, *, kind: str, positive: bool = False) -> Decimal:
    if kind == "quantity":
        return _decimal(
            value, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=_MAX_QUANTITY, positive=positive, nonnegative=not positive,
        )
    if kind == "price":
        return _decimal(
            value, low_exp=-6, high_exp=9, max_adjusted=9,
            maximum=_MAX_PRICE, positive=positive, nonnegative=not positive,
        )
    if kind == "execution_price":
        return _decimal(
            value, low_exp=-16, high_exp=10, max_adjusted=9,
            maximum=_MAX_EXECUTION_PRICE, positive=positive, nonnegative=not positive,
        )
    if kind == "holding":
        return _decimal(
            value, low_exp=-6, high_exp=12, max_adjusted=12,
            maximum=_MAX_HOLDINGS, nonnegative=True,
        )
    if kind == "money":
        return _decimal(
            value, low_exp=-24, high_exp=24, max_adjusted=24,
            maximum=_MAX_MONEY, nonnegative=True,
        )
    _reject("numeric_invalid")
    raise AssertionError("unreachable")


def _canonical_time(value: datetime) -> str:
    return value.isoformat(timespec="auto").replace("+00:00", "Z")


def _fraction(value: Decimal) -> Fraction:
    sign, digits, exponent = value.as_tuple()
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    if exponent >= 0:
        result = Fraction(coefficient * (10**exponent), 1)
    else:
        result = Fraction(coefficient, 10 ** (-exponent))
    return -result if sign else result


def _floor_lots(value: Decimal, lot: Decimal) -> int:
    ratio = _fraction(value) / _fraction(lot)
    return ratio.numerator // ratio.denominator


def _quantity_for_lots(count: int, lot: Decimal) -> Decimal:
    with localcontext(_fixed_context()):
        quantity = Decimal(count) * lot
    return _decimal_value(quantity, kind="quantity", positive=count > 0)


def _money_after_fill(
    cash: Decimal, fill: Fill, *, side: str
) -> Decimal:
    with localcontext(_fixed_context()):
        if side == "buy":
            value = cash - fill.quantity * fill.price - fill.fee
        else:
            value = cash + fill.quantity * fill.price - fill.fee
    try:
        return _decimal_value(value, kind="money")
    except OrderInputError:
        _reject("numeric_invalid")


def _bar_fields(value: object, model_type: type[object], reason: str) -> dict[str, object]:
    if type(value) is not model_type:
        _reject(reason)
    try:
        storage = object.__getattribute__(value, "__dict__")
        extra = object.__getattribute__(value, "__pydantic_extra__")
        private = object.__getattribute__(value, "__pydantic_private__")
        fields_set = object.__getattribute__(value, "__pydantic_fields_set__")
    except Exception:
        _reject(reason)
    fields = tuple(model_type.model_fields)
    if (
        type(storage) is not dict
        or extra is not None
        or private is not None
        or type(fields_set) is not set
        or set.__len__(fields_set) > 64
        or dict.__len__(storage) != len(fields)
    ):
        _reject("resource_limit" if type(fields_set) is set and set.__len__(fields_set) > 64 else reason)
    keys = tuple(islice(dict.keys(storage), 65))
    metadata = tuple(islice(set.__iter__(fields_set), 65))
    if len(keys) > len(fields) or len(metadata) > 64:
        _reject("resource_limit")
    if any(type(key) is not str for key in keys):
        _reject(reason)
    if any(not any(key == field for field in fields) for key in keys):
        _reject(reason)
    if any(type(item) is not str for item in metadata) or set(metadata) != set(fields):
        _reject(reason)
    metadata = tuple(set.__iter__(fields_set))
    if any(type(item) is not str for item in metadata) or set(metadata) != set(fields):
        _reject(reason)
    return {name: dict.__getitem__(storage, name) for name in fields}


def _manifest_snapshot(value: object) -> SourceManifest:
    p = _bar_fields(value, SourceManifest, "outcome_invalid")
    for name in ("schema_version", "manifest_id", "source", "checksum"):
        _safe_string(p[name], max_bytes=_MAX_TEXT)
    for name in ("schema_version", "manifest_id", "source"):
        _safe_id_token(p[name])
    for name in ("source_locator", "terms"):
        _safe_string(p[name], max_bytes=_MAX_TEXT)
    if p["event_time"] is not None:
        _safe_utc(p["event_time"])
    if p["published_at"] is not None:
        _safe_utc(p["published_at"])
    _safe_utc(p["fetched_at"])
    _safe_utc(p["available_at"])
    _safe_utc(p["ingested_at"])
    revision = p["revision"]
    if type(revision) is not int or not 0 <= revision <= 2**31 - 1:
        _reject("outcome_invalid")
    try:
        return SourceManifest.model_validate(p)
    except Exception:
        _reject("outcome_invalid")


def _bar_snapshot(value: object) -> DailyBar:
    p = _bar_fields(value, DailyBar, "outcome_invalid")
    for name in ("schema_version", "bar_id", "instrument_id", "calendar_id", "interval"):
        _safe_string(p[name], max_bytes=_MAX_TEXT)
        _safe_id_token(p[name])
    if p["adjustment_version"] is not None:
        _safe_string(p["adjustment_version"], max_bytes=_MAX_TEXT)
        _safe_id_token(p["adjustment_version"])
    for name in ("open", "high", "low", "close"):
        _decimal_value(p[name], kind="price", positive=True)
    _safe_date(p["session_date"])
    if type(p["volume"]) is not int or p["volume"] < 0 or p["volume"].bit_length() > 256:
        _reject("outcome_invalid")
    _enum_literal(p["adjustment_basis"], AdjustmentBasis, "outcome_invalid")
    _enum_literal(p["finality"], BarFinality, "outcome_invalid")
    p["manifest"] = _manifest_snapshot(p["manifest"])
    try:
        return DailyBar.model_validate(p)
    except Exception:
        _reject("outcome_invalid")


def _manifest_wire(manifest: SourceManifest) -> dict[str, object]:
    result: dict[str, object] = {}
    for name in SourceManifest.model_fields:
        value = object.__getattribute__(manifest, name)
        if type(value) is datetime:
            result[name] = _canonical_time(value)
        elif value is None:
            result[name] = None
        elif type(value) is int:
            result[name] = value
        else:
            result[name] = value
    return result


def _bar_wire(bar: DailyBar) -> dict[str, object]:
    p: dict[str, object] = {}
    for name in DailyBar.model_fields:
        value = object.__getattribute__(bar, name)
        if type(value) is Decimal:
            p[name] = _decimal_wire(value)
        elif type(value) is date:
            p[name] = value.isoformat()
        elif type(value) is AdjustmentBasis:
            p[name] = _enum_literal(value, AdjustmentBasis, "outcome_invalid")
        elif type(value) is BarFinality:
            p[name] = _enum_literal(value, BarFinality, "outcome_invalid")
        elif type(value) is SourceManifest:
            p[name] = _manifest_wire(value)
        else:
            p[name] = value
    return p


def _outcome_wire(
    bar: DailyBar,
    outcome_cutoff: datetime,
    archive_cutoff: datetime,
    replay_policy: BundleReplayPolicy,
) -> dict[str, object]:
    return {
        "archive_cutoff": _canonical_time(archive_cutoff),
        "bar": _bar_wire(bar),
        "outcome_cutoff": _canonical_time(outcome_cutoff),
        "replay_policy": _enum_literal(replay_policy, BundleReplayPolicy, "outcome_invalid"),
        "schema_version": "v1",
    }


class OutcomeEvidence:
    """Owned sealed snapshot of one exact existing DailyBar source record."""

    __slots__ = (
        "_bar_snapshot", "_outcome_cutoff", "_archive_cutoff", "_replay_policy",
        "_sealed_bytes", "_sealed_storage", "_outcome_hash",
    )

    def __init__(
        self,
        bar: DailyBar,
        *,
        outcome_cutoff: datetime,
        archive_cutoff: datetime,
        replay_policy: BundleReplayPolicy,
    ) -> None:
        if type(bar) is not DailyBar:
            _reject("outcome_invalid")
        outcome_time = _safe_utc(outcome_cutoff)
        archive_time = _safe_utc(archive_cutoff)
        _enum_literal(replay_policy, BundleReplayPolicy, "outcome_invalid")
        owned_bar = _bar_snapshot(bar)
        manifest = owned_bar.manifest
        if manifest.available_at > outcome_time:
            _reject("outcome_invalid")
        if replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC and manifest.ingested_at > archive_time:
            _reject("outcome_invalid")
        payload = _outcome_wire(owned_bar, outcome_time, archive_time, replay_policy)
        sealed = _canonical_json(payload)
        if len(sealed) > _MAX_CAPTURED_RECORD:
            _reject("resource_limit")
        storage_seal = _storage_bytes(_capture_root(owned_bar, _CaptureBudget()))
        digest = "sha256:" + hashlib.sha256(_OUTCOME_DOMAIN + sealed).hexdigest()
        object.__setattr__(self, "_bar_snapshot", owned_bar)
        object.__setattr__(self, "_outcome_cutoff", outcome_time)
        object.__setattr__(self, "_archive_cutoff", archive_time)
        object.__setattr__(self, "_replay_policy", replay_policy)
        object.__setattr__(self, "_sealed_bytes", sealed)
        object.__setattr__(self, "_sealed_storage", storage_seal)
        object.__setattr__(self, "_outcome_hash", digest)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("OutcomeEvidence is immutable")

    def __repr__(self) -> str:
        return "OutcomeEvidence(<sealed>)"

    @property
    def bar(self) -> DailyBar:
        owned = _refresh_outcome(self)
        return _bar_snapshot(owned[0])

    @property
    def outcome_cutoff(self) -> datetime:
        return _refresh_outcome(self)[1]

    @property
    def archive_cutoff(self) -> datetime:
        return _refresh_outcome(self)[2]

    @property
    def replay_policy(self) -> BundleReplayPolicy:
        return _refresh_outcome(self)[3]

    @property
    def outcome_hash(self) -> str:
        return _refresh_outcome(self)[5]

    def canonical_bytes(self) -> bytes:
        return _refresh_outcome(self)[4]


def _refresh_outcome(
    value: object,
) -> tuple[DailyBar, datetime, datetime, BundleReplayPolicy, bytes, str, bytes]:
    if type(value) is not OutcomeEvidence:
        _reject("outcome_invalid")
    try:
        bar = object.__getattribute__(value, "_bar_snapshot")
        outcome_time = object.__getattribute__(value, "_outcome_cutoff")
        archive_time = object.__getattribute__(value, "_archive_cutoff")
        replay_policy = object.__getattribute__(value, "_replay_policy")
        sealed = object.__getattribute__(value, "_sealed_bytes")
        sealed_storage = object.__getattribute__(value, "_sealed_storage")
        old_hash = object.__getattribute__(value, "_outcome_hash")
        outcome_time = _safe_utc(outcome_time)
        archive_time = _safe_utc(archive_time)
        _enum_literal(replay_policy, BundleReplayPolicy, "source_changed")
        if type(sealed) is not bytes or type(sealed_storage) is not bytes:
            _reject("source_changed")
        owned_bar = _bar_snapshot(bar)
        manifest = owned_bar.manifest
        if manifest.available_at > outcome_time:
            _reject("source_changed")
        if replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC and manifest.ingested_at > archive_time:
            _reject("source_changed")
        current = _canonical_json(_outcome_wire(owned_bar, outcome_time, archive_time, replay_policy))
        current_storage = _storage_bytes(_capture_root(owned_bar, _CaptureBudget()))
        digest = "sha256:" + hashlib.sha256(_OUTCOME_DOMAIN + current).hexdigest()
        if current != sealed or current_storage != sealed_storage or digest != old_hash:
            _reject("source_changed")
        return owned_bar, outcome_time, archive_time, replay_policy, current, digest, current_storage
    except OrderInputError:
        raise
    except Exception:
        _reject("source_changed")


@dataclass(frozen=True, slots=True)
class FillDecision:
    status: str
    fill: Fill | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    fills: tuple[Fill, ...]
    orders: tuple[SimOrder, ...]
    cash: Decimal
    holdings: tuple[tuple[str, Decimal], ...]
    accounting_basis: Literal["retrospective_simulation"] = "retrospective_simulation"


@dataclass(frozen=True, slots=True)
class _BindingData:
    binding: SessionBinding
    context: object
    bundle: object
    envelope: object
    session: TradingSession
    next_session: TradingSession
    source_bytes: bytes
    source_fingerprint: str
    decision_event_id: str
    instrument_id: str
    calendar: object
    calendar_fingerprint: tuple[bytes, bytes]


@dataclass(slots=True)
class _LocalOrder:
    intent: OrderIntent
    binding: _BindingData
    remaining: Decimal
    cumulative: Decimal = Decimal("0")
    cumulative_fee: Decimal = Decimal("0")
    status: str = "open_at_horizon"
    reason: str | None = None


def _binding_data(binding: object) -> tuple[_BindingData, tuple[object, ...]]:
    if type(binding) is not SessionBinding:
        _reject("input_invalid")
    try:
        prepared = _refresh_binding(binding, _CaptureBudget())
    except BacktestInputError as error:
        reason = "resource_limit" if getattr(error, "reason_code", "") == "resource_limit" else "binding_mismatch"
        _reject(reason)
    context, bundle, envelope, session, next_session, source_json, fingerprint, _ = prepared
    try:
        events = BacktestRunner().run((binding,))
        decision = next(event for event in events if type(event) is DecisionEvent)
        event_id = object.__getattribute__(decision, "event_id")
        quant = object.__getattribute__(envelope, "quant")
        instrument_id = object.__getattribute__(quant, "instrument_id")
        calendar = object.__getattribute__(bundle, "calendar")
        calendar_fingerprint = (
            _clock_canonical_json(calendar.model_dump(mode="json")),
            _storage_bytes(_capture_root(calendar, _CaptureBudget())),
        )
    except Exception:
        _reject("binding_mismatch")
    return (
        _BindingData(
            binding=binding,
            context=context,
            bundle=bundle,
            envelope=envelope,
            session=session,
            next_session=next_session,
            source_bytes=source_json,
            source_fingerprint=fingerprint,
            decision_event_id=event_id,
            instrument_id=instrument_id,
            calendar=calendar,
            calendar_fingerprint=calendar_fingerprint,
        ),
        prepared,
    )


def _refresh_binding_data(data: _BindingData, ingress: tuple[object, ...]) -> None:
    try:
        completion = _refresh_binding(data.binding, _CaptureBudget())
    except BacktestInputError:
        _reject("source_changed")
    if completion[5:] != ingress[5:]:
        _reject("source_changed")


def _capture_completion(
    *,
    data: _BindingData,
    binding_ingress: tuple[object, ...],
    intent: object,
    intent_bytes: bytes,
    intent_storage: tuple[object, ...],
    outcome: object,
    outcome_seals: tuple[bytes, bytes],
    policy: object,
    policy_bytes: bytes,
    policy_storage: tuple[object, ...],
    fill: object | None = None,
    fill_bytes: bytes | None = None,
    fill_storage: tuple[object, ...] | None = None,
) -> None:
    _refresh_binding_data(data, binding_ingress)
    try:
        current_intent = revalidate_order_intent(intent)
    except OrderInputError as error:
        if error.reason_code == "resource_limit":
            raise
        _reject("source_changed")
    if (
        current_intent.canonical_bytes() != intent_bytes
        or _contract_storage_fingerprint(intent, OrderIntent, reason="source_changed") != intent_storage
    ):
        _reject("source_changed")
    try:
        current_outcome = _refresh_outcome(outcome)
    except OrderInputError as error:
        if error.reason_code == "resource_limit":
            raise
        _reject("source_changed")
    if (current_outcome[4], current_outcome[6]) != outcome_seals:
        _reject("source_changed")
    try:
        current_policy = revalidate_cost_policy(policy)
    except OrderInputError as error:
        if error.reason_code == "resource_limit":
            raise
        _reject("source_changed")
    if (
        current_policy.canonical_bytes() != policy_bytes
        or _contract_storage_fingerprint(policy, CostPolicy, reason="source_changed") != policy_storage
    ):
        _reject("source_changed")
    if fill is not None:
        try:
            current_fill = revalidate_fill(fill)
        except OrderInputError:
            _reject("source_changed")
        if (
            fill_bytes is None
            or fill_storage is None
            or current_fill.canonical_bytes() != fill_bytes
            or _contract_storage_fingerprint(fill, Fill, reason="source_changed") != fill_storage
        ):
            _reject("source_changed")


def _binding_for_intent(intent: OrderIntent, bindings: dict[str, _BindingData]) -> _BindingData:
    data = bindings.get(intent.decision_event_id)
    if data is None:
        _reject("binding_mismatch")
    context = data.context
    envelope = data.envelope
    bundle = data.bundle
    if (
        intent.run_id != object.__getattribute__(context, "run_id")
        or intent.instrument_id != data.instrument_id
        or intent.calendar_id != object.__getattribute__(object.__getattribute__(bundle, "calendar"), "calendar_id")
        or intent.variant_id != object.__getattribute__(context, "variant_id")
        or intent.decision_event_id != data.decision_event_id
        or intent.envelope_id != object.__getattribute__(envelope, "envelope_id")
        or intent.source_fingerprint != data.source_fingerprint
        or intent.currency != object.__getattribute__(context, "base_currency")
    ):
        _reject("binding_mismatch")
    if object.__getattribute__(envelope, "no_trade"):
        _reject("intent_invalid")
    if intent.first_session_date != object.__getattribute__(data.next_session, "session_date"):
        _reject("binding_mismatch")
    if (
        intent.decision_time != object.__getattribute__(context, "decision_time")
        or intent.created_at < intent.decision_time
        or intent.created_at >= object.__getattribute__(data.next_session, "open_at")
        or intent.earliest_submit_time < object.__getattribute__(context, "earliest_execution_time")
    ):
        _reject("intent_invalid")
    return data


def _session_for(data: _BindingData, session_date: object) -> TradingSession:
    try:
        requested = _safe_date(session_date)
        session = data.calendar.session(requested)
        if type(session) is not TradingSession:
            _reject("session_unavailable")
        if requested < object.__getattribute__(data.next_session, "session_date"):
            _reject("session_unavailable")
        # Prove an uninterrupted sequence through the injected calendar; no
        # weekday inference or host timezone database is consulted.
        if requested != object.__getattribute__(data.next_session, "session_date"):
            try:
                data.calendar.sessions(
                    object.__getattribute__(data.next_session, "session_date"), requested
                )
            except Exception:
                _reject("session_unavailable")
        return session
    except OrderInputError:
        raise
    except Exception:
        _reject("session_unavailable")


def _check_intent_session(intent: OrderIntent, session: TradingSession) -> None:
    if (
        intent.time_in_force != "gtc"
        and object.__getattribute__(session, "session_date") != intent.first_session_date
    ):
        _reject("outcome_invalid")


def _validate_outcome_context(
    outcome: OutcomeEvidence,
    data: _BindingData,
    session_date: date,
    *,
    intent: OrderIntent | None = None,
) -> tuple[DailyBar, datetime]:
    bar, outcome_cutoff, archive_cutoff, replay_policy, _, outcome_hash, _ = _refresh_outcome(outcome)
    session = _session_for(data, session_date)
    manifest = object.__getattribute__(bar, "manifest")
    calendar_id = object.__getattribute__(object.__getattribute__(data.bundle, "calendar"), "calendar_id")
    if (
        object.__getattribute__(bar, "instrument_id") != data.instrument_id
        or object.__getattribute__(bar, "calendar_id") != calendar_id
        or object.__getattribute__(bar, "session_date") != session_date
        or object.__getattribute__(bar, "finality") is not BarFinality.FINAL
        or object.__getattribute__(bar, "adjustment_basis") is not AdjustmentBasis.UNADJUSTED
        or object.__getattribute__(manifest, "event_time") != object.__getattribute__(session, "close_at")
        or object.__getattribute__(manifest, "available_at") <= object.__getattribute__(session, "close_at")
        or object.__getattribute__(manifest, "available_at") > outcome_cutoff
        or replay_policy is not object.__getattribute__(data.bundle, "replay_policy")
    ):
        _reject("outcome_invalid")
    if replay_policy is BundleReplayPolicy.ARCHIVE_REALISTIC:
        if object.__getattribute__(manifest, "ingested_at") > archive_cutoff:
            _reject("outcome_invalid")
        received = max(
            object.__getattribute__(manifest, "available_at"),
            object.__getattribute__(manifest, "ingested_at"),
        )
    else:
        received = object.__getattribute__(manifest, "available_at")
    if intent is not None and (
        object.__getattribute__(manifest, "source") != intent.outcome_source
        or object.__getattribute__(manifest, "revision") != intent.outcome_revision
    ):
        _reject("outcome_invalid")
    if type(outcome_hash) is not str or len(outcome_hash) != 71:
        _reject("outcome_invalid")
    return bar, received


def _validate_simulation_inputs(
    intent: object,
    outcome: object,
    policy: object,
    binding: object,
    session_date: object,
    remaining_quantity: object,
    cumulative_quantity: object,
    cash_available: object,
    shares_available: object,
    cap_remaining: object,
) -> tuple[OrderIntent, OutcomeEvidence, CostPolicy, _BindingData, TradingSession, Decimal, Decimal, Decimal, Decimal, Decimal]:
    if type(binding) is not SessionBinding:
        _reject("input_invalid")
    try:
        data, _ = _binding_data(binding)
    except OrderInputError:
        raise
    intent_copy = revalidate_order_intent(intent)
    if type(outcome) is not OutcomeEvidence:
        _reject("outcome_invalid")
    _refresh_outcome(outcome)
    policy_copy = revalidate_cost_policy(policy)
    if policy_copy.currency != "USD":
        _reject("policy_invalid")
    remaining = _decimal_value(remaining_quantity, kind="quantity", positive=True)
    cumulative = _decimal_value(cumulative_quantity, kind="quantity")
    cash = _decimal_value(cash_available, kind="money")
    shares = _decimal_value(shares_available, kind="holding")
    cap = _decimal_value(cap_remaining, kind="quantity")
    with localcontext(_fixed_context()):
        requested_total = remaining + cumulative
    if requested_total != intent_copy.quantity or cumulative > intent_copy.quantity:
        _reject("intent_invalid")
    data = _binding_for_intent(intent_copy, {data.decision_event_id: data})
    session = _session_for(data, session_date)
    _check_intent_session(intent_copy, session)
    _validate_outcome_context(outcome, data, _safe_date(session_date), intent=intent_copy)
    return intent_copy, outcome, policy_copy, data, session, remaining, cumulative, cash, shares, cap


def _cash_feasible(cash: Decimal, quote: object, quantity: Decimal, side: str) -> bool:
    with localcontext(_fixed_context()):
        if side == "buy":
            after = cash - quantity * quote.price - quote.fee
        else:
            after = cash + quantity * quote.price - quote.fee
    return after >= _ZERO


def _lot_bounds(
    remaining: Decimal,
    shares: Decimal,
    cap: Decimal,
    side: str,
    lot: Decimal,
) -> int:
    available = min(remaining, cap)
    if side == "sell":
        available = min(available, shares)
    return _floor_lots(available, lot)


def _build_fill_for_attempt(
    intent: OrderIntent,
    outcome: OutcomeEvidence,
    policy: CostPolicy,
    data: _BindingData,
    session: TradingSession,
    quantity: Decimal,
    cumulative: Decimal,
    quote: object,
    received_at: datetime,
) -> Fill:
    bar, _ = _validate_outcome_context(
        outcome, data, object.__getattribute__(session, "session_date"), intent=intent
    )
    manifest = object.__getattribute__(bar, "manifest")
    fields: dict[str, object] = {
        "schema_version": "v1",
        "intent_id": intent.intent_id,
        "intent_hash": intent.intent_hash,
        "run_id": intent.run_id,
        "instrument_id": intent.instrument_id,
        "calendar_id": intent.calendar_id,
        "variant_id": intent.variant_id,
        "decision_event_id": intent.decision_event_id,
        "envelope_id": intent.envelope_id,
        "source_fingerprint": intent.source_fingerprint,
        "currency": "USD",
        "side": intent.side,
        "quantity": quantity,
        "cumulative_quantity_before": cumulative,
        "cumulative_quantity_after": _add_fixed(cumulative, quantity),
        "price": quote.price,
        "reference_price": object.__getattribute__(bar, "close"),
        "fee": quote.fee,
        "cost_breakdown": quote.cost_breakdown,
        "cost_policy_version": policy.policy_version,
        "cost_policy_hash": policy.policy_hash,
        "fee_policy_id": policy.fee_policy_id,
        "bar_id": object.__getattribute__(bar, "bar_id"),
        "manifest_id": object.__getattribute__(manifest, "manifest_id"),
        "outcome_source": object.__getattribute__(manifest, "source"),
        "outcome_revision": object.__getattribute__(manifest, "revision"),
        "source_checksum": object.__getattribute__(manifest, "checksum"),
        "outcome_hash": outcome.outcome_hash,
        "session_date": object.__getattribute__(session, "session_date"),
        "fill_time": object.__getattribute__(session, "close_at"),
        "received_at": received_at,
        "execution_authority": "simulation_only",
        "liquidity": "simulated",
    }
    return build_fill(**fields)


def _add_fixed(left: Decimal, right: Decimal) -> Decimal:
    with localcontext(_fixed_context()):
        return left + right


def _fill_context_check(
    fill: Fill,
    intent: OrderIntent,
    outcome: OutcomeEvidence,
    policy: CostPolicy,
    data: _BindingData,
    session: TradingSession,
    remaining: Decimal,
    cumulative: Decimal,
) -> Fill:
    fill_copy = revalidate_fill(fill)
    with localcontext(_fixed_context()):
        expected_after = cumulative + fill_copy.quantity
    if (
        fill_copy.intent_id != intent.intent_id
        or fill_copy.intent_hash != intent.intent_hash
        or fill_copy.cumulative_quantity_before != cumulative
        or fill_copy.cumulative_quantity_after != expected_after
        or fill_copy.quantity > remaining
        or fill_copy.cumulative_quantity_after > intent.quantity
        or (intent.time_in_force == "fok" and fill_copy.quantity != remaining)
    ):
        _reject("intent_invalid")
    context = data.context
    envelope = data.envelope
    if (
        fill_copy.run_id != object.__getattribute__(context, "run_id")
        or fill_copy.instrument_id != data.instrument_id
        or fill_copy.calendar_id != intent.calendar_id
        or fill_copy.variant_id != object.__getattribute__(context, "variant_id")
        or fill_copy.decision_event_id != data.decision_event_id
        or fill_copy.envelope_id != object.__getattribute__(envelope, "envelope_id")
        or fill_copy.source_fingerprint != data.source_fingerprint
        or fill_copy.side != intent.side
    ):
        _reject("binding_mismatch")
    if (
        fill_copy.cost_policy_version != policy.policy_version
        or fill_copy.cost_policy_hash != policy.policy_hash
        or fill_copy.fee_policy_id != policy.fee_policy_id
    ):
        _reject("policy_invalid")
    cost = fill_copy.cost_breakdown
    policy_values = _raw_payload(policy, include_id=True)
    if (
        cost.half_spread_bps != policy_values["half_spread_bps"]
        or cost.slippage_bps != policy_values["slippage_bps"]
        or cost.commission_per_share != policy_values["commission_per_share"]
        or cost.order_minimum != policy_values["order_minimum"]
        or cost.impact is not None
        or cost.impact_status != "unavailable"
        or cost.adv is not None
        or cost.adv_status != "unavailable"
        or cost.capacity is not None
        or cost.capacity_status != "unavailable"
    ):
        _reject("policy_invalid")
    with localcontext(_fixed_context()):
        direction = Decimal(1) if fill_copy.side == "buy" else Decimal(-1)
        expected_price = fill_copy.reference_price + direction * fill_copy.reference_price * (
            policy_values["half_spread_bps"] + policy_values["slippage_bps"]
        ) / Decimal(10_000)
        expected_spread = (
            fill_copy.reference_price * policy_values["half_spread_bps"] * fill_copy.quantity
            / Decimal(10_000)
        )
        expected_slippage = (
            fill_copy.reference_price * policy_values["slippage_bps"] * fill_copy.quantity
            / Decimal(10_000)
        )
        expected_fee = _fee_due(
            fill_copy.cumulative_quantity_after,
            policy_values["commission_per_share"],
            policy_values["order_minimum"],
        ) - _fee_due(
            fill_copy.cumulative_quantity_before,
            policy_values["commission_per_share"],
            policy_values["order_minimum"],
        )
    if (
        fill_copy.price != expected_price
        or cost.spread != expected_spread
        or cost.slippage != expected_slippage
        or fill_copy.fee != expected_fee
    ):
        _reject("policy_invalid")
    bar, received = _validate_outcome_context(
        outcome, data, object.__getattribute__(session, "session_date"), intent=intent
    )
    manifest = object.__getattribute__(bar, "manifest")
    if (
        fill_copy.bar_id != object.__getattribute__(bar, "bar_id")
        or fill_copy.manifest_id != object.__getattribute__(manifest, "manifest_id")
        or fill_copy.outcome_source != object.__getattribute__(manifest, "source")
        or fill_copy.outcome_revision != object.__getattribute__(manifest, "revision")
        or fill_copy.source_checksum != object.__getattribute__(manifest, "checksum")
        or fill_copy.outcome_hash != outcome.outcome_hash
        or fill_copy.session_date != object.__getattribute__(session, "session_date")
        or fill_copy.fill_time != object.__getattribute__(session, "close_at")
        or fill_copy.received_at != received
        or fill_copy.reference_price != object.__getattribute__(bar, "close")
    ):
        _reject("outcome_invalid")
    if fill_copy.quantity > policy.fixed_share_cap:
        _reject("policy_invalid")
    if not _marketable(intent, fill_copy.price):
        _reject("intent_invalid")
    with localcontext(_fixed_context()):
        lot_quantity = Decimal(_floor_lots(fill_copy.quantity, policy.lot_size)) * policy.lot_size
    if lot_quantity != fill_copy.quantity:
        _reject("policy_invalid")
    return fill_copy


class FillModel:
    """Pure single-session quote and fill decision for an owned intent."""

    __slots__ = ()

    @staticmethod
    def validate_fill(
        fill: Fill,
        intent: OrderIntent,
        outcome: OutcomeEvidence,
        policy: CostPolicy,
        *,
        binding: SessionBinding,
        session_date: date,
        remaining_quantity: Decimal,
        cumulative_quantity: Decimal,
    ) -> Fill:
        intent_storage = _contract_storage_fingerprint(intent, OrderIntent, reason="intent_invalid")
        intent_copy = revalidate_order_intent(intent)
        if _contract_storage_fingerprint(intent, OrderIntent, reason="source_changed") != intent_storage:
            _reject("source_changed")
        if type(binding) is not SessionBinding:
            _reject("input_invalid")
        data, binding_ingress = _binding_data(binding)
        policy_storage = _contract_storage_fingerprint(policy, CostPolicy, reason="policy_invalid")
        policy_copy = revalidate_cost_policy(policy)
        if _contract_storage_fingerprint(policy, CostPolicy, reason="source_changed") != policy_storage:
            _reject("source_changed")
        outcome_state = _refresh_outcome(outcome)
        fill_storage = _contract_storage_fingerprint(fill, Fill, reason="input_invalid")
        fill_copy = revalidate_fill(fill)
        if _contract_storage_fingerprint(fill, Fill, reason="source_changed") != fill_storage:
            _reject("source_changed")
        intent_bytes = intent_copy.canonical_bytes()
        outcome_seals = (outcome_state[4], outcome_state[6])
        policy_bytes = policy_copy.canonical_bytes()
        fill_bytes = fill_copy.canonical_bytes()
        remaining = _decimal_value(remaining_quantity, kind="quantity", positive=True)
        cumulative = _decimal_value(cumulative_quantity, kind="quantity")
        with localcontext(_fixed_context()):
            requested_total = remaining + cumulative
        if requested_total != intent_copy.quantity:
            _reject("intent_invalid")
        data = _binding_for_intent(intent_copy, {data.decision_event_id: data})
        session = _session_for(data, session_date)
        _check_intent_session(intent_copy, session)
        _validate_outcome_context(outcome, data, session_date, intent=intent_copy)
        checked = _fill_context_check(
            fill_copy, intent_copy, outcome, policy_copy, data, session, remaining, cumulative
        )
        _capture_completion(
            data=data,
            binding_ingress=binding_ingress,
            intent=intent,
            intent_bytes=intent_bytes,
            intent_storage=intent_storage,
            outcome=outcome,
            outcome_seals=outcome_seals,
            policy=policy,
            policy_bytes=policy_bytes,
            policy_storage=policy_storage,
            fill=fill,
            fill_bytes=fill_bytes,
            fill_storage=fill_storage,
        )
        return checked

    @staticmethod
    def simulate(
        intent: OrderIntent,
        outcome: OutcomeEvidence,
        remaining_quantity: Decimal,
        cash_available: Decimal,
        shares_available: Decimal,
        cap_remaining: Decimal,
        policy: CostPolicy,
        *,
        binding: SessionBinding,
        session_date: date,
        cumulative_quantity: Decimal,
    ) -> FillDecision:
        if type(binding) is not SessionBinding:
            _reject("input_invalid")
        intent_storage = _contract_storage_fingerprint(intent, OrderIntent, reason="intent_invalid")
        baseline_intent = revalidate_order_intent(intent)
        if _contract_storage_fingerprint(intent, OrderIntent, reason="source_changed") != intent_storage:
            _reject("source_changed")
        baseline_outcome = _refresh_outcome(outcome)
        policy_storage = _contract_storage_fingerprint(policy, CostPolicy, reason="policy_invalid")
        baseline_policy = revalidate_cost_policy(policy)
        if _contract_storage_fingerprint(policy, CostPolicy, reason="source_changed") != policy_storage:
            _reject("source_changed")
        baseline_data, binding_ingress = _binding_data(binding)
        intent_bytes = baseline_intent.canonical_bytes()
        outcome_seals = (baseline_outcome[4], baseline_outcome[6])
        policy_bytes = baseline_policy.canonical_bytes()

        def finish(decision: FillDecision) -> FillDecision:
            _capture_completion(
                data=baseline_data,
                binding_ingress=binding_ingress,
                intent=intent,
                intent_bytes=intent_bytes,
                intent_storage=intent_storage,
                outcome=outcome,
                outcome_seals=outcome_seals,
                policy=policy,
                policy_bytes=policy_bytes,
                policy_storage=policy_storage,
                fill=decision.fill,
                fill_bytes=(decision.fill.canonical_bytes() if decision.fill is not None else None),
                fill_storage=(
                    _contract_storage_fingerprint(decision.fill, Fill, reason="input_invalid")
                    if decision.fill is not None else None
                ),
            )
            return decision

        validated = _validate_simulation_inputs(
            intent, outcome, policy, binding, session_date, remaining_quantity,
            cumulative_quantity, cash_available, shares_available, cap_remaining,
        )
        intent_copy, outcome_copy, policy_copy, data, session, remaining, cumulative, cash, shares, cap = validated
        close_at = object.__getattribute__(session, "close_at")
        if close_at < intent_copy.earliest_submit_time:
            return finish(FillDecision("no_fill", None, "not_yet_eligible"))
        if close_at > intent_copy.expires_at:
            return finish(FillDecision("no_fill", None, "expired"))
        max_lots = _lot_bounds(remaining, shares, cap, intent_copy.side, policy_copy.lot_size)
        if max_lots <= 0:
            return finish(FillDecision("no_fill", None, "capacity_or_lot"))
        max_quantity = _quantity_for_lots(max_lots, policy_copy.lot_size)
        if intent_copy.time_in_force == "fok":
            with localcontext(_fixed_context()):
                expected_remaining = intent_copy.quantity - cumulative
                lot_remaining = Decimal(
                    _floor_lots(remaining, policy_copy.lot_size)
                ) * policy_copy.lot_size
            if (
                remaining != expected_remaining
                or lot_remaining != remaining
                or max_quantity != remaining
            ):
                return finish(FillDecision("no_fill", None, "fok_unavailable"))
            selected_quantity = remaining
            quote = CostModel.quote(
                object.__getattribute__(outcome_copy.bar, "close"), intent_copy.side,
                selected_quantity, _add_fixed(cumulative, selected_quantity), policy_copy,
            )
            if not _cash_feasible(cash, quote, selected_quantity, intent_copy.side):
                return finish(FillDecision("no_fill", None, "fok_unaffordable"))
        elif intent_copy.side == "buy":
            low = 0
            high = max_lots
            selected_quantity = Decimal("0")
            quote = None
            while low <= high:
                middle = (low + high) // 2
                if middle == 0:
                    low = 1
                    continue
                candidate_quantity = _quantity_for_lots(middle, policy_copy.lot_size)
                candidate_quote = CostModel.quote(
                    object.__getattribute__(outcome_copy.bar, "close"), intent_copy.side,
                    candidate_quantity, _add_fixed(cumulative, candidate_quantity), policy_copy,
                )
                if not _marketable(intent_copy, candidate_quote.price):
                    return finish(FillDecision("no_fill", None, "limit_not_marketable"))
                if _cash_feasible(cash, candidate_quote, candidate_quantity, intent_copy.side):
                    selected_quantity = candidate_quantity
                    quote = candidate_quote
                    low = middle + 1
                else:
                    high = middle - 1
            if selected_quantity <= 0 or quote is None:
                return finish(FillDecision("no_fill", None, "cash_or_lot"))
        else:
            selected_quantity, quote = _select_sale_quantity(
                intent_copy, outcome_copy, policy_copy, remaining, cumulative,
                cash, shares, cap, max_lots,
            )
            if selected_quantity <= 0 or quote is None:
                return finish(FillDecision("no_fill", None, "cash_or_lot"))
            if not _marketable(intent_copy, quote.price):
                return finish(FillDecision("no_fill", None, "limit_not_marketable"))
        if not _marketable(intent_copy, quote.price):
            return finish(FillDecision("no_fill", None, "limit_not_marketable"))
        _, received = _validate_outcome_context(
            outcome_copy, data, object.__getattribute__(session, "session_date"), intent=intent_copy
        )
        fill = _build_fill_for_attempt(
            intent_copy, outcome_copy, policy_copy, data, session,
            selected_quantity, cumulative, quote, received,
        )
        checked = FillModel.validate_fill(
            fill, intent_copy, outcome_copy, policy_copy,
            binding=binding, session_date=object.__getattribute__(session, "session_date"),
            remaining_quantity=remaining, cumulative_quantity=cumulative,
        )
        return finish(FillDecision("filled", checked, None))


def _marketable(intent: OrderIntent, adverse_price: Decimal) -> bool:
    if intent.order_type == "market":
        return True
    if intent.side == "buy":
        return adverse_price <= intent.limit_price
    return adverse_price >= intent.limit_price


def _select_sale_quantity(
    intent: OrderIntent,
    outcome: OutcomeEvidence,
    policy: CostPolicy,
    remaining: Decimal,
    cumulative: Decimal,
    cash: Decimal,
    shares: Decimal,
    cap: Decimal,
    max_lots: int,
) -> tuple[Decimal, object | None]:
    if max_lots <= 0:
        return Decimal("0"), None
    close = outcome.bar.close
    maximum_quantity = _quantity_for_lots(max_lots, policy.lot_size)
    first_quote = CostModel.quote(close, "sell", maximum_quantity, _add_fixed(cumulative, maximum_quantity), policy)
    if _marketable(intent, first_quote.price) and _cash_feasible(cash, first_quote, maximum_quantity, "sell"):
        return maximum_quantity, first_quote
    p = _raw_payload(policy, include_id=True)
    if p["commission_per_share"] <= first_quote.price:
        return Decimal("0"), None
    from mytradingalpha.contracts.orders import _fee_due

    fee_before = _fee_due(cumulative, p["commission_per_share"], p["order_minimum"])
    budget = _fraction(cash) + _fraction(fee_before) - _fraction(p["commission_per_share"]) * _fraction(cumulative)
    excess = _fraction(p["commission_per_share"]) - _fraction(first_quote.price)
    if budget <= 0 or excess <= 0:
        return Decimal("0"), None
    linear_quantity = budget / excess
    lot_ratio = linear_quantity / _fraction(policy.lot_size)
    candidate_lots = min(max_lots, lot_ratio.numerator // lot_ratio.denominator)
    if candidate_lots <= 0:
        return Decimal("0"), None
    candidate = _quantity_for_lots(candidate_lots, policy.lot_size)
    quote = CostModel.quote(close, "sell", candidate, _add_fixed(cumulative, candidate), policy)
    if _marketable(intent, quote.price) and _cash_feasible(cash, quote, candidate, "sell"):
        return candidate, quote
    reserve_budget = budget - Fraction(5, 1000)
    if reserve_budget <= 0:
        return Decimal("0"), None
    reserve_ratio = (reserve_budget / excess) / _fraction(policy.lot_size)
    reserve_lots = min(max_lots, reserve_ratio.numerator // reserve_ratio.denominator)
    if reserve_lots <= 0:
        return Decimal("0"), None
    reserved = _quantity_for_lots(reserve_lots, policy.lot_size)
    reserved_quote = CostModel.quote(close, "sell", reserved, _add_fixed(cumulative, reserved), policy)
    if _marketable(intent, reserved_quote.price) and _cash_feasible(cash, reserved_quote, reserved, "sell"):
        return reserved, reserved_quote
    return Decimal("0"), None


def _validate_initial_holdings(value: object) -> tuple[tuple[str, Decimal], ...]:
    if type(value) is not tuple:
        _reject("input_invalid")
    if len(value) > 256:
        _reject("resource_limit")
    result: list[tuple[str, Decimal]] = []
    prior: str | None = None
    for entry in value:
        if type(entry) is not tuple or len(entry) != 2:
            _reject("input_invalid")
        instrument = _safe_string(entry[0])
        shares = _decimal_value(entry[1], kind="holding")
        if shares < 0 or (prior is not None and instrument <= prior):
            _reject("numeric_invalid")
        result.append((instrument, shares))
        prior = instrument
    return tuple(result)


def _validate_outcome_record(
    value: object,
    bindings: dict[str, _BindingData],
) -> tuple[OutcomeEvidence, bytes, bytes, tuple[str, str, date, str, int]]:
    if type(value) is not OutcomeEvidence:
        _reject("outcome_invalid")
    state = _refresh_outcome(value)
    bar = state[0]
    instrument = object.__getattribute__(bar, "instrument_id")
    data = bindings.get(instrument)
    if data is None:
        _reject("binding_mismatch")
    session_date = object.__getattribute__(bar, "session_date")
    session = _session_for(data, session_date)
    manifest = object.__getattribute__(bar, "manifest")
    if (
        object.__getattribute__(bar, "calendar_id")
        != object.__getattribute__(object.__getattribute__(data.bundle, "calendar"), "calendar_id")
        or object.__getattribute__(manifest, "event_time") != object.__getattribute__(session, "close_at")
        or object.__getattribute__(bar, "finality") is not BarFinality.FINAL
        or object.__getattribute__(bar, "adjustment_basis") is not AdjustmentBasis.UNADJUSTED
        or object.__getattribute__(manifest, "available_at") <= object.__getattribute__(session, "close_at")
        or object.__getattribute__(manifest, "available_at") > state[1]
        or state[3] is not object.__getattribute__(data.bundle, "replay_policy")
    ):
        _reject("outcome_invalid")
    if state[3] is BundleReplayPolicy.ARCHIVE_REALISTIC and object.__getattribute__(manifest, "ingested_at") > state[2]:
        _reject("outcome_invalid")
    key = (
        instrument,
        object.__getattribute__(bar, "calendar_id"),
        session_date,
        object.__getattribute__(manifest, "source"),
        object.__getattribute__(manifest, "revision"),
    )
    return value, state[4], state[6], key


def _build_attempt_sessions(
    order: _LocalOrder,
    end_session: date,
) -> tuple[TradingSession, ...]:
    if order.remaining <= 0:
        return ()
    first_date = object.__getattribute__(order.binding.next_session, "session_date")
    expires = order.intent.expires_at
    if first_date > end_session:
        return ()
    try:
        first = order.binding.calendar.session(first_date)
    except Exception:
        _reject("session_unavailable")
    if object.__getattribute__(first, "close_at") > expires:
        return ()
    if order.intent.time_in_force != "gtc":
        return (first,)
    sessions = [first]
    current = first
    while (
        object.__getattribute__(current, "session_date") < end_session
        and object.__getattribute__(current, "close_at") < expires
    ):
        try:
            following = order.binding.calendar.next_session(
                object.__getattribute__(current, "session_date")
            )
        except Exception:
            _reject("session_unavailable")
        if object.__getattribute__(following, "session_date") > end_session:
            break
        if object.__getattribute__(following, "close_at") > expires:
            break
        sessions.append(following)
        if len(sessions) > _MAX_SESSIONS:
            _reject("resource_limit")
        current = following
    return tuple(sessions)


class Simulator:
    """All-or-nothing pure batch simulator with run-local cash and holdings."""

    __slots__ = ()

    def run(
        self,
        bindings: tuple[SessionBinding, ...],
        intents: tuple[OrderIntent, ...],
        outcomes: tuple[OutcomeEvidence, ...],
        policy: CostPolicy,
        *,
        initial_cash: Decimal,
        initial_holdings: tuple[tuple[str, Decimal], ...],
        end_session: date,
    ) -> SimulationResult:
        if type(bindings) is not tuple or type(intents) is not tuple or type(outcomes) is not tuple:
            _reject("input_invalid")
        if len(bindings) > _MAX_BINDINGS or len(intents) > _MAX_INTENTS or len(outcomes) > _MAX_OUTCOMES:
            _reject("resource_limit")
        if not bindings:
            _reject("binding_mismatch")
        for value, type_ in ((binding, SessionBinding) for binding in bindings):
            if type(value) is not type_:
                _reject("input_invalid")
        for value in intents:
            if type(value) is not OrderIntent:
                _reject("intent_invalid")
        for value in outcomes:
            if type(value) is not OutcomeEvidence:
                _reject("outcome_invalid")
        try:
            BacktestRunner().run(bindings)
        except BacktestInputError as error:
            reason = getattr(error, "reason_code", "")
            _reject("resource_limit" if reason == "resource_limit" else "binding_mismatch")
        policy_storage = _contract_storage_fingerprint(policy, CostPolicy, reason="policy_invalid")
        policy_copy = revalidate_cost_policy(policy)
        if _contract_storage_fingerprint(policy, CostPolicy, reason="source_changed") != policy_storage:
            _reject("source_changed")
        policy_wire = policy_copy.canonical_bytes()
        cash = _decimal_value(initial_cash, kind="money")
        holdings = dict(_validate_initial_holdings(initial_holdings))
        horizon = _safe_date(end_session)
        binding_map: dict[str, _BindingData] = {}
        outcome_bindings: dict[str, _BindingData] = {}
        binding_ingress: list[tuple[_BindingData, tuple[object, ...]]] = []
        source_total = 0
        source_total += len(policy_copy.canonical_bytes())
        source_total += sum(
            len(instrument.encode("utf-8")) + len(_decimal_wire(quantity).encode("utf-8"))
            for instrument, quantity in _validate_initial_holdings(initial_holdings)
        )
        run_id: str | None = None
        calendar_id: str | None = None
        variant_id: str | None = None
        currency: str | None = None
        replay_policy: BundleReplayPolicy | None = None
        calendar_fingerprint: tuple[bytes, bytes] | None = None
        for binding in bindings:
            data, ingress = _binding_data(binding)
            context = data.context
            candidate_run = object.__getattribute__(context, "run_id")
            candidate_calendar = object.__getattribute__(object.__getattribute__(data.bundle, "calendar"), "calendar_id")
            candidate_variant = object.__getattribute__(context, "variant_id")
            candidate_currency = object.__getattribute__(context, "base_currency")
            candidate_replay_policy = object.__getattribute__(data.bundle, "replay_policy")
            if run_id is None:
                run_id, calendar_id, variant_id = candidate_run, candidate_calendar, candidate_variant
                currency = candidate_currency
                replay_policy = candidate_replay_policy
                calendar_fingerprint = data.calendar_fingerprint
            elif (
                (run_id, calendar_id, variant_id, currency, replay_policy)
                != (candidate_run, candidate_calendar, candidate_variant, candidate_currency, candidate_replay_policy)
                or calendar_fingerprint != data.calendar_fingerprint
            ):
                _reject("binding_mismatch")
            if data.decision_event_id in binding_map:
                _reject("binding_mismatch")
            source_total += len(data.source_bytes)
            if source_total > _MAX_SOURCE_BYTES:
                _reject("resource_limit")
            try:
                data.calendar.session(horizon)
            except Exception:
                _reject("session_unavailable")
            binding_map[data.decision_event_id] = data
            outcome_bindings.setdefault(data.instrument_id, data)
            binding_ingress.append((data, ingress))
        if not binding_map and intents:
            _reject("binding_mismatch")
        order_book = OrderBook()
        intent_ingress: dict[str, tuple[bytes, tuple[object, ...]]] = {}
        local_orders: dict[str, _LocalOrder] = {}
        for raw_intent in intents:
            input_storage = _contract_storage_fingerprint(raw_intent, OrderIntent, reason="intent_invalid")
            try:
                owned_intent = revalidate_order_intent(raw_intent)
            except OrderInputError as error:
                if error.reason_code == "resource_limit":
                    raise
                _reject("intent_invalid")
            if _contract_storage_fingerprint(raw_intent, OrderIntent, reason="source_changed") != input_storage:
                _reject("source_changed")
            if owned_intent.intent_id in local_orders:
                _reject("duplicate_intent")
            data = _binding_for_intent(owned_intent, binding_map)
            intent_wire = owned_intent.canonical_bytes()
            intent_storage = input_storage
            intent_ingress[owned_intent.intent_id] = (intent_wire, intent_storage)
            source_total += len(intent_wire)
            if source_total > _MAX_SOURCE_BYTES:
                _reject("resource_limit")
            order = _LocalOrder(
                intent=owned_intent,
                binding=data,
                remaining=owned_intent.quantity,
            )
            local_orders[owned_intent.intent_id] = order
            order_book.add(owned_intent.intent_id, order)
        outcome_ingress: list[tuple[OutcomeEvidence, bytes, bytes]] = []
        outcome_lookup: dict[tuple[str, str, date, str, int], OutcomeEvidence] = {}
        outcome_ids: set[str] = set()
        manifest_ids: set[str] = set()
        for raw_outcome in outcomes:
            outcome, sealed, storage_seal, key = _validate_outcome_record(raw_outcome, outcome_bindings)
            if key in outcome_lookup:
                _reject("duplicate_outcome")
            bar = outcome.bar
            manifest = bar.manifest
            bar_id = object.__getattribute__(bar, "bar_id")
            manifest_id = object.__getattribute__(manifest, "manifest_id")
            if bar_id in outcome_ids or manifest_id in manifest_ids:
                _reject("duplicate_outcome")
            outcome_ids.add(bar_id)
            manifest_ids.add(manifest_id)
            outcome_lookup[key] = outcome
            outcome_ingress.append((outcome, sealed, storage_seal))
            source_total += len(sealed) + len(storage_seal)
            if source_total > _MAX_SOURCE_BYTES:
                _reject("resource_limit")
        attempt_rows: list[tuple[date, str, str, TradingSession]] = []
        for intent_id in sorted(local_orders):
            order = local_orders[intent_id]
            sessions = _build_attempt_sessions(order, horizon)
            for session in sessions:
                attempt_rows.append(
                    (
                        object.__getattribute__(session, "session_date"),
                        order.intent.instrument_id,
                        intent_id,
                        session,
                    )
                )
                if len(attempt_rows) > _MAX_ATTEMPTS:
                    _reject("resource_limit")
        attempt_rows.sort(key=lambda row: (row[0], row[1], row[2]))
        attempt_closes: dict[str, datetime] = {}
        for _, _, intent_id, session in attempt_rows:
            attempt_closes[intent_id] = object.__getattribute__(session, "close_at")
        cap_remaining: dict[tuple[str, date], Decimal] = {}
        fills: list[Fill] = []
        simulator = FillModel()
        terminal_attempts: set[str] = set()
        for session_date, instrument_id, intent_id, session in attempt_rows:
            order = local_orders[intent_id]
            if order.status == "filled" or order.status in ("cancelled", "expired"):
                continue
            if intent_id in terminal_attempts:
                continue
            close_at = object.__getattribute__(session, "close_at")
            if close_at < order.intent.earliest_submit_time:
                order.reason = "not_yet_eligible"
                if order.intent.time_in_force != "gtc":
                    order.status = "expired"
                    terminal_attempts.add(intent_id)
                continue
            slot = (instrument_id, session_date)
            cap = cap_remaining.get(slot, policy_copy.fixed_share_cap)
            selector = (
                instrument_id,
                order.intent.calendar_id,
                session_date,
                order.intent.outcome_source,
                order.intent.outcome_revision,
            )
            outcome = outcome_lookup.get(selector)
            if outcome is None:
                conflicting = any(
                    key[0] == instrument_id and key[1] == order.intent.calendar_id and key[2] == session_date
                    for key in outcome_lookup
                )
                _reject("outcome_invalid" if conflicting else "outcome_unavailable")
            available = holdings.get(instrument_id, _ZERO)
            decision = simulator.simulate(
                order.intent,
                outcome,
                order.remaining,
                cash,
                available,
                cap,
                policy_copy,
                binding=order.binding.binding,
                session_date=session_date,
                cumulative_quantity=order.cumulative,
            )
            if decision.status == "filled" and decision.fill is not None:
                checked = simulator.validate_fill(
                    decision.fill,
                    order.intent,
                    outcome,
                    policy_copy,
                    binding=order.binding.binding,
                    session_date=session_date,
                    remaining_quantity=order.remaining,
                    cumulative_quantity=order.cumulative,
                )
                if checked.canonical_bytes() != decision.fill.canonical_bytes():
                    _reject("source_changed")
                next_cash = _money_after_fill(cash, checked, side=checked.side)
                current_shares = holdings.get(instrument_id, _ZERO)
                with localcontext(_fixed_context()):
                    next_shares = current_shares + checked.quantity if checked.side == "buy" else current_shares - checked.quantity
                next_shares = _decimal_value(next_shares, kind="holding")
                if next_shares < 0:
                    _reject("numeric_invalid")
                cash = next_cash
                if next_shares:
                    holdings[instrument_id] = next_shares
                else:
                    holdings.pop(instrument_id, None)
                with localcontext(_fixed_context()):
                    cap_remaining[slot] = cap - checked.quantity
                    order.remaining -= checked.quantity
                    order.cumulative += checked.quantity
                    order.cumulative_fee += checked.fee
                order.remaining = _decimal_value(order.remaining, kind="quantity")
                order.cumulative = _decimal_value(order.cumulative, kind="quantity")
                order.cumulative_fee = _decimal_value(order.cumulative_fee, kind="money")
                fills.append(checked)
                if order.remaining == 0:
                    order.status = "filled"
                    order.reason = None
                    terminal_attempts.add(intent_id)
            if order.status != "filled" and order.intent.time_in_force != "gtc":
                if order.intent.time_in_force == "day":
                    order.status = "expired"
                    order.reason = "day_remainder_expired"
                else:
                    order.status = "cancelled"
                    order.reason = "time_in_force_remainder_cancelled"
                terminal_attempts.add(intent_id)
            elif order.status != "filled":
                order.status = "open_at_horizon"
                order.reason = decision.reason_code
        for intent_id, order in local_orders.items():
            if order.status == "open_at_horizon":
                first_date = object.__getattribute__(order.binding.next_session, "session_date")
                if first_date > horizon:
                    continue
                first_close = object.__getattribute__(order.binding.calendar.session(first_date), "close_at")
                last_attempt_close = attempt_closes.get(intent_id)
                if order.intent.expires_at < first_close or (
                    last_attempt_close is not None and order.intent.expires_at <= last_attempt_close
                ) or order.intent.expires_at <= object.__getattribute__(
                    order.binding.calendar.session(horizon), "close_at"
                ):
                    order.status = "expired"
                    order.reason = "intent_expired"
        # Recheck retained caller inputs independently after the final reducer step.
        for data, ingress in binding_ingress:
            _refresh_binding_data(data, ingress)
        for raw in intents:
            try:
                current = revalidate_order_intent(raw)
            except OrderInputError as error:
                if error.reason_code == "resource_limit":
                    raise
                _reject("source_changed")
            expected_intent = intent_ingress.get(current.intent_id)
            if (
                expected_intent is None
                or current.canonical_bytes() != expected_intent[0]
                or _contract_storage_fingerprint(raw, OrderIntent, reason="source_changed") != expected_intent[1]
            ):
                _reject("source_changed")
        current_policy = revalidate_cost_policy(policy)
        if (
            current_policy.canonical_bytes() != policy_wire
            or _contract_storage_fingerprint(policy, CostPolicy, reason="source_changed") != policy_storage
        ):
            _reject("source_changed")
        for outcome, sealed, storage_seal in outcome_ingress:
            final_outcome = _refresh_outcome(outcome)
            if (final_outcome[4], final_outcome[6]) != (sealed, storage_seal):
                _reject("source_changed")
        result_orders = tuple(
            SimOrder(
                intent_id=identifier,
                remaining_quantity=order.remaining,
                cumulative_quantity=order.cumulative,
                cumulative_fee=order.cumulative_fee,
                status=order.status,
                reason_code=order.reason,
            )
            for identifier, order in sorted(local_orders.items())
        )
        final_holdings = tuple(sorted((instrument, quantity) for instrument, quantity in holdings.items() if quantity > 0))
        return SimulationResult(tuple(fills), result_orders, cash, final_holdings)


__all__ = [
    "FillDecision",
    "FillModel",
    "OutcomeEvidence",
    "SimulationResult",
    "Simulator",
]
