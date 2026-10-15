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
    signed = quantity if side == "buy" else quantity.copy_negate()
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

        if kind == "action_batch":
            _check_actions(before, event, after)
            return None
        from .corporate_actions import _get, _state

        if _state(before).canonical_bytes() != _state(after).canonical_bytes() or _state(before)._storage != _state(after)._storage:
            _reject("accounting_invalid")
        if kind in _OBLIGATION_KINDS and any(_get(c, "obligation_id") == object.__getattribute__(event, "_obligation_id") for c in _get(_state(before), "claims")):
            _reject("accounting_invalid")
        if kind == "fill":
            intent, fill, _binding, _outcome, policy = _event_fill_parts(event)
            instrument = _safe_identifier(object.__getattribute__(fill, "instrument_id"))
            side = object.__getattribute__(fill, "side")
            quantity = _decimal_checked(object.__getattribute__(fill, "quantity"), "quantity", positive=True)
            price = _decimal_checked(object.__getattribute__(fill, "price"), "execution", positive=True)
            fee = _decimal_checked(object.__getattribute__(fill, "fee"), "money", nonnegative=True)
            notional = _exact_decimal(lambda: quantity * price)
            signed = notional if side == "buy" else notional.copy_negate()
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


def _check_actions(before: LedgerBalance, event: LedgerEvent, after: LedgerBalance) -> None:
    """Independent rational audit of economics, ownership and unaffected fields.

    Selection and source validation are shared. This audit never calls the
    publication reducer: it derives shares, principal, income and payments from
    the source records again using integer ratios.
    """
    import hashlib
    from fractions import Fraction

    from mytradingalpha.data.actions import (
        DelistingAction,
        DividendAction,
        SplitAction,
        TickerChangeAction,
    )

    from .corporate_actions import (
        _ActionState,
        _Applied,
        _Cancellation,
        _Claim,
        _claim_id,
        _due,
        _get,
        _selection,
        _SplitReference,
        _state,
        _validate_reference,
    )
    from .ledger import ObligationBalance

    batch = object.__getattribute__(event, "_action_batch")
    calendar, session, calendar_bytes, selected, mappings = _selection(batch, before)
    previous = _state(before)
    policy = _get(batch, "policy")
    quantities = {key: Fraction(q) for key, q in before.positions}
    expected_cash = Fraction(before.cash)
    expected_income = Fraction(before.recognized_income)
    obligations = {o.obligation_id: o for o in before.obligations}
    claims = {_get(c, "obligation_id"): c for c in _get(previous, "claims")}
    applied = {_get(a, "action_id"): a for a in _get(previous, "applied_actions")}
    symbols = dict(_get(previous, "symbols"))
    cancellations = {_get(c, "intent_id"): c for c in _get(previous, "cancelled_intents")}
    closed = set(_get(previous, "closed_instruments"))
    split_refs = {_get(r, "instrument_id"): r for r in _get(previous, "split_references")}
    boundaries = dict(_get(previous, "split_boundaries"))
    references = {_get(r, "instrument_id"): r for r in _get(batch, "references")}
    instruments = set(before.instrument_ids)
    converted_in_batch = set()

    def decimal(value: Fraction) -> Decimal:
        result = _exact_decimal(lambda: Decimal(value.numerator) / Decimal(value.denominator))
        return _decimal_checked(result, "money", nonnegative=True)

    def accrue(action_id: str, amount: Fraction, payable: object, kind: str) -> None:
        nonlocal expected_income
        due = _due(calendar, payable)
        if not amount:
            return
        key = _claim_id(action_id)
        if key in obligations:
            _reject("accounting_invalid")
        exact = decimal(amount)
        obligations[key] = ObligationBalance(key, "receivable", exact, exact, due, session.open_at)
        claims[key] = _Claim(obligation_id=key, action_id=action_id, kind=kind, amount=exact, due_at=due, paid=False)
        if kind == "dividend":
            expected_income += amount

    def cancel(instrument: str, reason: str) -> None:
        ids = {i.intent_id for i in _get(batch, "outstanding_intents") if i.instrument_id == instrument and i.created_at < session.open_at}
        ids.update(o.intent_id for o in before.intent_ownership if o.instrument_id == instrument and not o.terminal)
        for intent_id in ids:
            cancellations.setdefault(intent_id, _Cancellation(intent_id=intent_id, reason=reason))

    for wrapper in selected:
        action, terms = _get(wrapper, "action"), _get(wrapper, "terms")
        if type(action) is DividendAction:
            continue
        key = action.instrument_id
        original = quantities.get(key, Fraction(0))
        if type(action) is SplitAction:
            ratio = Fraction(action.new_shares_per_old_share)
            converted = original * ratio
            if _get(terms, "fractional_shares") == "cash_in_lieu":
                lot = Fraction(_get(terms, "lot_size"))
                retained = (converted // lot) * lot
                accrue(action.action_id, (converted - retained) * Fraction(_get(terms, "cash_in_lieu_price")), _get(terms, "payable_date"), "principal")
            else:
                retained = converted
            quantities[key] = retained
            if original:
                prior = split_refs.get(key) if key in converted_in_batch else None
                source = references[key]
                _validate_reference(source, before, session, calendar, _get(batch, "replay_policy"), _get(batch, "archive_cutoff"))
                basis = Fraction(_get(source, "cost_basis")) if prior is None else Fraction(_get(prior, "cost_basis_numerator"), _get(prior, "cost_basis_denominator"))
                mark = Fraction(_get(source, "bar").close) if prior is None else Fraction(_get(prior, "mark_numerator"), _get(prior, "mark_denominator"))
                basis, mark = basis / ratio, mark / ratio
                split_refs[key] = _SplitReference(instrument_id=key, cost_basis_numerator=basis.numerator,
                    cost_basis_denominator=basis.denominator, mark_numerator=mark.numerator, mark_denominator=mark.denominator)
                converted_in_batch.add(key)
            boundaries[key] = session.open_at
            cancel(key, "split_preexisting_intent")
        elif type(action) is TickerChangeAction:
            if symbols.get(key, _get(references[key], "symbol") if key in references else None) != action.old_symbol:
                _reject("accounting_invalid")
            symbols[key] = action.new_symbol
        elif type(action) is DelistingAction:
            quantities.pop(key, None)
            closed.add(key)
            cancel(key, "delisting_preexisting_intent")
            if _get(terms, "settlement") == "cash":
                accrue(action.action_id, original * Fraction(_get(terms, "amount_per_share")), _get(terms, "payable_date"), "principal")
    for mapping in mappings:
        source, target = _get(mapping, "source_instrument_id"), _get(mapping, "target_instrument_id")
        original = quantities.pop(source, Fraction(0))
        quantities[target] = quantities.get(target, Fraction(0)) + original * Fraction(_get(mapping, "new_shares_per_old_share"))
        closed.add(source)
        cancel(source, "merger_preexisting_intent")
        instruments.add(target)
        key = _get(mapping, "mapping_id")
        applied[key] = _Applied(action_id=key, revision=_get(mapping, "manifest").revision, source_hash=hashlib.sha256(mapping._canonical + mapping._storage).hexdigest())
    for wrapper in selected:
        action, terms = _get(wrapper, "action"), _get(wrapper, "terms")
        if type(action) is DividendAction:
            amount = quantities.get(action.instrument_id, Fraction(0)) * Fraction(action.amount_per_share)
            if _get(terms, "amount_basis") == "pre_split":
                amount /= Fraction(_get(terms, "conversion_ratio"))
            accrue(action.action_id, amount, action.payable_date, "dividend")
        applied[action.action_id] = _Applied(action_id=action.action_id, revision=action.manifest.revision,
            source_hash=hashlib.sha256(wrapper._canonical + wrapper._storage).hexdigest())
    if _get(batch, "mode") == "payment":
        for key, claim in tuple(claims.items()):
            if not _get(claim, "paid") and _get(claim, "due_at") <= session.open_at:
                original = obligations[key]
                amount = _get(claim, "amount")
                expected_cash += Fraction(amount)
                obligations[key] = ObligationBalance(key, "receivable", amount, Decimal(0), original.due_at, original.economic_time)
                claims[key] = _Claim(obligation_id=key, action_id=_get(claim, "action_id"), kind=_get(claim, "kind"), amount=amount, due_at=_get(claim, "due_at"), paid=True)
    expected_state = _ActionState(applied_actions=tuple(applied[k] for k in sorted(applied)), symbols=tuple(sorted(symbols.items())),
        cancelled_intents=tuple(cancellations[k] for k in sorted(cancellations)), closed_instruments=tuple(sorted(closed)),
        split_references=tuple(split_refs[k] for k in sorted(split_refs)), split_boundaries=tuple(sorted(boundaries.items())),
        claims=tuple(claims[k] for k in sorted(claims)), calendar_bytes=calendar_bytes, policy_bytes=policy.canonical_bytes())
    if (
        Fraction(after.cash) != expected_cash
        or {k: Fraction(q) for k, q in after.positions} != {k: q for k, q in quantities.items() if q}
        or after.obligations != tuple(obligations[k] for k in sorted(obligations))
        or Fraction(after.recognized_income) != expected_income
        or after.receivables != _exact_decimal(lambda: sum((o.amount_remaining for o in obligations.values() if o.kind == "receivable"), Decimal(0)))
        or after.liabilities != before.liabilities
        or after.recognized_expense != before.recognized_expense
        or after.total_fees != before.total_fees
        or after.intent_ownership != before.intent_ownership
        or after.session_cap_ownership != before.session_cap_ownership
        or after.fill_ids != before.fill_ids
        or after.instrument_ids != tuple(sorted(instruments))
        or _state(after).canonical_bytes() != expected_state.canonical_bytes()
    ):
        _reject("accounting_invalid")
