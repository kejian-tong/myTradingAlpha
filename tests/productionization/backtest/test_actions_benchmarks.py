"""BT-04 behavioral RED: synthetic, witnessed actions and independent baselines.

New APIs are resolved inside tests, so the BT-03 base collects successfully.
Fixture construction uses real PIT, BT-01, BT-02 and BT-03 validation; no core
validator is mocked. Cached source graphs are immutable inputs. Adversarial
tests damage private copies only, and every tested publication uses a fresh Ledger.
"""

from __future__ import annotations

import ast
import base64
import builtins
import copy
import hashlib
import importlib
import json
import os
import socket
import subprocess
import urllib.request
import warnings
import zoneinfo
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from functools import lru_cache
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

from mytradingalpha.data.actions import (
    DelistingAction,
    DividendAction,
    SplitAction,
    TickerChangeAction,
)
from mytradingalpha.data.bars import AdjustmentBasis, DailyBar
from mytradingalpha.data.bundle import BundleReplayPolicy, build_evidence_bundle
from mytradingalpha.data.calendar import TradingCalendar
from mytradingalpha.data.provenance import SourceManifest
from mytradingalpha.quant.envelope import combine_quant_overlay
from mytradingalpha.quant.variants import VariantRegistry
from tests.productionization.backtest import (
    test_clock_events as bt01,
    test_fills_costs as bt02,
    test_ledger_nav as bt03,
)
from tests.productionization.quant import test_signal as quant

D = Decimal
UTC = timezone.utc
ZERO = D("0")
ENTRY = date(2024, 7, 3)
EX_DATE = date(2024, 7, 5)
PAY_DATE = date(2024, 7, 8)
INST = "inst-survivor"
ROOT = Path(__file__).resolve().parents[3]
EXPECTED_POLICY_BYTES = (
    b'{"currency":"USD","dividend_treatment":"cash_no_reinvestment",'
    b'"fractional_shares":"retain_exact","payment_rule":"next_witnessed_session",'
    b'"policy_version":"bt04-synthetic-v1","price_basis":"unadjusted","schema_version":"v1"}'
)
SESSIONS = (
    ENTRY, EX_DATE, PAY_DATE, date(2024, 7, 9), date(2024, 7, 10),
    date(2024, 7, 11), date(2024, 7, 12), date(2024, 7, 15),
    date(2024, 7, 16), date(2024, 7, 17), date(2024, 7, 18),
    date(2024, 7, 19), date(2024, 7, 22), date(2024, 7, 23),
    date(2024, 7, 24), date(2024, 7, 25), date(2024, 7, 26),
)


def _api() -> SimpleNamespace:
    modules: dict[str, Any] = {}
    for name in ("corporate_actions", "benchmarks"):
        try:
            modules[name] = importlib.import_module(f"mytradingalpha.backtest.{name}")
        except ModuleNotFoundError as error:
            if error.name == f"mytradingalpha.backtest.{name}":
                pytest.fail(f"BT-04 RED: missing {name} behavioral contract")
            raise
    required = {
        "corporate_actions": (
            "ActionPolicy", "AvailableCorporateAction", "PositionReference", "SplitTerms",
            "DividendTerms", "DelistingTerms", "MergerMapping", "CorporateActionReducer",
        ),
        "benchmarks": (
            "BenchmarkCommonPolicy", "CashBenchmarkPolicy", "BuyAndHoldPolicy",
            "BenchmarkMember", "BenchmarkSessionInput", "BenchmarkRunner",
        ),
    }
    for module_name, names in required.items():
        missing = [name for name in names if not hasattr(modules[module_name], name)]
        if missing:
            pytest.fail(f"BT-04 RED: incomplete {module_name} contract: {','.join(missing)}")
    return SimpleNamespace(**{
        name: getattr(modules[module_name], name)
        for module_name, names in required.items() for name in names
    })


@lru_cache(maxsize=3)
def _case(session_count: int = 5) -> SimpleNamespace:
    """Extend a genuine synthetic calendar with explicit fixture dates only."""
    case = bt02._case_with_five_future_sessions()
    if session_count == 5:
        return case
    payload = case.bundle.calendar.model_dump(mode="python")
    end = SESSIONS[session_count - 1]
    for coverage in payload["coverage_ranges"]:
        if coverage["start"] == date(2024, 6, 28):
            coverage["end"] = end
    schedule = list(payload["schedule"])
    schedule.extend({
        "schema_version": "v1", "calendar_id": case.bundle.calendar.calendar_id,
        "session_date": day, "open_at": datetime.combine(day, datetime.min.time(), UTC).replace(hour=13, minute=30),
        "close_at": datetime.combine(day, datetime.min.time(), UTC).replace(hour=20),
        "session_type": "regular",
    } for day in SESSIONS[5:session_count])
    # Explicit synthetic closed dates; production must consume the sealed witness.
    closed = (date(2024, 7, 13), date(2024, 7, 14), date(2024, 7, 20), date(2024, 7, 21))
    closures = list(payload["closures"])
    closures.extend({"schema_version": "v1", "calendar_id": case.bundle.calendar.calendar_id,
                     "date": day, "reason": "synthetic_closed_date"}
                    for day in closed if day <= end)
    payload.update(schedule=tuple(sorted(schedule, key=lambda item: item["session_date"])),
                   closures=tuple(sorted(closures, key=lambda item: item["date"])), replay_evidence=None)
    calendar = TradingCalendar.model_validate(payload)
    bundle = quant._bundle(calendar=calendar, cutoff=bt01.PRE_CLOSE_CUTOFF)
    return bt02._case_for_bundle(bundle=bundle, run_id=case.context.run_id,
                                variant_id=case.context.variant_id,
                                decision_time=bt01.DECISION_TIME,
                                earliest_execution_time="2024-07-03T13:30:00Z")


@lru_cache(maxsize=8)
def _seed(quantity: str = "10", price: str = "100", cash: str = "2000") -> SimpleNamespace:
    api03, api02, case = bt03._bt03_api(), bt02._bt02_api(), _case()
    policy = bt02._policy(api02, half_spread_bps=ZERO, slippage_bps=ZERO,
                         commission_per_share=ZERO, order_minimum=ZERO,
                         fixed_share_cap=D("1E9"), lot_size=D("0.000001"))
    outcome = bt02._outcome(api02, case, price=D(price))
    intent = bt02._intent(api02, case, quantity=D(quantity), time_in_force="gtc",
                          expires_at=case.bundle.calendar.session(date(2024, 7, 10)).close_at)
    fill = bt03._make_fill(api02, case, intent=intent, outcome=outcome, policy=policy,
                          cash=D(cash), cap=D("1E9"))
    return SimpleNamespace(case=case, api03=api03, api02=api02, policy=policy,
                           outcome=outcome, intent=intent, fill=fill, cash=D(cash))


def _ledger(seed: SimpleNamespace | None = None, *, held: bool = True) -> Any:
    seed = seed or _seed()
    ledger = bt03._new_ledger(seed.api03, seed.case, opening_cash=seed.cash)
    if held:
        ledger.append(bt03._fill_event(seed.api03, ledger, intent=seed.intent, fill=seed.fill,
                                      case=seed.case, outcome=seed.outcome, policy=seed.policy,
                                      event_id="synthetic-entry"))
    return ledger


def _policy(api: SimpleNamespace, **changes: Any) -> Any:
    fields = {"schema_version": "v1", "policy_version": "bt04-synthetic-v1", "currency": "USD",
                  "price_basis": AdjustmentBasis.UNADJUSTED, "fractional_shares": "retain_exact",
                  "payment_rule": "next_witnessed_session", "dividend_treatment": "cash_no_reinvestment"}
    fields.update(changes)
    return api.ActionPolicy(**fields)


def _manifest(action_id: str, effective: date = EX_DATE, *, revision: int = 0,
              available: datetime | None = None, ingested: datetime | None = None,
              source: str = "synthetic-bt04-actions", terms: str = "synthetic BT-04 evidence") -> SourceManifest:
    available = available or datetime(2024, 7, 2, 12, tzinfo=UTC)
    return SourceManifest(schema_version="v1", manifest_id=f"{action_id}-r{revision}", source=source,
                          source_locator=f"fixture://bt04/{action_id}/r{revision}",
                          fetched_at=available, available_at=available, ingested_at=ingested or available,
                          event_time=datetime.combine(effective, datetime.min.time(), UTC),
                          published_at=available, checksum="sha256:" + hashlib.sha256(
                              f"synthetic:{action_id}:{revision}".encode()).hexdigest(),
                          terms=terms, revision=revision)


def _action(kind: str = "split", action_id: str = "split-synthetic", *,
            effective: date = EX_DATE, revision: int = 0, available: datetime | None = None,
            ingested: datetime | None = None, source: str = "synthetic-bt04-actions", **changes: Any) -> Any:
    fields = {"schema_version": "v1", "action_type": kind, "action_id": action_id, "instrument_id": INST,
                  "effective_date": effective, "manifest": _manifest(action_id, effective, revision=revision,
                                                               available=available, ingested=ingested, source=source)}
    fields.update({
        "split": {"new_shares_per_old_share": D("2")},
        "dividend": {"amount_per_share": D("1"), "currency": "USD", "payable_date": PAY_DATE},
        "ticker_change": {"old_symbol": "KEEP", "new_symbol": "RENAMED"},
        "delisting": {"reason": "synthetic delisting"},
    }[kind])
    fields.update(changes)
    cls = {"split": SplitAction, "dividend": DividendAction,
           "ticker_change": TickerChangeAction, "delisting": DelistingAction}[kind]
    return cls.model_validate(fields)


def _terms(api: SimpleNamespace, action: Any, *, basis: str = "post_split", **changes: Any) -> Any:
    fields = {"schema_version": "v1", "policy_version": "bt04-synthetic-terms-v1", "action_id": action.action_id,
                  "instrument_id": action.instrument_id, "currency": "USD", "effective_date": action.effective_date,
                  "action_source": action.manifest.source, "action_revision": action.manifest.revision,
                  "manifest": action.manifest}
    if type(action) is DividendAction:
        cls = api.DividendTerms
        fields.update(amount_basis=basis, conversion_action_id=None, conversion_ratio=None)
    elif type(action) is SplitAction:
        cls = api.SplitTerms
        fields.update(fractional_shares="retain_exact", lot_size=D("0.000001"),
                      cash_in_lieu_price=None, payable_date=None)
    elif type(action) is DelistingAction:
        cls = api.DelistingTerms
        fields.update(settlement="cash", amount_per_share=D("30"), payable_date=PAY_DATE)
    else:
        raise AssertionError("fixture terms are only required for financial actions")
    fields.update(changes)
    return cls(**fields)


def _available(api: SimpleNamespace, action: Any, *, terms: Any = ...) -> Any:
    if terms is ...:
        terms = None if type(action) is TickerChangeAction else _terms(api, action)
    return api.AvailableCorporateAction(action=action, terms=terms)


def _reference(api: SimpleNamespace, seed: SimpleNamespace | None = None) -> Any:
    seed = seed or _seed()
    return api.PositionReference(instrument_id=INST, symbol="KEEP", cost_basis=seed.fill.price,
                                 mark=bt03._mark(seed.api03, seed.case, seed.outcome))


def _opening(api: SimpleNamespace, ledger: Any, actions: tuple[Any, ...], *,
             session_date: date = EX_DATE, event_id: str | None = None, policy: Any = None,
             **changes: Any) -> tuple[Any, ...]:
    case = _case()
    fields = {"calendar": case.bundle.calendar, "event_id": event_id or f"synthetic-opening-{session_date}",
                  "outstanding_intents": (), "references": (_reference(api),), "mergers": (),
                  "replay_policy": BundleReplayPolicy.ARCHIVE_REALISTIC,
                  "archive_cutoff": case.bundle.calendar.session(session_date).open_at}
    fields.update(changes)
    return api.CorporateActionReducer().apply_opening_actions(
        ledger.balance(), actions, case.bundle.calendar.session(session_date), policy or _policy(api), **fields)


def _post(ledger: Any, events: tuple[Any, ...]) -> Any:
    assert type(events) is tuple
    assert len(events) <= 1, "the entire opening batch must publish atomically"
    for event in events:
        ledger.append(event)
    return ledger.balance()


def _payment(api: SimpleNamespace, ledger: Any, day: date, *, event_id: str = "synthetic-payment",
             calendar: Any = None, policy: Any = None) -> tuple[Any, ...]:
    calendar = calendar or _case().bundle.calendar
    return api.CorporateActionReducer().apply_payments(
        ledger.balance(), calendar.session(day), policy or _policy(api), calendar=calendar, event_id=event_id)


def _snapshot(ledger: Any) -> tuple[Any, ...]:
    return (ledger.balance().canonical_bytes(), tuple(e.canonical_bytes() for e in ledger.events),
            ledger.action_state().canonical_bytes())


def _reject(call: Callable[[], Any]) -> BaseException:
    with pytest.raises((TypeError, ValueError, OverflowError)) as caught:
        call()
    assert len(str(caught.value)) <= 256
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    return caught.value


def _nav(ledger: Any, day: date, price: str) -> Any:
    seed = _seed()
    outcome = bt02._outcome(seed.api02, seed.case, session=day, price=D(price))
    return bt03._nav(seed.api03, ledger.balance(), seed.case, outcome)


def _common(api: SimpleNamespace, *, case: SimpleNamespace | None = None,
            cost_policy: Any = None, end: date = PAY_DATE, **changes: Any) -> Any:
    seed = _seed()
    case = case or seed.case
    fields = {"schema_version": "v1", "policy_version": "bt04-common-synthetic-v1",
                  "run_id": case.context.run_id, "opening_cash": D("2000"), "opening_time": bt03.OPENING_TIME,
                  "resolution_cutoff": case.bundle.calendar.session(end).close_at + timedelta(hours=1),
                  "calendar": case.bundle.calendar, "currency": "USD", "cost_policy": cost_policy or seed.policy,
                  "action_policy": _policy(api), "entry_session": ENTRY, "end_session": end,
                  "mark_source": "synthetic-market-v1", "mark_revision": 0,
                  "replay_policy": BundleReplayPolicy.ARCHIVE_REALISTIC}
    fields.update(changes)
    return api.BenchmarkCommonPolicy(**fields)


def _member(api: SimpleNamespace, *, seed: SimpleNamespace | None = None, weight: str = "0.5",
            quantity: str = "10", **changes: Any) -> Any:
    seed = seed or _seed()
    fields = {"instrument_id": seed.intent.instrument_id, "weight": D(weight), "quantity": D(quantity),
                  "lot_size": D("0.000001"), "intent": seed.intent, "binding": seed.case.binding}
    fields.update(changes)
    return api.BenchmarkMember(**fields)


def _bh_policy(api: SimpleNamespace, *, common: Any = None, members: tuple[Any, ...] | None = None,
               universe: Any = None, **changes: Any) -> Any:
    fields = {"common": common or _common(api), "universe": universe or _case().bundle,
                  "members": members if members is not None else (_member(api),), "residual_cash": "retain",
                  "rebalance": "none", "dividend_treatment": "cash_no_reinvestment"}
    fields.update(changes)
    return api.BuyAndHoldPolicy(**fields)


def _session_input(api: SimpleNamespace, day: date, *, case: SimpleNamespace | None = None,
                   price: str = "100", marks: Any = ..., actions: tuple[Any, ...] = (), **changes: Any) -> Any:
    case = case or _case()
    seed = _seed()
    outcome = bt02._outcome(seed.api02, case, session=day, price=D(price))
    fields = {"session": case.bundle.calendar.session(day),
                  "marks": (bt03._mark(seed.api03, case, outcome),) if marks is ... else marks,
                  "accounting_policy": bt03._accounting_policy(seed.api03, case, outcome),
                  "actions": actions, "references": (), "mergers": ()}
    fields.update(changes)
    return api.BenchmarkSessionInput(**fields)


def _run_bh(api: SimpleNamespace, *, sessions: tuple[Any, ...] | None = None, policy: Any = None) -> Any:
    sessions = sessions if sessions is not None else tuple(_session_input(api, day) for day in SESSIONS[:3])
    return api.BenchmarkRunner().run_buy_and_hold(sessions, policy=policy or _bh_policy(api))


def _assert_unavailable(result: Any) -> None:
    assert bt03._result_status(result) == "unavailable"
    assert result.run_valid is False
    assert bt03._result_reason(result)


def test_synthetic_fixture_uses_real_witness_intent_fill_ledger_and_nav() -> None:
    seed = _seed()
    ledger = _ledger(seed)
    assert seed.case.binding.bundle.calendar.replay_evidence is not None
    assert seed.intent.execution_authority == "simulation_only"
    assert ledger.balance().cash == D("1000")
    assert ledger.balance().positions == ((INST, D("10")),)
    assert _nav(ledger, ENTRY, "100").value == D("2000")


def test_action_policy_small_independent_canonical_golden_and_explicit_assumptions() -> None:
    api = _api()
    policy = _policy(api)
    assert policy.canonical_bytes() == EXPECTED_POLICY_BYTES
    assert json.loads(EXPECTED_POLICY_BYTES)["price_basis"] == "unadjusted"
    for changes in ({"currency": "EUR"}, {"price_basis": AdjustmentBasis.PROVIDER_ADJUSTED},
                    {"fractional_shares": "truncate"}, {"payment_rule": "weekday"},
                    {"dividend_treatment": "reinvest"}, {"unexpected": True}):
        _reject(lambda changes=changes: _policy(api, **changes))


@pytest.mark.parametrize("late_field", ("available", "ingested"))
def test_full_series_cannot_hide_late_effective_business_action_among_eligible_actions(late_field: str) -> None:
    api = _api()
    ledger = _ledger()
    before = _snapshot(ledger)
    late = _case().bundle.calendar.session(EX_DATE).open_at + timedelta(microseconds=1)
    actions = (_available(api, _action("dividend", "eligible-dividend")),
               _available(api, _action(**{late_field: late})))
    _reject(lambda: _opening(api, ledger, actions))
    assert _snapshot(ledger) == before


def test_highest_eligible_revision_is_selected_at_effective_open_not_later_run_cutoff() -> None:
    api = _api()
    early = _action(revision=0, new_shares_per_old_share=D("2"))
    selected = _action(revision=1, new_shares_per_old_share=D("3"),
                       available=datetime(2024, 7, 3, 12, tzinfo=UTC))
    ledger = _ledger()
    _post(ledger, _opening(api, ledger, (_available(api, selected), _available(api, early))))
    assert ledger.balance().positions == ((INST, D("30")),)
    assert [(a.action_id, a.revision) for a in ledger.action_state().applied_actions] == [(early.action_id, 1)]
    # A late revision must invalidate, rather than silently selecting revision 1.
    late = _action(revision=2, available=datetime(2024, 7, 5, 14, tzinfo=UTC))
    other = _ledger()
    before = _snapshot(other)
    _reject(lambda: _opening(api, other, tuple(_available(api, a) for a in (early, selected, late))))
    assert _snapshot(other) == before


