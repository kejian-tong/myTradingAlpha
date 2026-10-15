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
    assert all(seed.case.bundle.content_hash == base.content_hash for seed in sources)
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
    sources = _member_sources(9, 16)
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
    _reject(lambda: _available(api, subclass))
    _reject(lambda: _available(api, hostile))
    damaged = copy.deepcopy(base)
    damaged.__dict__["manifest"] = hostile
    _reject(lambda: _available(api, damaged))
    damaged = copy.deepcopy(base)
    damaged.__dict__["unexpected"] = hostile
    _reject(lambda: _available(api, damaged))
    damaged = copy.deepcopy(base)
    damaged.__dict__["new_shares_per_old_share"] = DecimalSubclass("2")
    _reject(lambda: _available(api, damaged))
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
    _reject(lambda: _available(api, invalid))
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
    ranges.extend(({"schema_version": "v1", "start": date(2024, 6, 28), "end": date(2024, 7, 7)},
                   {"schema_version": "v1", "start": date(2024, 7, 9), "end": date(2024, 7, 10)}))
    payload.update(coverage_ranges=ranges, replay_evidence=None,
                   schedule=[item for item in payload["schedule"] if item["session_date"] != PAY_DATE])
    gap = quant._bundle(calendar=TradingCalendar.model_validate(payload), cutoff=bt01.PRE_CLOSE_CUTOFF).calendar
    before = _snapshot(ledger)
    _reject(lambda: _payment(api, ledger, date(2024, 7, 9), calendar=gap))
    assert _snapshot(ledger) == before
