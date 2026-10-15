"""Independent, fixed-assumption Cash and buy-and-hold simulation histories."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from mytradingalpha.backtest.clock import SessionBinding
from mytradingalpha.backtest.costs import CostPolicy
from mytradingalpha.backtest.fills import FillModel
from mytradingalpha.contracts.orders import OrderIntent
from mytradingalpha.data.bars import AdjustmentBasis, BarFinality
from mytradingalpha.data.bundle import BundleReplayPolicy, EvidenceBundle
from mytradingalpha.data.calendar import TradingCalendar, TradingSession

from .corporate_actions import (
    ActionPolicy,
    AvailableCorporateAction,
    CorporateActionReducer,
    MergerMapping,
    PositionReference,
    _calendar,
    _clone_value,
    _decimal_checked,
    _exact_decimal,
    _get,
    _part,
    _reject,
    _required,
    _safe_date,
    _safe_identifier,
    _safe_utc,
    _tuple,
    _Value,
)
from .ledger import Ledger, LedgerEvent
from .nav import AccountingPolicy, EligibleMark, NAVCalculator, _capture_mark, _refresh_policy

_ZERO = Decimal(0)


class BenchmarkCommonPolicy(_Value):
    __slots__ = ()
    _fields = ("schema_version", "policy_version", "run_id", "opening_cash", "opening_time", "resolution_cutoff", "calendar", "currency", "cost_policy", "action_policy", "entry_session", "end_session", "mark_source", "mark_revision", "replay_policy")

    def _validate(self) -> None:
        _required(self, "schema_version", "v1")
        _required(self, "currency", "USD")
        for name in ("policy_version", "run_id", "mark_source"):
            _safe_identifier(_get(self, name))
        _decimal_checked(_get(self, "opening_cash"), "money", positive=True)
        opened, cutoff = _safe_utc(_get(self, "opening_time")), _safe_utc(_get(self, "resolution_cutoff"))
        entry, end = _safe_date(_get(self, "entry_session")), _safe_date(_get(self, "end_session"))
        cal = _get(self, "calendar")
        if type(cal) is not TradingCalendar or type(_get(self, "cost_policy")) is not CostPolicy or type(_get(self, "action_policy")) is not ActionPolicy or type(_get(self, "replay_policy")) is not BundleReplayPolicy:
            _reject()
        first = _calendar(cal, cal.session(entry))[1]
        last = _calendar(cal, cal.session(end))[1]
        if entry > end or opened > first.open_at or cutoff < last.close_at:
            _reject()
        revision = _get(self, "mark_revision")
        if type(revision) is not int or not 0 <= revision <= (1 << 31) - 1:
            _reject()


class CashBenchmarkPolicy(_Value):
    __slots__ = ()
    _fields = ("common", "interest_policy", "annual_rate")

    def _validate(self) -> None:
        if type(_get(self, "common")) is not BenchmarkCommonPolicy:
            _reject()
        _required(self, "interest_policy", "zero")
        _required(self, "annual_rate", _ZERO)


class BenchmarkMember(_Value):
    __slots__ = ()
    _fields = ("instrument_id", "weight", "quantity", "lot_size", "intent", "binding")

    def _validate(self) -> None:
        _safe_identifier(_get(self, "instrument_id"))
        weight = _decimal_checked(_get(self, "weight"), "money", positive=True)
        quantity = _decimal_checked(_get(self, "quantity"), "quantity", positive=True)
        lot = _decimal_checked(_get(self, "lot_size"), "quantity", positive=True)
        if weight > 1 or (Fraction(quantity) / Fraction(lot)).denominator != 1:
            _reject()
        if type(_get(self, "intent")) is not OrderIntent or type(_get(self, "binding")) is not SessionBinding:
            _reject()


class BuyAndHoldPolicy(_Value):
    __slots__ = ()
    _fields = ("common", "universe", "members", "residual_cash", "rebalance", "dividend_treatment")

    def __init__(self, **fields: object) -> None:
        if "members" in fields:
            _tuple(fields["members"], 8)
        super().__init__(**fields)

    def _validate(self) -> None:
        common, universe, members = _get(self, "common"), _get(self, "universe"), _get(self, "members")
        if type(common) is not BenchmarkCommonPolicy or type(universe) is not EvidenceBundle:
            _reject()
        _tuple(members, 8)
        if not members or any(type(m) is not BenchmarkMember for m in members):
            _reject()
        if len({_get(m, "instrument_id") for m in members}) != len(members):
            _reject()
        if _exact_decimal(lambda: sum((_get(m, "weight") for m in members), _ZERO)) > 1:
            _reject()
        entry = _get(common, "entry_session")
        for member in members:
            identifier = _get(member, "instrument_id")
            if not any(i.instrument_id == identifier and i.currency == "USD" for i in universe.instruments):
                _reject("binding_mismatch")
            # Historical membership is evaluated on the frozen entry universe.
            if not any(m.instrument_id == identifier and m.valid_from <= entry and (m.valid_to is None or entry < m.valid_to) for m in universe.memberships):
                _reject("binding_mismatch")
        _required(self, "residual_cash", "retain")
        _required(self, "rebalance", "none")
        _required(self, "dividend_treatment", "cash_no_reinvestment")


class BenchmarkSessionInput(_Value):
    __slots__ = ()
    _fields = ("session", "marks", "accounting_policy", "actions", "references", "mergers")

    def __init__(self, **fields: object) -> None:
        for name, maximum in (("marks", 8), ("actions", 64), ("references", 32), ("mergers", 32)):
            if name in fields:
                _tuple(fields[name], maximum)
        super().__init__(**fields)

    def _validate(self) -> None:
        if type(_get(self, "session")) is not TradingSession or type(_get(self, "accounting_policy")) is not AccountingPolicy:
            _reject()
        for name, cls in (("marks", EligibleMark), ("actions", AvailableCorporateAction), ("references", PositionReference), ("mergers", MergerMapping)):
            if any(type(v) is not cls for v in _get(self, name)):
                _reject()


class BenchmarkSeries(_Value):
    __slots__ = ()
    _fields = ("status", "run_valid", "reason_code", "events", "balances", "nav_points", "policy")


_BENCH_VALUES = (BenchmarkCommonPolicy, CashBenchmarkPolicy, BenchmarkMember, BuyAndHoldPolicy, BenchmarkSessionInput, BenchmarkSeries)


def _result(policy, ledger, balances, points, reason=None):
    return BenchmarkSeries(status="available" if reason is None else "unavailable", run_valid=reason is None,
                           reason_code=reason, events=ledger.events, balances=tuple(balances), nav_points=tuple(points), policy=policy)


def _aligned(session_input, common):
    session = _get(session_input, "session")
    cal = _get(common, "calendar")
    _calendar(cal, session)
    policy = _get(session_input, "accounting_policy")
    parts = []
    _refresh_policy(policy, parts)
    prepared, target, valuation, archive, currency, source, revision = parts
    return not (target != session.session_date or currency != "USD" or source != _get(common, "mark_source") or revision != _get(common, "mark_revision") or prepared[0].run_id != _get(common, "run_id") or prepared[1].calendar.model_dump(mode="json") != cal.model_dump(mode="json") or prepared[1].replay_policy is not _get(common, "replay_policy") or valuation > _get(common, "resolution_cutoff") or archive > _get(common, "resolution_cutoff"))


class BenchmarkRunner:
    __slots__ = ()

    def run_cash(self, sessions: object, *, policy: object, **unknown: object) -> BenchmarkSeries:
        if unknown:
            _reject("input_invalid", TypeError)
        if type(policy) is not CashBenchmarkPolicy:
            _reject()
        return self._run(sessions, policy, False)

    def run_buy_and_hold(self, sessions: object, *, policy: object, **unknown: object) -> BenchmarkSeries:
        if unknown:
            _reject("input_invalid", TypeError)
        if type(policy) is not BuyAndHoldPolicy:
            _reject()
        return self._run(sessions, policy, True)

    @staticmethod
    def _run(sessions, policy, buy_hold):
        _tuple(sessions, 16)
        if any(type(s) is not BenchmarkSessionInput for s in sessions):
            _reject()
        frozen_policy = _clone_value(policy)
        frozen_sessions = tuple(_clone_value(s) for s in sessions)
        common = _get(frozen_policy, "common")
        members = _get(frozen_policy, "members") if buy_hold else ()
        if len(members) * len(sessions) > 128:
            _reject("resource_limit")
        cal = _get(common, "calendar")
        ledger = Ledger(run_id=_get(common, "run_id"), calendar_id=cal.calendar_id, currency="USD",
                        opening_cash=_get(common, "opening_cash"), opening_time=_get(common, "opening_time"),
                        resolution_cutoff=_get(common, "resolution_cutoff"))
        balances, points = [], []
        reason = None
        failed = False
        try:
            expected = _get(common, "entry_session")
            if not frozen_sessions or _get(frozen_sessions[-1], "session").session_date != _get(common, "end_session"):
                reason = "session_alignment"
            for index, item in enumerate(frozen_sessions):
                if reason:
                    break
                session = _get(item, "session")
                if session.session_date != expected or not _aligned(item, common):
                    reason = "session_alignment"
                    break
                if index + 1 < len(frozen_sessions):
                    expected = cal.next_session(session.session_date).session_date
                action_policy = _get(common, "action_policy")
                reducer = CorporateActionReducer()
                events = reducer.apply_opening_actions(ledger.balance(), _get(item, "actions"), session, action_policy,
                    calendar=cal, event_id=f"bt04-opening-{index}", outstanding_intents=(), references=_get(item, "references"),
                    mergers=_get(item, "mergers"), replay_policy=_get(common, "replay_policy"), archive_cutoff=session.open_at)
                for event in events:
                    ledger.append(event)
                for event in reducer.apply_payments(ledger.balance(), session, action_policy, calendar=cal, event_id=f"bt04-payment-{index}"):
                    ledger.append(event)
                marks = _get(item, "marks")
                if buy_hold and index == 0:
                    reason = BenchmarkRunner._enter(ledger, members, marks, session, common, _get(frozen_policy, "universe"))
                    if reason:
                        break
                nav = NAVCalculator().compute(ledger.balance(), marks if buy_hold else (), _get(item, "accounting_policy"))
                balances.append(ledger.balance())
                points.append(nav)
                if not nav.run_valid:
                    reason = "required_mark_unavailable"
                    break
        except Exception:
            failed = True
        if failed:
            reason = "benchmark_input_unavailable"
        # Completion checks run for success and unavailable outcomes alike.
        if _part(policy)[2] != _part(frozen_policy)[2] or _part(sessions)[2] != _part(frozen_sessions)[2]:
            _reject("source_changed")
        return _result(frozen_policy, ledger, balances, points, reason)

    @staticmethod
    def _enter(ledger, members, marks, session, common, universe):
        costs = _get(common, "cost_policy")
        captured_marks = tuple((_capture_mark(m)[0], m) for m in marks)
        cap_used = {}
        for index, member in enumerate(sorted(members, key=lambda m: _get(m, "instrument_id"))):
            instrument = _get(member, "instrument_id")
            intent = _get(member, "intent")
            binding = _get(member, "binding")
            quantity = _get(member, "quantity")
            matching = tuple(state for state, _ in captured_marks if state[1][0].instrument_id == instrument)
            if len(matching) != 1:
                return "entry_mark_unavailable"
            prepared, outcome_state = matching[0]
            bar = outcome_state[0]
            if intent.instrument_id != instrument or intent.quantity != quantity or intent.side != "buy" or intent.execution_authority != "simulation_only" or intent.run_id != _get(common, "run_id") or intent.created_at >= session.open_at or binding.next_session.session_date != session.session_date or bar.session_date != session.session_date or bar.adjustment_basis is not AdjustmentBasis.UNADJUSTED or bar.finality is not BarFinality.FINAL or bar.manifest.source != _get(common, "mark_source") or bar.manifest.revision != _get(common, "mark_revision"):
                return "entry_binding_mismatch"
            if binding.bundle.bundle_hash != universe.bundle_hash or prepared[1].bundle_hash != universe.bundle_hash:
                return "entry_universe_mismatch"
            if _exact_decimal(lambda quantity=quantity, bar=bar: quantity * bar.close) != _exact_decimal(lambda member=member: _get(member, "weight") * _get(common, "opening_cash")):
                return "entry_weight_mismatch"
            if (Fraction(quantity) / Fraction(costs.lot_size)).denominator != 1:
                return "entry_lot_mismatch"
            from .ledger import _outcome_from_state
            outcome = _outcome_from_state(outcome_state)
            decision = FillModel.simulate(intent, outcome, quantity, ledger.balance().cash, _ZERO,
                _exact_decimal(lambda instrument=instrument: costs.fixed_share_cap - cap_used.get(instrument, _ZERO)), costs,
                binding=binding, session_date=session.session_date, cumulative_quantity=_ZERO)
            if decision.fill is None or decision.fill.quantity != quantity:
                return "entry_not_filled"
            balance = ledger.balance()
            ledger.append(LedgerEvent.for_fill(event_id=f"bt04-entry-{index}", sequence=balance.next_sequence,
                previous_hash=balance.prefix_hashes[-1] if balance.prefix_hashes else balance.genesis_hash,
                intent=intent, fill=decision.fill, binding=binding, outcome=outcome, policy=costs))
            cap_used[instrument] = quantity
        return None


__all__ = ["BenchmarkCommonPolicy", "CashBenchmarkPolicy", "BenchmarkMember", "BuyAndHoldPolicy", "BenchmarkSessionInput", "BenchmarkRunner", "BenchmarkSeries"]