@pytest.mark.parametrize("changes", (
    {"instrument_id": "inst-other"}, {"effective": PAY_DATE},
    {"source": "synthetic-other"}, {"available": datetime(2024, 7, 1, 12, tzinfo=UTC)},
))
def test_revision_series_identity_and_monotone_provenance_are_checked(changes: dict[str, Any]) -> None:
    api = _api()
    ledger = _ledger()
    first = _action(available=datetime(2024, 7, 2, 12, tzinfo=UTC))
    second = _action(revision=1, **changes)
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, first), _available(api, second))))
    assert _snapshot(ledger) == before


def test_archive_and_availability_policies_are_explicit_and_terms_obey_same_boundary() -> None:
    api = _api()
    action = _action(ingested=datetime(2024, 7, 5, 14, tzinfo=UTC))
    ledger = _ledger()
    _post(ledger, _opening(api, ledger, (_available(api, action),),
                           replay_policy=BundleReplayPolicy.AVAILABILITY))
    assert ledger.balance().positions == ((INST, D("20")),)
    action = _action()
    late_manifest = _manifest("late-terms", available=datetime(2024, 7, 5, 14, tzinfo=UTC))
    other = _ledger()
    before = _snapshot(other)
    _reject(lambda: _opening(api, other, (_available(api, action,
                                                    terms=_terms(api, action, manifest=late_manifest)),)))
    assert _snapshot(other) == before


@pytest.mark.parametrize("field,value", (("action_id", "different-action"),
                                        ("instrument_id", "different-instrument"),
                                        ("action_source", "different-source"),
                                        ("action_revision", 1), ("currency", "EUR"),
                                        ("effective_date", PAY_DATE)))
def test_supplementary_terms_bind_exact_financial_action(field: str, value: Any) -> None:
    api = _api()
    action = _action("dividend", "dividend-terms")
    _reject(lambda: _available(api, action, terms=_terms(api, action, **{field: value})))


def test_split_alias_then_dividend_before_trades_is_one_atomic_transition() -> None:
    api = _api()
    ledger = _ledger()
    before = ledger.balance()
    split, alias, dividend = _action(), _action("ticker_change", "alias-synthetic"), _action("dividend", "div-synthetic")
    events = _opening(api, ledger, tuple(_available(api, a) for a in (dividend, alias, split)))
    assert len(events) == 1
    after = _post(ledger, events)
    assert after.event_count == before.event_count + 1
    assert after.positions == ((INST, D("20")),)
    assert after.cash == before.cash
    assert after.receivables == D("20")
    assert after.total_fees == before.total_fees == ZERO
    assert ledger.action_state().symbols == ((INST, "RENAMED"),)
    assert _nav(ledger, EX_DATE, "50").value == D("2020")
    assert _seed().api03.AccountingInvariant.check(before, events[0], after) is None
    replay = _ledger(held=False)
    replay.replay(ledger.events)
    assert _snapshot(replay) == _snapshot(ledger)


def test_invalid_later_action_rejects_entire_opening_batch_without_partial_publication() -> None:
    api = _api()
    ledger = _ledger()
    valid = _available(api, _action())
    unsupported = _available(api, _action("delisting", "delist-no-evidence"), terms=None)
    before = _snapshot(ledger)
    _reject(lambda: _post(ledger, _opening(api, ledger, (valid, unsupported))))
    assert _snapshot(ledger) == before


@pytest.mark.parametrize("quantity,ratio,expected", (("1", "0.000001", "0.000001"),
                                                   ("3", "0.5", "1.5"), ("10", "3", "30")))
def test_split_preserves_supported_exact_fractions_and_rational_inverse_references(
    quantity: str, ratio: str, expected: str,
) -> None:
    api = _api()
    seed = _seed(quantity)
    ledger = _ledger(seed)
    action = _action(new_shares_per_old_share=D(ratio))
    before = ledger.balance()
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        ambient.traps[Rounded] = True
        _post(ledger, _opening(api, ledger, (_available(api, action),), references=(_reference(api, seed),)))
    after = ledger.balance()
    assert after.positions == ((INST, D(expected)),)
    assert after.cash == before.cash
    reference = ledger.action_state().split_references[0]
    # Integer cross-products prove the inverse without rounded Decimal division.
    n, d = D(ratio).as_integer_ratio()
    assert reference.cost_basis_numerator * n == 100 * reference.cost_basis_denominator * d
    assert reference.mark_numerator * n == 100 * reference.mark_denominator * d
    if ratio == "3":
        assert (reference.cost_basis_numerator, reference.cost_basis_denominator) == (100, 3)
    assert reference.instrument_id == INST
    # A reference is not a fresh mark: an empty mark set still invalidates NAV.
    outcome = bt02._outcome(seed.api02, seed.case, session=EX_DATE)
    result = seed.api03.NAVCalculator().compute(after, (), bt03._accounting_policy(seed.api03, seed.case, outcome))
    _assert_unavailable(result)


@pytest.mark.parametrize("quantity,ratio", (("1", "0.0000001"), ("1000000000", "1001")))
def test_unsupported_precision_or_holding_overflow_never_rounds_or_truncates(quantity: str, ratio: str) -> None:
    api = _api()
    seed = _seed(quantity, "1", "1000000000000")
    ledger = _ledger(seed)
    action = _action(new_shares_per_old_share=D(ratio))
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, action),), references=(_reference(api, seed),)))
    assert _snapshot(ledger) == before


def test_evidenced_cash_in_lieu_accrues_fraction_and_cannot_pay_early() -> None:
    api = _api()
    seed = _seed("3")
    ledger = _ledger(seed)
    action = _action(new_shares_per_old_share=D("0.5"))
    terms = _terms(api, action, fractional_shares="cash_in_lieu", lot_size=D("1"),
                   cash_in_lieu_price=D("200"), payable_date=PAY_DATE)
    policy = _policy(api, fractional_shares="cash_in_lieu")
    before = ledger.balance()
    _post(ledger, _opening(api, ledger, (_available(api, action, terms=terms),), references=(_reference(api, seed),), policy=policy))
    assert ledger.balance().positions == ((INST, D("1")),)
    assert ledger.balance().cash == before.cash
    assert ledger.balance().receivables == D("100")
    _post(ledger, _payment(api, ledger, EX_DATE, policy=policy))
    assert ledger.balance().cash == before.cash
    _post(ledger, _payment(api, ledger, PAY_DATE, policy=policy))
    assert ledger.balance().cash == before.cash + D("100")
    assert ledger.balance().receivables == ZERO
    assert _nav(ledger, PAY_DATE, "200").value == D("2000")


def test_split_cancels_filled_and_never_filled_gtc_intents_and_denies_actual_later_fills() -> None:
    api = _api()
    seed = SimpleNamespace(**vars(_seed()))
    seed.policy = bt02._policy(seed.api02, half_spread_bps=ZERO, slippage_bps=ZERO,
                               commission_per_share=ZERO, order_minimum=ZERO,
                               fixed_share_cap=D("10"), lot_size=D("0.000001"))
    seed.intent = bt02._intent(seed.api02, seed.case, quantity=D("20"), time_in_force="gtc",
                               expires_at=_seed().intent.expires_at)
    seed.fill = bt03._make_fill(seed.api02, seed.case, intent=seed.intent, outcome=seed.outcome,
                               policy=seed.policy, cap=D("10"))
    unfilled = bt02._intent(seed.api02, seed.case, quantity=D("1"), side="sell", time_in_force="gtc",
                            expires_at=seed.intent.expires_at, plan_id="synthetic-never-filled")
    ledger = _ledger(seed)
    _post(ledger, _opening(api, ledger, (_available(api, _action()),),
                           outstanding_intents=(seed.intent, unfilled)))
    cancellations = ledger.action_state().cancelled_intents
    assert {entry.intent_id for entry in cancellations} == {seed.intent.intent_id, unfilled.intent_id}
    assert all(entry.reason == "split_preexisting_intent" for entry in cancellations)
    outcome = bt02._outcome(seed.api02, seed.case, session=PAY_DATE, price=D("50"))
    fill = bt03._make_fill(seed.api02, seed.case, intent=unfilled, outcome=outcome,
                          policy=seed.policy, shares=D("20"))
    before = _snapshot(ledger)
    _reject(lambda: ledger.append(bt03._fill_event(
        seed.api03, ledger, intent=unfilled, fill=fill, case=seed.case, outcome=outcome,
        policy=seed.policy, event_id="forbidden-after-split")))
    assert _snapshot(ledger) == before
    remainder = bt03._make_fill(seed.api02, seed.case, intent=seed.intent, outcome=outcome,
        policy=seed.policy, remaining=D("10"), cumulative=D("10"), cash=D("1000"), cap=D("10"))
    _reject(lambda: ledger.append(bt03._fill_event(seed.api03, ledger, intent=seed.intent,
        fill=remainder, case=seed.case, outcome=outcome, policy=seed.policy, event_id="cancelled-gtc-remainder")))
    assert _snapshot(ledger) == before
    # Omission from the caller's outstanding list cannot bypass the split boundary.
    omitted = bt02._intent(seed.api02, seed.case, quantity=D("1"), side="sell", time_in_force="gtc",
                           expires_at=seed.intent.expires_at, plan_id="synthetic-omitted-intent")
    omitted_fill = bt03._make_fill(seed.api02, seed.case, intent=omitted, outcome=outcome,
                                  policy=seed.policy, shares=D("20"))
    _reject(lambda: ledger.append(bt03._fill_event(
        seed.api03, ledger, intent=omitted, fill=omitted_fill, case=seed.case, outcome=outcome,
        policy=seed.policy, event_id="omitted-after-split")))
    assert _snapshot(ledger) == before


@pytest.mark.parametrize("basis,conversion,expected", (("post_split", False, "20"),
                                                     ("pre_split", True, "10")))
def test_dividend_basis_is_explicit_and_pre_basis_conversion_is_evidenced(
    basis: str, conversion: bool, expected: str,
) -> None:
    api = _api()
    ledger = _ledger()
    split, dividend = _action(), _action("dividend", "div-basis")
    terms = _terms(api, dividend, basis=basis,
                   conversion_action_id=split.action_id if conversion else None,
                   conversion_ratio=D("2") if conversion else None)
    _post(ledger, _opening(api, ledger, (_available(api, dividend, terms=terms), _available(api, split))))
    assert ledger.balance().receivables == D(expected)


@pytest.mark.parametrize("basis,ratio", (("unknown", None), ("pre_split", None), ("pre_split", D("3"))))
def test_ambiguous_or_mismatched_dividend_basis_never_invents_entitlement(basis: str, ratio: Any) -> None:
    api = _api()
    ledger = _ledger()
    split, dividend = _action(), _action("dividend", "div-ambiguous")
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (
        _available(api, split), _available(api, dividend, terms=_terms(
            api, dividend, basis=basis, conversion_action_id=split.action_id, conversion_ratio=ratio)),)))
    assert _snapshot(ledger) == before


def test_entitlement_survives_sale_and_payment_is_once_only_on_next_witnessed_session() -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger(seed)
    dividend = _action("dividend", "div-closed-pay", payable_date=date(2024, 7, 6))
    _post(ledger, _opening(api, ledger, (_available(api, dividend),)))
    assert ledger.balance().receivables == D("10")
    sale = bt02._intent(seed.api02, seed.case, quantity=D("10"), side="sell", time_in_force="gtc",
                        expires_at=seed.intent.expires_at)
    outcome = bt02._outcome(seed.api02, seed.case, session=EX_DATE)
    fill = bt03._make_fill(seed.api02, seed.case, intent=sale, outcome=outcome, policy=seed.policy)
    ledger.append(bt03._fill_event(seed.api03, ledger, intent=sale, fill=fill, case=seed.case,
                                   outcome=outcome, policy=seed.policy, event_id="sale-after-entitlement"))
    assert ledger.balance().positions == ()
    assert ledger.balance().receivables == D("10")
    # Opening payment must be evaluated before this session's fills; use an earlier snapshot.
    early = _ledger(seed)
    _post(early, _opening(api, early, (_available(api, dividend),)))
    _post(early, _payment(api, early, EX_DATE))
    assert early.balance().cash == D("1000")
    payment = _payment(api, ledger, PAY_DATE)
    _post(ledger, payment)
    assert ledger.balance().cash == D("2010")
    assert ledger.balance().receivables == ZERO
    before = _snapshot(ledger)
    assert _payment(api, ledger, date(2024, 7, 9), event_id="pay-again") == ()
    assert _opening(api, ledger, (_available(api, dividend),), event_id="entitle-again") == ()
    assert _snapshot(ledger) == before
    assert ledger.append(payment[0]) == ledger.balance()


def test_zero_holding_entitlement_retains_business_identity_without_income() -> None:
    api = _api()
    ledger = _ledger(held=False)
    dividend = _action("dividend", "div-zero")
    _post(ledger, _opening(api, ledger, (_available(api, dividend),), references=()))
    assert ledger.balance().cash == D("2000")
    assert ledger.balance().receivables == ZERO
    assert [a.action_id for a in ledger.action_state().applied_actions] == [dividend.action_id]


def test_non_session_effective_date_and_unknown_pay_calendar_coverage_fail_closed() -> None:
    api = _api()
    ledger = _ledger()
    closed_action = _action(effective=date(2024, 7, 4))
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, closed_action),)))
    assert _snapshot(ledger) == before
    # There is no witnessed next eligible session beyond the sealed range.
    far_pay = _action("dividend", "div-beyond-calendar", payable_date=date(2024, 7, 13))
    _reject(lambda: _opening(api, ledger, (_available(api, far_pay),)))
    assert _snapshot(ledger) == before


def test_alias_continuity_preserves_stable_id_and_cash_and_rejects_broken_chain() -> None:
    api = _api()
    ledger = _ledger()
    first = _action("ticker_change", "alias-1")
    _post(ledger, _opening(api, ledger, (_available(api, first),)))
    assert ledger.balance().cash == D("1000")
    assert ledger.balance().positions == ((INST, D("10")),)
    assert ledger.action_state().symbols == ((INST, "RENAMED"),)
    bad = _action("ticker_change", "alias-2", effective=PAY_DATE, old_symbol="KEEP", new_symbol="BROKEN")
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, bad),), session_date=PAY_DATE))
    assert _snapshot(ledger) == before


def test_merger_is_internal_explicit_evidenced_mapping_and_denies_stale_source_fills() -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger(seed)
    fields = {"schema_version": "v1", "mapping_id": "merger-synthetic", "policy_version": "bt04-merger-v1",
                  "source_instrument_id": INST, "target_instrument_id": "inst-acquirer", "currency": "USD",
                  "effective_date": EX_DATE, "new_shares_per_old_share": D("0.5"),
                  "manifest": _manifest("merger-synthetic")}
    _reject(lambda: api.MergerMapping(**{**fields, "manifest": None}))
    before = ledger.balance()
    mapping = api.MergerMapping(**fields)
    _post(ledger, _opening(api, ledger, (), mergers=(mapping,)))
    assert ledger.balance().positions == (("inst-acquirer", D("5")),)
    assert ledger.balance().cash == before.cash
    assert INST in ledger.action_state().closed_instruments
    stale = bt02._intent(seed.api02, seed.case, side="buy", quantity=D("1"), time_in_force="gtc",
                         expires_at=seed.intent.expires_at)
    outcome = bt02._outcome(seed.api02, seed.case, session=PAY_DATE)
    fill = bt03._make_fill(seed.api02, seed.case, intent=stale, outcome=outcome, policy=seed.policy)
    snapshot = _snapshot(ledger)
    _reject(lambda: ledger.append(bt03._fill_event(seed.api03, ledger, intent=stale, fill=fill,
        case=seed.case, outcome=outcome, policy=seed.policy, event_id="stale-merger-fill")))
    assert _snapshot(ledger) == snapshot
    # Distinct-ID evidence never adds a PIT wire action variant.
    assert {a.value for a in importlib.import_module("mytradingalpha.data.actions").ActionType} == {
        "ticker_change", "split", "dividend", "delisting"}


@pytest.mark.parametrize("settlement", ("cash", "writeoff"))
def test_delisting_requires_evidence_or_explicit_writeoff_and_blocks_later_trade(settlement: str) -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger(seed)
    action = _action("delisting", "delisting-synthetic")
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, action, terms=None),)))
    assert _snapshot(ledger) == before
    terms = _terms(api, action, settlement=settlement,
                   amount_per_share=D("30") if settlement == "cash" else ZERO,
                   payable_date=PAY_DATE if settlement == "cash" else None)
    _post(ledger, _opening(api, ledger, (_available(api, action, terms=terms),),
                           outstanding_intents=(seed.intent,)))
    assert ledger.balance().positions == ()
    assert ledger.balance().cash == D("1000")
    assert ledger.balance().receivables == (D("300") if settlement == "cash" else ZERO)
    assert INST in ledger.action_state().closed_instruments
    _post(ledger, _payment(api, ledger, PAY_DATE))
    assert ledger.balance().cash == (D("1300") if settlement == "cash" else D("1000"))
    later = bt02._outcome(seed.api02, seed.case, session=date(2024, 7, 9))
    buy = bt02._intent(seed.api02, seed.case, quantity=D("1"), time_in_force="gtc", expires_at=seed.intent.expires_at,
                       plan_id="synthetic-delisted-buy")
    fill = bt03._make_fill(seed.api02, seed.case, intent=buy, outcome=later, policy=seed.policy)
    snapshot = _snapshot(ledger)
    _reject(lambda: ledger.append(bt03._fill_event(seed.api03, ledger, intent=buy, fill=fill,
        case=seed.case, outcome=later, policy=seed.policy, event_id="delisted-trade")))
    assert _snapshot(ledger) == snapshot


def test_action_event_retry_after_later_event_returns_current_state_and_business_id_cannot_double_post() -> None:
    api = _api()
    ledger = _ledger()
    action = _action()
    events = _opening(api, ledger, (_available(api, action),))
    _post(ledger, events)
    later = _action("dividend", "later-dividend", effective=PAY_DATE, payable_date=date(2024, 7, 9))
    _post(ledger, _opening(api, ledger, (_available(api, later),), session_date=PAY_DATE))
    before = _snapshot(ledger)
    assert ledger.append(events[0]) == ledger.balance()
    assert _opening(api, ledger, (_available(api, action),), event_id="different-event-id") == ()
    assert _snapshot(ledger) == before
    changed = _action(revision=1, new_shares_per_old_share=D("3"))
    _reject(lambda: _opening(api, ledger, (_available(api, changed),), event_id="changed-revision"))
    assert _snapshot(ledger) == before


