"""Bounded, in-memory BT-03 accounting with deterministic event identities."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, Inexact, Rounded, localcontext
from typing import Any

from mytradingalpha.backtest.clock import (
    BacktestInputError,
    SessionBinding,
    _CaptureBudget,
    _refresh_binding,
)
from mytradingalpha.backtest.costs import CostPolicy, revalidate_cost_policy
from mytradingalpha.backtest.fills import (
    FillModel,
    OutcomeEvidence,
    _refresh_outcome,
)
from mytradingalpha.contracts.orders import (
    Fill,
    OrderInputError,
    OrderIntent,
    _contract_storage_fingerprint,
    _decimal as _order_decimal,
    _decimal_wire,
    _fee_due,
    _fixed_context,
    _json_time,
    _safe_date as _order_safe_date,
    _safe_id_token,
    _safe_utc as _order_safe_utc,
    _wire_payload,
    revalidate_fill,
    revalidate_order_intent,
)

_GENESIS_DOMAIN = b"mytradingalpha:bt03:genesis:v1\0"
_EVENT_DOMAIN = b"mytradingalpha:bt03:event:v1\0"
_PREFIX_DOMAIN = b"mytradingalpha:bt03:prefix:v1\0"
_STORAGE_DOMAIN = b"mytradingalpha:bt03:event-storage:v1\0"
_BALANCE_DOMAIN = b"mytradingalpha:bt03:balance:v1\0"
_NUMERIC_POLICY_VERSION = "bt03-decimal-v1"
_SCHEMA_VERSION = "v1"
_MAX_SEQUENCE = (1 << 63) - 1
_MAX_EVENTS = 4096
_MAX_INSTRUMENTS = 256
_MAX_INTENTS = 256
_MAX_OBLIGATIONS = 256
_MAX_CAP_SLOTS = 4096
_MAX_EVENT_BYTES = 4 * 1024 * 1024
_MAX_RETAINED_BYTES = 64 * 1024 * 1024
_MAX_BINDING_BYTES = 2 * 1024 * 1024
_MAX_ID_BYTES = 128
_MAX_MONEY = Decimal("1E24")
_MAX_QUANTITY = Decimal("1E9")
_MAX_EXECUTION = Decimal("2E9")
_MAX_HOLDINGS = Decimal("1E12")
_ZERO = Decimal("0")
_OBLIGATION_KINDS = frozenset(
    ("receivable_create", "receivable_settle", "liability_create", "liability_settle")
)
_REASONS = frozenset(
    (
        "input_invalid",
        "resource_limit",
        "source_changed",
        "binding_mismatch",
        "fill_invalid",
        "event_conflict",
        "sequence_invalid",
        "chronology_invalid",
        "accounting_invalid",
        "obligation_invalid",
        "numeric_invalid",
    )
)
_MISSING = object()


class LedgerInputError(ValueError):
    """Fixed, non-reflective BT-03 diagnostic."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str = "input_invalid") -> None:
        code = reason_code if type(reason_code) is str and reason_code in _REASONS else "input_invalid"
        object.__setattr__(self, "reason_code", code)
        super().__init__(f"BT-03 input rejected ({code})")

    def errors(self) -> list[dict[str, object]]:
        return [{"type": "ledger_input_error", "loc": (), "msg": str(self), "input": None}]


def _reject(
    reason: str = "input_invalid", error_type: type[Exception] = LedgerInputError
) -> None:
    code = reason if type(reason) is str and reason in _REASONS else "input_invalid"
    if error_type is TypeError:
        raise TypeError("BT-03 input rejected") from None
    raise LedgerInputError(code) from None


def _capture_call(call: Callable[[], Any], reason: str = "input_invalid") -> Any:
    """Run a trusted validator and raise only after its exception context ends."""

    failed = False
    failure_reason = reason
    result: Any = None
    try:
        result = call()
    except BacktestInputError as error:
        failed = True
        if type(error) is BacktestInputError:
            code = object.__getattribute__(error, "reason_code")
            if type(code) is str:
                if code == "resource_limit":
                    failure_reason = "resource_limit"
                elif code == "source_changed":
                    failure_reason = "source_changed"
    except Exception as error:
        failed = True
        if type(error) is OrderInputError or type(error) is LedgerInputError:
            code = object.__getattribute__(error, "reason_code")
            if type(code) is str:
                if code == "resource_limit":
                    failure_reason = "resource_limit"
                elif code == "source_changed":
                    failure_reason = "source_changed"
    if failed:
        _reject(failure_reason)
    return result


def _contract_call(call: Callable[[], Any], reason: str = "input_invalid") -> Any:
    failed = False
    failure_reason = reason
    result: Any = None
    try:
        result = call()
    except Exception as error:
        failed = True
        if type(error) is OrderInputError or type(error) is BacktestInputError:
            code = object.__getattribute__(error, "reason_code")
            if type(code) is str:
                if code == "resource_limit":
                    failure_reason = "resource_limit"
                elif code == "source_changed":
                    failure_reason = "source_changed"
    if failed:
        _reject(failure_reason)
    return result


def _canonical_json(payload: object) -> bytes:
    failed = False
    result = b""
    try:
        result = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8", "strict")
    except Exception:
        failed = True
    if failed:
        _reject("input_invalid")
    return result


def _jsonable(value: object) -> object:
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return value
    if value_type is bytes:
        return ["bytes", value.hex()]
    if value_type is tuple or value_type is list:
        return [_jsonable(item) for item in value]
    if value_type is dict:
        return {key: _jsonable(item) for key, item in dict.items(value)}
    _reject("input_invalid")
    raise AssertionError("unreachable")


def _safe_identifier(value: object) -> str:
    if type(value) is not str:
        _reject()
    if not value or len(value) > _MAX_ID_BYTES:
        _reject("resource_limit" if len(value) > _MAX_ID_BYTES else "input_invalid")
    encoding_failed = False
    encoded_size = 0
    try:
        encoded_size = len(value.encode("utf-8", "strict"))
    except Exception:
        encoding_failed = True
    if encoding_failed:
        _reject()
    if encoded_size > _MAX_ID_BYTES:
        _reject("resource_limit")
    failed = False
    checked = ""
    try:
        checked = _safe_id_token(value)
    except Exception:
        failed = True
    if failed:
        _reject()
    return checked


def _safe_hash(value: object) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        _reject()
    raw = value[7:]
    if any(char not in "0123456789abcdef" for char in raw):
        _reject()
    return value


def _safe_utc(value: object) -> datetime:
    if type(value) is not datetime:
        _reject()
    failed = False
    checked: datetime | None = None
    try:
        checked = _order_safe_utc(value)
    except Exception:
        failed = True
    if failed or checked is None:
        _reject()
    return checked


def _safe_date(value: object) -> date:
    if type(value) is not date:
        _reject()
    failed = False
    checked: date | None = None
    try:
        checked = _order_safe_date(value)
    except Exception:
        failed = True
    if failed or checked is None:
        _reject()
    return checked


