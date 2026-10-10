"""Independent transition checks for BT-03 ledger balances."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .ledger import (
    _OBLIGATION_KINDS,
    LedgerBalance,
    LedgerEvent,
    _capture_event,
    _clone_balance,
    _decimal_checked,
    _event_fill_parts,
    _exact_decimal,
    _fee_due_checked,
    _prefix_hash,
    _reject,
    _safe_date,
    _safe_identifier,
    _safe_utc,
    _verify_balance,
    _verify_event,
)


def _expected_positions(
    before: LedgerBalance, instrument: str, side: str, quantity: Decimal
) -> tuple[tuple[str, Decimal], ...]:
    positions = dict(before.positions)
    current = positions.get(instrument, Decimal(0))
    signed = quantity if side == "buy" else -quantity
    result = _decimal_checked(_exact_decimal(lambda: current + signed), "holding", nonnegative=True)
    if result == 0:
        positions.pop(instrument, None)
    else:
        positions[instrument] = result
    return tuple((key, positions[key]) for key in sorted(positions))


def _intent_record(balance: LedgerBalance, intent_id: str) -> object | None:
    matches = tuple(item for item in balance.intent_ownership if item.intent_id == intent_id)
    if len(matches) > 1:
        _reject("accounting_invalid")
    return None if not matches else matches[0]


def _cap_record(balance: LedgerBalance, instrument_id: str, session_date: object) -> object | None:
    matches = tuple(
        item
        for item in balance.session_cap_ownership
        if item.instrument_id == instrument_id and item.session_date == session_date
    )
    if len(matches) > 1:
        _reject("accounting_invalid")
    return None if not matches else matches[0]


def _expected_fill_owner(before: LedgerBalance, event: LedgerEvent) -> tuple[object, object, Decimal]:
    intent, fill, _binding, _outcome, policy = _event_fill_parts(event)
    intent_id = _safe_identifier(object.__getattribute__(intent, "intent_id"))
    fill_id = _safe_identifier(object.__getattribute__(fill, "fill_id"))
    quantity = _decimal_checked(object.__getattribute__(fill, "quantity"), "quantity", positive=True)
    cumulative_before = _decimal_checked(
        object.__getattribute__(fill, "cumulative_quantity_before"), "quantity", nonnegative=True
    )
    cumulative_after = _decimal_checked(
        object.__getattribute__(fill, "cumulative_quantity_after"), "quantity", positive=True
    )
    fee = _decimal_checked(object.__getattribute__(fill, "fee"), "money", nonnegative=True)
    session = _safe_date(object.__getattribute__(fill, "session_date"))
    instrument = _safe_identifier(object.__getattribute__(fill, "instrument_id"))
    old = _intent_record(before, intent_id)
    expected_before = Decimal(0) if old is None else old.cumulative_quantity
    if cumulative_before != expected_before or cumulative_after != _exact_decimal(lambda: cumulative_before + quantity):
        _reject("accounting_invalid")
    old_fee = Decimal(0) if old is None else old.cumulative_fee
    if old_fee != _fee_due_checked(cumulative_before, policy):
        _reject("accounting_invalid")
    expected_total_fee = _fee_due_checked(cumulative_after, policy)
    fee_delta = _decimal_checked(_exact_decimal(lambda: expected_total_fee - old_fee), "money", nonnegative=True)
    if fee != fee_delta:
        _reject("accounting_invalid")
    old_fill_ids = () if old is None else old.fill_ids
    expected_owner = (
        intent_id,
        object.__getattribute__(intent, "intent_hash"),
        instrument,
        object.__getattribute__(intent, "side"),
        object.__getattribute__(intent, "quantity"),
        cumulative_after,
        expected_total_fee,
        object.__getattribute__(policy, "policy_version"),
        object.__getattribute__(policy, "fee_policy_id"),
        object.__getattribute__(policy, "fixed_share_cap"),
        session,
        cumulative_after == object.__getattribute__(intent, "quantity")
        or object.__getattribute__(intent, "time_in_force") in ("day", "ioc", "fok"),
        object.__getattribute__(intent, "time_in_force"),
        old_fill_ids + (fill_id,),
    )
    slot = _cap_record(before, instrument, session)
    prior_cap_fill = Decimal(0) if slot is None else slot.filled_quantity
    cap_after = _decimal_checked(_exact_decimal(lambda: prior_cap_fill + quantity), "quantity", nonnegative=True)
    expected_cap = (
        instrument,
        session,
        cap_after,
        object.__getattribute__(policy, "fixed_share_cap"),
        object.__getattribute__(policy, "policy_version"),
        object.__getattribute__(policy, "fee_policy_id"),
    )
    return expected_owner, expected_cap, fee


class AccountingInvariant:
    """Checks complete accounting transitions before ledger state publication."""

    __slots__ = ()

    @staticmethod
    def check(
        before: object,
        event: object,
        after: object,
        **unknown: object,
    ) -> None:
        if unknown:
            _reject("input_invalid", TypeError)
        if type(before) is not LedgerBalance or type(after) is not LedgerBalance or type(event) is not LedgerEvent:
            _reject()
        before_owned = _clone_balance(before)
        event_owned, canonical, witness, size = _capture_event(event)
        after_owned = _clone_balance(after)
        AccountingInvariant._check_proposed(before_owned, event_owned, after_owned, canonical)
        if (
            _verify_balance(before) != (before_owned._canonical, before_owned._witness)
            or _verify_event(event) != (canonical, witness, size)
            or _verify_balance(after) != (after_owned._canonical, after_owned._witness)
        ):
            _reject("source_changed")
        return None

    @staticmethod
    def _check_proposed(
        before: LedgerBalance, event: LedgerEvent, after: LedgerBalance, canonical: bytes
    ) -> None:
        """Recompute transitions from private, operation-owned verified inputs."""

        sequence = object.__getattribute__(event, "_sequence")
        previous_hash = object.__getattribute__(event, "_previous_hash")
        expected_previous = before.prefix_hashes[-1] if before.prefix_hashes else before.genesis_hash
        if (
            before.run_id != after.run_id
            or before.calendar_id != after.calendar_id
            or before.currency != after.currency
            or before.opening_cash != after.opening_cash
            or before.opening_time != after.opening_time
            or before.resolution_cutoff != after.resolution_cutoff
            or before.start_sequence != after.start_sequence
            or object.__getattribute__(event, "_run_id") != before.run_id
            or object.__getattribute__(event, "_calendar_id") != before.calendar_id
            or object.__getattribute__(event, "_currency") != before.currency
            or sequence != before.next_sequence
            or previous_hash != expected_previous
            or after.event_count != before.event_count + 1
            or after.next_sequence != before.next_sequence + 1
            or after.genesis_hash != before.genesis_hash
            or after.prefix_hashes != before.prefix_hashes + (_prefix_hash(previous_hash, canonical),)
        ):
            _reject("accounting_invalid")
        kind = object.__getattribute__(event, "_kind")
        economic_time = _safe_utc(object.__getattribute__(event, "_economic_time"))
        observed_at = _safe_utc(object.__getattribute__(event, "_observed_at"))
        if (
            observed_at < economic_time
            or economic_time < before.opening_time
            or economic_time > before.resolution_cutoff
            or observed_at > before.resolution_cutoff
            or (before.latest_economic_time is not None and economic_time < before.latest_economic_time)
        ):
            _reject("accounting_invalid")
        expected_latest_observation = (
            observed_at
            if before.latest_observation_time is None or observed_at > before.latest_observation_time
            else before.latest_observation_time
        )
        if after.latest_economic_time != economic_time or after.latest_observation_time != expected_latest_observation:
            _reject("accounting_invalid")

        if kind == "fill":
            intent, fill, _binding, _outcome, policy = _event_fill_parts(event)
            instrument = _safe_identifier(object.__getattribute__(fill, "instrument_id"))
            side = object.__getattribute__(fill, "side")
            quantity = _decimal_checked(object.__getattribute__(fill, "quantity"), "quantity", positive=True)
            price = _decimal_checked(object.__getattribute__(fill, "price"), "execution", positive=True)
            fee = _decimal_checked(object.__getattribute__(fill, "fee"), "money", nonnegative=True)
            notional = _exact_decimal(lambda: quantity * price)
            signed = notional if side == "buy" else -notional
            expected_cash = _decimal_checked(_exact_decimal(lambda: before.cash - signed - fee), "money", nonnegative=True)
            expected_positions = _expected_positions(before, instrument, side, quantity)
            expected_fees = _decimal_checked(_exact_decimal(lambda: before.total_fees + fee), "money", nonnegative=True)
            if (
                after.cash != expected_cash
                or after.positions != expected_positions
                or after.total_fees != expected_fees
                or after.receivables != before.receivables
                or after.liabilities != before.liabilities
                or after.obligations != before.obligations
                or after.recognized_income != before.recognized_income
                or after.recognized_expense != before.recognized_expense
            ):
                _reject("accounting_invalid")
            expected_owner, expected_cap, _ = _expected_fill_owner(before, event)
            owner = _intent_record(after, expected_owner[0])
            if owner is None or (
                owner.intent_id, owner.intent_hash, owner.instrument_id, owner.side, owner.quantity,
                owner.cumulative_quantity, owner.cumulative_fee, owner.policy_version, owner.fee_policy_id,
                owner.fixed_share_cap, owner.last_session_date, owner.terminal, owner.time_in_force, owner.fill_ids,
            ) != expected_owner:
                _reject("accounting_invalid")
            cap = _cap_record(after, expected_cap[0], expected_cap[1])
            if cap is None or (
                cap.instrument_id, cap.session_date, cap.filled_quantity, cap.fixed_share_cap,
                cap.policy_version, cap.fee_policy_id,
            ) != expected_cap:
                _reject("accounting_invalid")
            fill_id = _safe_identifier(object.__getattribute__(fill, "fill_id"))
            expected_fill_ids = tuple(sorted(set(before.fill_ids) | {fill_id}))
            expected_instruments = tuple(sorted(set(before.instrument_ids) | {instrument}))
            if after.fill_ids != expected_fill_ids or after.instrument_ids != expected_instruments:
                _reject("accounting_invalid")
            old_owners = {item.intent_id: item for item in before.intent_ownership}
            new_owners = {item.intent_id: item for item in after.intent_ownership}
            if set(new_owners) != set(old_owners) | {expected_owner[0]}:
                _reject("accounting_invalid")
            for key, value in old_owners.items():
                if key != expected_owner[0] and new_owners.get(key) != value:
                    _reject("accounting_invalid")
            old_caps = {(item.instrument_id, item.session_date): item for item in before.session_cap_ownership}
            new_caps = {(item.instrument_id, item.session_date): item for item in after.session_cap_ownership}
            if set(new_caps) != set(old_caps) | {(expected_cap[0], expected_cap[1])}:
                _reject("accounting_invalid")
            for key, value in old_caps.items():
                if key != (expected_cap[0], expected_cap[1]) and new_caps.get(key) != value:
                    _reject("accounting_invalid")
            return None

        if kind not in _OBLIGATION_KINDS:
            _reject("accounting_invalid")
        obligation_id = _safe_identifier(object.__getattribute__(event, "_obligation_id"))
        amount = _decimal_checked(object.__getattribute__(event, "_amount"), "money", positive=True)
        due_at = _safe_utc(object.__getattribute__(event, "_due_at"))
        obligations = {item.obligation_id: item for item in before.obligations}
        old = obligations.get(obligation_id)
        expected_cash = before.cash
        expected_income = before.recognized_income
        expected_expense = before.recognized_expense
        if kind.endswith("_create"):
            if old is not None or due_at < economic_time:
                _reject("accounting_invalid")
            obligation_kind = "receivable" if kind.startswith("receivable") else "liability"
            obligations[obligation_id] = type(before.obligations[0])(
                obligation_id, obligation_kind, amount, amount, due_at, economic_time
            ) if before.obligations else _make_obligation(
                obligation_id, obligation_kind, amount, amount, due_at, economic_time
            )
            if obligation_kind == "receivable":
                expected_income = _decimal_checked(_exact_decimal(lambda: expected_income + amount), "money", nonnegative=True)
            else:
                expected_expense = _decimal_checked(_exact_decimal(lambda: expected_expense + amount), "money", nonnegative=True)
        else:
            if old is None:
                _reject("accounting_invalid")
            obligation_kind = "receivable" if kind.startswith("receivable") else "liability"
            if old.kind != obligation_kind or old.due_at != due_at or economic_time < due_at or amount > old.amount_remaining:
                _reject("accounting_invalid")
            remaining = _decimal_checked(_exact_decimal(lambda: old.amount_remaining - amount), "money", nonnegative=True)
            obligations[obligation_id] = _make_obligation(
                old.obligation_id, old.kind, old.amount_created, remaining, old.due_at, old.economic_time
            )
            if obligation_kind == "receivable":
                expected_cash = _decimal_checked(_exact_decimal(lambda: expected_cash + amount), "money", nonnegative=True)
            else:
                expected_cash = _decimal_checked(_exact_decimal(lambda: expected_cash - amount), "money", nonnegative=True)
        expected_obligations = tuple(obligations[key] for key in sorted(obligations))
        expected_receivables = _decimal_checked(
            _exact_decimal(lambda: sum((item.amount_remaining for item in expected_obligations if item.kind == "receivable"), Decimal(0))),
            "money", nonnegative=True,
        )
        expected_liabilities = _decimal_checked(
            _exact_decimal(lambda: sum((item.amount_remaining for item in expected_obligations if item.kind == "liability"), Decimal(0))),
            "money", nonnegative=True,
        )
        if (
            after.cash != expected_cash
            or after.obligations != expected_obligations
            or after.receivables != expected_receivables
            or after.liabilities != expected_liabilities
            or after.recognized_income != expected_income
            or after.recognized_expense != expected_expense
            or after.total_fees != before.total_fees
            or after.positions != before.positions
            or after.intent_ownership != before.intent_ownership
            or after.session_cap_ownership != before.session_cap_ownership
            or after.fill_ids != before.fill_ids
            or after.instrument_ids != before.instrument_ids
        ):
            _reject("accounting_invalid")
        return None


def _make_obligation(
    obligation_id: str,
    kind: str,
    amount_created: Decimal,
    amount_remaining: Decimal,
    due_at: datetime,
    economic_time: datetime,
) -> object:
    from .ledger import ObligationBalance

    return ObligationBalance(obligation_id, kind, amount_created, amount_remaining, due_at, economic_time)


__all__ = ["AccountingInvariant"]