def test_action_posting_is_bound_to_exact_prefix_and_accounting_recomputes_transition() -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger()
    event = _opening(api, ledger, (_available(api, _action()),))[0]
    # A valid, unrelated event advances the exact same ledger before action append.
    ledger.append(bt03._obligation_event(seed.api03, ledger, event_id="prefix-interloper",
        kind="receivable_create", obligation_id="independent-claim", amount=D("1"),
        economic_time=datetime(2024, 7, 3, 18, tzinfo=UTC),
        observed_at=datetime(2024, 7, 3, 18, tzinfo=UTC), due_at=datetime(2024, 7, 5, 0, tzinfo=UTC)))
    before = _snapshot(ledger)
    _reject(lambda: ledger.append(event))
    assert _snapshot(ledger) == before
    fresh = _ledger()
    prior = fresh.balance()
    accepted = fresh.append(event)
    _reject(lambda: seed.api03.AccountingInvariant.check(prior, event, prior))
    forged = copy.deepcopy(accepted)
    object.__setattr__(forged, "cash", accepted.cash + D("1"))
    _reject(lambda: seed.api03.AccountingInvariant.check(prior, event, forged))


def test_cash_and_buy_hold_own_independent_events_balances_nav_and_explicit_policies() -> None:
    api = _api()
    common = _common(api)
    sessions = tuple(_session_input(api, day, price=price)
                     for day, price in zip(SESSIONS[:3], ("100", "110", "90"), strict=True))
    runner = api.BenchmarkRunner()
    cash = runner.run_cash(sessions, policy=api.CashBenchmarkPolicy(common=common, interest_policy="zero", annual_rate=ZERO))
    bh = runner.run_buy_and_hold(sessions, policy=_bh_policy(api, common=common))
    strategy = bt03._new_ledger(_seed().api03, _case(), resolution_cutoff=common.resolution_cutoff)
    assert bt03._result_status(cash) == bt03._result_status(bh) == "available"
    assert cash.run_valid is bh.run_valid is True
    assert cash.events == ()
    assert [b.cash for b in cash.balances] == [D("2000")] * 3
    assert [p.value for p in cash.nav_points] == [D("2000")] * 3
    assert [p.value for p in bh.nav_points] == [D("2000"), D("2100"), D("1900")]
    assert bh.balances[-1].positions == ((INST, D("10")),)
    assert bh.balances[-1].cash == D("1000")
    assert len(bh.events) == 1
    assert all(event.kind == "fill" for event in bh.events)
    assert strategy.balance().positions == ()
    assert strategy.balance().cash == D("2000")
    replay = bt03._new_ledger(_seed().api03, _case(), resolution_cutoff=common.resolution_cutoff)
    replay.replay(bh.events)
    assert replay.balance() == bh.balances[-1]
    assert _run_bh(api, sessions=sessions).canonical_bytes() == bh.canonical_bytes()
    _reject(lambda: runner.run_cash(sessions, policy=api.CashBenchmarkPolicy(
        common=common, interest_policy="zero", annual_rate=ZERO), ledger=strategy))


def test_benchmark_entry_is_precommitted_simulation_intent_independent_of_strategy_no_trade() -> None:
    api = _api()
    no_trade = bt02._case(no_trade=True)
    assert no_trade.envelope.no_trade is True
    seed = _seed()
    assert seed.intent.created_at < seed.case.binding.next_session.open_at
    assert seed.intent.execution_authority == "simulation_only"
    result = _run_bh(api)
    assert bt03._result_status(result) == "available"
    assert result.events[0].intent.intent_id == seed.intent.intent_id
    assert result.balances[-1].positions == ((INST, D("10")),)
    assert no_trade.envelope.no_trade is True


def test_benchmark_entry_costs_fee_once_lots_and_residual_cash_are_exact() -> None:
    api = _api()
    policy = bt02._policy(_seed().api02, half_spread_bps=D("50"), slippage_bps=D("50"),
                         commission_per_share=D("0.1"), order_minimum=D("1"),
                         fixed_share_cap=D("100"), lot_size=D("1"))
    result = _run_bh(api, policy=_bh_policy(api, common=_common(api, cost_policy=policy),
                                           members=(_member(api, lot_size=D("1")),)))
    assert bt03._result_status(result) == "available"
    assert result.balances[-1].cash == D("989")
    assert result.balances[-1].total_fees == D("1")
    assert result.nav_points[-1].value == D("1989")
    assert len(result.events) == 1
    assert result.events[0].fill.price == D("101")
    assert result.events[0].fill.fee == D("1")


@pytest.mark.parametrize("field,value", (("opening_cash", D("900")), ("currency", "EUR"),
                                        ("mark_source", "wrong-source"), ("mark_revision", 1)))
def test_benchmark_cannot_silently_change_entry_lots_or_common_source_assumptions(field: str, value: Any) -> None:
    api = _api()
    if field == "currency":
        _reject(lambda: _common(api, **{field: value}))
    else:
        result = _run_bh(api, policy=_bh_policy(api, common=_common(api, **{field: value})))
        _assert_unavailable(result)


def test_benchmark_cap_or_limit_failure_does_not_retry_enter_later_or_resize_lots() -> None:
    api = _api()
    seed = _seed()
    cap_policy = bt02._policy(seed.api02, half_spread_bps=ZERO, slippage_bps=ZERO,
                              commission_per_share=ZERO, order_minimum=ZERO, fixed_share_cap=D("5"))
    _assert_unavailable(_run_bh(api, policy=_bh_policy(api, common=_common(api, cost_policy=cap_policy))))
    limit = bt02._intent(seed.api02, seed.case, quantity=D("10"), order_type="limit", limit_price=D("90"),
                          time_in_force="gtc", expires_at=seed.intent.expires_at)
    sessions = tuple(_session_input(api, day, price=price)
                     for day, price in zip(SESSIONS[:3], ("100", "80", "80"), strict=True))
    _assert_unavailable(_run_bh(api, sessions=sessions,
                               policy=_bh_policy(api, members=(_member(api, intent=limit),))))


def test_benchmark_dividends_stay_cash_without_reinvestment_or_rebalance() -> None:
    api = _api()
    dividend = _available(api, _action("dividend", "benchmark-dividend", amount_per_share=D("10")))
    sessions = (_session_input(api, ENTRY), _session_input(api, EX_DATE, actions=(dividend,)),
                _session_input(api, PAY_DATE, price="120"))
    result = _run_bh(api, sessions=sessions)
    assert bt03._result_status(result) == "available"
    assert [b.positions for b in result.balances] == [((INST, D("10")),)] * 3
    assert [b.cash for b in result.balances] == [D("1000"), D("1000"), D("1100")]
    assert result.balances[1].receivables == D("100")
    assert result.balances[-1].receivables == ZERO
    assert result.nav_points[-1].value == D("2300")
    assert sum(event.kind == "fill" for event in result.events) == 1
    for changes in ({"rebalance": "daily"}, {"dividend_treatment": "reinvest"}, {"residual_cash": "spend"}):
        _reject(lambda changes=changes: _bh_policy(api, **changes))


def test_benchmark_uses_own_opening_actions_and_fresh_post_split_marks() -> None:
    api = _api()
    split = _available(api, _action())
    dividend = _available(api, _action("dividend", "benchmark-split-dividend"))
    sessions = (_session_input(api, ENTRY),
                _session_input(api, EX_DATE, price="50", actions=(dividend, split), references=(_reference(api),)),
                _session_input(api, PAY_DATE, price="50"))
    result = _run_bh(api, sessions=sessions)
    assert bt03._result_status(result) == "available"
    assert result.balances[1].positions == ((INST, D("20")),)
    assert result.balances[1].receivables == D("20")
    assert result.balances[-1].cash == D("1020")
    assert result.nav_points[-1].value == D("2020")
    assert sum(e.kind == "fill" for e in result.events) == 1
    saved = result.canonical_bytes()
    returned = result.policy.members[0].intent
    returned.__dict__["quantity"] = D("99")
    assert result.canonical_bytes() == saved
    assert result.policy.members[0].intent.quantity == D("10")


def test_dividend_claim_survives_later_delisting_and_both_payments_reconcile() -> None:
    api = _api()
    ledger = _ledger()
    dividend = _available(api, _action("dividend", "claim-before-delisting"))
    _post(ledger, _opening(api, ledger, (dividend,)))
    delisting = _action("delisting", "later-delisting", effective=PAY_DATE)
    terms = _terms(api, delisting, payable_date=date(2024, 7, 9))
    _post(ledger, _opening(api, ledger, (_available(api, delisting, terms=terms),), session_date=PAY_DATE))
    assert ledger.balance().receivables == D("310")
    _post(ledger, _payment(api, ledger, PAY_DATE))
    assert ledger.balance().cash == D("1010")
    assert ledger.balance().receivables == D("300")
    _post(ledger, _payment(api, ledger, date(2024, 7, 9), event_id="final-settlement"))
    assert ledger.balance().positions == ()
    assert ledger.balance().receivables == ZERO
    assert ledger.balance().cash == D("1310")


def test_benchmark_keeps_delisted_initial_member_and_uses_only_evidenced_settlement() -> None:
    api = _api()
    action = _action("delisting", "benchmark-delisting")
    missing = (_session_input(api, ENTRY), _session_input(api, EX_DATE, actions=(_available(api, action, terms=None),)),
               _session_input(api, PAY_DATE, marks=()))
    _assert_unavailable(_run_bh(api, sessions=missing))
    evidenced = (_session_input(api, ENTRY), _session_input(api, EX_DATE, marks=(), actions=(_available(api, action),)),
                 _session_input(api, PAY_DATE, marks=()))
    result = _run_bh(api, sessions=evidenced)
    assert bt03._result_status(result) == "available"
    assert result.balances[0].positions == ((INST, D("10")),)
    assert result.balances[-1].positions == ()
    assert result.balances[-1].cash == D("1300")
    assert result.nav_points[-1].value == D("1300")
    assert result.policy.members[0].instrument_id == INST


@pytest.mark.parametrize("change", ("missing", "future", "adjusted", "wrong_id", "wrong_currency"))
def test_required_benchmark_marks_never_fall_back_to_reference_or_last_price(change: str) -> None:
    api = _api()
    seed = _seed()
    marks: tuple[Any, ...] = ()
    if change != "missing":
        bar = bt02._make_bar(seed.case, session=EX_DATE,
                            adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED if change == "adjusted" else AdjustmentBasis.UNADJUSTED)
        if change == "wrong_id":
            bar = DailyBar.model_validate({**bar.model_dump(mode="python"), "instrument_id": "inst-wrong"})
        if change == "future":
            bar = bt02._make_bar(seed.case, session=PAY_DATE)
        if change == "wrong_currency":
            # Explicit policy mismatch; no fabricated EligibleMark.
            wrong_policy = bt03._accounting_policy(seed.api03, seed.case,
                bt02._outcome(seed.api02, seed.case, bar=bar), currency="EUR")
            sessions = (_session_input(api, ENTRY), _session_input(api, EX_DATE, accounting_policy=wrong_policy),
                        _session_input(api, PAY_DATE))
            _assert_unavailable(_run_bh(api, sessions=sessions))
            return
        outcome = bt02._outcome(seed.api02, seed.case, bar=bar)
        marks = (bt03._mark(seed.api03, seed.case, outcome),)
    sessions = (_session_input(api, ENTRY), _session_input(api, EX_DATE, marks=marks), _session_input(api, PAY_DATE))
    _assert_unavailable(_run_bh(api, sessions=sessions))


def test_benchmark_sessions_are_contiguous_unique_and_common_policy_aligned() -> None:
    api = _api()
    first, second, third = (_session_input(api, day) for day in SESSIONS[:3])
    for sessions in ((first, third), (first, second, second, third), (second, first, third)):
        _assert_unavailable(_run_bh(api, sessions=sessions))
    _reject(lambda: api.CashBenchmarkPolicy(common=_common(api), interest_policy="zero", annual_rate=D("0.01")))
    _reject(lambda: api.CashBenchmarkPolicy(common=_common(api), interest_policy="evidenced", annual_rate=D("0.01")))
    bad_member = _member(api, instrument_id="inst-not-in-frozen-universe")
    _reject(lambda: _bh_policy(api, members=(bad_member,)))
    _reject(lambda: _bh_policy(api, members=(_member(api, weight="1.1"),)))
    _reject(lambda: _bh_policy(api, members=(_member(api, quantity="10.5", lot_size=D("1")),)))


def _renamed(model: Any, index: int) -> Any:
    """Create labelled synthetic typed sources, then use the real public builder."""
    raw = model.model_dump(mode="json")

    def replace(value: Any) -> Any:
        if type(value) is dict:
            return {key: replace(item) for key, item in value.items()}
        if type(value) is list:
            return [replace(item) for item in value]
        if type(value) is str:
            return value.replace("survivor", f"bt04-member-{index:02d}").replace("KEEP", f"SYN{index:02d}")
        return value

    return type(model).model_validate(replace(raw))


@lru_cache(maxsize=3)
def _member_sources(count: int, session_count: int = 5, *, shared: bool = True) -> tuple[SimpleNamespace, ...]:
    base = _case(session_count)
    bundle = base.bundle
    api01, api02, api03 = bt01._bt_api(), bt02._bt02_api(), bt03._bt03_api()
    instruments = tuple(_renamed(next(x for x in bundle.instruments if x.instrument_id == INST), i) for i in range(count))
    aliases = tuple(_renamed(next(x for x in bundle.aliases if x.instrument_id == INST), i) for i in range(count))
    memberships = tuple(_renamed(next(x for x in bundle.memberships if x.instrument_id == INST), i) for i in range(count))
    bars = tuple(_renamed(bar, i) for i in range(count) for bar in bundle.bars if bar.instrument_id == INST)
    extended = build_evidence_bundle(
        schema_version="v1", bundle_id=f"synthetic-bt04-common-{count:02d}",
        created_at=bundle.created_at, knowledge_cutoff=bundle.knowledge_cutoff,
        replay_policy=bundle.replay_policy, requirements=bundle.requirements,
        missing_optional=bundle.missing_optional, calendar=bundle.calendar,
        instrument_candidates=(*bundle.instruments, *instruments),
        alias_candidates=(*bundle.aliases, *aliases), membership_candidates=(*bundle.memberships, *memberships),
        action_candidates=bundle.actions, bar_candidates=(*bundle.bars, *bars), filing_candidates=bundle.filings,
        event_candidates=bundle.events, social_post_candidates=bundle.social_posts,
        macro_observation_candidates=bundle.macro_observations,
    )
    common_bundle = extended
    results: list[SimpleNamespace] = []
    for index, instrument in enumerate(instruments):
        if shared:
            extended = common_bundle
        else:
            # Action references prove each instrument separately. Unlike a multi-mark
            # NAV, those inputs need no common bundle. Keep genuine fill retention bounded.
            extended = build_evidence_bundle(
                schema_version="v1", bundle_id=f"synthetic-bt04-isolated-{index:02d}",
                created_at=bundle.created_at, knowledge_cutoff=bundle.knowledge_cutoff,
                replay_policy=bundle.replay_policy, requirements=bundle.requirements,
                missing_optional=bundle.missing_optional, calendar=bundle.calendar,
                instrument_candidates=(*bundle.instruments, instrument),
                alias_candidates=(*bundle.aliases, aliases[index]),
                membership_candidates=(*bundle.memberships, memberships[index]),
                action_candidates=bundle.actions,
                bar_candidates=(*bundle.bars, *(bar for bar in bars if bar.instrument_id == instrument.instrument_id)),
                filing_candidates=bundle.filings, event_candidates=bundle.events,
                social_post_candidates=bundle.social_posts, macro_observation_candidates=bundle.macro_observations,
            )
        context = bt01._context(extended, run_id=base.context.run_id, variant_id=base.context.variant_id,
                                decision_time=bt01.DECISION_TIME, earliest_execution_time="2024-07-03T13:30:00Z")
        qapi = quant._api()
        signal = quant._score(qapi, bundle=extended, run_id=context.run_id,
                              feature_set=quant._features(qapi, bundle=extended, instrument_id=instrument.instrument_id))
        envelope = combine_quant_overlay(signal, context=context,
                                         registry=VariantRegistry().register(context.variant_id, kind="quant_only"))
        binding = api01.SessionClock.bind(context, extended, envelope)
        decision, opportunity = api01.BacktestRunner().run((binding,))
        case = SimpleNamespace(context=context, bundle=extended, envelope=envelope,
                               binding=binding, decision=decision, opportunity=opportunity)
        bar = _renamed(bt02._make_bar(base), index)
        outcome = bt02._outcome(api02, case, bar=bar)
        intent = bt02._intent(api02, case, bar=bar, quantity=D("1"))
        policy = _seed().policy
        fill = bt03._make_fill(api02, case, intent=intent, outcome=outcome, policy=policy)
        results.append(SimpleNamespace(case=case, api02=api02, api03=api03, intent=intent,
                                       outcome=outcome, fill=fill, policy=policy, cash=D("2000")))
    return tuple(results)


def _union_universe(sources: tuple[SimpleNamespace, ...]) -> Any:
    base = sources[0].case.bundle
    assert all(seed.case.context == sources[0].case.context for seed in sources)
    assert all(seed.case.bundle.bundle_hash == base.bundle_hash for seed in sources)
    return base


def test_revision_selected_action_and_term_count_bounds_accept_limit_and_reject_one_over() -> None:
    api = _api()
    actions = tuple(_available(api, _action("dividend", f"capacity-div-{index:02d}", revision=revision,
                                            amount_per_share=D(revision + 1)))
                    for index in range(32) for revision in range(2))
    ledger = _ledger()
    _post(ledger, _opening(api, ledger, actions))
    assert ledger.balance().receivables == D("640")
    assert len(ledger.action_state().applied_actions) == 32
    for extra in (_available(api, _action("dividend", "capacity-div-00", revision=2)),
                  _available(api, _action("dividend", "capacity-div-32"))):
        fresh = _ledger()
        before = _snapshot(fresh)
        candidate = (*actions, extra) if extra.action.action_id.endswith("00") else (*actions[::2], extra)
        _reject(lambda fresh=fresh, candidate=candidate: _opening(api, fresh, candidate))
        assert _snapshot(fresh) == before
    # One supplementary term per selected action makes 33 terms unreachable
    # without also exceeding the selected-action bound. The 32/33 control covers both.