def _decimal_checked(
    value: object,
    kind: str,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    if type(value) is not Decimal:
        _reject()
    if not value.is_finite():
        _reject("numeric_invalid")
    # The exponent scan is bounded and does not copy an attacker-sized coefficient.
    bounds = {
        "money": (-24, 24, 24, _MAX_MONEY),
        "quantity": (-6, 9, 9, _MAX_QUANTITY),
        "execution": (-16, 10, 9, _MAX_EXECUTION),
        "holding": (-6, 12, 12, _MAX_HOLDINGS),
    }
    if kind not in bounds:
        _reject("numeric_invalid")
    low, high, adjusted_limit, maximum = bounds[kind]
    exponent = None
    for candidate in range(low, high + 1):
        if value.same_quantum(Decimal((0, (1,), candidate))):
            exponent = candidate
            break
    if exponent is None:
        _reject("numeric_invalid")
    if not value.is_zero():
        adjusted = value.adjusted()
        if adjusted > adjusted_limit or value.copy_abs() > maximum:
            _reject("numeric_invalid")
        # For a nonzero Decimal, adjusted and exponent bound the coefficient
        # before as_tuple() or canonical formatting can copy its digits.
        if adjusted - exponent + 1 > 100:
            _reject("resource_limit")
    result = _contract_call(
        lambda: _order_decimal(
            value,
            low_exp=low,
            high_exp=high,
            max_adjusted=adjusted_limit,
            maximum=maximum,
            positive=positive,
            nonnegative=nonnegative,
        ),
        "numeric_invalid",
    )
    return result


def _decimal_storage(value: Decimal) -> tuple[object, ...]:
    sign, digits, exponent = value.as_tuple()
    if len(digits) > 100:
        _reject("resource_limit")
    return (sign, tuple(digits), exponent)


def _exact_decimal(call: Callable[[], Decimal]) -> Decimal:
    failed = False
    rounded = False
    result = Decimal(0)
    try:
        with localcontext(_fixed_context()) as context:
            context.clear_flags()
            result = call()
            rounded = context.flags[Inexact] or context.flags[Rounded]
    except Exception:
        failed = True
    if failed or rounded:
        _reject("numeric_invalid")
    return result


def _time_native(value: datetime) -> tuple[object, ...]:
    return (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond,
    )


def _time_wire(value: datetime) -> str:
    return _json_time(value)


def _contract_record(value: object, model_type: type[object], reason: str) -> tuple[Any, bytes, tuple[object, ...]]:
    if type(value) is not model_type:
        _reject(reason)
    if model_type is OrderIntent:
        owned = _contract_call(lambda: revalidate_order_intent(value), reason)
    elif model_type is Fill:
        owned = _contract_call(lambda: revalidate_fill(value), reason)
    elif model_type is CostPolicy:
        owned = _contract_call(lambda: revalidate_cost_policy(value), reason)
    else:
        _reject()
    # Revalidation has produced an owned exact native model. Serialize that
    # local snapshot without invoking the public revalidation entry again.
    canonical = _canonical_json(_contract_call(lambda: _wire_payload(owned, include_id=True), reason))
    storage = _contract_call(
        lambda: _contract_storage_fingerprint(value, model_type, reason=reason), reason
    )
    return owned, canonical, storage


def _safe_saved(value: object) -> None:
    """Bound sealed primitive trees before equality or serialization."""

    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 64 or nodes > 1_000_000:
            _reject("resource_limit")
        native = type(item)
        if item is None or native is bool:
            continue
        if native is int:
            if item.bit_length() > 64:
                _reject("source_changed")
        elif native is str or native is bytes:
            if len(item) > _MAX_RETAINED_BYTES:
                _reject("resource_limit")
        elif native is tuple:
            if len(item) > 4096:
                _reject("resource_limit")
            pending.extend((child, depth + 1) for child in item)
        else:
            _reject("source_changed")


def _native_witness_equal(left: object, right: object) -> bool:
    """Compare bounded primitive witnesses without integer/bool aliasing."""

    pending = [(left, right)]
    while pending:
        current, saved = pending.pop()
        native = type(current)
        if native is not type(saved):
            return False
        if native is tuple:
            if len(current) != len(saved):
                return False
            pending.extend(zip(current, saved, strict=True))
        elif current is None:
            continue
        elif native in (bool, int, str, bytes):
            if current != saved:
                return False
        else:
            return False
    return True


def _saved_bytes(value: object, maximum: int) -> bytes:
    if type(value) is not bytes:
        _reject("source_changed")
    if len(value) > maximum:
        _reject("resource_limit")
    return value


def _binding_seal_guard(value: object) -> None:
    if type(value) is not SessionBinding:
        _reject()
    _saved_bytes(object.__getattribute__(value, "_sealed_source_json"), _MAX_BINDING_BYTES)
    _saved_bytes(object.__getattribute__(value, "_sealed_storage_bytes"), _MAX_BINDING_BYTES)
    _safe_hash(object.__getattribute__(value, "_source_fingerprint"))


def _outcome_seal_guard(value: object) -> None:
    if type(value) is not OutcomeEvidence:
        _reject()
    _saved_bytes(object.__getattribute__(value, "_sealed_bytes"), _MAX_BINDING_BYTES)
    _saved_bytes(object.__getattribute__(value, "_sealed_storage"), _MAX_BINDING_BYTES)
    _safe_hash(object.__getattribute__(value, "_outcome_hash"))


def _contract_storage_bytes(storage: tuple[object, ...]) -> bytes:
    return _canonical_json(_jsonable(storage))


def _binding_capture(value: object) -> tuple[SessionBinding, tuple[object, ...]]:
    if type(value) is not SessionBinding:
        _reject()
    _binding_seal_guard(value)
    prepared = _capture_call(lambda: _refresh_binding(value, _CaptureBudget()))
    if len(prepared[5]) + len(prepared[7]) > _MAX_BINDING_BYTES:
        _reject("resource_limit")
    context, bundle, envelope, session, next_session, source_bytes, fingerprint, storage_bytes = prepared
    if type(source_bytes) is not bytes or type(storage_bytes) is not bytes:
        _reject("source_changed")
    if len(source_bytes) + len(storage_bytes) > _MAX_BINDING_BYTES:
        _reject("resource_limit")
    clone = _binding_from_prepared(prepared)
    return clone, prepared[5:]


def _binding_from_prepared(prepared: tuple[object, ...]) -> SessionBinding:
    if type(prepared) is not tuple or len(prepared) != 8:
        _reject("input_invalid")
    context, bundle, envelope, session, next_session, source_bytes, fingerprint, storage_bytes = prepared
    clone = object.__new__(SessionBinding)
    object.__setattr__(clone, "_context_snapshot", context)
    object.__setattr__(clone, "_bundle_snapshot", bundle)
    object.__setattr__(clone, "_envelope_snapshot", envelope)
    object.__setattr__(clone, "_session_snapshot", session)
    object.__setattr__(clone, "_next_session_snapshot", next_session)
    object.__setattr__(clone, "_sealed_source_json", source_bytes)
    object.__setattr__(clone, "_source_fingerprint", fingerprint)
    object.__setattr__(clone, "_sealed_storage_bytes", storage_bytes)
    return clone


def _binding_refresh(value: object, expected: tuple[object, ...] | None = None) -> tuple[object, ...]:
    if type(value) is not SessionBinding:
        _reject()
    _binding_seal_guard(value)
    prepared = _capture_call(lambda: _refresh_binding(value, _CaptureBudget()))
    if len(prepared[5]) + len(prepared[7]) > _MAX_BINDING_BYTES:
        _reject("resource_limit")
    if expected is not None:
        _safe_saved(expected)
    if expected is not None and prepared[5:] != expected:
        _reject("source_changed")
    return prepared


def _binding_instrument(prepared: tuple[object, ...], instrument_id: str) -> object:
    bundle = prepared[1]
    instruments = object.__getattribute__(bundle, "instruments")
    matches = tuple(
        item
        for item in instruments
        if object.__getattribute__(item, "instrument_id") == instrument_id
    )
    if len(matches) != 1:
        _reject("binding_mismatch")
    return matches[0]


def _outcome_capture(value: object) -> tuple[OutcomeEvidence, tuple[object, ...]]:
    if type(value) is not OutcomeEvidence:
        _reject()
    _outcome_seal_guard(value)
    state = _contract_call(lambda: _refresh_outcome(value), "source_changed")
    bar, outcome_cutoff, archive_cutoff, replay_policy, sealed, outcome_hash, storage = state
    if type(sealed) is not bytes or type(storage) is not bytes:
        _reject("source_changed")
    return _outcome_from_state(state), (sealed, storage, outcome_hash)


def _outcome_from_state(state: tuple[object, ...]) -> OutcomeEvidence:
    bar, outcome_cutoff, archive_cutoff, replay_policy, sealed, outcome_hash, storage = state
    clone = object.__new__(OutcomeEvidence)
    for name, value in (("_bar_snapshot", bar), ("_outcome_cutoff", outcome_cutoff),
                        ("_archive_cutoff", archive_cutoff), ("_replay_policy", replay_policy),
                        ("_sealed_bytes", sealed), ("_sealed_storage", storage),
                        ("_outcome_hash", outcome_hash)):
        object.__setattr__(clone, name, value)
    return clone


def _outcome_refresh(value: object, expected: tuple[object, ...] | None = None) -> tuple[object, ...]:
    if type(value) is not OutcomeEvidence:
        _reject()
    _outcome_seal_guard(value)
    state = _contract_call(lambda: _refresh_outcome(value), "source_changed")
    current = (state[4], state[6], state[5])
    if expected is not None:
        _safe_saved(expected)
    if expected is not None and current != expected:
        _reject("source_changed")
    return state


def _new_contract_copy(value: object, model_type: type[object], reason: str) -> tuple[Any, bytes, tuple[object, ...]]:
    return _contract_record(value, model_type, reason)


def _intent_storage_payload(intent: OrderIntent, intent_bytes: bytes, storage: tuple[object, ...]) -> dict[str, object]:
    del intent
    return {"canonical": intent_bytes.decode("utf-8"), "storage": hashlib.sha256(_contract_storage_bytes(storage)).hexdigest()}


def _event_hash(canonical: bytes) -> str:
    return "sha256:" + hashlib.sha256(_EVENT_DOMAIN + canonical).hexdigest()


def _prefix_hash(previous_hash: str, canonical: bytes) -> str:
    previous = bytes.fromhex(previous_hash[7:])
    return "sha256:" + hashlib.sha256(_PREFIX_DOMAIN + previous + canonical).hexdigest()


class LedgerEvent:
    """Immutable, sealed posting of one validated fill or obligation fact."""

    __slots__ = (
        "_kind", "_event_id", "_sequence", "_previous_hash", "previous_hash", "_run_id", "_calendar_id",
        "_currency", "_instrument_id", "_intent_id", "_fill_id", "_obligation_id",
        "_amount", "_economic_time", "_observed_at", "_due_at", "_intent", "_fill",
        "_binding", "_outcome", "_policy", "_intent_bytes", "_fill_bytes", "_policy_bytes",
        "_binding_seals", "_outcome_seals", "_intent_storage", "_fill_storage", "_policy_storage",
        "_canonical", "_storage_witness", "_storage_bytes", "_seal", "_retained_size",
    )

    def __init__(self, *_: object, **__: object) -> None:
        _reject("input_invalid", TypeError)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("LedgerEvent is immutable")

    def __repr__(self) -> str:
        return "LedgerEvent(<sealed>)"

    @classmethod
    def for_obligation(
        cls,
        *,
        event_id: object = _MISSING,
        sequence: object = _MISSING,
        previous_hash: object = _MISSING,
        run_id: object = _MISSING,
        calendar_id: object = _MISSING,
        currency: object = _MISSING,
        kind: object = _MISSING,
        obligation_id: object = _MISSING,
        amount: object = _MISSING,
        economic_time: object = _MISSING,
        observed_at: object = _MISSING,
        due_at: object = _MISSING,
        **unknown: object,
    ) -> LedgerEvent:
        if unknown:
            _reject("input_invalid", TypeError)
        event = _empty_event(cls)
        object.__setattr__(event, "_kind", kind)
        object.__setattr__(event, "_event_id", event_id)
        object.__setattr__(event, "_sequence", sequence)
        object.__setattr__(event, "_previous_hash", previous_hash)
        object.__setattr__(event, "previous_hash", previous_hash)
        object.__setattr__(event, "_run_id", run_id)
        object.__setattr__(event, "_calendar_id", calendar_id)
        object.__setattr__(event, "_currency", currency)
        object.__setattr__(event, "_instrument_id", None)
        object.__setattr__(event, "_intent_id", None)
        object.__setattr__(event, "_fill_id", None)
        object.__setattr__(event, "_obligation_id", obligation_id)
        object.__setattr__(event, "_amount", amount)
        object.__setattr__(event, "_economic_time", economic_time)
        object.__setattr__(event, "_observed_at", observed_at)
        object.__setattr__(event, "_due_at", due_at)
        _seal_event(event)
        return event

    @classmethod
    def for_fill(
        cls,
        *,
        event_id: object = _MISSING,
        sequence: object = _MISSING,
        previous_hash: object = _MISSING,
        intent: object = _MISSING,
        fill: object = _MISSING,
        binding: object = _MISSING,
        outcome: object = _MISSING,
        policy: object = _MISSING,
        **unknown: object,
    ) -> LedgerEvent:
        if unknown:
            _reject("input_invalid", TypeError)
        event_token = _safe_identifier(event_id)
        seq = _sequence_value(sequence)
        predecessor = _safe_hash(previous_hash)
        intent_copy, intent_bytes, intent_storage = _new_contract_copy(intent, OrderIntent, "fill_invalid")
        fill_copy, fill_bytes, fill_storage = _new_contract_copy(fill, Fill, "fill_invalid")
        policy_copy, policy_bytes, policy_storage = _new_contract_copy(policy, CostPolicy, "fill_invalid")
        binding_copy, binding_seals = _binding_capture(binding)
        outcome_copy, outcome_seals = _outcome_capture(outcome)

        context = object.__getattribute__(binding_copy, "_context_snapshot")
        bundle = object.__getattribute__(binding_copy, "_bundle_snapshot")
        run_id = _safe_identifier(object.__getattribute__(context, "run_id"))
        calendar_id = _safe_identifier(object.__getattribute__(bundle.calendar, "calendar_id"))
        currency = object.__getattribute__(intent_copy, "currency")
        instrument_id = _safe_identifier(object.__getattribute__(intent_copy, "instrument_id"))
        instrument = _binding_instrument((context, bundle), instrument_id)
        instrument_currency = object.__getattribute__(instrument, "currency")
        if (
            type(currency) is not str
            or currency != "USD"
            or instrument_currency != currency
            or object.__getattribute__(fill_copy, "currency") != currency
            or object.__getattribute__(intent_copy, "run_id") != run_id
            or object.__getattribute__(intent_copy, "calendar_id") != calendar_id
        ):
            _reject("binding_mismatch")

        cumulative = _decimal_checked(
            object.__getattribute__(fill_copy, "cumulative_quantity_before"), "quantity", nonnegative=True
        )
        quantity = _decimal_checked(object.__getattribute__(intent_copy, "quantity"), "quantity", positive=True)
        remaining = _exact_decimal(lambda: quantity - cumulative)
        if remaining <= 0:
            _reject("fill_invalid")
        validation_fill, validation_intent, validation_policy = fill_copy, intent_copy, policy_copy
        validation_outcome, validation_binding = outcome_copy, binding_copy
        checked = _validate_fill(
            validation_fill,
            validation_intent,
            validation_outcome,
            validation_policy,
            validation_binding,
            cumulative,
            remaining,
        )
        if type(checked) is not Fill:
            _reject("fill_invalid")

        # Verify each ingress source again after contextual validation. This also
        # detects canonical-equal but native-storage-different mutation.
        _require_raw_contract_unchanged(intent, OrderIntent, intent_bytes, intent_storage, "source_changed")
        _require_raw_contract_unchanged(fill, Fill, fill_bytes, fill_storage, "source_changed")
        _require_raw_contract_unchanged(policy, CostPolicy, policy_bytes, policy_storage, "source_changed")
        _binding_refresh(binding, binding_seals)
        _outcome_refresh(outcome, outcome_seals)
        _require_raw_contract_unchanged(validation_intent, OrderIntent, intent_bytes, intent_storage, "source_changed")
        _require_raw_contract_unchanged(validation_policy, CostPolicy, policy_bytes, policy_storage, "source_changed")
        _require_raw_contract_unchanged(validation_fill, Fill, fill_bytes, fill_storage, "source_changed")
        _binding_refresh(validation_binding, binding_seals)
        _outcome_refresh(validation_outcome, outcome_seals)

        # Retain a fresh validated fill returned by the existing contextual
        # validator, then seal its exact native storage independently.
        checked_copy, checked_bytes, checked_storage = _new_contract_copy(checked, Fill, "fill_invalid")
        if checked_bytes != fill_bytes or checked_storage != fill_storage:
            _reject("source_changed")

        event = _empty_event(cls)
        object.__setattr__(event, "_kind", "fill")
        object.__setattr__(event, "_event_id", event_token)
        object.__setattr__(event, "_sequence", seq)
        object.__setattr__(event, "_previous_hash", predecessor)
        object.__setattr__(event, "previous_hash", predecessor)
        object.__setattr__(event, "_run_id", run_id)
        object.__setattr__(event, "_calendar_id", calendar_id)
        object.__setattr__(event, "_currency", currency)
        object.__setattr__(event, "_instrument_id", instrument_id)
        object.__setattr__(event, "_intent_id", object.__getattribute__(intent_copy, "intent_id"))
        object.__setattr__(event, "_fill_id", object.__getattribute__(checked_copy, "fill_id"))
        object.__setattr__(event, "_obligation_id", None)
        object.__setattr__(event, "_amount", None)
        object.__setattr__(event, "_economic_time", object.__getattribute__(checked_copy, "fill_time"))
        object.__setattr__(event, "_observed_at", object.__getattribute__(checked_copy, "received_at"))
        object.__setattr__(event, "_due_at", None)
        object.__setattr__(event, "_intent", intent_copy)
        object.__setattr__(event, "_fill", checked_copy)
        object.__setattr__(event, "_binding", binding_copy)
        object.__setattr__(event, "_outcome", outcome_copy)
        object.__setattr__(event, "_policy", policy_copy)
        object.__setattr__(event, "_intent_bytes", intent_bytes)
        object.__setattr__(event, "_fill_bytes", checked_bytes)
        object.__setattr__(event, "_policy_bytes", policy_bytes)
        object.__setattr__(event, "_binding_seals", binding_seals)
        object.__setattr__(event, "_outcome_seals", outcome_seals)
        object.__setattr__(event, "_intent_storage", intent_storage)
        object.__setattr__(event, "_fill_storage", checked_storage)
        object.__setattr__(event, "_policy_storage", policy_storage)
        _seal_event(event)
        return event

    @property
    def kind(self) -> str:
        _verify_event(self)
        return object.__getattribute__(self, "_kind")

    @property
    def event_id(self) -> str:
        _verify_event(self)
        return object.__getattribute__(self, "_event_id")

    @property
    def sequence(self) -> int:
        _verify_event(self)
        return object.__getattribute__(self, "_sequence")

    @property
    def run_id(self) -> str:
        _verify_event(self)
        return object.__getattribute__(self, "_run_id")

    @property
    def calendar_id(self) -> str:
        _verify_event(self)
        return object.__getattribute__(self, "_calendar_id")

    @property
    def currency(self) -> str:
        _verify_event(self)
        return object.__getattribute__(self, "_currency")

    @property
    def instrument_id(self) -> str | None:
        _verify_event(self)
        return object.__getattribute__(self, "_instrument_id")

    @property
    def intent_id(self) -> str | None:
        _verify_event(self)
        return object.__getattribute__(self, "_intent_id")

    @property
    def fill_id(self) -> str | None:
        _verify_event(self)
        return object.__getattribute__(self, "_fill_id")

    @property
    def obligation_id(self) -> str | None:
        _verify_event(self)
        return object.__getattribute__(self, "_obligation_id")

    @property
    def amount(self) -> Decimal | None:
        _verify_event(self)
        return object.__getattribute__(self, "_amount")

    @property
    def economic_time(self) -> datetime:
        _verify_event(self)
        return object.__getattribute__(self, "_economic_time")

    @property
    def observed_at(self) -> datetime:
        _verify_event(self)
        return object.__getattribute__(self, "_observed_at")

    @property
    def due_at(self) -> datetime | None:
        _verify_event(self)
        return object.__getattribute__(self, "_due_at")

    @property
    def intent(self) -> OrderIntent | None:
        return object.__getattribute__(_capture_event(self)[0], "_intent")

    @property
    def fill(self) -> Fill | None:
        return object.__getattribute__(_capture_event(self)[0], "_fill")

    @property
    def binding(self) -> SessionBinding | None:
        return object.__getattribute__(_capture_event(self)[0], "_binding")

    @property
    def outcome(self) -> OutcomeEvidence | None:
        return object.__getattribute__(_capture_event(self)[0], "_outcome")

    @property
    def policy(self) -> CostPolicy | None:
        return object.__getattribute__(_capture_event(self)[0], "_policy")

    @property
    def event_hash(self) -> str:
        return _event_hash(self.canonical_bytes())

    def canonical_bytes(self) -> bytes:
        return _verify_event(self)[0]


def _empty_event(cls: type[LedgerEvent]) -> LedgerEvent:
    if cls is not LedgerEvent:
        _reject()
    event = object.__new__(cls)
    for name in LedgerEvent.__slots__:
        object.__setattr__(event, name, None)
    return event


def _sequence_value(value: object) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SEQUENCE:
        _reject("sequence_invalid")
    return value


def _event_values(event: object, captured: list[object] | None = None) -> dict[str, object]:
    if type(event) is not LedgerEvent:
        _reject()
    kind = object.__getattribute__(event, "_kind")
    event_id = _safe_identifier(object.__getattribute__(event, "_event_id"))
    sequence = _sequence_value(object.__getattribute__(event, "_sequence"))
    previous = _safe_hash(object.__getattribute__(event, "_previous_hash"))
    public_previous = _safe_hash(object.__getattribute__(event, "previous_hash"))
    if public_previous != previous:
        _reject("source_changed")
    run_id = _safe_identifier(object.__getattribute__(event, "_run_id"))
    calendar_id = _safe_identifier(object.__getattribute__(event, "_calendar_id"))
    currency = object.__getattribute__(event, "_currency")
    if type(currency) is not str or currency != "USD":
        _reject("input_invalid")
    if type(kind) is not str:
        _reject()
    result: dict[str, object] = {
        "event_id": event_id,
        "sequence": sequence,
        "previous_hash": previous,
        "run_id": run_id,
        "calendar_id": calendar_id,
        "currency": currency,
        "kind": kind,
        "schema_version": _SCHEMA_VERSION,
    }
    if kind in _OBLIGATION_KINDS:
        obligation_id = _safe_identifier(object.__getattribute__(event, "_obligation_id"))
        amount = _decimal_checked(object.__getattribute__(event, "_amount"), "money", positive=True)
        economic_time = _safe_utc(object.__getattribute__(event, "_economic_time"))
        observed_at = _safe_utc(object.__getattribute__(event, "_observed_at"))
        due_at = _safe_utc(object.__getattribute__(event, "_due_at"))
        if observed_at < economic_time:
            _reject("chronology_invalid")
        if kind.endswith("_create") and due_at < economic_time:
            _reject("obligation_invalid")
        if any(object.__getattribute__(event, name) is not None for name in (
            "_instrument_id", "_intent_id", "_fill_id", "_intent", "_fill", "_binding", "_outcome", "_policy",
            "_intent_bytes", "_fill_bytes", "_policy_bytes", "_binding_seals", "_outcome_seals",
            "_intent_storage", "_fill_storage", "_policy_storage"
        )):
            _reject("source_changed")
        result.update(
            {
                "amount": _decimal_wire(amount),
                "due_at": _time_wire(due_at),
                "economic_time": _time_wire(economic_time),
                "obligation_id": obligation_id,
                "observed_at": _time_wire(observed_at),
            }
        )
        return result
    if kind != "fill":
        _reject("input_invalid")
    for name in ("_intent_storage", "_fill_storage", "_policy_storage", "_binding_seals", "_outcome_seals"):
        _safe_saved(object.__getattribute__(event, name))
    for name in ("_intent_bytes", "_fill_bytes", "_policy_bytes"):
        _saved_bytes(object.__getattribute__(event, name), _MAX_EVENT_BYTES)
    for name in ("_instrument_id", "_intent_id", "_fill_id"):
        _safe_identifier(object.__getattribute__(event, name))
    _safe_utc(object.__getattribute__(event, "_economic_time"))
    _safe_utc(object.__getattribute__(event, "_observed_at"))
    intent = object.__getattribute__(event, "_intent")
    fill = object.__getattribute__(event, "_fill")
    binding = object.__getattribute__(event, "_binding")
    outcome = object.__getattribute__(event, "_outcome")
    policy = object.__getattribute__(event, "_policy")
    intent_copy, intent_bytes, intent_storage = _contract_record(intent, OrderIntent, "source_changed")
    fill_copy, fill_bytes, fill_storage = _contract_record(fill, Fill, "source_changed")
    policy_copy, policy_bytes, policy_storage = _contract_record(policy, CostPolicy, "source_changed")
    binding_prepared = _binding_refresh(binding, object.__getattribute__(event, "_binding_seals"))
    outcome_state = _outcome_refresh(outcome, object.__getattribute__(event, "_outcome_seals"))
    if (
        intent_bytes != object.__getattribute__(event, "_intent_bytes")
        or fill_bytes != object.__getattribute__(event, "_fill_bytes")
        or policy_bytes != object.__getattribute__(event, "_policy_bytes")
        or intent_storage != object.__getattribute__(event, "_intent_storage")
        or fill_storage != object.__getattribute__(event, "_fill_storage")
        or policy_storage != object.__getattribute__(event, "_policy_storage")
    ):
        _reject("source_changed")
    if captured is not None:
        captured.extend((intent_copy, fill_copy, policy_copy, binding_prepared, outcome_state))
    context = binding_prepared[0]
    bundle = binding_prepared[1]
    instrument_id = _safe_identifier(object.__getattribute__(fill_copy, "instrument_id"))
    instrument = _binding_instrument(binding_prepared, instrument_id)
    fill_time = _safe_utc(object.__getattribute__(fill_copy, "fill_time"))
    received_at = _safe_utc(object.__getattribute__(fill_copy, "received_at"))
    expected = {
        "calendar_id": object.__getattribute__(bundle.calendar, "calendar_id"),
        "currency": object.__getattribute__(instrument, "currency"),
        "event_id": event_id,
        "kind": "fill",
        "run_id": object.__getattribute__(context, "run_id"),
    }
    if (
        object.__getattribute__(intent_copy, "run_id") != expected["run_id"]
        or object.__getattribute__(intent_copy, "calendar_id") != expected["calendar_id"]
        or object.__getattribute__(instrument, "currency") != "USD"
        or fill_time != object.__getattribute__(event, "_economic_time")
        or received_at != object.__getattribute__(event, "_observed_at")
        or any(result[key] != value for key, value in expected.items())
        or object.__getattribute__(event, "_instrument_id") != instrument_id
        or object.__getattribute__(event, "_intent_id") != object.__getattribute__(intent_copy, "intent_id")
        or object.__getattribute__(event, "_fill_id") != object.__getattribute__(fill_copy, "fill_id")
        or object.__getattribute__(event, "_due_at") is not None
        or object.__getattribute__(event, "_amount") is not None
        or object.__getattribute__(event, "_obligation_id") is not None
    ):
        _reject("source_changed")
    result.update(
        {
            "binding_source": binding_prepared[5].decode("utf-8"),
            "binding_storage_seal": hashlib.sha256(binding_prepared[7]).hexdigest(),
            "economic_time": _time_wire(fill_time),
            "fill_source": fill_bytes.decode("utf-8"),
            "fill_storage_seal": hashlib.sha256(_contract_storage_bytes(fill_storage)).hexdigest(),
            "intent_source": intent_bytes.decode("utf-8"),
            "intent_storage_seal": hashlib.sha256(_contract_storage_bytes(intent_storage)).hexdigest(),
            "instrument_id": instrument_id,
            "intent_id": object.__getattribute__(intent_copy, "intent_id"),
            "fill_id": object.__getattribute__(fill_copy, "fill_id"),
            "observed_at": _time_wire(received_at),
            "outcome_source": outcome_state[4].decode("utf-8"),
            "outcome_storage_seal": hashlib.sha256(outcome_state[6]).hexdigest(),
            "policy_source": policy_bytes.decode("utf-8"),
            "policy_storage_seal": hashlib.sha256(_contract_storage_bytes(policy_storage)).hexdigest(),
        }
    )
    return result


def _event_witness(event: object, values: dict[str, object]) -> tuple[object, ...]:
    kind = values["kind"]
    common: tuple[object, ...] = (
        values["schema_version"], values["kind"], values["event_id"], values["sequence"],
        values["previous_hash"], values["run_id"], values["calendar_id"], values["currency"],
        _time_native(_safe_utc(object.__getattribute__(event, "_economic_time"))),
        _time_native(_safe_utc(object.__getattribute__(event, "_observed_at"))),
    )
    if kind in _OBLIGATION_KINDS:
        amount = _decimal_checked(object.__getattribute__(event, "_amount"), "money", positive=True)
        return common + (
            values["obligation_id"], _decimal_storage(amount),
            _time_native(_safe_utc(object.__getattribute__(event, "_due_at"))),
        )
    intent_storage = object.__getattribute__(event, "_intent_storage")
    fill_storage = object.__getattribute__(event, "_fill_storage")
    policy_storage = object.__getattribute__(event, "_policy_storage")
    binding_seals = object.__getattribute__(event, "_binding_seals")
    outcome_seals = object.__getattribute__(event, "_outcome_seals")
    return common + (
        object.__getattribute__(event, "_instrument_id"),
        object.__getattribute__(event, "_intent_id"),
        object.__getattribute__(event, "_fill_id"),
        intent_storage,
        fill_storage,
        policy_storage,
        binding_seals,
        outcome_seals,
    )


def _event_retained_size(event: LedgerEvent, canonical: bytes, witness_bytes: bytes) -> int:
    """Charge every retained canonical, native witness and full-source component."""

    retained = len(canonical) + len(witness_bytes)
    if object.__getattribute__(event, "_kind") == "fill":
        retained += sum(
            len(object.__getattribute__(event, name))
            for name in ("_intent_bytes", "_fill_bytes", "_policy_bytes")
        )
        retained += sum(len(item) for item in object.__getattribute__(event, "_binding_seals"))
        retained += sum(len(item) for item in object.__getattribute__(event, "_outcome_seals")[:2])
        retained += sum(
            len(_contract_storage_bytes(object.__getattribute__(event, name)))
            for name in ("_intent_storage", "_fill_storage", "_policy_storage")
        )
    return retained


def _seal_event(event: LedgerEvent) -> None:
    payload = _event_values(event)
    canonical = _canonical_json(payload)
    if len(canonical) > _MAX_EVENT_BYTES:
        _reject("resource_limit")
    witness = _event_witness(event, payload)
    witness_bytes = _canonical_json(_jsonable(witness))
    retained = _event_retained_size(event, canonical, witness_bytes)
    seal = hashlib.sha256(_STORAGE_DOMAIN + canonical + witness_bytes).digest()
    object.__setattr__(event, "_canonical", canonical)
    object.__setattr__(event, "_storage_witness", witness)
    object.__setattr__(event, "_storage_bytes", witness_bytes)
    object.__setattr__(event, "_seal", seal)
    object.__setattr__(event, "_retained_size", retained)


def _capture_event(event: object) -> tuple[LedgerEvent, bytes, tuple[object, ...], int]:
    return _capture_call(lambda: _capture_event_native(event), "source_changed")


def _capture_event_native(event: object) -> tuple[LedgerEvent, bytes, tuple[object, ...], int]:
    if type(event) is not LedgerEvent:
        _reject()
    saved_canonical = object.__getattribute__(event, "_canonical")
    saved_witness = object.__getattribute__(event, "_storage_witness")
    saved_storage = object.__getattribute__(event, "_storage_bytes")
    saved_seal = object.__getattribute__(event, "_seal")
    saved_size = object.__getattribute__(event, "_retained_size")
    if type(saved_canonical) is not bytes or type(saved_storage) is not bytes or type(saved_seal) is not bytes:
        _reject("source_changed")
    _safe_saved(saved_witness)
    _saved_bytes(saved_canonical, _MAX_EVENT_BYTES)
    _saved_bytes(saved_storage, _MAX_RETAINED_BYTES)
    _saved_bytes(saved_seal, 32)
    captured: list[object] = []
    payload = _event_values(event, captured)
    current = _canonical_json(payload)
    if len(current) > _MAX_EVENT_BYTES:
        _reject("resource_limit")
    witness = _event_witness(event, payload)
    storage = _canonical_json(_jsonable(witness))
    seal = hashlib.sha256(_STORAGE_DOMAIN + current + storage).digest()
    if current != saved_canonical or not _native_witness_equal(witness, saved_witness) or storage != saved_storage or seal != saved_seal:
        _reject("source_changed")
    retained = _event_retained_size(event, current, storage)
    if type(saved_size) is not int or saved_size != retained:
        _reject("source_changed")
    clone = _empty_event(LedgerEvent)
    for name in LedgerEvent.__slots__:
        object.__setattr__(clone, name, object.__getattribute__(event, name))
    if captured:
        intent, fill, policy, binding_prepared, outcome_state = captured
        for name, value in (("_intent", intent), ("_fill", fill), ("_policy", policy),
                            ("_binding", _binding_from_prepared(binding_prepared)),
                            ("_outcome", _outcome_from_state(outcome_state))):
            object.__setattr__(clone, name, value)
    return clone, current, witness, retained


def _verify_event(event: object) -> tuple[bytes, tuple[object, ...], int]:
    return _capture_event(event)[1:]


def _clone_event(event: LedgerEvent) -> LedgerEvent:
    return _capture_event(event)[0]


def _require_raw_contract_unchanged(
    value: object,
    model_type: type[object],
    expected_bytes: bytes,
    expected_storage: tuple[object, ...],
    reason: str,
) -> None:
    current, canonical, storage = _contract_record(value, model_type, reason)
    del current
    if canonical != expected_bytes or storage != expected_storage:
        _reject(reason)


def _validate_fill(
    fill: Fill,
    intent: OrderIntent,
    outcome: OutcomeEvidence,
    policy: CostPolicy,
    binding: SessionBinding,
    cumulative: Decimal,
    remaining: Decimal,
) -> Fill:
    error: Exception | None = None
    checked: object = None
    try:
        checked = FillModel.validate_fill(
            fill,
            intent,
            outcome,
            policy,
            binding=binding,
            session_date=object.__getattribute__(fill, "session_date"),
            remaining_quantity=remaining,
            cumulative_quantity=cumulative,
        )
    except Exception as caught:
        error = caught
    if error is not None:
        code = (
            object.__getattribute__(error, "reason_code")
            if type(error) is OrderInputError
            else None
        )
        _reject(code if type(code) is str and code in _REASONS else "fill_invalid")
    if type(checked) is not Fill:
        _reject("fill_invalid")
    return checked


@dataclass(frozen=True, slots=True)
class ObligationBalance:
    obligation_id: str
    kind: str
    amount_created: Decimal
    amount_remaining: Decimal
    due_at: datetime
    economic_time: datetime


@dataclass(frozen=True, slots=True)
class IntentOwnership:
    intent_id: str
    intent_hash: str
    instrument_id: str
    side: str
    quantity: Decimal
    cumulative_quantity: Decimal
    cumulative_fee: Decimal
    policy_version: str
    fee_policy_id: str
    fixed_share_cap: Decimal
    last_session_date: date
    terminal: bool
    time_in_force: str
    fill_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionCapOwnership:
    instrument_id: str
    session_date: date
    filled_quantity: Decimal
    fixed_share_cap: Decimal
    policy_version: str
    fee_policy_id: str


class LedgerBalance:
    """Read-only defensive accounting snapshot. Instances are ledger-issued."""

    __slots__ = (
        "schema_version", "numeric_policy_version", "run_id", "calendar_id", "currency",
        "opening_cash", "opening_time", "resolution_cutoff", "start_sequence", "cash",
        "positions", "receivables", "liabilities", "obligations", "recognized_income",
        "recognized_expense", "total_fees", "intent_ownership", "session_cap_ownership",
        "fill_ids", "instrument_ids", "event_count", "next_sequence", "genesis_hash",
        "prefix_hashes", "latest_economic_time", "latest_observation_time", "_canonical",
        "_witness", "_seal", "_prefix_witness",
    )

    def __init__(self, *_: object, **__: object) -> None:
        _reject("input_invalid", TypeError)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("LedgerBalance is immutable")

    def __repr__(self) -> str:
        return "LedgerBalance(<sealed>)"

    def __eq__(self, other: object) -> bool:
        if type(other) is not LedgerBalance:
            return False
        left = _verify_balance(self)
        right = _verify_balance(other)
        return left == right

    def __deepcopy__(self, memo: dict[int, object]) -> LedgerBalance:
        del memo
        return _clone_balance(self)

    @property
    def outstanding_obligations(self) -> tuple[ObligationBalance, ...]:
        _verify_balance(self)
        return tuple(item for item in self.obligations if item.amount_remaining > 0)

    def canonical_bytes(self) -> bytes:
        return _verify_balance(self)[0]


def _balance_wire(balance: LedgerBalance) -> dict[str, object]:
    return {
        "calendar_id": balance.calendar_id,
        "cash": _decimal_wire(balance.cash),
        "currency": balance.currency,
        "event_count": balance.event_count,
        "fill_ids": list(balance.fill_ids),
        "genesis_hash": balance.genesis_hash,
        "instrument_ids": list(balance.instrument_ids),
        "intent_ownership": [
            {
                "cumulative_fee": _decimal_wire(item.cumulative_fee),
                "cumulative_quantity": _decimal_wire(item.cumulative_quantity),
                "fee_policy_id": item.fee_policy_id,
                "fill_ids": list(item.fill_ids),
                "fixed_share_cap": _decimal_wire(item.fixed_share_cap),
                "instrument_id": item.instrument_id,
                "intent_hash": item.intent_hash,
                "intent_id": item.intent_id,
                "last_session_date": item.last_session_date.isoformat(),
                "policy_version": item.policy_version,
                "quantity": _decimal_wire(item.quantity),
                "side": item.side,
                "terminal": item.terminal,
                "time_in_force": item.time_in_force,
            }
            for item in balance.intent_ownership
        ],
        "latest_economic_time": None if balance.latest_economic_time is None else _time_wire(balance.latest_economic_time),
        "latest_observation_time": None if balance.latest_observation_time is None else _time_wire(balance.latest_observation_time),
        "liabilities": _decimal_wire(balance.liabilities),
        "numeric_policy_version": balance.numeric_policy_version,
        "obligations": [
            {
                "amount_created": _decimal_wire(item.amount_created),
                "amount_remaining": _decimal_wire(item.amount_remaining),
                "due_at": _time_wire(item.due_at),
                "economic_time": _time_wire(item.economic_time),
                "kind": item.kind,
                "obligation_id": item.obligation_id,
            }
            for item in balance.obligations
        ],
        "opening_cash": _decimal_wire(balance.opening_cash),
        "opening_time": _time_wire(balance.opening_time),
        "positions": [[instrument, _decimal_wire(quantity)] for instrument, quantity in balance.positions],
        "prefix_count": len(balance.prefix_hashes),
        "prefix_tail": balance.genesis_hash if not balance.prefix_hashes else balance.prefix_hashes[-1],
        "recognized_expense": _decimal_wire(balance.recognized_expense),
        "recognized_income": _decimal_wire(balance.recognized_income),
        "receivables": _decimal_wire(balance.receivables),
        "resolution_cutoff": _time_wire(balance.resolution_cutoff),
        "run_id": balance.run_id,
        "schema_version": balance.schema_version,
        "session_cap_ownership": [
            {
                "fee_policy_id": item.fee_policy_id,
                "filled_quantity": _decimal_wire(item.filled_quantity),
                "fixed_share_cap": _decimal_wire(item.fixed_share_cap),
                "instrument_id": item.instrument_id,
                "policy_version": item.policy_version,
                "session_date": item.session_date.isoformat(),
            }
            for item in balance.session_cap_ownership
        ],
        "start_sequence": balance.start_sequence,
        "total_fees": _decimal_wire(balance.total_fees),
        "next_sequence": balance.next_sequence,
    }


def _balance_witness(balance: LedgerBalance) -> tuple[object, ...]:
    return (
        _decimal_storage(balance.opening_cash),
        _time_native(balance.opening_time),
        _time_native(balance.resolution_cutoff),
        _decimal_storage(balance.cash),
        tuple((item, _decimal_storage(quantity)) for item, quantity in balance.positions),
        _decimal_storage(balance.receivables),
        _decimal_storage(balance.liabilities),
        tuple(
            (item.obligation_id, item.kind, _decimal_storage(item.amount_created), _decimal_storage(item.amount_remaining), _time_native(item.due_at), _time_native(item.economic_time))
            for item in balance.obligations
        ),
        _decimal_storage(balance.recognized_income),
        _decimal_storage(balance.recognized_expense),
        _decimal_storage(balance.total_fees),
        tuple(
            (item.intent_id, item.intent_hash, item.instrument_id, item.side, _decimal_storage(item.quantity), _decimal_storage(item.cumulative_quantity), _decimal_storage(item.cumulative_fee), item.policy_version, item.fee_policy_id, _decimal_storage(item.fixed_share_cap), item.last_session_date.isoformat(), item.terminal, item.time_in_force, item.fill_ids)
            for item in balance.intent_ownership
        ),
        tuple(
            (item.instrument_id, item.session_date.isoformat(), _decimal_storage(item.filled_quantity), _decimal_storage(item.fixed_share_cap), item.policy_version, item.fee_policy_id)
            for item in balance.session_cap_ownership
        ),
        balance.fill_ids,
        balance.instrument_ids,
        balance.event_count,
        balance.next_sequence,
        balance.genesis_hash,
        len(balance.prefix_hashes),
        balance.genesis_hash if not balance.prefix_hashes else balance.prefix_hashes[-1],
        None if balance.latest_economic_time is None else _time_native(balance.latest_economic_time),
        None if balance.latest_observation_time is None else _time_native(balance.latest_observation_time),
        hashlib.sha256(_canonical_json(list(balance.prefix_hashes))).digest(),
    )


def _seal_balance(balance: LedgerBalance) -> None:
    object.__setattr__(balance, "_prefix_witness", balance.prefix_hashes)
    canonical = _canonical_json(_balance_wire(balance))
    witness = _balance_witness(balance)
    witness_bytes = _canonical_json(_jsonable(witness))
    seal = hashlib.sha256(_BALANCE_DOMAIN + canonical + witness_bytes).digest()
    object.__setattr__(balance, "_canonical", canonical)
    object.__setattr__(balance, "_witness", witness)
    object.__setattr__(balance, "_seal", seal)


def _native_tuple(value: object, maximum: int) -> tuple[object, ...]:
    if type(value) is not tuple:
        _reject("source_changed")
    if len(value) > maximum:
        _reject("resource_limit")
    return value


def _native_balance(balance: LedgerBalance) -> None:
    """Guard every native field before traversal, comparison or wire formatting."""

    for name, expected in (("schema_version", _SCHEMA_VERSION),
                           ("numeric_policy_version", _NUMERIC_POLICY_VERSION),
                           ("currency", "USD")):
        value = object.__getattribute__(balance, name)
        if type(value) is not str or value != expected:
            _reject("source_changed")
    for name in ("run_id", "calendar_id"):
        _safe_identifier(object.__getattribute__(balance, name))
    for name in ("opening_cash", "cash", "receivables", "liabilities",
                 "recognized_income", "recognized_expense", "total_fees"):
        _decimal_checked(object.__getattribute__(balance, name), "money", nonnegative=True)
    for name in ("opening_time", "resolution_cutoff"):
        _safe_utc(object.__getattribute__(balance, name))
    for name in ("latest_economic_time", "latest_observation_time"):
        value = object.__getattribute__(balance, name)
        if value is not None:
            _safe_utc(value)
    for name in ("start_sequence", "next_sequence"):
        _sequence_value(object.__getattribute__(balance, name))
    count = object.__getattribute__(balance, "event_count")
    if type(count) is not int or not 0 <= count <= _MAX_EVENTS:
        _reject("source_changed")
    _safe_hash(object.__getattribute__(balance, "genesis_hash"))
    prefixes = _native_tuple(object.__getattribute__(balance, "prefix_hashes"), _MAX_EVENTS)
    saved_prefixes = _native_tuple(object.__getattribute__(balance, "_prefix_witness"), _MAX_EVENTS)
    for value in prefixes + saved_prefixes:
        _safe_hash(value)
    if len(prefixes) != count or prefixes != saved_prefixes:
        _reject("source_changed")
    positions = _native_tuple(object.__getattribute__(balance, "positions"), _MAX_INSTRUMENTS)
    for position in positions:
        if type(position) is not tuple or len(position) != 2:
            _reject("source_changed")
        _safe_identifier(position[0])
        _decimal_checked(position[1], "holding", positive=True)
    for name, maximum in (("fill_ids", _MAX_EVENTS), ("instrument_ids", _MAX_INSTRUMENTS)):
        for value in _native_tuple(object.__getattribute__(balance, name), maximum):
            _safe_identifier(value)
    obligations = _native_tuple(object.__getattribute__(balance, "obligations"), _MAX_OBLIGATIONS)
    for item in obligations:
        if type(item) is not ObligationBalance:
            _reject("source_changed")
        _safe_identifier(item.obligation_id)
        if type(item.kind) is not str or item.kind not in ("receivable", "liability"):
            _reject("source_changed")
        _decimal_checked(item.amount_created, "money", positive=True)
        _decimal_checked(item.amount_remaining, "money", nonnegative=True)
        _safe_utc(item.due_at)
        _safe_utc(item.economic_time)
    owners = _native_tuple(object.__getattribute__(balance, "intent_ownership"), _MAX_INTENTS)
    for item in owners:
        if type(item) is not IntentOwnership:
            _reject("source_changed")
        for value in (item.intent_id, item.instrument_id, item.policy_version, item.fee_policy_id):
            _safe_identifier(value)
        _safe_hash(item.intent_hash)
        if type(item.side) is not str or item.side not in ("buy", "sell"):
            _reject("source_changed")
        if type(item.time_in_force) is not str or item.time_in_force not in ("day", "gtc", "ioc", "fok"):
            _reject("source_changed")
        if type(item.terminal) is not bool:
            _reject("source_changed")
        for value in (item.quantity, item.cumulative_quantity, item.fixed_share_cap):
            _decimal_checked(value, "quantity", positive=True)
        _decimal_checked(item.cumulative_fee, "money", nonnegative=True)
        _safe_date(item.last_session_date)
        for value in _native_tuple(item.fill_ids, _MAX_EVENTS):
            _safe_identifier(value)
    caps = _native_tuple(object.__getattribute__(balance, "session_cap_ownership"), _MAX_CAP_SLOTS)
    for item in caps:
        if type(item) is not SessionCapOwnership:
            _reject("source_changed")
        for value in (item.instrument_id, item.policy_version, item.fee_policy_id):
            _safe_identifier(value)
        _safe_date(item.session_date)
        _decimal_checked(item.filled_quantity, "quantity", positive=True)
        _decimal_checked(item.fixed_share_cap, "quantity", positive=True)


def _verify_balance(balance: object) -> tuple[bytes, tuple[object, ...]]:
    if type(balance) is not LedgerBalance:
        _reject()
    return _capture_call(lambda: _verify_balance_native(balance), "source_changed")


def _verify_balance_native(balance: LedgerBalance) -> tuple[bytes, tuple[object, ...]]:
    saved_canonical = _saved_bytes(object.__getattribute__(balance, "_canonical"), _MAX_RETAINED_BYTES)
    saved_witness = object.__getattribute__(balance, "_witness")
    if type(saved_witness) is not tuple:
        _reject("source_changed")
    _safe_saved(saved_witness)
    saved_seal = _saved_bytes(object.__getattribute__(balance, "_seal"), 32)
    _native_balance(balance)
    payload = _canonical_json(_balance_wire(balance))
    witness = _balance_witness(balance)
    witness_bytes = _canonical_json(_jsonable(witness))
    seal = hashlib.sha256(_BALANCE_DOMAIN + payload + witness_bytes).digest()
    if payload != saved_canonical or not _native_witness_equal(witness, saved_witness) or seal != saved_seal:
        _reject("source_changed")
    return payload, witness


def _make_balance(**values: object) -> LedgerBalance:
    balance = object.__new__(LedgerBalance)
    for name in (
        "schema_version", "numeric_policy_version", "run_id", "calendar_id", "currency", "opening_cash",
        "opening_time", "resolution_cutoff", "start_sequence", "cash", "positions", "receivables",
        "liabilities", "obligations", "recognized_income", "recognized_expense", "total_fees",
        "intent_ownership", "session_cap_ownership", "fill_ids", "instrument_ids", "event_count",
        "next_sequence", "genesis_hash", "prefix_hashes", "latest_economic_time", "latest_observation_time",
    ):
        if name not in values:
            _reject("accounting_invalid")
        object.__setattr__(balance, name, values[name])
    _seal_balance(balance)
    return balance


@dataclass(frozen=True, slots=True)
class _ObligationState:
    obligation_id: str
    kind: str
    amount_created: Decimal
    amount_remaining: Decimal
    due_at: datetime
    economic_time: datetime


@dataclass(frozen=True, slots=True)
class _IntentState:
    intent: OrderIntent
    intent_bytes: bytes
    intent_storage: tuple[object, ...]
    policy: CostPolicy
    policy_bytes: bytes
    policy_storage: tuple[object, ...]
    cumulative_quantity: Decimal
    cumulative_fee: Decimal
    last_session_date: date
    terminal: bool
    fill_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _CapState:
    filled_quantity: Decimal
    fixed_share_cap: Decimal
    policy_bytes: bytes
    policy_storage: tuple[object, ...]
    policy_version: str
    fee_policy_id: str


@dataclass(frozen=True, slots=True)
class _LedgerState:
    run_id: str
    calendar_id: str
    currency: str
    opening_cash: Decimal
    opening_time: datetime
    resolution_cutoff: datetime
    start_sequence: int
    cash: Decimal
    positions: dict[str, Decimal]
    obligations: dict[str, _ObligationState]
    recognized_income: Decimal
    recognized_expense: Decimal
    total_fees: Decimal
    intents: dict[str, _IntentState]
    cap_slots: dict[tuple[str, date], _CapState]
    fill_ids: frozenset[str]
    instrument_ids: frozenset[str]
    event_ids: dict[str, tuple[bytes, tuple[object, ...]]]
    events: tuple[LedgerEvent, ...]
    prefix_hashes: tuple[str, ...]
    genesis_hash: str
    latest_economic_time: datetime | None
    latest_observation_time: datetime | None
    retained_size: int
    balance: LedgerBalance


def _genesis_hash(
    run_id: str,
    calendar_id: str,
    currency: str,
    opening_cash: Decimal,
    opening_time: datetime,
    resolution_cutoff: datetime,
    start_sequence: int,
) -> str:
    payload = {
        "calendar_id": calendar_id,
        "currency": currency,
        "numeric_policy_version": _NUMERIC_POLICY_VERSION,
        "opening_cash": _decimal_wire(opening_cash),
        "opening_time": _time_wire(opening_time),
        "resolution_cutoff": _time_wire(resolution_cutoff),
        "run_id": run_id,
        "schema_version": _SCHEMA_VERSION,
        "start_sequence": start_sequence,
    }
    return "sha256:" + hashlib.sha256(_GENESIS_DOMAIN + _canonical_json(payload)).hexdigest()


def _public_obligations(values: dict[str, _ObligationState]) -> tuple[ObligationBalance, ...]:
    return tuple(
        ObligationBalance(
            obligation_id=value.obligation_id,
            kind=value.kind,
            amount_created=value.amount_created,
            amount_remaining=value.amount_remaining,
            due_at=value.due_at,
            economic_time=value.economic_time,
        )
        for _, value in sorted(values.items())
    )


def _public_intents(values: dict[str, _IntentState]) -> tuple[IntentOwnership, ...]:
    result: list[IntentOwnership] = []
    for _, value in sorted(values.items()):
        intent = value.intent
        policy = value.policy
        result.append(
            IntentOwnership(
                intent_id=object.__getattribute__(intent, "intent_id"),
                intent_hash=object.__getattribute__(intent, "intent_hash"),
                instrument_id=object.__getattribute__(intent, "instrument_id"),
                side=object.__getattribute__(intent, "side"),
                quantity=object.__getattribute__(intent, "quantity"),
                cumulative_quantity=value.cumulative_quantity,
                cumulative_fee=value.cumulative_fee,
                policy_version=object.__getattribute__(policy, "policy_version"),
                fee_policy_id=object.__getattribute__(policy, "fee_policy_id"),
                fixed_share_cap=object.__getattribute__(policy, "fixed_share_cap"),
                last_session_date=value.last_session_date,
                terminal=value.terminal,
                time_in_force=object.__getattribute__(intent, "time_in_force"),
                fill_ids=value.fill_ids,
            )
        )
    return tuple(result)


def _public_caps(values: dict[tuple[str, date], _CapState]) -> tuple[SessionCapOwnership, ...]:
    return tuple(
        SessionCapOwnership(
            instrument_id=instrument,
            session_date=session,
            filled_quantity=value.filled_quantity,
            fixed_share_cap=value.fixed_share_cap,
            policy_version=value.policy_version,
            fee_policy_id=value.fee_policy_id,
        )
        for (instrument, session), value in sorted(values.items())
    )


def _balance_from_state(state: _LedgerState, *, event_count: int, next_sequence: int, prefixes: tuple[str, ...], cash: Decimal, positions: dict[str, Decimal], obligations: dict[str, _ObligationState], recognized_income: Decimal, recognized_expense: Decimal, total_fees: Decimal, intents: dict[str, _IntentState], cap_slots: dict[tuple[str, date], _CapState], fill_ids: frozenset[str], instrument_ids: frozenset[str], latest_economic_time: datetime | None, latest_observation_time: datetime | None) -> LedgerBalance:
    receivables = _exact_decimal(lambda: sum((item.amount_remaining for item in obligations.values() if item.kind == "receivable"), Decimal(0)))
    liabilities = _exact_decimal(lambda: sum((item.amount_remaining for item in obligations.values() if item.kind == "liability"), Decimal(0)))
    _decimal_checked(receivables, "money", nonnegative=True)
    _decimal_checked(liabilities, "money", nonnegative=True)
    return _make_balance(
        schema_version=_SCHEMA_VERSION,
        numeric_policy_version=_NUMERIC_POLICY_VERSION,
        run_id=state.run_id,
        calendar_id=state.calendar_id,
        currency=state.currency,
        opening_cash=state.opening_cash,
        opening_time=state.opening_time,
        resolution_cutoff=state.resolution_cutoff,
        start_sequence=state.start_sequence,
        cash=cash,
        positions=tuple((key, positions[key]) for key in sorted(positions) if positions[key] != 0),
        receivables=receivables,
        liabilities=liabilities,
        obligations=_public_obligations(obligations),
        recognized_income=recognized_income,
        recognized_expense=recognized_expense,
        total_fees=total_fees,
        intent_ownership=_public_intents(intents),
        session_cap_ownership=_public_caps(cap_slots),
        fill_ids=tuple(sorted(fill_ids)),
        instrument_ids=tuple(sorted(instrument_ids)),
        event_count=event_count,
        next_sequence=next_sequence,
        genesis_hash=state.genesis_hash,
        prefix_hashes=prefixes,
        latest_economic_time=latest_economic_time,
        latest_observation_time=latest_observation_time,
    )


def _clone_balance(balance: LedgerBalance) -> LedgerBalance:
    _verify_balance(balance)
    values = {
        name: object.__getattribute__(balance, name)
        for name in LedgerBalance.__slots__
        if not name.startswith("_")
    }
    for name, record_type in (("obligations", ObligationBalance),
                              ("intent_ownership", IntentOwnership),
                              ("session_cap_ownership", SessionCapOwnership)):
        values[name] = tuple(
            record_type(*(object.__getattribute__(item, field) for field in record_type.__slots__))
            for item in values[name]
        )
    return _make_balance(**values)


def _state_from(
    *, run_id: str, calendar_id: str, opening_cash: Decimal, opening_time: datetime,
    resolution_cutoff: datetime, start_sequence: int,
) -> _LedgerState:
    genesis = _genesis_hash(run_id, calendar_id, "USD", opening_cash, opening_time, resolution_cutoff, start_sequence)
    provisional = _LedgerState(
        run_id, calendar_id, "USD", opening_cash, opening_time, resolution_cutoff, start_sequence,
        opening_cash, {}, {}, _ZERO, _ZERO, _ZERO, {}, {}, frozenset(), frozenset(), {}, (), (), genesis,
        None, None, 0, None,  # type: ignore[arg-type]
    )
    balance = _balance_from_state(
        provisional, event_count=0, next_sequence=start_sequence, prefixes=(), cash=opening_cash,
        positions={}, obligations={}, recognized_income=_ZERO, recognized_expense=_ZERO,
        total_fees=_ZERO, intents={}, cap_slots={}, fill_ids=frozenset(), instrument_ids=frozenset(),
        latest_economic_time=None, latest_observation_time=None,
    )
    return _LedgerState(
        run_id, calendar_id, "USD", opening_cash, opening_time, resolution_cutoff, start_sequence,
        opening_cash, {}, {}, _ZERO, _ZERO, _ZERO, {}, {}, frozenset(), frozenset(), {}, (), (), genesis,
        None, None, 0, balance,
    )


def _obligation_totals(obligations: dict[str, _ObligationState]) -> tuple[Decimal, Decimal]:
    receivables = _exact_decimal(lambda: sum((item.amount_remaining for item in obligations.values() if item.kind == "receivable"), Decimal(0)))
    liabilities = _exact_decimal(lambda: sum((item.amount_remaining for item in obligations.values() if item.kind == "liability"), Decimal(0)))
    return _decimal_checked(receivables, "money", nonnegative=True), _decimal_checked(liabilities, "money", nonnegative=True)


def _fee_due_checked(cumulative: Decimal, policy: CostPolicy) -> Decimal:
    failed = False
    result = Decimal(0)
    try:
        result = _fee_due(
            cumulative,
            object.__getattribute__(policy, "commission_per_share"),
            object.__getattribute__(policy, "order_minimum"),
        )
    except Exception:
        failed = True
    if failed:
        _reject("numeric_invalid")
    return _decimal_checked(result, "money", nonnegative=True)


def _event_fill_parts(event: LedgerEvent) -> tuple[OrderIntent, Fill, SessionBinding, OutcomeEvidence, CostPolicy]:
    return tuple(object.__getattribute__(event, name) for name in ("_intent", "_fill", "_binding", "_outcome", "_policy"))  # type: ignore[return-value]


def _validate_fill_for_state(event: LedgerEvent, state: _LedgerState, owner: _IntentState | None) -> Fill:
    intent, fill, binding, outcome, policy = _event_fill_parts(event)
    quantity = _decimal_checked(object.__getattribute__(intent, "quantity"), "quantity", positive=True)
    cumulative = _ZERO if owner is None else owner.cumulative_quantity
    before = _decimal_checked(object.__getattribute__(fill, "cumulative_quantity_before"), "quantity", nonnegative=True)
    if before != cumulative or cumulative >= quantity:
        _reject("accounting_invalid")
    remaining = _exact_decimal(lambda: quantity - cumulative)
    checked = _validate_fill(fill, intent, outcome, policy, binding, cumulative, remaining)
    checked, fill_bytes, fill_storage = _contract_record(checked, Fill, "source_changed")
    if fill_bytes != object.__getattribute__(event, "_fill_bytes") or fill_storage != object.__getattribute__(event, "_fill_storage"):
        _reject("source_changed")
    session = _safe_date(object.__getattribute__(checked, "session_date"))
    if owner is not None:
        if owner.terminal or session <= owner.last_session_date:
            _reject("accounting_invalid")
        if object.__getattribute__(owner.intent, "time_in_force") != "gtc":
            _reject("accounting_invalid")
    if object.__getattribute__(checked, "received_at") <= object.__getattribute__(checked, "fill_time"):
        _reject("chronology_invalid")
    if object.__getattribute__(checked, "received_at") > state.resolution_cutoff:
        _reject("chronology_invalid")
    if object.__getattribute__(checked, "fill_time") < state.opening_time:
        _reject("chronology_invalid")
    if state.latest_economic_time is not None and object.__getattribute__(checked, "fill_time") < state.latest_economic_time:
        _reject("chronology_invalid")
    return checked


def _apply_fill(
    state: _LedgerState,
    event: LedgerEvent,
    *,
    positions: dict[str, Decimal],
    intents: dict[str, _IntentState],
    cap_slots: dict[tuple[str, date], _CapState],
    fill_ids: set[str],
    instrument_ids: set[str],
) -> tuple[Decimal, Decimal]:
    intent, fill, binding, outcome, policy = _event_fill_parts(event)
    intent_id = _safe_identifier(object.__getattribute__(intent, "intent_id"))
    fill_id = _safe_identifier(object.__getattribute__(fill, "fill_id"))
    if fill_id in state.fill_ids or fill_id in fill_ids:
        _reject("event_conflict")
    owner = intents.get(intent_id)
    checked = _validate_fill_for_state(event, state, owner)
    intent_bytes = object.__getattribute__(event, "_intent_bytes")
    intent_storage = object.__getattribute__(event, "_intent_storage")
    policy_bytes = object.__getattribute__(event, "_policy_bytes")
    policy_storage = object.__getattribute__(event, "_policy_storage")
    if owner is not None and (
        intent_bytes != owner.intent_bytes
        or intent_storage != owner.intent_storage
        or policy_bytes != owner.policy_bytes
        or policy_storage != owner.policy_storage
    ):
        _reject("accounting_invalid")
    if owner is None and len(intents) >= _MAX_INTENTS:
        _reject("resource_limit")
    instrument = _safe_identifier(object.__getattribute__(checked, "instrument_id"))
    if instrument not in instrument_ids and len(instrument_ids) >= _MAX_INSTRUMENTS:
        _reject("resource_limit")
    session = _safe_date(object.__getattribute__(checked, "session_date"))
    slot_key = (instrument, session)
    fixed_cap = _decimal_checked(object.__getattribute__(policy, "fixed_share_cap"), "quantity", positive=True)
    slot = cap_slots.get(slot_key)
    if slot is not None and (slot.policy_bytes != policy_bytes or slot.policy_storage != policy_storage):
        _reject("accounting_invalid")
    if slot is None and len(cap_slots) >= _MAX_CAP_SLOTS:
        _reject("resource_limit")
    filled = _ZERO if slot is None else slot.filled_quantity
    quantity = _decimal_checked(object.__getattribute__(checked, "quantity"), "quantity", positive=True)
    cap_after = _decimal_checked(_exact_decimal(lambda: filled + quantity), "quantity", nonnegative=True)
    if cap_after > fixed_cap:
        _reject("accounting_invalid")

    cumulative = _ZERO if owner is None else owner.cumulative_quantity
    cumulative_after = _decimal_checked(_exact_decimal(lambda: cumulative + quantity), "quantity", positive=True)
    posted_fee = _ZERO if owner is None else owner.cumulative_fee
    expected_prior_fee = _fee_due_checked(cumulative, policy)
    if posted_fee != expected_prior_fee:
        _reject("accounting_invalid")
    expected_after_fee = _fee_due_checked(cumulative_after, policy)
    incremental_fee = _decimal_checked(object.__getattribute__(checked, "fee"), "money", nonnegative=True)
    fee_delta = _decimal_checked(_exact_decimal(lambda: expected_after_fee - posted_fee), "money", nonnegative=True)
    if incremental_fee != fee_delta:
        _reject("accounting_invalid")
    price = _decimal_checked(object.__getattribute__(checked, "price"), "execution", positive=True)
    notional = _exact_decimal(lambda: quantity * price)
    signed = notional if object.__getattribute__(checked, "side") == "buy" else notional.copy_negate()
    cash = _exact_decimal(lambda: state.cash - signed - incremental_fee)
    cash = _decimal_checked(cash, "money", nonnegative=True)
    before_position = positions.get(instrument, _ZERO)
    delta_quantity = quantity if object.__getattribute__(checked, "side") == "buy" else quantity.copy_negate()
    after_position = _decimal_checked(_exact_decimal(lambda: before_position + delta_quantity), "holding", nonnegative=True)
    if after_position == 0:
        positions.pop(instrument, None)
    else:
        positions[instrument] = after_position
    total_fees = _decimal_checked(_exact_decimal(lambda: state.total_fees + incremental_fee), "money", nonnegative=True)
    fill_ids.add(fill_id)
    instrument_ids.add(instrument)
    till = object.__getattribute__(intent, "quantity")
    tif = object.__getattribute__(intent, "time_in_force")
    terminal = cumulative_after >= till or tif in ("day", "ioc", "fok")
    prior_fill_ids = () if owner is None else owner.fill_ids
    new_owner = _IntentState(
        intent=intent,
        intent_bytes=intent_bytes,
        intent_storage=intent_storage,
        policy=policy,
        policy_bytes=policy_bytes,
        policy_storage=policy_storage,
        cumulative_quantity=cumulative_after,
        cumulative_fee=expected_after_fee,
        last_session_date=session,
        terminal=terminal,
        fill_ids=prior_fill_ids + (fill_id,),
    )
    intents[intent_id] = new_owner
    cap_slots[slot_key] = _CapState(
        filled_quantity=cap_after,
        fixed_share_cap=fixed_cap,
        policy_bytes=policy_bytes,
        policy_storage=policy_storage,
        policy_version=object.__getattribute__(policy, "policy_version"),
        fee_policy_id=object.__getattribute__(policy, "fee_policy_id"),
    )
    return cash, total_fees


def _apply_obligation(
    state: _LedgerState,
    event: LedgerEvent,
    *,
    obligations: dict[str, _ObligationState],
    cash: Decimal,
    recognized_income: Decimal,
    recognized_expense: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    kind = object.__getattribute__(event, "_kind")
    obligation_id = _safe_identifier(object.__getattribute__(event, "_obligation_id"))
    amount = _decimal_checked(object.__getattribute__(event, "_amount"), "money", positive=True)
    economic_time = _safe_utc(object.__getattribute__(event, "_economic_time"))
    due_at = _safe_utc(object.__getattribute__(event, "_due_at"))
    prior = obligations.get(obligation_id)
    if kind.endswith("_create"):
        if prior is not None:
            _reject("obligation_invalid")
        if len(obligations) >= _MAX_OBLIGATIONS:
            _reject("resource_limit")
        obligation_kind = "receivable" if kind.startswith("receivable") else "liability"
        obligations[obligation_id] = _ObligationState(
            obligation_id, obligation_kind, amount, amount, due_at, economic_time
        )
        if obligation_kind == "receivable":
            recognized_income = _decimal_checked(_exact_decimal(lambda: recognized_income + amount), "money", nonnegative=True)
        else:
            recognized_expense = _decimal_checked(_exact_decimal(lambda: recognized_expense + amount), "money", nonnegative=True)
        return cash, recognized_income, recognized_expense
    if prior is None:
        _reject("obligation_invalid")
    expected_kind = "receivable" if kind.startswith("receivable") else "liability"
    if prior.kind != expected_kind or prior.due_at != due_at or economic_time < prior.due_at or amount > prior.amount_remaining:
        _reject("obligation_invalid")
    remaining = _decimal_checked(_exact_decimal(lambda: prior.amount_remaining - amount), "money", nonnegative=True)
    obligations[obligation_id] = _ObligationState(
        prior.obligation_id, prior.kind, prior.amount_created, remaining, prior.due_at, prior.economic_time
    )
    if expected_kind == "receivable":
        cash = _decimal_checked(_exact_decimal(lambda: cash + amount), "money", nonnegative=True)
    else:
        cash = _decimal_checked(_exact_decimal(lambda: cash - amount), "money", nonnegative=True)
    return cash, recognized_income, recognized_expense


def _cap_retained_size(values: dict[tuple[str, date], _CapState]) -> int:
    """Account for the bounded slot keys and exact native ownership records."""

    return len(_canonical_json([
        [instrument, session.isoformat(), _decimal_storage(item.filled_quantity),
         _decimal_storage(item.fixed_share_cap), item.policy_bytes.decode("utf-8"),
         _jsonable(item.policy_storage), item.policy_version, item.fee_policy_id]
        for (instrument, session), item in sorted(values.items())
    ])) if values else 0


def _proposed_state(state: _LedgerState, event: LedgerEvent, canonical: bytes, witness: tuple[object, ...], retained_size: int) -> _LedgerState:
    kind = object.__getattribute__(event, "_kind")
    events_count = len(state.events) + 1
    if events_count > _MAX_EVENTS or state.start_sequence + events_count > _MAX_SEQUENCE:
        _reject("resource_limit")
    retained = state.retained_size + retained_size
    positions = dict(state.positions)
    obligations = dict(state.obligations)
    intents = dict(state.intents)
    cap_slots = dict(state.cap_slots)
    fill_ids = set(state.fill_ids)
    instrument_ids = set(state.instrument_ids)
    cash = state.cash
    fees = state.total_fees
    income = state.recognized_income
    expense = state.recognized_expense
    if kind == "fill":
        cash, fees = _apply_fill(
            state, event, positions=positions, intents=intents, cap_slots=cap_slots,
            fill_ids=fill_ids, instrument_ids=instrument_ids,
        )
    else:
        cash, income, expense = _apply_obligation(
            state, event, obligations=obligations, cash=cash,
            recognized_income=income, recognized_expense=expense,
        )
    retained += _cap_retained_size(cap_slots) - _cap_retained_size(state.cap_slots)
    if retained > _MAX_RETAINED_BYTES:
        _reject("resource_limit")
    economic_time = _safe_utc(object.__getattribute__(event, "_economic_time"))
    observed_at = _safe_utc(object.__getattribute__(event, "_observed_at"))
    if economic_time < state.opening_time or economic_time > state.resolution_cutoff or observed_at > state.resolution_cutoff:
        _reject("chronology_invalid")
    if state.latest_economic_time is not None and economic_time < state.latest_economic_time:
        _reject("chronology_invalid")
    latest_observation = observed_at if state.latest_observation_time is None else max(state.latest_observation_time, observed_at)
    event_copy = event
    prefix = _prefix_hash(object.__getattribute__(event, "_previous_hash"), canonical)
    event_ids = dict(state.event_ids)
    event_ids[object.__getattribute__(event, "_event_id")] = (canonical, witness)
    events = state.events + (event_copy,)
    prefixes = state.prefix_hashes + (prefix,)
    provisional = _LedgerState(
        state.run_id, state.calendar_id, state.currency, state.opening_cash, state.opening_time,
        state.resolution_cutoff, state.start_sequence, cash, positions, obligations, income, expense,
        fees, intents, cap_slots, frozenset(fill_ids), frozenset(instrument_ids), event_ids,
        events, prefixes, state.genesis_hash, economic_time, latest_observation, retained, state.balance,
    )
    balance = _balance_from_state(
        provisional, event_count=events_count, next_sequence=state.start_sequence + events_count,
        prefixes=prefixes, cash=cash, positions=positions, obligations=obligations,
        recognized_income=income, recognized_expense=expense, total_fees=fees, intents=intents,
        cap_slots=cap_slots, fill_ids=frozenset(fill_ids), instrument_ids=frozenset(instrument_ids),
        latest_economic_time=economic_time, latest_observation_time=latest_observation,
    )
    next_state = _LedgerState(
        state.run_id, state.calendar_id, state.currency, state.opening_cash, state.opening_time,
        state.resolution_cutoff, state.start_sequence, cash, positions, obligations, income, expense,
        fees, intents, cap_slots, frozenset(fill_ids), frozenset(instrument_ids), event_ids,
        events, prefixes, state.genesis_hash, economic_time, latest_observation, retained, balance,
    )
    return next_state


def _clone_state_snapshot(state: _LedgerState) -> LedgerBalance:
    return _clone_balance(state.balance)


class Ledger:
    """Atomic, in-memory append/replay ledger for retrospective USD accounting."""

    __slots__ = ("_state", "_lock", "_mutation_owner")

    def __init__(
        self,
        *,
        run_id: object = _MISSING,
        calendar_id: object = _MISSING,
        currency: object = _MISSING,
        opening_cash: object = _MISSING,
        opening_time: object = _MISSING,
        resolution_cutoff: object = _MISSING,
        start_sequence: object = 0,
        **unknown: object,
    ) -> None:
        if unknown:
            _reject("input_invalid", TypeError)
        run = _safe_identifier(run_id)
        calendar = _safe_identifier(calendar_id)
        if type(currency) is not str or currency != "USD":
            _reject()
        cash = _decimal_checked(opening_cash, "money", nonnegative=True)
        opened = _safe_utc(opening_time)
        cutoff = _safe_utc(resolution_cutoff)
        sequence = _sequence_value(start_sequence)
        if opened > cutoff:
            _reject("chronology_invalid")
        state = _state_from(
            run_id=run,
            calendar_id=calendar,
            opening_cash=cash,
            opening_time=opened,
            resolution_cutoff=cutoff,
            start_sequence=sequence,
        )
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_mutation_owner", None)

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("Ledger is immutable")

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            state = object.__getattribute__(self, "_state")
            return tuple(_clone_event(event) for event in state.events)

    def balance(self) -> LedgerBalance:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            return _clone_state_snapshot(object.__getattribute__(self, "_state"))

    def append(self, event: object) -> LedgerBalance:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            owner = object.__getattribute__(self, "_mutation_owner")
            current_thread = threading.get_ident()
            if owner == current_thread:
                _reject("accounting_invalid")
            object.__setattr__(self, "_mutation_owner", current_thread)
            try:
                return self._append_locked(event, return_public=True)
            finally:
                object.__setattr__(self, "_mutation_owner", None)

    def replay(self, events: object) -> LedgerBalance:
        lock = object.__getattribute__(self, "_lock")
        with lock:
            owner = object.__getattribute__(self, "_mutation_owner")
            current_thread = threading.get_ident()
            if owner == current_thread:
                _reject("accounting_invalid")
            if type(events) is not tuple:
                _reject()
            if len(events) > _MAX_EVENTS:
                _reject("resource_limit")
            object.__setattr__(self, "_mutation_owner", current_thread)
            try:
                for event in events:
                    self._append_locked(event, return_public=False)
                return _clone_state_snapshot(object.__getattribute__(self, "_state"))
            finally:
                object.__setattr__(self, "_mutation_owner", None)

    def _append_locked(self, event: object, *, return_public: bool) -> LedgerBalance:
        owned, canonical, witness, retained_size = _capture_event(event)
        state = object.__getattribute__(self, "_state")
        event_id = object.__getattribute__(event, "_event_id")
        prior = state.event_ids.get(event_id)
        if prior is not None:
            if prior[0] != canonical or prior[1] != witness:
                _reject("event_conflict")
            return _clone_state_snapshot(state) if return_public else state.balance
        sequence = object.__getattribute__(event, "_sequence")
        previous = object.__getattribute__(event, "_previous_hash")
        expected_previous = state.prefix_hashes[-1] if state.prefix_hashes else state.genesis_hash
        if sequence != state.start_sequence + len(state.events) or previous != expected_previous:
            _reject("sequence_invalid")
        if (
            object.__getattribute__(event, "_run_id") != state.run_id
            or object.__getattribute__(event, "_calendar_id") != state.calendar_id
            or object.__getattribute__(event, "_currency") != state.currency
        ):
            _reject("binding_mismatch")
        proposed = _proposed_state(state, owned, canonical, witness, retained_size)
        # This import is local to avoid an accounting/ledger import cycle.
        from mytradingalpha.backtest.accounting import AccountingInvariant

        AccountingInvariant._check_proposed(state.balance, owned, proposed.balance, canonical)
        result = _clone_balance(proposed.balance) if return_public else proposed.balance
        # All arithmetic, ownership, output preparation and validation have ended.
        # Recheck both original ingress and the owned validator arguments before
        # the one publication; no reusable cross-operation trust flag exists.
        if _verify_event(event) != (canonical, witness, retained_size):
            _reject("source_changed")
        if _verify_event(owned) != (canonical, witness, retained_size):
            _reject("source_changed")
        object.__setattr__(self, "_state", proposed)
        return result


__all__ = [
    "IntentOwnership",
    "Ledger",
    "LedgerBalance",
    "LedgerEvent",
    "LedgerInputError",
    "ObligationBalance",
    "SessionCapOwnership",
]