def test_outstanding_intent_count_accepts_64_unique_cancellations_and_rejects_65() -> None:
    api = _api()
    seed = _seed()
    intents = tuple(bt02._intent(seed.api02, seed.case, quantity=D("1"), time_in_force="gtc",
                                 expires_at=seed.intent.expires_at, plan_id=f"synthetic-open-{index:02d}")
                    for index in range(65))
    ledger = _ledger()
    _post(ledger, _opening(api, ledger, (_available(api, _action()),), outstanding_intents=intents[:64]))
    assert len(ledger.action_state().cancelled_intents) == 64
    assert len({x.intent_id for x in ledger.action_state().cancelled_intents}) == 64
    fresh = _ledger()
    before = _snapshot(fresh)
    _reject(lambda: _opening(api, fresh, (_available(api, _action()),), outstanding_intents=intents))
    assert _snapshot(fresh) == before


def test_reference_count_accepts_32_genuine_instruments_and_rejects_33_before_work() -> None:
    api = _api()
    sources = _member_sources(33, shared=False)
    ledger = bt03._new_ledger(_seed().api03, _case(), opening_cash=D("10000"))
    references, actions = [], []
    for index, seed in enumerate(sources):
        references.append(api.PositionReference(instrument_id=seed.intent.instrument_id, symbol=f"SYN{index:02d}",
            cost_basis=D("100"), mark=bt03._mark(seed.api03, seed.case, seed.outcome)))
        if index < 32:
            ledger.append(bt03._fill_event(seed.api03, ledger, intent=seed.intent, fill=seed.fill, case=seed.case,
                outcome=seed.outcome, policy=seed.policy, event_id=f"synthetic-member-entry-{index:02d}"))
            actions.append(_available(api, _action(action_id=f"member-split-{index:02d}",
                                                  instrument_id=seed.intent.instrument_id)))
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, tuple(actions), references=tuple(references)))
    assert _snapshot(ledger) == before
    _post(ledger, _opening(api, ledger, tuple(actions), references=tuple(references[:32])))
    assert len(ledger.balance().positions) == 32
    assert all(quantity == D("2") for _, quantity in ledger.balance().positions)
    assert len(ledger.action_state().split_references) == 32
    assert _nav(ledger, EX_DATE, "50").value is None  # one mark cannot cover 32 holdings


def test_eight_benchmark_members_sixteen_sessions_and_128_work_units_are_real() -> None:
    api = _api()
    sources = _compact_member_sources(9, 16)
    case = sources[0].case
    members = tuple(_member(api, seed=seed, quantity="1", weight="0.05") for seed in sources)
    universe = _union_universe(sources)
    common = _common(api, case=case, end=SESSIONS[15])
    sessions = []
    for day in SESSIONS[:16]:
        marks = tuple(bt03._mark(seed.api03, seed.case, bt02._outcome(seed.api02, seed.case,
            bar=_renamed(bt02._make_bar(case, session=day), index)))
            for index, seed in enumerate(sources[:8]))
        sessions.append(_session_input(api, day, case=case, marks=marks))
    policy = _bh_policy(api, common=common, universe=universe, members=members[:8])
    result = _run_bh(api, sessions=tuple(sessions), policy=policy)
    assert bt03._result_status(result) == "available"
    assert len(result.nav_points) == 16
    assert len(result.balances[-1].positions) == 8
    assert result.balances[-1].cash == D("1200")
    assert all(point.value == D("2000") for point in result.nav_points)
    _reject(lambda: _bh_policy(api, common=common, universe=universe, members=members))
    # 129 cannot be represented by a rectangular run with both public limits:
    assert max(m * s for m in range(1, 9) for s in range(1, 17)) == 128
    too_long_case = _case(17)
    extra = _session_input(api, SESSIONS[16], case=too_long_case)
    _reject(lambda: api.BenchmarkRunner().run_buy_and_hold((*sessions, extra), policy=policy))


@pytest.mark.parametrize("ratio", (D("1E999999999"), D("1E-999999999"), D("NaN"), D("Infinity")))
def test_hostile_numeric_scalar_is_bounded_before_arithmetic(ratio: Decimal) -> None:
    api = _api()
    action = _action()
    action.__dict__["new_shares_per_old_share"] = ratio
    _reject(lambda: _available(api, action))


def test_source_text_byte_bounds_are_utf8_and_oversize_is_denied_before_inherited_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    action = _action("delisting", "text-bound")
    accepted = DelistingAction.model_validate({**action.model_dump(mode="python"), "reason": "é" * 1024})
    assert _available(api, accepted).action.reason == "é" * 1024
    oversized = copy.deepcopy(action)
    oversized.__dict__["reason"] = "é" * 1024 + "x"
    calls: list[str] = []
    original = DelistingAction.model_validate

    def observed(*args: Any, **kwargs: Any) -> Any:
        calls.append("validator")
        return original(*args, **kwargs)

    monkeypatch.setattr(DelistingAction, "model_validate", observed)
    _reject(lambda: _available(api, oversized))
    assert calls == []
    oversized.__dict__["reason"] = "x" * (2 * 1024 * 1024 + 1)
    _reject(lambda: _available(api, oversized))
    assert calls == []


class _Hostile:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def _called(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls.append("hostile protocol")
        raise AssertionError("synthetic secret must never be evaluated")

    __str__ = __repr__ = __iter__ = __call__ = __eq__ = __hash__ = _called


def test_exact_native_subclasses_callbacks_and_unknown_fields_are_rejected_without_protocols() -> None:
    api = _api()
    calls: list[str] = []
    hostile = _Hostile(calls)

    class ActionSubclass(SplitAction):
        def model_dump(self, *_args: Any, **_kwargs: Any) -> Any:
            calls.append("subclass serializer")
            raise AssertionError("untrusted serializer")

    class TupleSubclass(tuple):
        __iter__ = hostile._called

    class DecimalSubclass(Decimal):
        __str__ = __repr__ = hostile._called

    base = _action()
    subclass = ActionSubclass.model_validate(base.model_dump(mode="python"))
    _reject(lambda: _available(api, subclass, terms=None))
    _reject(lambda: _available(api, hostile, terms=None))
    damaged = copy.deepcopy(base)
    damaged.__dict__["manifest"] = hostile
    _reject(lambda: _available(api, damaged, terms=None))
    damaged = copy.deepcopy(base)
    damaged.__dict__["unexpected"] = hostile
    _reject(lambda: _available(api, damaged, terms=None))
    damaged = copy.deepcopy(base)
    damaged.__dict__["new_shares_per_old_share"] = DecimalSubclass("2")
    _reject(lambda: _available(api, damaged, terms=None))
    ledger = _ledger()
    for actions in (hostile, [hostile], TupleSubclass((_available(api, base),))):
        _reject(lambda actions=actions: _opening(api, ledger, actions))
    _reject(lambda: api.AvailableCorporateAction(action=base, terms=_terms(api, base), loader=hostile))
    _reject(lambda: api.BenchmarkSessionInput(session=_case().binding.next_session,
        marks=hostile, accounting_policy=hostile, actions=(), references=(), mergers=()))
    assert calls == []


def _native_action(root: Any) -> SplitAction:
    """Find the real captured model without prescribing a private field name."""
    seen: set[int] = set()
    stack = [root]
    while stack:
        value = stack.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if type(value) is SplitAction:
            return value
        if type(value) is dict:
            stack.extend(dict.values(value))
        elif type(value) in (tuple, list):
            stack.extend(value)
        elif type(value).__module__.startswith("mytradingalpha"):
            for cls in type(value).__mro__:
                fields = vars(cls).get("__slots__", ())
                for field in ((fields,) if type(fields) is str else fields):
                    if field in ("__dict__", "__weakref__"):
                        continue
                    with suppress(AttributeError):
                        stack.append(object.__getattribute__(value, field))
            with suppress(AttributeError):
                stack.extend(dict.values(object.__getattribute__(value, "__dict__")))
    pytest.fail("BT-04 must retain the full typed native action evidence")


def test_defensive_action_outputs_and_native_equal_mutation_cannot_alias_original_seals() -> None:
    api = _api()
    original = _action()
    wrapped = _available(api, original)
    saved = wrapped.canonical_bytes()
    original.__dict__["new_shares_per_old_share"] = D("7")
    returned = wrapped.action
    returned.__dict__["new_shares_per_old_share"] = D("9")
    assert wrapped.canonical_bytes() == saved
    assert wrapped.action.new_shares_per_old_share == D("2")
    for native in (D("2.0"), 2, True):
        damaged = _available(api, _action())
        _native_action(damaged).__dict__["new_shares_per_old_share"] = native
        _reject(damaged.canonical_bytes)


def test_action_source_changed_during_trusted_validation_is_rejected_at_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    action = _action()
    original = SplitAction.model_validate
    changed: list[bool] = []

    def mutate(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        action.__dict__["new_shares_per_old_share"] = D("2.0")
        changed.append(True)
        return result

    monkeypatch.setattr(SplitAction, "model_validate", mutate)
    _reject(lambda: _available(api, action))
    assert changed, "the test must exercise the trusted revalidation boundary"


@pytest.mark.parametrize("encoding", ("raw", "base64", "json_escape"))
def test_nested_canary_errors_have_fixed_diagnostics_without_chains_logs_or_warnings(
    encoding: str, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
) -> None:
    api = _api()
    canary = "sk-syntheticBT04CanaryOnly000000000000000000"
    encoded = {"raw": canary, "base64": base64.b64encode(canary.encode()).decode(),
               "json_escape": "".join(f"\\u{ord(c):04x}" for c in canary)}[encoding]
    action = _action()
    action.manifest.__dict__["terms"] = {"nested": [encoded]}
    with warnings.catch_warnings(record=True) as emitted:
        warnings.simplefilter("always")
        error = _reject(lambda: _available(api, action))
    diagnostic = str(error) + repr(error)
    if hasattr(error, "errors"):
        diagnostic += str(error.errors())
    outputs = capsys.readouterr()
    all_text = diagnostic + caplog.text + outputs.out + outputs.err + str(emitted)
    assert canary not in all_text
    assert encoded not in all_text
    assert emitted == []
    assert len(diagnostic) < 1024


def test_duplicate_and_stale_concurrent_action_publications_remain_atomic() -> None:
    api = _api()
    ledger = _ledger()
    event = _opening(api, ledger, (_available(api, _action()),))[0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = tuple(pool.map(ledger.append, (event,) * 4))
    assert all(balance == ledger.balance() for balance in results)
    assert ledger.balance().event_count == 2
    assert ledger.balance().positions == ((INST, D("20")),)
    other = _ledger()
    left = _opening(api, other, (_available(api, _action()),), event_id="competing-left")[0]
    right = _opening(api, other, (_available(api, _action(new_shares_per_old_share=D("3"))),), event_id="competing-right")[0]

    def append(candidate: Any) -> bool:
        try:
            other.append(candidate)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(append, (left, right))) == [False, True]
    assert other.balance().event_count == 2
    assert other.balance().positions in (((INST, D("20")),), ((INST, D("30")),))


def test_action_publication_barrier_reentry_and_completion_capture_precede_one_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger()
    event = _opening(api, ledger, (_available(api, _action()),))[0]
    entered, release, reader_started, reader_done = Event(), Event(), Event(), Event()
    original = seed.api03.AccountingInvariant._check_proposed
    nested_errors: list[BaseException] = []

    def pause(*args: Any, **kwargs: Any) -> Any:
        try:
            ledger.append(event)
        except (TypeError, ValueError) as error:
            nested_errors.append(error)
        entered.set()
        assert release.wait(5), "bounded action publication pause was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(seed.api03.AccountingInvariant, "_check_proposed", staticmethod(pause))

    def read() -> Any:
        reader_started.set()
        try:
            return ledger.balance()
        finally:
            reader_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(ledger.append, event)
        assert entered.wait(5)
        reader = pool.submit(read)
        try:
            assert reader_started.wait(5)
            assert not reader_done.wait(0.05), "reader observed a partially checked action"
        finally:
            release.set()
        assert writer.result(timeout=10) == reader.result(timeout=10)
    assert len(nested_errors) == 1
    assert ledger.balance().event_count == 2
    assert ledger.balance().positions == ((INST, D("20")),)


def test_action_native_completion_mutation_rejects_without_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger()
    event = _opening(api, ledger, (_available(api, _action()),))[0]
    before = _snapshot(ledger)
    original = seed.api03.AccountingInvariant._check_proposed

    def mutate(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        _native_action(event).__dict__["new_shares_per_old_share"] = D("2.0")
        return result

    monkeypatch.setattr(seed.api03.AccountingInvariant, "_check_proposed", staticmethod(mutate))
    _reject(lambda: ledger.append(event))
    assert _snapshot(ledger) == before


def test_actions_and_benchmarks_are_pure_under_armed_success_and_negative_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger()
    actions = (_available(api, _action()),)
    references = (_reference(api),)
    common = _common(api)
    bh_policy = _bh_policy(api, common=common)
    cash_policy = api.CashBenchmarkPolicy(common=common, interest_policy="zero", annual_rate=ZERO)
    sessions = tuple(_session_input(api, day) for day in SESSIONS[:3])
    missing_mark_sessions = (sessions[0], _session_input(api, EX_DATE, marks=()), sessions[2])
    invalid = _action()
    invalid.__dict__["manifest"] = None
    attempts: list[str] = []

    def deny(name: str) -> Callable[..., Any]:
        def blocked(*_args: Any, **_kwargs: Any) -> Any:
            attempts.append(name)
            raise AssertionError("unexpected external side effect")
        return blocked

    # Setup and imports above are outside the armed operation window.
    monkeypatch.setattr(builtins, "open", deny("file"))
    monkeypatch.setattr(Path, "open", deny("path"))
    monkeypatch.setattr(socket, "socket", deny("socket"))
    monkeypatch.setattr(socket, "create_connection", deny("connection"))
    monkeypatch.setattr(urllib.request, "urlopen", deny("HTTP"))
    monkeypatch.setattr(subprocess, "Popen", deny("process"))
    monkeypatch.setattr(subprocess, "run", deny("run"))
    monkeypatch.setattr(os, "getenv", deny("environment"))
    monkeypatch.setattr(os, "system", deny("shell"))
    monkeypatch.setattr(type(os.environ), "__getitem__", deny("environ"))
    monkeypatch.setattr(zoneinfo, "ZoneInfo", deny("timezone"))
    original_import = builtins.__import__

    def no_provider(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] in {"tradingagents", "openai", "anthropic", "langchain", "langgraph", "backtrader", "yfinance", "requests", "httpx"}:
            return deny("provider import")()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_provider)
    calendar_module = importlib.import_module("mytradingalpha.data.calendar")
    monkeypatch.setattr(calendar_module, "ZoneInfo", deny("calendar timezone"))
    monkeypatch.setattr(calendar_module, "capture_calendar_replay_evidence", deny("witness capture"))
    event = _opening(api, ledger, actions, references=references)[0]
    before = ledger.balance()
    after = ledger.append(event)
    seed.api03.AccountingInvariant.check(before, event, after)
    assert ledger.append(event) == after
    assert bt03._result_status(api.BenchmarkRunner().run_cash(sessions, policy=cash_policy)) == "available"
    assert bt03._result_status(api.BenchmarkRunner().run_buy_and_hold(sessions, policy=bh_policy)) == "available"
    _assert_unavailable(api.BenchmarkRunner().run_buy_and_hold(missing_mark_sessions, policy=bh_policy))
    _reject(lambda: _available(api, invalid, terms=None))
    _reject(lambda: _policy(api, currency="EUR"))
    assert attempts == []


def test_bt04_dependencies_are_offline_and_later_slices_remain_absent() -> None:
    _api()
    forbidden = {"os", "pathlib", "socket", "http", "urllib", "requests", "subprocess", "importlib",
                 "pickle", "marshal", "sqlite3", "yfinance", "langchain", "langgraph", "backtrader", "tradingagents"}
    for name in ("corporate_actions", "benchmarks"):
        source = ROOT / f"mytradingalpha/backtest/{name}.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        assert not {name for name in imports if name.split(".")[0] in forbidden}
        assert not any(isinstance(node, ast.Name) and node.id in {"eval", "exec", "__import__", "open", "ZoneInfo", "capture_calendar_replay_evidence"}
                       for node in ast.walk(tree))
        assert not any(name.startswith(("mytradingalpha.execution", "mytradingalpha.portfolio", "mytradingalpha.risk", "mytradingalpha.research"))
                       for name in imports)
    assert not any((ROOT / f"mytradingalpha/backtest/{name}.py").exists()
                   for name in ("manifest", "replay", "metrics", "reports"))


def test_adjusted_reference_with_explicit_actions_is_rejected() -> None:
    api = _api()
    seed = _seed()
    bar = bt02._make_bar(seed.case, adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED)
    outcome = bt02._outcome(seed.api02, seed.case, bar=bar)
    mark = bt03._mark(seed.api03, seed.case, outcome)
    _reject(lambda: api.PositionReference(instrument_id=INST, symbol="KEEP", cost_basis=D("100"), mark=mark))


@pytest.mark.parametrize("changed", (False, True))
def test_repeated_revision_record_cannot_be_coalesced_or_conflicted(changed: bool) -> None:
    api = _api()
    first = _action()
    second = _action(new_shares_per_old_share=D("3") if changed else D("2"))
    ledger = _ledger()
    before = _snapshot(ledger)
    _reject(lambda: _opening(api, ledger, (_available(api, first), _available(api, second))))
    assert _snapshot(ledger) == before


def test_payment_cannot_bridge_an_unwitnessed_calendar_gap() -> None:
    api = _api()
    ledger = _ledger()
    dividend = _action("dividend", "div-gap", payable_date=date(2024, 7, 6))
    _post(ledger, _opening(api, ledger, (_available(api, dividend),)))
    payload = _case().bundle.calendar.model_dump(mode="python")
    ranges = [item for item in payload["coverage_ranges"] if item["start"] != date(2024, 6, 28)]
    ranges.extend(({"start": date(2024, 6, 28), "end": date(2024, 7, 7)},
                   {"start": date(2024, 7, 9), "end": date(2024, 7, 10)}))
    payload.update(coverage_ranges=tuple(sorted(ranges, key=lambda item: item["start"])), replay_evidence=None,
                   schedule=[item for item in payload["schedule"] if item["session_date"] != PAY_DATE])
    gap = quant._bundle(calendar=TradingCalendar.model_validate(payload), cutoff=bt01.PRE_CLOSE_CUTOFF).calendar
    before = _snapshot(ledger)
    _reject(lambda: _payment(api, ledger, date(2024, 7, 9), calendar=gap))
    assert _snapshot(ledger) == before


@pytest.mark.parametrize("boundary", ("availability", "ingestion", "archive"))
@pytest.mark.parametrize("offset_us", (-1, 0, 1), ids=("before", "equal", "after"))
def test_bt04_supplement_opening_provenance_boundaries(boundary: str, offset_us: int) -> None:
    api = _api()
    ledger = _ledger()
    opening = _case().bundle.calendar.session(EX_DATE).open_at
    cutoff = opening - timedelta(microseconds=2) if boundary == "archive" else opening
    observed = cutoff + timedelta(microseconds=offset_us)
    action = _action(action_id=f"supplement-boundary-{boundary}",
                     available=observed if boundary == "availability" else None,
                     ingested=observed if boundary != "availability" else None)
    candidate = _available(api, action)
    replay = BundleReplayPolicy.AVAILABILITY if boundary == "availability" else BundleReplayPolicy.ARCHIVE_REALISTIC
    before = _snapshot(ledger)
    if offset_us > 0:
        _reject(lambda: _post(ledger, _opening(api, ledger, (candidate,),
                                                archive_cutoff=cutoff, replay_policy=replay)))
        assert _snapshot(ledger) == before
    else:
        _post(ledger, _opening(api, ledger, (candidate,), archive_cutoff=cutoff, replay_policy=replay))
        assert ledger.balance().positions == ((INST, D("20")),)
        assert ledger.balance().cash == D("1000")
        assert ledger.balance().recognized_income == ZERO


def test_bt04_supplement_buy_after_zero_entitlement_cannot_create_retroactive_claim() -> None:
    api = _api()
    seed = _seed()
    intent = bt02._intent(seed.api02, seed.case, quantity=D("10"), time_in_force="gtc",
                          order_type="limit", limit_price=D("95"), expires_at=seed.intent.expires_at,
                          plan_id="supplement-precommitted-ex-date-buy")
    assert intent.created_at < seed.case.binding.next_session.open_at
    first_attempt = bt02._simulate_direct(seed.api02, seed.case, intent, seed.outcome, seed.policy)
    assert first_attempt.fill is None  # Entry100 is above the precommitted95 limit.
    outcome = bt02._outcome(seed.api02, seed.case, session=EX_DATE, price=D("90"))
    fill = bt03._make_fill(seed.api02, seed.case, intent=intent, outcome=outcome, policy=seed.policy)
    control = _ledger(held=False)
    control.append(bt03._fill_event(seed.api03, control, intent=intent, fill=fill, case=seed.case,
                                    outcome=outcome, policy=seed.policy, event_id="supplement-buy-control"))
    assert control.balance().positions == ((INST, D("10")),)
    assert control.balance().cash == D("1100")

    ledger = _ledger(held=False)
    dividend = _available(api, _action("dividend", "supplement-zero-entitlement"))
    _post(ledger, _opening(api, ledger, (dividend,), references=()))
    assert ledger.balance().positions == ()
    assert ledger.balance().receivables == ledger.balance().recognized_income == ZERO
    ledger.append(bt03._fill_event(seed.api03, ledger, intent=intent, fill=fill, case=seed.case,
                                   outcome=outcome, policy=seed.policy, event_id="supplement-ex-date-buy"))
    before = _snapshot(ledger)
    assert _payment(api, ledger, PAY_DATE) == ()
    assert _opening(api, ledger, (dividend,), references=(), event_id="supplement-reapply-zero-entitlement") == ()
    assert _snapshot(ledger) == before
    assert ledger.balance().positions == ((INST, D("10")),)
    assert ledger.balance().cash == D("1100")
    assert ledger.balance().receivables == ledger.balance().recognized_income == ZERO


def test_bt04_supplement_independent_accounting_rejects_validly_sealed_wrong_cash() -> None:
    api = _api()
    from mytradingalpha.backtest.ledger import _seal_balance

    seed = _seed()
    ledger = _ledger()
    before = ledger.balance()
    event = _opening(api, ledger, (_available(api, _action()),))[0]
    accepted = ledger.append(event)
    assert seed.api03.AccountingInvariant.check(before, event, accepted) is None
    wrong = copy.deepcopy(accepted)
    object.__setattr__(wrong, "cash", accepted.cash + D("1"))
    _seal_balance(wrong)  # Trusted adversarial resealing; no production ingress bypass.
    canonical = wrong.canonical_bytes()  # Must succeed before testing the economic invariant.
    assert D(json.loads(canonical)["cash"]) == accepted.cash + D("1")
    assert wrong.positions == accepted.positions
    snapshot = _snapshot(ledger)
    error = _reject(lambda: seed.api03.AccountingInvariant.check(before, event, wrong))
    assert getattr(error, "reason_code", None) == "accounting_invalid"
    assert wrong.canonical_bytes() == canonical
    assert _snapshot(ledger) == snapshot


@pytest.mark.parametrize("claim_kind,claim_amount,income", (
    ("dividend", "10", "10"), ("cash_in_lieu", "100", "0"), ("delisting", "300", "0"),
))
def test_bt04_supplement_income_distinguishes_dividend_from_disposal_principal(
    claim_kind: str, claim_amount: str, income: str,
) -> None:
    api = _api()
    seed = _seed("3") if claim_kind == "cash_in_lieu" else _seed()
    ledger = _ledger(seed)
    policy = _policy(api, fractional_shares="cash_in_lieu") if claim_kind == "cash_in_lieu" else _policy(api)
    if claim_kind == "cash_in_lieu":
        action = _action(new_shares_per_old_share=D("0.5"))
        terms = _terms(api, action, fractional_shares="cash_in_lieu", lot_size=D("1"),
                       cash_in_lieu_price=D("200"), payable_date=PAY_DATE)
        candidate = _available(api, action, terms=terms)
    else:
        candidate = _available(api, _action(claim_kind, f"supplement-{claim_kind}-income"))
    before = ledger.balance()
    assert before.recognized_income == ZERO
    opening = _opening(api, ledger, (candidate,), policy=policy, references=(_reference(api, seed),))
    _post(ledger, opening)
    assert ledger.balance().cash == before.cash
    assert ledger.balance().receivables == D(claim_amount)
    assert ledger.balance().recognized_income == D(income)
    _post(ledger, _payment(api, ledger, PAY_DATE, policy=policy))
    assert ledger.balance().cash == before.cash + D(claim_amount)
    assert ledger.balance().receivables == ZERO
    assert ledger.balance().recognized_income == D(income)
    snapshot = _snapshot(ledger)
    assert ledger.append(opening[0]) == ledger.balance()
    assert _payment(api, ledger, PAY_DATE, policy=policy, event_id="supplement-repeat-payment") == ()
    assert ledger.balance().recognized_income == D(income)
    assert _snapshot(ledger) == snapshot


def test_bt04_supplement_generic_obligation_cannot_settle_reserved_action_claim() -> None:
    api = _api()
    seed = _seed()
    ledger = _ledger()
    dividend = _available(api, _action("dividend", "supplement-reserved-claim", payable_date=EX_DATE))
    _post(ledger, _opening(api, ledger, (dividend,)))
    claims = ledger.balance().outstanding_obligations
    assert len(claims) == 1
    claim = claims[0]
    assert claim.kind == "receivable"
    closed_time = datetime(2024, 7, 6, 14, tzinfo=UTC)
    assert claim.due_at < closed_time < ledger.balance().resolution_cutoff

    # Unrelated generic claims retain their existing due-time semantics.
    control = _ledger()
    created = min(_case().bundle.calendar.session(EX_DATE).open_at, claim.due_at)
    control.append(bt03._obligation_event(seed.api03, control, event_id="supplement-generic-create",
        kind="receivable_create", obligation_id="supplement-unrelated-claim", amount=claim.amount_remaining,
        economic_time=created, observed_at=created, due_at=claim.due_at))
    control.append(bt03._obligation_event(seed.api03, control, event_id="supplement-generic-settle",
        kind="receivable_settle", obligation_id="supplement-unrelated-claim", amount=claim.amount_remaining,
        economic_time=closed_time, observed_at=closed_time, due_at=claim.due_at))
    assert control.balance().cash == D("1010")
    assert control.balance().receivables == ZERO

    bypass = bt03._obligation_event(seed.api03, ledger, event_id="supplement-action-claim-bypass",
        kind="receivable_settle", obligation_id=claim.obligation_id, amount=claim.amount_remaining,
        economic_time=closed_time, observed_at=closed_time, due_at=claim.due_at)
    snapshot = _snapshot(ledger)
    _reject(lambda: ledger.append(bypass))
    assert _snapshot(ledger) == snapshot
    _post(ledger, _payment(api, ledger, EX_DATE))
    assert ledger.balance().cash == D("1010")
    assert ledger.balance().receivables == ZERO
    assert ledger.balance().recognized_income == D("10")
    snapshot = _snapshot(ledger)
    assert _payment(api, ledger, EX_DATE, event_id="supplement-reserved-payment-retry") == ()
    assert _snapshot(ledger) == snapshot


def _bt04_repair_removal_actions(api: SimpleNamespace, settlement: str, payable: date) -> tuple[Any, ...]:
    split = _action(action_id="repair-removal-split")
    dividend = _action("dividend", "repair-removal-dividend", payable_date=payable)
    delisting = _action("delisting", "repair-removal-delisting")
    terms = _terms(api, delisting, settlement=settlement,
                   amount_per_share=D("30") if settlement == "cash" else ZERO,
                   payable_date=payable if settlement == "cash" else None)
    # Caller order must not decide split-adjusted carried entitlement.
    return (_available(api, dividend), _available(api, delisting, terms=terms), _available(api, split))


def _bt04_repair_mapping(
    api: SimpleNamespace, source: str, target: str, mapping_id: str, ratio: str,
    *, effective: date = EX_DATE,
) -> Any:
    return api.MergerMapping(
        schema_version="v1", mapping_id=mapping_id, policy_version="bt04-merger-v1",
        source_instrument_id=source, target_instrument_id=target, currency="USD",
        effective_date=effective, new_shares_per_old_share=D(ratio),
        manifest=_manifest(mapping_id, effective),
    )


def _bt04_repair_three_holdings() -> tuple[Any, tuple[SimpleNamespace, ...]]:
    sources = _member_sources(3)
    ledger = bt03._new_ledger(sources[0].api03, sources[0].case, opening_cash=D("2000"))
    for index, seed in enumerate(sources):
        ledger.append(bt03._fill_event(seed.api03, ledger, intent=seed.intent, fill=seed.fill,
            case=seed.case, outcome=seed.outcome, policy=seed.policy, event_id=f"repair-entry-{index}"))
    assert ledger.balance().cash == D("1700")
    assert ledger.balance().positions == tuple(sorted((s.intent.instrument_id, D("1")) for s in sources))
    return ledger, sources


@pytest.mark.parametrize("settlement,principal", (("cash", "600"), ("writeoff", "0")))
@pytest.mark.parametrize("payable", (EX_DATE, PAY_DATE), ids=("same-open", "later-session"))
def test_bt04_repair_split_adjusted_dividend_survives_same_open_removal(
    settlement: str, principal: str, payable: date,
) -> None:
    api = _api()
    ledger = _ledger()
    actions = _bt04_repair_removal_actions(api, settlement, payable)
    opening_events = _opening(api, ledger, actions)
    opening_balance = _post(ledger, opening_events)
    assert opening_balance.positions == ()
    assert opening_balance.cash == D("1000")
    assert INST in ledger.action_state().closed_instruments
    assert {a.action_id for a in ledger.action_state().applied_actions} == {
        "repair-removal-split", "repair-removal-delisting", "repair-removal-dividend",
    }
    if payable != EX_DATE:
        assert _payment(api, ledger, EX_DATE, event_id="repair-before-pay-date") == ()
    _post(ledger, _payment(api, ledger, payable, event_id="repair-removal-payment"))
    replay = _ledger(held=False)
    replay.replay(ledger.events)
    assert _snapshot(replay) == _snapshot(ledger)
    snapshot = _snapshot(ledger)
    assert ledger.append(opening_events[0]) == ledger.balance()
    assert _opening(api, ledger, actions, event_id="repair-removal-retry") == ()
    assert _payment(api, ledger, payable, event_id="repair-removal-payment-retry") == ()
    assert _snapshot(ledger) == snapshot
    assert opening_balance.receivables == D(principal) + D("20"), "20 split-adjusted dividend is owed after removal"
    assert opening_balance.recognized_income == D("20")
    assert ledger.balance().receivables == ZERO
    assert ledger.balance().cash == D("1000") + D(principal) + D("20")
    assert ledger.balance().recognized_income == D("20")


@pytest.mark.parametrize("settlement,principal", (("cash", "600"), ("writeoff", "0")))
def test_bt04_repair_independent_checker_rejects_sealed_omitted_dividend(settlement: str, principal: str) -> None:
    api = _api()
    from mytradingalpha.backtest.corporate_actions import _ActionState
    from mytradingalpha.backtest.ledger import _seal_balance

    ledger = _ledger()
    before = ledger.balance()
    event = _opening(api, ledger, _bt04_repair_removal_actions(api, settlement, PAY_DATE))[0]
    accepted = ledger.append(event)
    assert _seed().api03.AccountingInvariant.check(before, event, accepted) is None
    state = ledger.action_state()
    dividend_claims = tuple(c for c in state.claims if c.action_id == "repair-removal-dividend")
    removed_ids = {c.obligation_id for c in dividend_claims}
    omitted = sum((c.amount for c in dividend_claims), ZERO)
    fields = {name: getattr(state, name) for name in _ActionState._fields}
    fields["claims"] = tuple(c for c in state.claims if c.obligation_id not in removed_ids)
    wrong = copy.deepcopy(accepted)
    object.__setattr__(wrong, "obligations", tuple(o for o in accepted.obligations if o.obligation_id not in removed_ids))
    object.__setattr__(wrong, "receivables", accepted.receivables - omitted)
    object.__setattr__(wrong, "recognized_income", accepted.recognized_income - omitted)
    object.__setattr__(wrong, "_action_state", _ActionState(**fields))
    _seal_balance(wrong)  # Adversarial resealing only; goldens use public Ledger publication.
    canonical = wrong.canonical_bytes()
    assert wrong.receivables == D(principal)
    assert wrong.recognized_income == before.recognized_income == ZERO
    assert wrong.positions == accepted.positions == ()
    assert wrong.cash == accepted.cash
    assert wrong.prefix_hashes == accepted.prefix_hashes
    assert {a.action_id for a in state.applied_actions} == {
        "repair-removal-split", "repair-removal-delisting", "repair-removal-dividend",
    }
    snapshot = _snapshot(ledger)
    error = _reject(lambda: _seed().api03.AccountingInvariant.check(before, event, wrong))
    assert getattr(error, "reason_code", None) == "accounting_invalid"
    assert wrong.canonical_bytes() == canonical
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_source_dividend_overlapping_new_merger_rejects_atomically() -> None:
    api = _api()
    ledger, sources = _bt04_repair_three_holdings()
    source, target = (s.intent.instrument_id for s in sources[:2])
    mapping = _bt04_repair_mapping(api, source, target, "repair-source-dividend-merger", "2")
    dividend = _available(api, _action("dividend", "repair-source-dividend", instrument_id=source))
    snapshot = _snapshot(ledger)
    _reject(lambda: _post(ledger, _opening(api, ledger, (dividend,), mergers=(mapping,), references=())))
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_target_dividend_uses_existing_plus_converted_holdings_once() -> None:
    api = _api()
    ledger, sources = _bt04_repair_three_holdings()
    source, target, untouched = (s.intent.instrument_id for s in sources)
    mapping = _bt04_repair_mapping(api, source, target, "repair-target-dividend-merger", "2")
    dividend = _available(api, _action("dividend", "repair-target-dividend", instrument_id=target))
    _post(ledger, _opening(api, ledger, (dividend,), mergers=(mapping,), references=()))
    assert ledger.balance().positions == tuple(sorted(((target, D("3")), (untouched, D("1")))))
    assert ledger.balance().receivables == ledger.balance().recognized_income == D("3")
    assert ledger.balance().cash == D("1700")
    _post(ledger, _payment(api, ledger, PAY_DATE))
    assert ledger.balance().cash == D("1703")
    assert ledger.balance().recognized_income == D("3")
    snapshot = _snapshot(ledger)
    assert _opening(api, ledger, (dividend,), mergers=(mapping,), references=(), event_id="repair-target-retry") == ()
    assert _snapshot(ledger) == snapshot


@pytest.mark.parametrize("unseen_kind", ("action", "mapping"))
@pytest.mark.parametrize("include_retry", (False, True), ids=("unseen-only", "retry-plus-unseen"))
def test_bt04_repair_committed_opening_rejects_unseen_evidence(unseen_kind: str, include_retry: bool) -> None:
    api = _api()
    ledger = _ledger()
    first = _available(api, _action(action_id="repair-committed-split"))
    _post(ledger, _opening(api, ledger, (first,)))
    assert ledger.balance().latest_economic_time == _case().bundle.calendar.session(EX_DATE).open_at
    actions = (first,) if include_retry else ()
    mappings: tuple[Any, ...] = ()
    if unseen_kind == "action":
        actions += (_available(api, _action("dividend", "repair-unseen-dividend")),)
    else:
        mappings = (_bt04_repair_mapping(api, INST, "inst-repair-target", "repair-unseen-merger", "0.5"),)
    snapshot = _snapshot(ledger)
    _reject(lambda: _post(ledger, _opening(api, ledger, actions, mergers=mappings,
        references=(), event_id="repair-unseen-opening")))
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_same_open_payment_and_retry_only_remain_valid() -> None:
    api = _api()
    ledger = _ledger()
    dividend = _available(api, _action("dividend", "repair-open-payment", payable_date=EX_DATE))
    events = _opening(api, ledger, (dividend,), references=())
    _post(ledger, events)
    _post(ledger, _payment(api, ledger, EX_DATE))
    assert ledger.balance().cash == D("1010")
    assert ledger.balance().receivables == ZERO
    assert ledger.balance().recognized_income == D("10")
    snapshot = _snapshot(ledger)
    assert ledger.append(events[0]) == ledger.balance()
    assert _opening(api, ledger, (dividend,), references=(), event_id="repair-open-only-retry") == ()
    assert _payment(api, ledger, EX_DATE, event_id="repair-open-pay-retry") == ()
    changed = _available(api, _action("dividend", "repair-open-payment", revision=1, payable_date=EX_DATE))
    _reject(lambda: _opening(api, ledger, (changed,), references=(), event_id="repair-open-conflict"))
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_empty_evaluation_does_not_close_genesis_opening() -> None:
    api = _api()
    ledger = _ledger(held=False)
    assert ledger.balance().latest_economic_time is None
    assert _opening(api, ledger, (), references=()) == ()
    assert ledger.balance().event_count == 0
    dividend = _available(api, _action("dividend", "repair-genesis-dividend"))
    _post(ledger, _opening(api, ledger, (dividend,), references=()))
    assert ledger.balance().event_count == 1
    assert ledger.balance().cash == D("2000")
    assert ledger.balance().receivables == ledger.balance().recognized_income == ZERO


@pytest.mark.parametrize("reverse", (False, True), ids=("a-to-b-first", "b-to-c-first"))
def test_bt04_repair_same_open_mapping_chain_rejects_both_orders(reverse: bool) -> None:
    api = _api()
    ledger, sources = _bt04_repair_three_holdings()
    a, b, c = (s.intent.instrument_id for s in sources)
    mappings = (_bt04_repair_mapping(api, a, b, "repair-chain-a-b", "2"),
                _bt04_repair_mapping(api, b, c, "repair-chain-b-c", "3"))
    if reverse:
        mappings = tuple(reversed(mappings))
    snapshot = _snapshot(ledger)
    _reject(lambda: _post(ledger, _opening(api, ledger, (), mergers=mappings, references=())))
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_convergent_mappings_are_additive_in_both_orders() -> None:
    api = _api()
    economics = []
    for reverse in (False, True):
        ledger, sources = _bt04_repair_three_holdings()
        a, b, target = (s.intent.instrument_id for s in sources)
        mappings = (_bt04_repair_mapping(api, a, target, "repair-converge-a", "2"),
                    _bt04_repair_mapping(api, b, target, "repair-converge-b", "3"))
        if reverse:
            mappings = tuple(reversed(mappings))
        _post(ledger, _opening(api, ledger, (), mergers=mappings, references=()))
        balance = ledger.balance()
        assert balance.positions == ((target, D("6")),)
        assert balance.cash == D("1700")
        assert balance.receivables == balance.recognized_income == ZERO
        state = ledger.action_state()
        assert state.closed_instruments == tuple(sorted((a, b)))
        economics.append((balance.cash, balance.positions, balance.receivables, balance.recognized_income,
                          balance.total_fees, state.closed_instruments, tuple(a.action_id for a in state.applied_actions)))
        snapshot = _snapshot(ledger)
        assert _opening(api, ledger, (), mergers=mappings, references=(), event_id="repair-converge-retry") == ()
        assert _snapshot(ledger) == snapshot
    assert economics[0] == economics[1]  # Caller-order hashes are not economic equality.


def test_bt04_repair_historical_mapping_retry_does_not_poison_later_mapping_graph() -> None:
    api = _api()
    ledger, sources = _bt04_repair_three_holdings()
    a, b, c = (s.intent.instrument_id for s in sources)
    first = _bt04_repair_mapping(api, a, b, "repair-historical-a-b", "2")
    _post(ledger, _opening(api, ledger, (), mergers=(first,), references=()))
    later = _bt04_repair_mapping(api, b, c, "repair-later-b-c", "3", effective=PAY_DATE)
    _post(ledger, _opening(api, ledger, (), mergers=(first, later), references=(),
                           session_date=PAY_DATE, event_id="repair-later-mapping"))
    assert ledger.balance().positions == ((c, D("10")),)
    assert ledger.balance().cash == D("1700")
    assert ledger.balance().receivables == ledger.balance().recognized_income == ZERO
    snapshot = _snapshot(ledger)
    assert _opening(api, ledger, (), mergers=(later, first), references=(), session_date=PAY_DATE,
                    event_id="repair-historical-retry") == ()
    assert _snapshot(ledger) == snapshot


@lru_cache(maxsize=2)
def _compact_member_sources(count: int, session_count: int = 5) -> tuple[SimpleNamespace, ...]:
    """Use the genuine common bundle, omitting only bars outside this lookback."""
    base = _case(session_count)
    bundle = base.bundle
    current_bars = tuple(bar for bar in bundle.bars if bar.session_date >= date(2024, 6, 28))
    instruments = tuple(_renamed(next(x for x in bundle.instruments if x.instrument_id == INST), i) for i in range(count))
    aliases = tuple(_renamed(next(x for x in bundle.aliases if x.instrument_id == INST), i) for i in range(count))
    memberships = tuple(_renamed(next(x for x in bundle.memberships if x.instrument_id == INST), i) for i in range(count))
    bars = tuple(_renamed(bar, i) for i in range(count) for bar in current_bars if bar.instrument_id == INST)
    extended = build_evidence_bundle(
        schema_version="v1", bundle_id=f"synthetic-bt04-compact-{count:02d}",
        created_at=bundle.created_at, knowledge_cutoff=bundle.knowledge_cutoff,
        replay_policy=bundle.replay_policy, requirements=bundle.requirements,
        missing_optional=bundle.missing_optional, calendar=bundle.calendar,
        instrument_candidates=(*bundle.instruments, *instruments),
        alias_candidates=(*bundle.aliases, *aliases), membership_candidates=(*bundle.memberships, *memberships),
        action_candidates=bundle.actions, bar_candidates=(*current_bars, *bars), filing_candidates=bundle.filings,
        event_candidates=bundle.events, social_post_candidates=bundle.social_posts,
        macro_observation_candidates=bundle.macro_observations,
    )
    context = bt01._context(extended, run_id=base.context.run_id, variant_id=base.context.variant_id,
                            decision_time=bt01.DECISION_TIME, earliest_execution_time="2024-07-03T13:30:00Z")
    api01, api02, api03, qapi = bt01._bt_api(), bt02._bt02_api(), bt03._bt03_api(), quant._api()
    results = []
    for index, instrument in enumerate(instruments):
        features = quant._features(qapi, bundle=extended, instrument_id=instrument.instrument_id)
        signal = quant._score(qapi, bundle=extended, run_id=context.run_id, feature_set=features)
        envelope = combine_quant_overlay(signal, context=context,
            registry=VariantRegistry().register(context.variant_id, kind="quant_only"))
        binding = api01.SessionClock.bind(context, extended, envelope)
        decision, opportunity = api01.BacktestRunner().run((binding,))
        case = SimpleNamespace(context=context, bundle=extended, envelope=envelope,
                               binding=binding, decision=decision, opportunity=opportunity)
        bar = _renamed(bt02._make_bar(base), index)
        outcome = bt02._outcome(api02, case, bar=bar)
        intent = bt02._intent(api02, case, bar=bar, quantity=D("1"))
        policy = _seed().policy
        fill = bt03._make_fill(api02, case, intent=intent, outcome=outcome, policy=policy)
        results.append(SimpleNamespace(case=case, api02=api02, api03=api03, intent=intent,
            outcome=outcome, fill=fill, policy=policy, cash=D("2000"), features=features))
    return tuple(results)


@pytest.mark.parametrize("first_ratio,second_ratio", (("1.5", "2"), ("2", "1.5")))
def test_bt04_repair_new_same_instrument_splits_have_no_lexical_economic_order(
    first_ratio: str, second_ratio: str,
) -> None:
    api = _api()
    seed = _seed("1")
    ledger = _ledger(seed)
    policy = _policy(api, fractional_shares="cash_in_lieu")
    actions = []
    for suffix, ratio in (("a", first_ratio), ("b", second_ratio)):
        action = _action(action_id=f"repair-multi-split-{suffix}", new_shares_per_old_share=D(ratio))
        terms = _terms(api, action, fractional_shares="cash_in_lieu", lot_size=D("1"),
                       cash_in_lieu_price=D("10"), payable_date=PAY_DATE)
        actions.append(_available(api, action, terms=terms))
    snapshot = _snapshot(ledger)
    _reject(lambda: _post(ledger, _opening(api, ledger, tuple(actions), policy=policy,
                                          references=(_reference(api, seed),))))
    assert _snapshot(ledger) == snapshot


def test_bt04_repair_later_split_filters_old_retry_and_uses_fresh_reference() -> None:
    api = _api()
    seed = _seed("1")
    ledger = _ledger(seed)
    policy = _policy(api, fractional_shares="cash_in_lieu")
    first = _action(action_id="repair-earlier-split", new_shares_per_old_share=D("1.5"))
    first_terms = _terms(api, first, fractional_shares="cash_in_lieu", lot_size=D("1"),
                         cash_in_lieu_price=D("10"), payable_date=PAY_DATE)
    first_wrapper = _available(api, first, terms=first_terms)
    _post(ledger, _opening(api, ledger, (first_wrapper,), policy=policy, references=(_reference(api, seed),)))
    assert ledger.balance().positions == ((INST, D("1")),)
    assert ledger.balance().receivables == D("5")
    second = _action(action_id="repair-later-split", effective=PAY_DATE, new_shares_per_old_share=D("2"))
    second_terms = _terms(api, second, fractional_shares="cash_in_lieu", lot_size=D("1"),
                          cash_in_lieu_price=D("10"), payable_date=PAY_DATE)
    second_wrapper = _available(api, second, terms=second_terms)
    fresh = bt02._outcome(seed.api02, seed.case, session=EX_DATE, price=D("80"))
    reference = api.PositionReference(instrument_id=INST, symbol="KEEP", cost_basis=D("90"),
                                      mark=bt03._mark(seed.api03, seed.case, fresh))
    _post(ledger, _opening(api, ledger, (first_wrapper, second_wrapper), policy=policy,
                           references=(reference,), session_date=PAY_DATE, event_id="repair-later-split-opening"))
    assert ledger.balance().positions == ((INST, D("2")),)
    converted = ledger.action_state().split_references[0]
    assert (converted.cost_basis_numerator, converted.cost_basis_denominator) == (45, 1)
    assert (converted.mark_numerator, converted.mark_denominator) == (40, 1)
    _post(ledger, _payment(api, ledger, PAY_DATE, policy=policy))
    assert ledger.balance().cash == D("1905")
    assert ledger.balance().receivables == ledger.balance().recognized_income == ZERO
    snapshot = _snapshot(ledger)
    assert _opening(api, ledger, (second_wrapper, first_wrapper), policy=policy, references=(reference,),
                    session_date=PAY_DATE, event_id="repair-later-split-retry") == ()
    assert _snapshot(ledger) == snapshot


def _bt04_repair_native_digest(value: Any) -> str:
    """Stream honest fixture storage, including metadata, without opaque getters."""
    from enum import Enum

    digest = hashlib.sha256()

    def visit(item: Any) -> None:
        cls = type(item)
        digest.update((cls.__module__ + "." + cls.__name__ + "\0").encode())
        if item is None or cls in (bool, int, str, bytes, Decimal, date, datetime):
            raw = item if cls is bytes else repr(item).encode()
            digest.update(str(len(raw)).encode() + b":" + raw)
        elif isinstance(item, Enum):
            visit(item.name)
            visit(item.value)
        elif cls in (tuple, list, set):
            values = sorted(item) if cls is set else item
            for child in values:
                visit(child)
        elif cls is dict:
            for key in sorted(item):
                visit(key)
                visit(item[key])
        elif hasattr(cls, "model_fields"):
            for name in ("__dict__", "__pydantic_fields_set__", "__pydantic_extra__", "__pydantic_private__"):
                visit(object.__getattribute__(item, name))
        elif hasattr(cls, "_fields"):
            for name in ("_data", "_canonical", "_storage"):
                visit(object.__getattribute__(item, name))
        elif hasattr(item, "__dict__"):
            visit(object.__getattribute__(item, "__dict__"))
        else:
            for name in cls.__slots__:
                visit(object.__getattribute__(item, name))
        digest.update(b";")

    visit(value)
    return digest.hexdigest()


@lru_cache(maxsize=1)
def _bt04_repair_oversized_request() -> SimpleNamespace:
    api = _api()
    sources = _member_sources(9, 16)  # Retain the original genuinely oversized graph.
    case = sources[0].case
    members = tuple(_member(api, seed=s, quantity="1", weight="0.05") for s in sources[:8])
    sessions = []
    for day in SESSIONS[:16]:
        marks = tuple(bt03._mark(s.api03, s.case, bt02._outcome(s.api02, s.case,
            bar=_renamed(bt02._make_bar(case, session=day), i))) for i, s in enumerate(sources[:8]))
        sessions.append(_session_input(api, day, case=case, marks=marks))
    return SimpleNamespace(case=case, sources=sources, members=members, sessions=tuple(sessions))


@pytest.mark.parametrize("session_count,admissible", ((12, True), (13, False), (16, False)))
def test_bt04_repair_resource_admission_precedes_ledger_and_economics(
    session_count: int, admissible: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    from mytradingalpha.backtest import benchmarks
    from mytradingalpha.backtest.clock import _BINDING_DOMAIN, _capture_root, _CaptureBudget

    request = _bt04_repair_oversized_request()
    common = _common(api, case=request.case, end=SESSIONS[session_count - 1])
    policy = _bh_policy(api, common=common, universe=_union_universe(request.sources), members=request.members)
    sessions = request.sessions[:session_count]
    occurrences = 8 + 9 * session_count
    budget = _CaptureBudget()
    binding = request.sources[0].case.binding
    for name in ("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot", "_session_snapshot", "_next_session_snapshot"):
        _capture_root(object.__getattribute__(binding, name), budget)
    unit = len(_BINDING_DOMAIN) + len(object.__getattribute__(binding, "_sealed_source_json"))
    if session_count == 13:
        assert occurrences * budget.run_nodes > 1_000_000  # Nodes alone reject, below the byte ceiling.
        assert occurrences * unit < 16 * 1024 * 1024
    elif session_count == 16:
        assert occurrences * unit > 16 * 1024 * 1024
    # Complete external producer proof includes all direct evidence and metadata:
    # N12 upper=13433132 bytes/992142 nodes; N13 lower=1039875 binding nodes.
    # The 76180-node session quantum straddles 1M; no exact-unit pass is claimed.
    before = _bt04_repair_native_digest((policy, sessions))
    attempts: list[str] = []

    class ExecutionStarted(Exception):
        pass

    def observe_ledger(*_args: Any, **_kwargs: Any) -> Any:
        attempts.append("Ledger")
        raise ExecutionStarted("bounded spy stopped before ledger/economic execution")

    monkeypatch.setattr(benchmarks, "Ledger", observe_ledger)
    rejection = None
    try:
        api.BenchmarkRunner().run_buy_and_hold(sessions, policy=policy)
    except ExecutionStarted:
        pass
    except (TypeError, ValueError) as error:
        rejection = error
    assert _bt04_repair_native_digest((policy, sessions)) == before
    if admissible:
        assert attempts == ["Ledger"], "nearest representable in-budget request must reach execution"
    else:
        assert attempts == [], "oversized source graph reached Ledger before aggregate admission"
        assert rejection is not None
        assert getattr(rejection, "reason_code", None) == "resource_limit"


def _bt04_repair_policy_kwargs(api: SimpleNamespace, *, universe: Any = None) -> dict[str, Any]:
    return {"common": _common(api), "universe": _case().bundle if universe is None else universe,
            "members": (_member(api),), "residual_cash": "retain", "rebalance": "none",
            "dividend_treatment": "cash_no_reinvestment"}


def test_bt04_repair_initial_buy_hold_construction_is_pure(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    kwargs = _bt04_repair_policy_kwargs(api)
    before = _bt04_repair_native_digest(kwargs)
    calendar_module = importlib.import_module("mytradingalpha.data.calendar")
    attempts: list[str] = []

    def deny(name: str) -> Callable[..., Any]:
        def blocked(*_args: Any, **_kwargs: Any) -> Any:
            attempts.append(name)
            raise AssertionError("unexpected external access during initial policy construction")
        return blocked

    error = None
    policy = None
    with monkeypatch.context() as armed:
        for owner, name in ((builtins, "open"), (Path, "open"), (socket, "socket"),
                            (socket, "create_connection"), (urllib.request, "urlopen"),
                            (subprocess, "Popen"), (subprocess, "run"), (os, "getenv"),
                            (os, "system"), (type(os.environ), "__getitem__"),
                            (zoneinfo, "ZoneInfo"), (calendar_module, "ZoneInfo"),
                            (calendar_module, "capture_calendar_replay_evidence")):
            armed.setattr(owner, name, deny(name))
        try:
            policy = api.BuyAndHoldPolicy(**kwargs)  # All fixture preparation precedes arming.
        except (TypeError, ValueError) as caught:
            error = caught
    assert _bt04_repair_native_digest(kwargs) == before
    assert attempts == [], "initial EvidenceBundle proof attempted ambient operations"
    assert error is None
    assert policy is not None
    assert policy.canonical_bytes()


@pytest.mark.parametrize("change", ("created_at", "witness_metadata", "missing_witness"))
def test_bt04_repair_universe_requires_full_native_binding_equality(change: str) -> None:
    api = _api()
    universe = copy.deepcopy(_case().bundle)
    advertised = universe.bundle_hash
    if change == "created_at":
        universe.__dict__["created_at"] += timedelta(microseconds=1)
    elif change == "witness_metadata":
        day = universe.calendar.replay_evidence.days[0]
        day.__pydantic_fields_set__.remove("start_utc")
    else:
        universe.calendar.__dict__["replay_evidence"] = None
    assert universe.bundle_hash == advertised
    kwargs = _bt04_repair_policy_kwargs(api, universe=universe)
    _reject(lambda: api.BuyAndHoldPolicy(**kwargs))


def test_bt04_repair_forged_outer_policy_seal_is_rejected() -> None:
    api = _api()
    policy = _bh_policy(api)
    object.__setattr__(policy, "_canonical", b"{}")
    _reject(policy.canonical_bytes)


def _bt04_repair_coordinated_semantic_forgery(kind: str) -> tuple[Any, dict[str, Any], Any]:
    """Recompute unkeyed data seals; they deliberately confer no issuer authority."""
    from mytradingalpha.backtest import clock, corporate_actions
    from mytradingalpha.backtest.ledger import _binding_capture
    from mytradingalpha.data.bundle import _semantic_hash

    api, seed = _api(), _seed()
    universe = copy.deepcopy(seed.case.bundle)
    if kind == "split":
        leaf = next(a for a in universe.actions if type(a) is SplitAction)
        leaf.__dict__["new_shares_per_old_share"] = D("-1")
    else:
        leaf = universe.events[0]  # News is unused by this quant-only member.
        leaf.__dict__["event_id"] = ""
    names = ("schema_version", "knowledge_cutoff", "replay_policy", "requirements", "missing_optional",
             "calendar", "instruments", "aliases", "memberships", "actions", "bars", "filings",
             "events", "social_posts", "macro_observations")
    source_hash = _semantic_hash(**{name: getattr(universe, name) for name in names})
    universe.__dict__["bundle_hash"] = source_hash
    context = type(seed.case.context).model_validate({**seed.case.context.model_dump(mode="python"), "bundle_hash": source_hash})
    quant_signal = bt01._rehashed_quant_signal(seed.case.envelope.quant, bundle_hash=source_hash)
    envelope = combine_quant_overlay(quant_signal, context=context,
        registry=VariantRegistry().register(context.variant_id, kind="quant_only"))
    binding = object.__new__(clock.SessionBinding)
    roots = (context, universe, envelope, seed.case.binding.session, seed.case.binding.next_session)
    for name, value in zip(("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot", "_session_snapshot", "_next_session_snapshot"), roots, strict=True):
        object.__setattr__(binding, name, value)
    raw = clock._source_json(context, universe, envelope)
    object.__setattr__(binding, "_sealed_source_json", raw)
    object.__setattr__(binding, "_source_fingerprint", "sha256:" + hashlib.sha256(clock._BINDING_DOMAIN + raw).hexdigest())
    budget = clock._CaptureBudget()
    object.__setattr__(binding, "_sealed_storage_bytes", clock._storage_bytes(*(clock._capture_root(root, budget) for root in roots)))
    # Establish that the negative passes inherited structural/native binding checks.
    clock._refresh_binding(binding, clock._CaptureBudget())
    decision, opportunity = bt01._bt_api().BacktestRunner().run((binding,))
    case = SimpleNamespace(context=context, bundle=universe, envelope=envelope, binding=binding,
                           decision=decision, opportunity=opportunity)
    intent = bt02._intent(seed.api02, case, quantity=D("10"), time_in_force="gtc", expires_at=seed.intent.expires_at)
    # Capture only genuine fields through BT04. Build the hostile native parts
    # from inherited structural capture so future semantic guards cannot reject
    # fixture preparation before the public boundary under test is reached.
    genuine_member = _member(api)
    member_fields = type(genuine_member)._fields
    member_parts = list(corporate_actions._parts(tuple(corporate_actions._get(genuine_member, n) for n in member_fields)))
    member_parts[member_fields.index("intent")] = corporate_actions._parts((intent,))[0]
    owned_binding, seals = _binding_capture(binding)
    member_parts[member_fields.index("binding")] = (
        owned_binding, seals[0].decode(), [seals[0].decode(), seals[1], seals[2].hex()],
    )
    member = object.__new__(api.BenchmarkMember)
    object.__setattr__(member, "_data", tuple(p[0] for p in member_parts))
    object.__setattr__(member, "_canonical", corporate_actions._canonical_json(dict(zip(member_fields, (p[1] for p in member_parts), strict=True))))
    object.__setattr__(member, "_storage", corporate_actions._DOMAIN + corporate_actions._canonical_json([p[2] for p in member_parts]))
    kwargs = {"common": _common(api), "universe": universe, "members": (member,), "residual_cash": "retain",
              "rebalance": "none", "dividend_treatment": "cash_no_reinvestment"}
    policy = object.__new__(api.BuyAndHoldPolicy)
    genuine_policy = _bh_policy(api)
    names_in_policy = type(policy)._fields
    parts = list(corporate_actions._parts(tuple(corporate_actions._get(genuine_policy, n) for n in names_in_policy)))
    captured_universe = clock._capture_root(universe, clock._CaptureBudget())
    parts[names_in_policy.index("universe")] = (
        universe, universe.model_dump(mode="json"), ["EvidenceBundle", clock._storage_bytes(captured_universe).hex()],
    )
    parts[names_in_policy.index("members")] = (
        (member,), [["BenchmarkMember", member._canonical.decode()]], [["BenchmarkMember", member._storage.hex()]],
    )
    object.__setattr__(policy, "_data", tuple(part[0] for part in parts))
    object.__setattr__(policy, "_canonical", corporate_actions._canonical_json(dict(zip(type(policy)._fields, (part[1] for part in parts), strict=True))))
    object.__setattr__(policy, "_storage", corporate_actions._DOMAIN + corporate_actions._canonical_json([part[2] for part in parts]))
    assert universe.bundle_hash == _semantic_hash(**{name: getattr(universe, name) for name in names})
    return policy, kwargs, leaf


@pytest.mark.parametrize("kind", ("split", "unused_event"))
def test_bt04_repair_semantic_proof_survives_coordinated_unkeyed_resealing(kind: str) -> None:
    api = _api()
    policy, kwargs, leaf = _bt04_repair_coordinated_semantic_forgery(kind)
    with pytest.raises(ValueError):
        type(leaf).model_validate(leaf.model_dump(mode="python"))
    before = _bt04_repair_native_digest((policy, kwargs))
    _reject(lambda: api.BuyAndHoldPolicy(**kwargs))
    _reject(policy.canonical_bytes)
    assert _bt04_repair_native_digest((policy, kwargs)) == before


@lru_cache(maxsize=2)
def _bt04_repair_padded_member_sources(text_length: int) -> tuple[SimpleNamespace, ...]:
    """Increase only existing attribution text; all financial source values survive."""
    original = _compact_member_sources(9, 16)
    base, copied = original[0].case, copy.deepcopy(original[0].case.bundle)
    domains = ("instruments", "aliases", "memberships", "actions", "bars", "filings", "events", "social_posts", "macro_observations")
    manifests = [record.manifest for domain in domains for record in getattr(copied, domain)]
    text = "synthetic budget fixture " + "x" * (text_length - len("synthetic budget fixture "))
    assert len(text.encode()) == text_length <= 2048
    for manifest in manifests[:20]:
        manifest.__dict__["terms"] = text
    bundle = build_evidence_bundle(
        schema_version="v1", bundle_id=copied.bundle_id, created_at=copied.created_at,
        knowledge_cutoff=copied.knowledge_cutoff, replay_policy=copied.replay_policy,
        requirements=copied.requirements, missing_optional=copied.missing_optional, calendar=copied.calendar,
        instrument_candidates=copied.instruments, alias_candidates=copied.aliases,
        membership_candidates=copied.memberships, action_candidates=copied.actions, bar_candidates=copied.bars,
        filing_candidates=copied.filings, event_candidates=copied.events, social_post_candidates=copied.social_posts,
        macro_observation_candidates=copied.macro_observations,
    )
    context = bt01._context(bundle, run_id=base.context.run_id, variant_id=base.context.variant_id,
                            decision_time=bt01.DECISION_TIME, earliest_execution_time="2024-07-03T13:30:00Z")
    api01, api02, api03, qapi = bt01._bt_api(), bt02._bt02_api(), bt03._bt03_api(), quant._api()
    result = []
    for index, prior in enumerate(original):
        identifier = prior.intent.instrument_id
        features = quant._features(qapi, bundle=bundle, instrument_id=identifier)
        signal = quant._score(qapi, bundle=bundle, run_id=context.run_id, feature_set=features)
        envelope = combine_quant_overlay(signal, context=context,
            registry=VariantRegistry().register(context.variant_id, kind="quant_only"))
        binding = api01.SessionClock.bind(context, bundle, envelope)
        decision, opportunity = api01.BacktestRunner().run((binding,))
        case = SimpleNamespace(context=context, bundle=bundle, envelope=envelope, binding=binding,
                               decision=decision, opportunity=opportunity)
        bar = _renamed(bt02._make_bar(base), index)
        outcome = bt02._outcome(api02, case, bar=bar)
        intent = bt02._intent(api02, case, bar=bar, quantity=D("1"))
        policy = _seed().policy
        fill = bt03._make_fill(api02, case, intent=intent, outcome=outcome, policy=policy)
        result.append(SimpleNamespace(case=case, api02=api02, api03=api03, intent=intent,
            outcome=outcome, fill=fill, policy=policy, cash=D("2000"), features=features))
    return tuple(result)


@pytest.mark.parametrize("text_length,admissible", ((1539, True), (1653, False)))
def test_bt04_repair_byte_admission_is_independent_of_native_node_limit(
    text_length: int, admissible: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    from mytradingalpha.backtest import benchmarks
    from mytradingalpha.backtest.clock import _BINDING_DOMAIN, _capture_root, _CaptureBudget

    sources = _bt04_repair_padded_member_sources(text_length)
    case = sources[0].case
    members = tuple(_member(api, seed=s, quantity="1", weight="0.05") for s in sources[:8])
    common = _common(api, case=case, end=SESSIONS[15])
    policy = _bh_policy(api, common=common, universe=_union_universe(sources), members=members)
    sessions = []
    for day in SESSIONS[:16]:
        marks = tuple(bt03._mark(s.api03, s.case, bt02._outcome(s.api02, s.case,
            bar=_renamed(bt02._make_bar(case, session=day), i))) for i, s in enumerate(sources[:8]))
        sessions.append(_session_input(api, day, case=case, marks=marks))
    sessions = tuple(sessions)
    budget = _CaptureBudget()
    binding = sources[0].case.binding
    for name in ("_context_snapshot", "_bundle_snapshot", "_envelope_snapshot", "_session_snapshot", "_next_session_snapshot"):
        _capture_root(object.__getattribute__(binding, name), budget)
    unit = len(_BINDING_DOMAIN) + len(object.__getattribute__(binding, "_sealed_source_json"))
    assert budget.run_nodes == 5759  # Changing existing terms adds bytes, never nodes.
    # The complete independent receipt includes all 152 bindings, direct universe,
    # calendars, intents, 128 outcomes and scalars: 905182 native nodes in both cases.
    # Its 1539-byte text request upper is 16775893 bytes; 1653-byte text bindings
    # alone contain 16779888 bytes. Only the byte cap rejects the latter.
    if admissible:
        assert 152 * unit == 16_433_328 < 16 * 1024 * 1024
    else:
        assert 152 * unit == 16_779_888 > 16 * 1024 * 1024
    before = _bt04_repair_native_digest((policy, sessions))
    attempts: list[str] = []

    class ExecutionStarted(Exception):
        pass

    def observe_ledger(*_args: Any, **_kwargs: Any) -> Any:
        attempts.append("Ledger")
        raise ExecutionStarted("bounded spy stopped before ledger/economic execution")

    monkeypatch.setattr(benchmarks, "Ledger", observe_ledger)
    rejection = None
    try:
        api.BenchmarkRunner().run_buy_and_hold(sessions, policy=policy)
    except ExecutionStarted:
        pass
    except (TypeError, ValueError) as error:
        rejection = error
    assert _bt04_repair_native_digest((policy, sessions)) == before
    if admissible:
        assert attempts == ["Ledger"], "in-budget source-text control must reach execution"
    else:
        assert attempts == [], "byte-only oversized request reached Ledger before admission"
        assert rejection is not None
        assert getattr(rejection, "reason_code", None) == "resource_limit"


@pytest.mark.parametrize("kind", ("split", "unused_event"))
def test_bt04_repair_nonentry_session_rejects_resealed_invalid_nested_bundle(kind: str) -> None:
    api = _api()
    from mytradingalpha.backtest.corporate_actions import _get

    genuine_policy = _bh_policy(api)
    genuine_endpoints = (_session_input(api, ENTRY), _session_input(api, PAY_DATE))
    forged_policy, forged_kwargs, leaf = _bt04_repair_coordinated_semantic_forgery(kind)
    binding = _get(forged_kwargs["members"][0], "binding")
    bad_case = SimpleNamespace(context=binding.context, bundle=binding.bundle,
                               envelope=binding.envelope, binding=binding)
    with pytest.raises(ValueError):
        type(leaf).model_validate(leaf.model_dump(mode="python"))
    # The mark/outcome and accounting wrappers are genuinely issued by unchanged
    # BT03. Only their nested unused PIT record is semantically invalid.
    seed = _seed()
    outcome = bt02._outcome(seed.api02, bad_case, session=EX_DATE, price=D("100"))
    middle = {"session": bad_case.bundle.calendar.session(EX_DATE),
              "marks": (bt03._mark(seed.api03, bad_case, outcome),),
              "accounting_policy": bt03._accounting_policy(seed.api03, bad_case, outcome),
              "actions": (), "references": (), "mergers": ()}
    assert genuine_policy.canonical_bytes()
    assert _get(genuine_policy, "universe").bundle_hash == _case().bundle.bundle_hash
    assert bad_case.bundle.bundle_hash != _case().bundle.bundle_hash
    inputs = (genuine_policy, genuine_endpoints, forged_policy, forged_kwargs, middle)
    before = _bt04_repair_native_digest(inputs)
    try:
        _reject(lambda: api.BenchmarkSessionInput(**middle))
    finally:
        assert _bt04_repair_native_digest(inputs) == before


@pytest.mark.parametrize("kind", ("foreign", "str_subclass"))
def test_bt04_ingress_position_reference_rejects_hostile_instrument_id_before_protocols(kind: str) -> None:
    api, seed = _api(), _seed()
    mark = bt03._mark(seed.api03, seed.case, seed.outcome)
    before = _bt04_repair_native_digest(mark)
    calls: list[str] = []
    hostile = _Hostile(calls)

    class HostileIdentifier(str):
        __str__ = __repr__ = __iter__ = __eq__ = __ne__ = __hash__ = hostile._called

    instrument_id = hostile if kind == "foreign" else HostileIdentifier(INST)
    assert calls == []  # Fixture construction must not evaluate the hostile input.
    try:
        with pytest.raises((TypeError, ValueError)) as caught:
            api.PositionReference(instrument_id=instrument_id, symbol="KEEP", cost_basis=seed.fill.price, mark=mark)
    finally:
        assert _bt04_repair_native_digest(mark) == before
        assert calls == [], "PositionReference ingress evaluated a hostile identifier protocol"
    assert len(str(caught.value).encode("utf-8")) <= 256


# H1-H3 repair contracts: original 133-case prefix above remains immutable.
def _h123_set_data(value: Any, name: str, replacement: Any, changes: list[Any]) -> None:
    data = object.__getattribute__(value, "_data")
    changes.append((value, "_data", data))
    index = type(value)._fields.index(name)
    object.__setattr__(value, "_data", data[:index] + (replacement,) + data[index + 1:])


def _h123_set_slot(value: Any, name: str, replacement: Any, changes: list[Any]) -> None:
    changes.append((value, name, object.__getattribute__(value, name)))
    object.__setattr__(value, name, replacement)


def _h123_restore(changes: list[Any]) -> None:
    for value, name, previous in reversed(changes):
        object.__setattr__(value, name, previous)


def _h123_hash_spy(armed: pytest.MonkeyPatch, *payloads: bytes) -> list[int]:
    original = hashlib.sha256
    calls: list[int] = []

    def observed(data: Any = b"", *args: Any, **kwargs: Any) -> Any:
        if any(data is payload for payload in payloads):
            calls.append(len(data))
        return original(data, *args, **kwargs)

    armed.setattr(hashlib, "sha256", observed)
    return calls


@pytest.mark.parametrize("kind", ("members", "marks", "scalar", "nested"))
def test_bt04_h123_fixed_field_guards_precede_repeated_representation_hashing(
    kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    common = _common(api, end=ENTRY)
    policy = (_bh_policy(api, common=common) if kind in ("members", "scalar") else
              api.CashBenchmarkPolicy(common=common, interest_policy="zero", annual_rate=ZERO))
    item = _session_input(api, ENTRY)
    inputs = (policy, (item,))
    honest = _bt04_repair_native_digest(inputs)
    probe = b"h123-unique-shared-representation\0".ljust(64 * 1024, b"x")
    changes: list[Any] = []
    if kind == "members":
        member = _get_native(policy, "members")[0]
        _h123_set_slot(member, "_canonical", probe, changes)
        _h123_set_slot(member, "_storage", probe, changes)
        _h123_set_data(policy, "members", (member,) * 9, changes)
    elif kind == "marks":
        mark = _get_native(item, "marks")[0]
        _h123_set_slot(mark, "_seal", probe, changes)
        _h123_set_data(item, "marks", (mark,) * 9, changes)
    else:
        child = _policy(api)
        _h123_set_slot(child, "_canonical", probe, changes)
        _h123_set_slot(child, "_storage", probe, changes)
        if kind == "scalar":
            _h123_set_data(_get_native(policy, "members")[0], "weight", (child, child), changes)
        else:
            _h123_set_data(policy, "common", child, changes)
    damaged = _bt04_repair_native_digest(inputs)
    run = api.BenchmarkRunner().run_buy_and_hold if kind in ("members", "scalar") else api.BenchmarkRunner().run_cash
    try:
        with monkeypatch.context() as armed:
            calls = _h123_hash_spy(armed, probe)
            _reject(lambda: run(inputs[1], policy=policy))
        assert calls == [], "fixed field/cardinality rejection must precede full stored-payload hashing"
    finally:
        assert _bt04_repair_native_digest(inputs) == damaged
        _h123_restore(changes)
        assert _bt04_repair_native_digest(inputs) == honest


def _get_native(value: Any, name: str) -> Any:
    return object.__getattribute__(value, "_data")[type(value)._fields.index(name)]


@pytest.mark.parametrize("slot", ("_canonical", "_storage"))
def test_bt04_h123_legal_shaped_forged_term_performs_zero_payload_hashing(
    slot: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    wrapper = _available(api, _action())
    item = _session_input(api, ENTRY, actions=(wrapper,))
    policy = api.CashBenchmarkPolicy(common=_common(api, end=ENTRY), interest_policy="zero", annual_rate=ZERO)
    inputs = (policy, (item,))
    # All fields/types/counts are genuine; only one redundant term seal is forged.
    terms = _get_native(_get_native(item, "actions")[0], "terms")
    assert type(terms) is api.SplitTerms
    honest = _bt04_repair_native_digest(inputs)
    probe = b"h123-legal-shaped-term\0".ljust(128 * 1024, b"t")
    changes: list[Any] = []
    _h123_set_slot(terms, slot, probe, changes)
    damaged = _bt04_repair_native_digest(inputs)
    try:
        with monkeypatch.context() as armed:
            calls = _h123_hash_spy(armed, probe)
            _reject(lambda: api.BenchmarkRunner().run_cash(inputs[1], policy=policy))
        assert calls == [], "shape guards alone must not authorize hashing forged derived representations"
    finally:
        assert _bt04_repair_native_digest(inputs) == damaged
        _h123_restore(changes)
        assert _bt04_repair_native_digest(inputs) == honest


def test_bt04_h123_combined_representation_cap_precedes_payload_work(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    item = _session_input(api, ENTRY, actions=(_available(api, _action()),))
    policy = api.CashBenchmarkPolicy(common=_common(api, end=ENTRY), interest_policy="zero", annual_rate=ZERO)
    inputs = (policy, (item,))
    terms = _get_native(_get_native(item, "actions")[0], "terms")
    honest = _bt04_repair_native_digest(inputs)
    quantum = b"h123-combined-representation\0".ljust(128 * 1024, b"c")
    # One shared allocation: each side is legal in isolation, their sum is not.
    representation = quantum * 65
    assert len(representation) < 16 * 1024 * 1024 < 2 * len(representation)
    changes: list[Any] = []
    for slot in ("_canonical", "_storage"):
        _h123_set_slot(terms, slot, representation, changes)
    damaged = _bt04_repair_native_digest(inputs)
    try:
        with monkeypatch.context() as armed:
            calls = _h123_hash_spy(armed, representation)
            _reject(lambda: api.BenchmarkRunner().run_cash(inputs[1], policy=policy))
        assert calls == [], "the combined canonical/native cap must reject before either representation is hashed"
    finally:
        assert _bt04_repair_native_digest(inputs) == damaged
        _h123_restore(changes)
        assert _bt04_repair_native_digest(inputs) == honest


def _h123_resealed_nine_mark_input(api: SimpleNamespace) -> Any:
    from mytradingalpha.backtest import corporate_actions

    item = _session_input(api, ENTRY)
    fields = type(item)._fields
    data = object.__getattribute__(item, "_data")
    # Encode only genuine child parts. Never ask an invalid wrapper to validate
    # itself while preparing the adversarial, correctly resealed nine-mark copy.
    parts = list(corporate_actions._parts(data))
    mark_part = corporate_actions._parts((_get_native(item, "marks")[0],))[0]
    parts[fields.index("marks")] = ((mark_part[0],) * 9, [mark_part[1]] * 9, [mark_part[2]] * 9)
    forged = object.__new__(type(item))
    object.__setattr__(forged, "_data", tuple(part[0] for part in parts))
    object.__setattr__(forged, "_canonical", corporate_actions._canonical_json(
        dict(zip(fields, (part[1] for part in parts), strict=True))))
    object.__setattr__(forged, "_storage", corporate_actions._DOMAIN + corporate_actions._canonical_json([part[2] for part in parts]))
    assert len(_get_native(forged, "marks")) == 9
    return forged


@pytest.mark.parametrize("boundary", ("refresh", "cash"))
def test_bt04_h123_resealed_nine_marks_reject_on_refresh_and_public_cash(boundary: str) -> None:
    api = _api()
    item = _h123_resealed_nine_mark_input(api)
    policy = api.CashBenchmarkPolicy(common=_common(api, end=ENTRY), interest_policy="zero", annual_rate=ZERO)
    before = _bt04_repair_native_digest((policy, item))
    try:
        _reject(item.canonical_bytes if boundary == "refresh" else
                lambda: api.BenchmarkRunner().run_cash((item,), policy=policy))
    finally:
        assert _bt04_repair_native_digest((policy, item)) == before


@pytest.mark.parametrize("slot", ("_canonical", "_storage"))
@pytest.mark.parametrize("available", (True, False), ids=("available", "unavailable"))
def test_bt04_h123_completion_rejects_derived_bytes_only_changes(
    slot: str, available: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mytradingalpha.backtest import benchmarks

    api = _api()
    policy = api.CashBenchmarkPolicy(common=_common(api, end=ENTRY), interest_policy="zero", annual_rate=ZERO)
    sessions = (_session_input(api, ENTRY),) if available else ()
    control = api.BenchmarkRunner().run_cash(sessions, policy=policy)
    assert bt03._result_status(control) == ("available" if available else "unavailable")
    honest = _bt04_repair_native_digest((policy, sessions))
    data = object.__getattribute__(policy, "_data")
    data_digest = _bt04_repair_native_digest(data)
    original_ledger = benchmarks.Ledger
    original_bytes = object.__getattribute__(policy, slot)
    calls: list[str] = []

    def mutate_during_execution(*args: Any, **kwargs: Any) -> Any:
        ledger = original_ledger(*args, **kwargs)  # Real construction/validation remains intact.
        calls.append(slot)
        object.__setattr__(policy, slot, original_bytes + b" ")
        return ledger

    try:
        with monkeypatch.context() as armed:
            armed.setattr(benchmarks, "Ledger", mutate_during_execution)
            error = _reject(lambda: api.BenchmarkRunner().run_cash(sessions, policy=policy))
        assert calls == [slot]
        assert getattr(error, "reason_code", None) == "source_changed"
        assert object.__getattribute__(policy, "_data") is data
        assert _bt04_repair_native_digest(data) == data_digest
        assert object.__getattribute__(policy, slot) == original_bytes + b" "
    finally:
        object.__setattr__(policy, slot, original_bytes)
        assert _bt04_repair_native_digest((policy, sessions)) == honest


@pytest.mark.parametrize("order", ("corporate_only", "benchmark_first"))
def test_bt04_h123_fresh_action_policy_construction_is_pure_without_hidden_import(
    order: str, tmp_path: Path,
) -> None:
    import sys

    script = r'''
import _io
import builtins
import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
import urllib.request
import zoneinfo
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

name = "mytradingalpha.backtest.benchmarks"
if sys.argv[1] == "benchmark_first":
    importlib.import_module(name)
corporate = importlib.import_module("mytradingalpha.backtest.corporate_actions")
calendar = importlib.import_module("mytradingalpha.data.calendar")
before = name in sys.modules
attempts = []
def deny(label):
    def blocked(*args, **kwargs):
        attempts.append(label)
        raise AssertionError("armed external operation: " + label)
    return blocked
error = None
canonical = None
with ExitStack() as stack:
    for owner, attribute in (
        (_io, "open_code"), (builtins, "open"), (Path, "open"),
        (os, "open"), (os, "stat"), (os, "lstat"), (os, "getenv"), (os, "system"),
        (type(os.environ), "__getitem__"), (socket, "socket"),
        (socket, "create_connection"), (urllib.request, "urlopen"),
        (subprocess, "Popen"), (subprocess, "run"), (zoneinfo, "ZoneInfo"),
        (calendar, "ZoneInfo"), (calendar, "capture_calendar_replay_evidence"),
    ):
        stack.enter_context(patch.object(owner, attribute, deny(attribute)))
    try:
        policy = corporate.ActionPolicy(schema_version="v1", policy_version="bt04-synthetic-v1",
            currency="USD", price_basis=corporate.AdjustmentBasis.UNADJUSTED,
            fractional_shares="retain_exact", payment_rule="next_witnessed_session",
            dividend_treatment="cash_no_reinvestment")
        canonical = policy.canonical_bytes()
    except Exception as caught:
        error = type(caught).__name__ + ":" + str(caught)
after = name in sys.modules
print(json.dumps({"before": before, "after": after, "attempts": attempts, "error": error,
    "origin": corporate.__file__, "canonical": None if canonical is None else hashlib.sha256(canonical).hexdigest()}))
'''
    result = subprocess.run((sys.executable, "-B", "-c", script, order), cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert Path(observed["origin"]).resolve() == ROOT / "mytradingalpha/backtest/corporate_actions.py"
    assert observed["before"] is (order == "benchmark_first")
    assert observed["attempts"] == [], observed
    assert observed["error"] is None, observed
    assert observed["after"] is (order == "benchmark_first"), observed
    assert observed["canonical"] == hashlib.sha256(EXPECTED_POLICY_BYTES).hexdigest()


@pytest.mark.parametrize("kind,size,digest", (
    ("cash", 10606, "6692cc19ac636b8d5c1199943458ffe952a1fcd4e8910116327f39a98c1bd8cd"),
    ("buy_hold", 132323, "f655fff5860d95deb4154b717847c132bea0fdd1a7a7d772292aaef9b80b8a86"),
))
def test_bt04_h123_whole_small_series_canonical_baseline(kind: str, size: int, digest: str) -> None:
    api = _api()
    common = _common(api, end=ENTRY)
    policy = (_bh_policy(api, common=common) if kind == "buy_hold" else
              api.CashBenchmarkPolicy(common=common, interest_policy="zero", annual_rate=ZERO))
    sessions = (_session_input(api, ENTRY),)
    before = _bt04_repair_native_digest((policy, sessions))
    run = api.BenchmarkRunner().run_buy_and_hold if kind == "buy_hold" else api.BenchmarkRunner().run_cash
    result = run(sessions, policy=policy)
    assert bt03._result_status(result) == "available"
    canonical = result.canonical_bytes()
    assert len(canonical) == size
    assert hashlib.sha256(canonical).hexdigest() == digest
    assert _bt04_repair_native_digest((policy, sessions)) == before


# R2 event boundary: independent event evidence must receive full BT04 proof.
def _r2_event_evidence_fields(kind: str | None = None) -> tuple[dict[str, Any], Any]:
    from mytradingalpha.backtest import ledger as ledger_module

    api, seed = _api(), _seed()
    common = _common(api, end=ENTRY)
    ordinary_policy = _bh_policy(api, common=common)
    assert ordinary_policy.canonical_bytes()  # The policy's separate bundle is genuine.
    if kind is None:
        case, intent = seed.case, seed.intent
    else:
        _forged_policy, kwargs, _leaf = _bt04_repair_coordinated_semantic_forgery(kind)
        member = kwargs["members"][0]
        binding = _get_native(member, "binding")
        intent = _get_native(member, "intent")
        case = SimpleNamespace(binding=binding,
            context=object.__getattribute__(binding, "_context_snapshot"),
            bundle=object.__getattribute__(binding, "_bundle_snapshot"),
            envelope=object.__getattribute__(binding, "_envelope_snapshot"))
    outcome = bt02._outcome(seed.api02, case, price=D("100"), session=ENTRY)
    fill = bt03._make_fill(seed.api02, case, intent=intent, outcome=outcome,
                          policy=seed.policy, cash=D("2000"), cap=D("1E9"))
    ledger = bt03._new_ledger(seed.api03, case, opening_cash=D("2000"),
        resolution_cutoff=_get_native(common, "resolution_cutoff"))
    event = bt03._fill_event(seed.api03, ledger, intent=intent, fill=fill, case=case,
        outcome=outcome, policy=seed.policy, event_id="r2-independent-event-evidence")
    # Real simulation, inherited native capture, and Ledger validation establish
    # complete linkage before any new BT04 rejection assertion is reached.
    captured, canonical, witness, retained = ledger_module._capture_event(event)
    assert captured.canonical_bytes() == canonical == event.canonical_bytes()
    assert witness and retained > 0
    balance = ledger.append(event)
    assert balance.cash == D("1000") and balance.positions == ((INST, D("10")),)
    assert balance.total_fees == ZERO
    nav = bt03._nav(seed.api03, balance, case, outcome)
    assert bt03._result_status(nav) == "available" and nav.value == D("2000")
    if kind is not None:
        native_binding = object.__getattribute__(event, "_binding")
        bundle = object.__getattribute__(native_binding, "_bundle_snapshot")
        leaf = next(action for action in bundle.actions if type(action) is SplitAction) if kind == "split" else bundle.events[0]
        with pytest.raises(ValueError):
            type(leaf).model_validate(leaf.model_dump(mode="python"))
        assert bundle.bundle_hash != _get_native(ordinary_policy, "universe").bundle_hash
    return {"status": "available", "run_valid": True, "reason_code": None,
        "events": (event,), "balances": (balance,), "nav_points": (nav,), "policy": ordinary_policy}, event


def _r2_event_resealed_series(fields: dict[str, Any]) -> Any:
    from mytradingalpha.backtest import benchmarks, corporate_actions
    from mytradingalpha.backtest.ledger import _capture_event, _jsonable

    genuine_fields, _genuine_event = _r2_event_evidence_fields()
    # All children used by _value_parts are genuine. The final balance/NAV were
    # produced by the real Ledger for the independent event, not fabricated.
    safe_fields = {**fields, "events": genuine_fields["events"]}
    parts = list(corporate_actions._value_parts(benchmarks.BenchmarkSeries,
        tuple(safe_fields[name] for name in benchmarks.BenchmarkSeries._fields)))
    event, canonical, witness, _retained = _capture_event(fields["events"][0])
    parts[benchmarks.BenchmarkSeries._fields.index("events")] = (
        (event,), [canonical.decode("utf-8")], [[canonical.decode("utf-8"), _jsonable(witness)]])
    series = object.__new__(benchmarks.BenchmarkSeries)
    object.__setattr__(series, "_data", tuple(part[0] for part in parts))
    object.__setattr__(series, "_canonical", corporate_actions._canonical_json(dict(zip(
        benchmarks.BenchmarkSeries._fields, (part[1] for part in parts), strict=True))))
    object.__setattr__(series, "_storage", corporate_actions._DOMAIN + corporate_actions._canonical_json([part[2] for part in parts]))
    return series


@pytest.mark.parametrize("kind", ("split", "unused_event"), ids=("unused-action", "unused-news"))
@pytest.mark.parametrize("boundary", ("construction", "refresh"))
def test_bt04_r2_event_unused_evidence_requires_independent_full_proof(kind: str, boundary: str) -> None:
    from mytradingalpha.backtest import benchmarks

    fields, event = _r2_event_evidence_fields(kind)
    before = _bt04_repair_native_digest(fields)
    try:
        if boundary == "construction":
            _reject(lambda: benchmarks.BenchmarkSeries(**fields))
        else:
            series = _r2_event_resealed_series(fields)
            series_before = _bt04_repair_native_digest(series)
            try:
                _reject(series.canonical_bytes)
            finally:
                assert _bt04_repair_native_digest(series) == series_before
    finally:
        assert _bt04_repair_native_digest(fields) == before
        assert event is fields["events"][0]


def test_bt04_r2_event_genuine_fill_series_construction_and_refresh_control() -> None:
    from mytradingalpha.backtest import benchmarks

    fields, event = _r2_event_evidence_fields()
    before = _bt04_repair_native_digest(fields)
    series = benchmarks.BenchmarkSeries(**fields)
    assert series.canonical_bytes() == object.__getattribute__(series, "_canonical")
    assert _get_native(series, "status") == "available"
    assert _get_native(series, "balances")[-1].cash == D("1000")
    assert _get_native(series, "nav_points")[0].value == D("2000")
    assert _get_native(series, "events")[0].canonical_bytes() == event.canonical_bytes()
    assert _bt04_repair_native_digest(fields) == before


@pytest.mark.parametrize("slot", ("_canonical", "_storage_bytes"))
def test_bt04_r2_event_original_stored_bytes_change_during_real_proof_rejects_refresh(
    slot: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mytradingalpha.backtest import benchmarks, corporate_actions

    fields, _event = _r2_event_evidence_fields()
    series = benchmarks.BenchmarkSeries(**fields)
    assert series.canonical_bytes()  # Genuine positive control precedes arming.
    event = _get_native(series, "events")[0]
    before = _bt04_repair_native_digest(series)
    original_bytes = object.__getattribute__(event, slot)
    data_slots = tuple(name for name in type(event).__slots__ if name not in ("_canonical", "_storage_bytes"))
    data_before = _bt04_repair_native_digest(tuple(object.__getattribute__(event, name) for name in data_slots))
    original_proof = corporate_actions._pure_bundle
    calls: list[bool] = []

    def prove_then_change(captured: Any) -> Any:
        result = original_proof(captured)  # Always execute the real semantic proof.
        if not calls:
            object.__setattr__(event, slot, original_bytes + b" ")
        calls.append(True)
        return result

    try:
        with monkeypatch.context() as armed:
            armed.setattr(corporate_actions, "_pure_bundle", prove_then_change)
            error = _reject(series.canonical_bytes)
        assert getattr(error, "reason_code", None) == "source_changed"
    finally:
        assert calls, "the real pure bundle validation must run during refresh"
        assert object.__getattribute__(event, slot) == original_bytes + b" "
        assert _bt04_repair_native_digest(tuple(object.__getattribute__(event, name) for name in data_slots)) == data_before
        object.__setattr__(event, slot, original_bytes)
        assert _bt04_repair_native_digest(series) == before


@pytest.mark.parametrize("slot", ("_canonical", "_storage"))
@pytest.mark.parametrize("available", (True, False), ids=("available", "unavailable"))
def test_bt04_f1_late_result_proof_must_precede_final_original_policy_check(
    slot: str, available: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mytradingalpha.backtest import benchmarks, corporate_actions

    api = _api()
    policy = _bh_policy(api, common=_common(api, end=ENTRY))
    sessions = (_session_input(api, ENTRY),) if available else ()
    control = api.BenchmarkRunner().run_buy_and_hold(sessions, policy=policy)
    expected_status = "available" if available else "unavailable"
    assert bt03._result_status(control) == expected_status
    before = _bt04_repair_native_digest((policy, sessions))
    data = object.__getattribute__(policy, "_data")
    data_before = _bt04_repair_native_digest(data)
    original_bytes = object.__getattribute__(policy, slot)
    original_result = benchmarks._result
    original_proof = corporate_actions._pure_bundle
    inside_result = False
    result_calls: list[bool] = []
    returned: list[Any] = []
    phase_proofs: list[bool] = []
    changed: list[bool] = []

    def observe_real_result(*args: Any, **kwargs: Any) -> Any:
        nonlocal inside_result
        result_calls.append(True)
        inside_result = True
        try:
            result = original_result(*args, **kwargs)
            returned.append(result)
            return result
        finally:
            inside_result = False

    def prove_then_change_original(captured: Any) -> Any:
        result = original_proof(captured)
        if inside_result:
            phase_proofs.append(True)
            if not changed:
                object.__setattr__(policy, slot, original_bytes + b" ")
                changed.append(True)
        return result

    try:
        with monkeypatch.context() as armed:
            armed.setattr(benchmarks, "_result", observe_real_result)
            armed.setattr(corporate_actions, "_pure_bundle", prove_then_change_original)
            error = _reject(lambda: api.BenchmarkRunner().run_buy_and_hold(sessions, policy=policy))
        assert getattr(error, "reason_code", None) == "source_changed"
    finally:
        assert phase_proofs, "the real pure proof must execute inside final result sealing"
        assert result_calls == [True] and len(returned) == 1
        assert _get_native(returned[0], "status") == expected_status
        assert inside_result is False and changed == [True]
        assert object.__getattribute__(policy, "_data") is data
        assert _bt04_repair_native_digest(data) == data_before
        assert object.__getattribute__(policy, slot) == original_bytes + b" "
        object.__setattr__(policy, slot, original_bytes)
        assert _bt04_repair_native_digest((policy, sessions)) == before
