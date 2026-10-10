"""BT-03 RED contracts for atomic ledger accounting and retrospective NAV.

The BT-03 API is loaded inside test bodies so this module collects on the
BT-02 base and reports an explicit missing-contract RED.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import importlib
import os
import pathlib
import socket
import subprocess
import urllib.request
import warnings
import zoneinfo
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, Inexact, Rounded, localcontext
from threading import Event, Lock, Thread
from types import SimpleNamespace
from typing import Any

import pytest

from mytradingalpha.data.bars import AdjustmentBasis, BarFinality
from tests.productionization.backtest import test_fills_costs as bt02_fixtures
from tests.productionization.quant import test_signal as pit_fixtures

D = Decimal
ZERO = Decimal("0")
DEFAULT_OPENING_CASH = Decimal("2000")
TEN = Decimal("10")
DEFAULT_CAP = Decimal("100")
UTC = timezone.utc
OPENING_TIME = datetime(2024, 7, 1, 0, 0, tzinfo=UTC)
EVENT_ECONOMIC_TIME = datetime(2024, 7, 1, 1, 0, tzinfo=UTC)
EVENT_OBSERVED_AT = datetime(2024, 7, 1, 2, 0, tzinfo=UTC)
RESOLUTION_CUTOFF = datetime(2024, 7, 4, 0, 0, tzinfo=UTC)
GENESIS_DOMAIN = b"mytradingalpha:bt03:genesis:v1\0"
EVENT_DOMAIN = b"mytradingalpha:bt03:event:v1\0"
PREFIX_DOMAIN = b"mytradingalpha:bt03:prefix:v1\0"

EXPECTED_GENESIS_HASH = "sha256:71db0baeef95ed47d6653554586a43f7c22d0b3671fb6d884508fe76b8b703c8"
EXPECTED_EVENT_BYTES = (
    b'{"amount":"3","calendar_id":"calendar-golden","currency":"USD",'
    b'"due_at":"2024-07-02T00:00:00Z","economic_time":"2024-07-01T01:00:00Z",'
    b'"event_id":"claim-create-1","kind":"receivable_create",'
    b'"obligation_id":"claim-1","observed_at":"2024-07-01T02:00:00Z",'
    b'"previous_hash":"sha256:71db0baeef95ed47d6653554586a43f7c22d0b3671fb6d884508fe76b8b703c8",'
    b'"run_id":"run-bt03-golden","schema_version":"v1","sequence":0}'
)
EXPECTED_EVENT_HASH = "sha256:1a4ef53bc96fe8c42d09f6d666ebc50ebd75c6b447f9f202449c6483b50609a0"
EXPECTED_PREFIX_HASH = "sha256:96f5d394645b2f14e8f3544d6f6d9e494a50002d94c2b8363dc87594803d5e83"


def _bt03_api() -> SimpleNamespace:
    """Resolve only BT-03-owned modules after collection."""

    try:
        ledger = importlib.import_module("mytradingalpha.backtest.ledger")
        nav = importlib.import_module("mytradingalpha.backtest.nav")
        accounting = importlib.import_module("mytradingalpha.backtest.accounting")
    except ModuleNotFoundError as exc:
        if (exc.name or "").startswith("mytradingalpha.backtest"):
            pytest.fail(f"BT-03 RED: ledger, NAV, and accounting contracts are missing ({exc.name})")
        raise
    except ImportError as exc:
        pytest.fail(f"BT-03 RED: ledger, NAV, and accounting contracts cannot load ({type(exc).__name__})")

    names = {
        "Ledger": (ledger, "Ledger"),
        "LedgerEvent": (ledger, "LedgerEvent"),
        "LedgerBalance": (ledger, "LedgerBalance"),
        "EligibleMark": (nav, "EligibleMark"),
        "AccountingPolicy": (nav, "AccountingPolicy"),
        "NAVCalculator": (nav, "NAVCalculator"),
        "AccountingInvariant": (accounting, "AccountingInvariant"),
    }
    missing = [public_name for public_name, (module, attribute) in names.items() if not hasattr(module, attribute)]
    if missing:
        pytest.fail(f"BT-03 RED: required owned API is incomplete ({', '.join(missing)})")
    return SimpleNamespace(**{name: getattr(module, attr) for name, (module, attr) in names.items()})


def _case(*, extended: bool = False) -> SimpleNamespace:
    return bt02_fixtures._case_with_five_future_sessions() if extended else bt02_fixtures._case()


def _new_ledger(
    api: SimpleNamespace,
    case: SimpleNamespace,
    *,
    opening_cash: Decimal = DEFAULT_OPENING_CASH,
    opening_time: datetime | None = None,
    resolution_cutoff: datetime | None = None,
    start_sequence: int = 0,
) -> Any:
    next_session_date = case.binding.next_session.session_date
    containing_ranges = tuple(
        coverage_range
        for coverage_range in case.bundle.calendar.coverage_ranges
        if coverage_range.start <= next_session_date <= coverage_range.end
    )
    assert len(containing_ranges) == 1
    latest_session = case.bundle.calendar.sessions(
        next_session_date, containing_ranges[0].end
    )[-1]
    return api.Ledger(
        run_id=case.context.run_id,
        calendar_id=case.bundle.calendar.calendar_id,
        currency="USD",
        opening_cash=opening_cash,
        opening_time=OPENING_TIME if opening_time is None else opening_time,
        resolution_cutoff=resolution_cutoff or latest_session.close_at + timedelta(hours=1),
        start_sequence=start_sequence,
    )


def _tail(balance: Any) -> str:
    if balance.event_count == 0:
        return balance.genesis_hash
    return balance.prefix_hashes[-1]


def _fill_event(
    api: SimpleNamespace,
    ledger: Any,
    *,
    intent: Any,
    fill: Any,
    case: SimpleNamespace,
    outcome: Any,
    policy: Any,
    event_id: str,
) -> Any:
    balance = ledger.balance()
    return api.LedgerEvent.for_fill(
        event_id=event_id,
        sequence=balance.next_sequence,
        previous_hash=_tail(balance),
        intent=intent,
        fill=fill,
        binding=case.binding,
        outcome=outcome,
        policy=policy,
    )


def _obligation_event(
    api: SimpleNamespace,
    ledger: Any,
    *,
    event_id: str,
    kind: str,
    obligation_id: str,
    amount: Decimal,
    economic_time: datetime,
    observed_at: datetime,
    due_at: datetime,
) -> Any:
    balance = ledger.balance()
    return api.LedgerEvent.for_obligation(
        event_id=event_id,
        sequence=balance.next_sequence,
        previous_hash=_tail(balance),
        run_id=balance.run_id,
        calendar_id=balance.calendar_id,
        currency="USD",
        kind=kind,
        obligation_id=obligation_id,
        amount=amount,
        economic_time=economic_time,
        observed_at=observed_at,
        due_at=due_at,
    )


def _policy(api: SimpleNamespace, **changes: object) -> Any:
    fields: dict[str, object] = {
        "half_spread_bps": D("0"),
        "slippage_bps": D("0"),
        "commission_per_share": D("0.1"),
        "order_minimum": D("0.2"),
        "fixed_share_cap": D("100"),
    }
    fields.update(changes)
    return bt02_fixtures._policy(api, **fields)


def _make_fill(
    bt02: SimpleNamespace,
    case: SimpleNamespace,
    *,
    intent: Any,
    outcome: Any,
    policy: Any,
    remaining: Decimal | None = None,
    cumulative: Decimal = ZERO,
    cash: Decimal = DEFAULT_OPENING_CASH,
    shares: Decimal = TEN,
    cap: Decimal = DEFAULT_CAP,
) -> Any:
    decision = bt02_fixtures._simulate_direct(
        bt02,
        case,
        intent,
        outcome,
        policy,
        remaining=remaining,
        cumulative=cumulative,
        cash=cash,
        shares=shares,
        cap=cap,
    )
    assert decision.fill is not None, f"BT-02 fixture did not produce one fill: {decision.status}"
    return decision.fill


def _snapshot(ledger: Any) -> tuple[Any, tuple[tuple[object, ...], ...]]:
    balance = ledger.balance()
    events = tuple(
        (
            event.event_id,
            event.sequence,
            event.canonical_bytes(),
            _prefix_hash(event.previous_hash, event.canonical_bytes()),
        )
        for event in ledger.events
    )
    return balance, events


def _expect_rejection(action: Callable[[], object]) -> BaseException:
    with pytest.raises((ValueError, TypeError, OverflowError)) as captured:
        action()
    assert len(str(captured.value)) <= 256
    return captured.value


def _mark(api: SimpleNamespace, case: SimpleNamespace, outcome: Any) -> Any:
    return api.EligibleMark(binding=case.binding, outcome=outcome)


def _accounting_policy(
    api: SimpleNamespace,
    case: SimpleNamespace,
    outcome: Any,
    *,
    valuation_cutoff: datetime | None = None,
    archive_cutoff: datetime | None = None,
    session_date: date | None = None,
    currency: str = "USD",
    mark_source: str | None = None,
    mark_revision: int | None = None,
) -> Any:
    bar = outcome.bar
    default_cutoff = max(bar.manifest.available_at, bar.manifest.ingested_at)
    return api.AccountingPolicy(
        binding=case.binding,
        session_date=session_date or bar.session_date,
        valuation_cutoff=default_cutoff if valuation_cutoff is None else valuation_cutoff,
        archive_cutoff=bar.manifest.ingested_at if archive_cutoff is None else archive_cutoff,
        currency=currency,
        mark_source=mark_source if mark_source is not None else bar.manifest.source,
        mark_revision=mark_revision if mark_revision is not None else bar.manifest.revision,
    )


def _nav(api: SimpleNamespace, balance: Any, case: SimpleNamespace, outcome: Any, **policy: object) -> Any:
    return api.NAVCalculator().compute(
        balance,
        (_mark(api, case, outcome),),
        _accounting_policy(api, case, outcome, **policy),
    )


def _result_status(value: Any) -> str:
    return str(getattr(value.status, "value", value.status))


def _result_reason(value: Any) -> str | None:
    reason = getattr(value, "reason_code", None)
    if reason is None:
        reason = getattr(value, "reason", None)
    if reason is None:
        return None
    return str(getattr(reason, "value", reason))


def _prefix_hash(previous_hash: str, canonical_event: bytes) -> str:
    previous_raw = bytes.fromhex(previous_hash.removeprefix("sha256:"))
    raw = hashlib.sha256(PREFIX_DOMAIN + previous_raw + canonical_event).hexdigest()
    return f"sha256:{raw}"


def _golden_ledger(api: SimpleNamespace) -> tuple[Any, Any]:
    ledger = api.Ledger(
        run_id="run-bt03-golden",
        calendar_id="calendar-golden",
        currency="USD",
        opening_cash=D("1000.00"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
        start_sequence=0,
    )
    event = api.LedgerEvent.for_obligation(
        event_id="claim-create-1",
        sequence=0,
        previous_hash=ledger.balance().genesis_hash,
        run_id="run-bt03-golden",
        calendar_id="calendar-golden",
        currency="USD",
        kind="receivable_create",
        obligation_id="claim-1",
        amount=D("3.00"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=datetime(2024, 7, 2, 0, 0, tzinfo=UTC),
    )
    return ledger, event


def _obligation_chain(api: SimpleNamespace, ledger: Any, count: int) -> tuple[Any, ...]:
    balance = ledger.balance()
    previous_hash = balance.genesis_hash
    due_at = datetime(2024, 7, 2, 1, 0, tzinfo=UTC)
    events: list[Any] = []
    for offset in range(count):
        if offset == 0:
            event_id = "capacity-claim-create"
            kind = "receivable_create"
            obligation_id = "capacity-claim"
            amount = D(count - 1)
            economic_time = EVENT_ECONOMIC_TIME
            observed_at = EVENT_OBSERVED_AT
        else:
            event_id = f"capacity-claim-settle-{offset:04d}"
            kind = "receivable_settle"
            obligation_id = "capacity-claim"
            amount = D("1")
            economic_time = due_at
            observed_at = due_at
        event = api.LedgerEvent.for_obligation(
            event_id=event_id,
            sequence=balance.next_sequence + offset,
            previous_hash=previous_hash,
            run_id=balance.run_id,
            calendar_id=balance.calendar_id,
            currency="USD",
            kind=kind,
            obligation_id=obligation_id,
            amount=amount,
            economic_time=economic_time,
            observed_at=observed_at,
            due_at=due_at,
        )
        events.append(event)
        previous_hash = _prefix_hash(previous_hash, event.canonical_bytes())
    return tuple(events)


def test_bt03_surface_and_independent_small_canonical_hash_golden() -> None:
    api = _bt03_api()
    assert api.Ledger
    assert api.LedgerEvent
    assert api.LedgerBalance
    assert api.NAVCalculator
    assert api.AccountingInvariant

    ledger, event = _golden_ledger(api)
    assert ledger.balance().genesis_hash == EXPECTED_GENESIS_HASH
    assert event.canonical_bytes() == EXPECTED_EVENT_BYTES
    assert f"sha256:{hashlib.sha256(EVENT_DOMAIN + EXPECTED_EVENT_BYTES).hexdigest()}" == EXPECTED_EVENT_HASH

    balance = ledger.append(event)
    assert balance.event_count == 1
    assert balance.next_sequence == 1
    assert balance.prefix_hashes == (EXPECTED_PREFIX_HASH,)
    assert balance.genesis_hash == EXPECTED_GENESIS_HASH
    assert balance.cash == D("1000.00")
    assert balance.receivables == D("3")
    assert balance.positions == ()


def test_fill_posting_is_atomic_and_nav_charges_fee_once() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case, price=D("100"))
    policy = _policy(bt02, commission_per_share=D("0.1"), order_minimum=D("0.2"))
    buy_intent = bt02_fixtures._intent(bt02, case, quantity=D("10"), time_in_force="day")
    buy_fill = _make_fill(bt02, case, intent=buy_intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    before = ledger.balance()
    buy = _fill_event(
        api,
        ledger,
        intent=buy_intent,
        fill=buy_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="fill-buy-1",
    )
    with pytest.raises(TypeError):
        api.LedgerEvent.for_fill(
            event_id="caller-legs-forbidden",
            sequence=0,
            previous_hash=before.genesis_hash,
            intent=buy_intent,
            fill=buy_fill,
            binding=case.binding,
            outcome=outcome,
            policy=policy,
            cash_delta=D("-1006"),
            position_delta=D("10"),
        )
    after_buy = ledger.append(buy)

    assert api.AccountingInvariant.check(before, buy, after_buy) is None
    assert after_buy.cash == D("999.0")
    assert after_buy.positions == (("inst-survivor", D("10")),)
    assert after_buy.total_fees == D("1.0")

    sell_intent = bt02_fixtures._intent(
        bt02,
        case,
        side="sell",
        quantity=D("4"),
        time_in_force="day",
        plan_id="plan-bt03-sale",
    )
    sell_fill = _make_fill(
        bt02,
        case,
        intent=sell_intent,
        outcome=outcome,
        policy=policy,
        cash=after_buy.cash,
        shares=D("10"),
    )
    sell = _fill_event(
        api,
        ledger,
        intent=sell_intent,
        fill=sell_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="fill-sell-1",
    )
    before_sell = ledger.balance()
    after_sell = ledger.append(sell)
    assert api.AccountingInvariant.check(before_sell, sell, after_sell) is None
    assert after_sell.cash == D("1398.6")
    assert after_sell.positions == (("inst-survivor", D("6")),)
    assert after_sell.total_fees == D("1.4")

    result = _nav(api, after_sell, case, outcome)
    assert _result_status(result) == "available"
    assert result.value == D("1998.6")
    assert result.run_valid is True


def test_unaffordable_buy_and_oversell_leave_all_ledger_state_unchanged() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    buy = bt02_fixtures._intent(bt02, case, quantity=D("2"))
    buy_fill = _make_fill(bt02, case, intent=buy, outcome=outcome, policy=policy)

    underfunded = _new_ledger(api, case, opening_cash=D("100"))
    before = _snapshot(underfunded)
    buy_event = _fill_event(
        api,
        underfunded,
        intent=buy,
        fill=buy_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="unaffordable-buy",
    )
    _expect_rejection(lambda: underfunded.append(buy_event))
    assert _snapshot(underfunded) == before

    ledger = _new_ledger(api, case, opening_cash=D("200"))
    funded_fill = _make_fill(
        bt02,
        case,
        intent=buy,
        outcome=outcome,
        policy=policy,
        cash=D("200"),
    )
    funded_event = _fill_event(
        api,
        ledger,
        intent=buy,
        fill=funded_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="funded-buy",
    )
    after_buy = ledger.append(funded_event)
    assert after_buy.cash == D("0")
    assert after_buy.positions == (("inst-survivor", D("2")),)

    sell = bt02_fixtures._intent(
        bt02,
        case,
        side="sell",
        quantity=D("3"),
        plan_id="plan-oversell-fixture",
    )
    oversell_fill = _make_fill(
        bt02,
        case,
        intent=sell,
        outcome=outcome,
        policy=policy,
        cash=after_buy.cash,
        shares=D("10"),
    )
    oversell_event = _fill_event(
        api,
        ledger,
        intent=sell,
        fill=oversell_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="oversell",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(oversell_event))
    assert _snapshot(ledger) == before


@pytest.mark.parametrize(
    ("quantities", "cap"),
    (
        ((D("5"), D("5")), D("5")),
        ((D("4"), D("4"), D("2")), D("4")),
        ((D("2"), D("2"), D("2"), D("2"), D("2")), D("2")),
    ),
)
def test_cumulative_fee_once_reconciles_two_three_and_five_partials(
    quantities: tuple[Decimal, ...], cap: Decimal
) -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    session_dates = (
        date(2024, 7, 3),
        date(2024, 7, 5),
        date(2024, 7, 8),
        date(2024, 7, 9),
        date(2024, 7, 10),
    )[: len(quantities)]
    outcomes = tuple(
        bt02_fixtures._outcome(bt02, case, session=session_date)
        for session_date in session_dates
    )
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(session_dates[-1]).close_at,
    )
    policy = _policy(
        bt02,
        commission_per_share=D("0.1"),
        order_minimum=D("0.2"),
        fixed_share_cap=cap,
    )
    simulated = bt02_fixtures._run(
        bt02,
        case,
        (intent,),
        outcomes,
        policy,
        cash=D("2000"),
        end_session=session_dates[-1],
    )
    assert tuple(fill.quantity for fill in simulated.fills) == quantities
    ledger = _new_ledger(api, case, opening_cash=D("2000"))

    for index, (fill, outcome) in enumerate(zip(simulated.fills, outcomes, strict=True)):
        event = _fill_event(
            api,
            ledger,
            intent=intent,
            fill=fill,
            case=case,
            outcome=outcome,
            policy=policy,
            event_id=f"partial-fill-{index + 1}",
        )
        ledger.append(event)

    final = ledger.balance()
    assert final.cash == D("999")
    assert final.positions == (("inst-survivor", D("10")),)
    assert final.total_fees == D("1.00")
    assert final.event_count == len(quantities)


def test_older_identical_event_retry_returns_current_balance_and_keeps_prefix() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    session_dates = (date(2024, 7, 3), date(2024, 7, 5))
    outcomes = tuple(
        bt02_fixtures._outcome(bt02, case, session=session_date)
        for session_date in session_dates
    )
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(session_dates[-1]).close_at,
    )
    policy = _policy(bt02, fixed_share_cap=D("5"))
    simulated = bt02_fixtures._run(
        bt02,
        case,
        (intent,),
        outcomes,
        policy,
        cash=D("2000"),
        end_session=session_dates[-1],
    )
    assert len(simulated.fills) == 2

    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    accepted: list[Any] = []
    for index, (fill, outcome) in enumerate(zip(simulated.fills, outcomes, strict=True)):
        event = _fill_event(
            api,
            ledger,
            intent=intent,
            fill=fill,
            case=case,
            outcome=outcome,
            policy=policy,
            event_id=f"retry-fill-{index + 1}",
        )
        ledger.append(event)
        accepted.append(event)

    final_snapshot = _snapshot(ledger)
    original = ledger.events[0]
    original_bytes = original.canonical_bytes()
    original_sequence = original.sequence
    original_prefix = _prefix_hash(original.previous_hash, original.canonical_bytes())
    retry_balance = ledger.append(accepted[0])
    assert retry_balance == final_snapshot[0]
    assert _snapshot(ledger) == final_snapshot
    assert ledger.events[0].canonical_bytes() == original_bytes
    assert ledger.events[0].sequence == original_sequence == 0
    assert _prefix_hash(
        ledger.events[0].previous_hash, ledger.events[0].canonical_bytes()
    ) == original_prefix
    assert ledger.balance().event_count == 2

    conflicting = api.LedgerEvent.for_obligation(
        event_id=accepted[0].event_id,
        sequence=ledger.balance().next_sequence,
        previous_hash=_tail(ledger.balance()),
        run_id=case.context.run_id,
        calendar_id=case.bundle.calendar.calendar_id,
        currency="USD",
        kind="receivable_create",
        obligation_id="different-payload",
        amount=D("1"),
        economic_time=case.binding.next_session.close_at + timedelta(minutes=5),
        observed_at=case.binding.next_session.close_at + timedelta(minutes=6),
        due_at=case.binding.next_session.close_at + timedelta(days=1),
    )
    before_conflict = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(conflicting))
    assert _snapshot(ledger) == before_conflict


def test_sequence_gap_wrong_hash_reused_fill_and_missing_partial_are_atomic() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    first_day, second_day = date(2024, 7, 3), date(2024, 7, 5)
    first_outcome = bt02_fixtures._outcome(bt02, case, session=first_day)
    second_outcome = bt02_fixtures._outcome(bt02, case, session=second_day)
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(second_day).close_at,
    )
    policy = _policy(bt02, fixed_share_cap=D("5"))
    first_fill = _make_fill(
        bt02, case, intent=intent, outcome=first_outcome, policy=policy, cap=D("5")
    )
    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    first = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=first_fill,
        case=case,
        outcome=first_outcome,
        policy=policy,
        event_id="atomic-first-fill",
    )
    ledger.append(first)

    good_second_fill = _make_fill(
        bt02,
        case,
        intent=intent,
        outcome=second_outcome,
        policy=policy,
        remaining=D("5"),
        cumulative=D("5"),
        cash=ledger.balance().cash,
        cap=D("5"),
    )
    current = ledger.balance()
    gap = api.LedgerEvent.for_obligation(
        event_id="sequence-gap",
        sequence=current.next_sequence + 1,
        previous_hash=_tail(current),
        run_id=case.context.run_id,
        calendar_id=case.bundle.calendar.calendar_id,
        currency="USD",
        kind="receivable_create",
        obligation_id="gap-claim",
        amount=D("1"),
        economic_time=second_outcome.bar.manifest.event_time,
        observed_at=second_outcome.bar.manifest.ingested_at,
        due_at=second_outcome.bar.manifest.event_time,
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(gap))
    assert _snapshot(ledger) == before

    wrong_predecessor = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=good_second_fill,
        case=case,
        outcome=second_outcome,
        policy=policy,
        event_id="wrong-predecessor",
    )
    object.__setattr__(wrong_predecessor, "previous_hash", "sha256:" + "0" * 64)
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(wrong_predecessor))
    assert _snapshot(ledger) == before

    duplicate_fill = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=first_fill,
        case=case,
        outcome=first_outcome,
        policy=policy,
        event_id="new-event-same-fill-id",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(duplicate_fill))
    assert _snapshot(ledger) == before

    missing_partial_fill = _make_fill(
        bt02,
        case,
        intent=intent,
        outcome=second_outcome,
        policy=policy,
        remaining=D("8"),
        cumulative=D("2"),
        cash=ledger.balance().cash,
        cap=D("3"),
    )
    missing_partial = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=missing_partial_fill,
        case=case,
        outcome=second_outcome,
        policy=policy,
        event_id="missing-prior-partial",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(missing_partial))
    assert _snapshot(ledger) == before


def test_fill_cumulative_ownership_rejects_repeat_attempt_and_changed_policy() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    first_day, next_day = date(2024, 7, 3), date(2024, 7, 5)
    first_outcome = bt02_fixtures._outcome(bt02, case, session=first_day)
    next_outcome = bt02_fixtures._outcome(bt02, case, session=next_day)
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(next_day).close_at,
    )
    policy = _policy(bt02, fixed_share_cap=D("5"))
    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    first_fill = _make_fill(
        bt02,
        case,
        intent=intent,
        outcome=first_outcome,
        policy=policy,
        cap=D("2"),
    )
    first = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=first_fill,
        case=case,
        outcome=first_outcome,
        policy=policy,
        event_id="one-attempt-first",
    )
    ledger.append(first)

    same_session_fill = _make_fill(
        bt02,
        case,
        intent=intent,
        outcome=first_outcome,
        policy=policy,
        remaining=D("8"),
        cumulative=D("2"),
        cash=ledger.balance().cash,
        cap=D("2"),
    )
    same_session = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=same_session_fill,
        case=case,
        outcome=first_outcome,
        policy=policy,
        event_id="one-attempt-repeat",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(same_session))
    assert _snapshot(ledger) == before

    changed_policy = _policy(
        bt02,
        fixed_share_cap=D("5"),
        policy_version="bt02-alternate-policy-v1",
    )
    later_fill = _make_fill(
        bt02,
        case,
        intent=intent,
        outcome=next_outcome,
        policy=changed_policy,
        remaining=D("8"),
        cumulative=D("2"),
        cash=ledger.balance().cash,
        cap=D("2"),
    )
    changed_owner = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=later_fill,
        case=case,
        outcome=next_outcome,
        policy=changed_policy,
        event_id="changed-intent-policy-owner",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(changed_owner))
    assert _snapshot(ledger) == before


def test_aggregate_instrument_session_cap_and_slot_policy_are_owned_once() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    cap_policy = _policy(bt02, fixed_share_cap=D("5"))
    ledger = _new_ledger(api, case, opening_cash=D("2000"))

    def make_slot_event(label: str, quantity: Decimal, selected_policy: Any) -> Any:
        intent = bt02_fixtures._intent(
            bt02,
            case,
            quantity=quantity,
            time_in_force="day",
            plan_id=f"plan-slot-{label}",
        )
        fill = _make_fill(
            bt02,
            case,
            intent=intent,
            outcome=outcome,
            policy=selected_policy,
            cap=quantity,
        )
        return _fill_event(
            api,
            ledger,
            intent=intent,
            fill=fill,
            case=case,
            outcome=outcome,
            policy=selected_policy,
            event_id=f"slot-fill-{label}",
        )

    first = make_slot_event("first", D("3"), cap_policy)
    ledger.append(first)
    over_cap = make_slot_event("over-cap", D("3"), cap_policy)
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(over_cap))
    assert _snapshot(ledger) == before

    changed_slot_policy = _policy(
        bt02,
        fixed_share_cap=D("10"),
        policy_version="bt02-other-slot-policy-v1",
    )
    changed = make_slot_event("changed-policy", D("1"), changed_slot_policy)
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(changed))
    assert _snapshot(ledger) == before


def test_balanced_claims_settlements_due_dates_and_unaffordable_payables() -> None:
    api = _bt03_api()
    case = _case()
    ledger = _new_ledger(api, case, opening_cash=D("100"))
    due = EVENT_ECONOMIC_TIME + timedelta(days=1)
    claim = _obligation_event(
        api,
        ledger,
        event_id="claim-create",
        kind="receivable_create",
        obligation_id="claim-dividend-fixture",
        amount=D("50"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=due,
    )
    before_claim = ledger.balance()
    after_claim = ledger.append(claim)
    assert api.AccountingInvariant.check(before_claim, claim, after_claim) is None
    assert after_claim.cash == D("100")
    assert after_claim.receivables == D("50")
    assert after_claim.recognized_income == D("50")

    def reject_settlement_reference(
        *, event_id: str, kind: str, obligation_id: str, due_at: datetime
    ) -> None:
        current = ledger.balance()
        economic_time = max(due, due_at, current.latest_economic_time or due)
        observed_at = max(economic_time, current.latest_observation_time or economic_time)
        event = api.LedgerEvent.for_obligation(
            event_id=event_id,
            sequence=current.next_sequence,
            previous_hash=_tail(current),
            run_id=current.run_id,
            calendar_id=current.calendar_id,
            currency="USD",
            kind=kind,
            obligation_id=obligation_id,
            amount=D("1"),
            economic_time=economic_time,
            observed_at=observed_at,
            due_at=due_at,
        )
        before = _snapshot(ledger)
        _expect_rejection(lambda: ledger.append(event))
        assert _snapshot(ledger) == before

    reject_settlement_reference(
        event_id="claim-settle-missing-reference",
        kind="receivable_settle",
        obligation_id="missing-claim",
        due_at=due,
    )
    reject_settlement_reference(
        event_id="claim-settle-wrong-kind",
        kind="liability_settle",
        obligation_id="claim-dividend-fixture",
        due_at=due,
    )
    reject_settlement_reference(
        event_id="claim-settle-wrong-due-date",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        due_at=due + timedelta(seconds=1),
    )

    early = api.LedgerEvent.for_obligation(
        event_id="claim-settle-early",
        sequence=after_claim.next_sequence,
        previous_hash=_tail(after_claim),
        run_id=after_claim.run_id,
        calendar_id=after_claim.calendar_id,
        currency="USD",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        amount=D("1"),
        economic_time=due - timedelta(microseconds=1),
        observed_at=due,
        due_at=due,
    )
    before_early = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(early))
    assert _snapshot(ledger) == before_early

    first_settlement = api.LedgerEvent.for_obligation(
        event_id="claim-settle-part-1",
        sequence=after_claim.next_sequence,
        previous_hash=_tail(after_claim),
        run_id=after_claim.run_id,
        calendar_id=after_claim.calendar_id,
        currency="USD",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        amount=D("20"),
        economic_time=due,
        observed_at=due,
        due_at=due,
    )
    before_partial = ledger.balance()
    partial = ledger.append(first_settlement)
    assert api.AccountingInvariant.check(before_partial, first_settlement, partial) is None
    assert partial.cash == D("120")
    assert partial.receivables == D("30")

    final_settlement = _obligation_event(
        api,
        ledger,
        event_id="claim-settle-part-2",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        amount=D("30"),
        economic_time=due + timedelta(seconds=1),
        observed_at=due + timedelta(seconds=1),
        due_at=due,
    )
    settled = ledger.append(final_settlement)
    assert settled.cash == D("150")
    assert settled.receivables == D("0")

    reject_settlement_reference(
        event_id="claim-settle-repeated-identity",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        due_at=due,
    )

    liability_due = due + timedelta(days=1)
    liability = _obligation_event(
        api,
        ledger,
        event_id="liability-create",
        kind="liability_create",
        obligation_id="payable-fixture",
        amount=D("250"),
        economic_time=due + timedelta(seconds=2),
        observed_at=due + timedelta(seconds=2),
        due_at=liability_due,
    )
    before_liability = ledger.balance()
    accrued = ledger.append(liability)
    assert api.AccountingInvariant.check(before_liability, liability, accrued) is None
    assert accrued.cash == D("150")
    assert accrued.liabilities == D("250")
    assert accrued.recognized_expense == D("250")

    unaffordable = api.LedgerEvent.for_obligation(
        event_id="liability-settle-unaffordable",
        sequence=accrued.next_sequence,
        previous_hash=_tail(accrued),
        run_id=accrued.run_id,
        calendar_id=accrued.calendar_id,
        currency="USD",
        kind="liability_settle",
        obligation_id="payable-fixture",
        amount=D("250"),
        economic_time=liability_due,
        observed_at=liability_due,
        due_at=liability_due,
    )
    before_pay = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(unaffordable))
    assert _snapshot(ledger) == before_pay

    before_over_settlement = ledger.balance()
    over_settlement = api.LedgerEvent.for_obligation(
        event_id="claim-over-settlement",
        sequence=before_over_settlement.next_sequence,
        previous_hash=_tail(before_over_settlement),
        run_id=before_over_settlement.run_id,
        calendar_id=before_over_settlement.calendar_id,
        currency="USD",
        kind="receivable_settle",
        obligation_id="claim-dividend-fixture",
        amount=D("1"),
        economic_time=liability_due,
        observed_at=liability_due,
        due_at=due,
    )
    before_over = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(over_settlement))
    assert _snapshot(ledger) == before_over


def test_payable_partial_and_final_settlement_preserve_expense_and_nav() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    session_date = case.binding.next_session.session_date
    close = case.bundle.calendar.session(session_date).close_at
    mark_outcome = bt02_fixtures._outcome(bt02, case, session=session_date)
    ledger = _new_ledger(api, case, opening_cash=D("100"))
    payable = _obligation_event(
        api,
        ledger,
        event_id="solvent-payable-create",
        kind="liability_create",
        obligation_id="solvent-payable",
        amount=D("50"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=close,
    )
    accrued = ledger.append(payable)
    assert accrued.cash == D("100")
    assert accrued.liabilities == D("50")
    assert accrued.recognized_expense == D("50")

    def nav(balance: Any) -> Any:
        policy = _accounting_policy(
            api,
            case,
            mark_outcome,
            valuation_cutoff=mark_outcome.bar.manifest.ingested_at,
            archive_cutoff=mark_outcome.bar.manifest.ingested_at,
            session_date=session_date,
        )
        return api.NAVCalculator().compute(balance, (), policy)

    accrued_nav = nav(accrued)
    assert _result_status(accrued_nav) == "available"
    assert accrued_nav.value == D("50")

    partial_event = _obligation_event(
        api,
        ledger,
        event_id="solvent-payable-settle-part-1",
        kind="liability_settle",
        obligation_id="solvent-payable",
        amount=D("20"),
        economic_time=close,
        observed_at=close,
        due_at=close,
    )
    partial = ledger.append(partial_event)
    partial_nav = nav(partial)
    assert partial.cash == D("80")
    assert partial.liabilities == D("30")
    assert partial.recognized_expense == D("50")
    assert _result_status(partial_nav) == "available"
    assert partial_nav.value == accrued_nav.value == D("50")

    final_event = _obligation_event(
        api,
        ledger,
        event_id="solvent-payable-settle-final",
        kind="liability_settle",
        obligation_id="solvent-payable",
        amount=D("30"),
        economic_time=close,
        observed_at=close,
        due_at=close,
    )
    final = ledger.append(final_event)
    final_nav = nav(final)
    assert final.cash == D("50")
    assert final.liabilities == D("0")
    assert final.recognized_expense == D("50")
    assert _result_status(final_nav) == "available"
    assert final_nav.value == partial_nav.value == D("50")

    negative_ledger = _new_ledger(api, case, opening_cash=ZERO)
    negative_liability = _obligation_event(
        api,
        negative_ledger,
        event_id="liability-exceeds-assets",
        kind="liability_create",
        obligation_id="negative-nav-payable",
        amount=D("25"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=close,
    )
    negative_balance = negative_ledger.append(negative_liability)
    negative_nav = nav(negative_balance)
    assert negative_balance.cash == ZERO
    assert negative_balance.positions == ()
    assert _result_status(negative_nav) == "available"
    assert negative_nav.value == D("-25")
    assert negative_nav.run_valid is True


def test_nav_requires_complete_marks_and_respects_cutoff_and_latest_receipt() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    fill_outcome = bt02_fixtures._outcome(
        bt02,
        case,
        price=D("100"),
        available_offset_minutes=5,
        ingestion_offset_minutes=7,
    )
    mark_outcome = bt02_fixtures._outcome(
        bt02,
        case,
        price=D("100"),
        source="synthetic-mark-v1",
        available_offset_minutes=1,
        ingestion_offset_minutes=3,
    )
    intent = bt02_fixtures._intent(bt02, case, quantity=D("2"))
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    fill = _make_fill(bt02, case, intent=intent, outcome=fill_outcome, policy=policy)
    ledger = _new_ledger(api, case, opening_cash=D("1000"))
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=fill_outcome,
        policy=policy,
        event_id="nav-fill",
    )
    balance = ledger.append(event)
    receipt_cutoff = fill.received_at
    result = _nav(
        api,
        balance,
        case,
        mark_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
    )
    assert _result_status(result) == "available"
    assert result.value == D("1000")

    later_mark = bt02_fixtures._outcome(
        bt02,
        case,
        session=date(2024, 7, 5),
        source="synthetic-mark-later-v1",
        available_offset_minutes=1,
        ingestion_offset_minutes=3,
    )
    later_mark_ingestion = later_mark.bar.manifest.ingested_at
    later_mark_availability = later_mark.bar.manifest.available_at
    default_later_policy = _accounting_policy(api, case, later_mark)
    assert default_later_policy.valuation_cutoff == later_mark_ingestion
    at_mark_cutoffs = _nav(
        api,
        balance,
        case,
        later_mark,
        session_date=date(2024, 7, 5),
        valuation_cutoff=later_mark_availability,
        archive_cutoff=later_mark_ingestion,
    )
    assert _result_status(at_mark_cutoffs) == "available"
    assert at_mark_cutoffs.value == D("1000")

    before_availability = _nav(
        api,
        balance,
        case,
        later_mark,
        session_date=date(2024, 7, 5),
        valuation_cutoff=later_mark_availability - timedelta(microseconds=1),
        archive_cutoff=later_mark_ingestion,
    )
    assert _result_status(before_availability) == "unavailable"
    assert before_availability.value is None
    assert before_availability.run_valid is False

    before_ingestion = _nav(
        api,
        balance,
        case,
        later_mark,
        session_date=date(2024, 7, 5),
        valuation_cutoff=later_mark_availability,
        archive_cutoff=later_mark_ingestion - timedelta(microseconds=1),
    )
    assert _result_status(before_ingestion) == "unavailable"
    assert before_ingestion.value is None

    before_receipt = _nav(
        api,
        balance,
        case,
        mark_outcome,
        archive_cutoff=mark_outcome.bar.manifest.ingested_at,
    )
    assert _result_status(before_receipt) == "unavailable"
    assert before_receipt.value is None

    valuation_before_receipt = _nav(
        api,
        balance,
        case,
        mark_outcome,
        valuation_cutoff=receipt_cutoff - timedelta(microseconds=1),
        archive_cutoff=receipt_cutoff,
    )
    assert _result_status(valuation_before_receipt) == "unavailable"
    assert valuation_before_receipt.value is None

    archive_before_receipt = _nav(
        api,
        balance,
        case,
        mark_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff - timedelta(microseconds=1),
    )
    assert _result_status(archive_before_receipt) == "unavailable"
    assert archive_before_receipt.value is None

    missing = api.NAVCalculator().compute(
        balance,
        (),
        _accounting_policy(
            api,
            case,
            mark_outcome,
            valuation_cutoff=receipt_cutoff,
            archive_cutoff=receipt_cutoff,
        ),
    )
    assert _result_status(missing) == "unavailable"
    assert missing.value is None

    wrong_source = _nav(
        api,
        balance,
        case,
        mark_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
        mark_source="other-captured-source",
    )
    assert _result_status(wrong_source) == "unavailable"
    wrong_revision = _nav(
        api,
        balance,
        case,
        mark_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
        mark_revision=1,
    )
    assert _result_status(wrong_revision) == "unavailable"

    later_outcome = bt02_fixtures._outcome(bt02, case, session=date(2024, 7, 5))
    future = _nav(
        api,
        balance,
        case,
        later_outcome,
        session_date=mark_outcome.bar.session_date,
    )
    assert _result_status(future) == "unavailable"

    earlier_target = _nav(
        api,
        balance,
        case,
        mark_outcome,
        session_date=date(2024, 7, 2),
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
    )
    assert _result_status(earlier_target) == "unavailable"


def test_nav_uses_sealed_instrument_currency_and_requires_one_mark_per_holding() -> None:
    bt02 = bt02_fixtures._bt02_api()
    usd_case = _case()
    usd_outcome = bt02_fixtures._outcome(bt02, usd_case)
    usd_intent = bt02_fixtures._intent(bt02, usd_case, quantity=D("1"))
    usd_policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    usd_fill = _make_fill(
        bt02,
        usd_case,
        intent=usd_intent,
        outcome=usd_outcome,
        policy=usd_policy,
    )
    assert usd_fill.quantity == D("1")
    assert usd_fill.fee == D("0")
    bt02_fixtures._validate_fill_context(
        bt02, usd_case, usd_fill, usd_intent, usd_outcome, usd_policy
    )

    bt01 = bt02_fixtures.bt01_fixtures
    base = pit_fixtures._bundle(
        cutoff=bt01.PRE_CLOSE_CUTOFF,
        calendar=usd_case.bundle.calendar,
    )
    instrument_id = usd_case.envelope.quant.instrument_id
    assert instrument_id == "inst-survivor"
    instruments = tuple(
        instrument.model_copy(update={"currency": "EUR"})
        if instrument.instrument_id == instrument_id
        else instrument
        for instrument in base.instruments
    )
    euro_bundle = pit_fixtures._bundle(
        cutoff=bt01.PRE_CLOSE_CUTOFF,
        calendar=base.calendar,
        instruments=instruments,
    )
    assert next(
        instrument.currency
        for instrument in usd_case.bundle.instruments
        if instrument.instrument_id == instrument_id
    ) == "USD"
    assert next(
        instrument.currency
        for instrument in euro_bundle.instruments
        if instrument.instrument_id == instrument_id
    ) == "EUR"
    usd_bundle_data = usd_case.bundle.model_dump(mode="python")
    euro_bundle_data = euro_bundle.model_dump(mode="python")
    usd_bundle_hash = usd_bundle_data.pop("bundle_hash", None)
    euro_bundle_hash = euro_bundle_data.pop("bundle_hash", None)
    for payload in (usd_bundle_data, euro_bundle_data):
        for instrument in payload["instruments"]:
            if instrument["instrument_id"] == instrument_id:
                instrument["currency"] = "USD"
    assert usd_bundle_data == euro_bundle_data
    assert usd_bundle_hash != euro_bundle_hash

    context, bundle, envelope = bt01._quant_only_inputs(
        bundle=euro_bundle,
        cutoff=bt01.PRE_CLOSE_CUTOFF,
        base_currency="EUR",
        run_id=usd_case.context.run_id,
        variant_id=usd_case.context.variant_id,
        decision_time=usd_case.context.decision_time.isoformat().replace("+00:00", "Z"),
        earliest_execution_time=usd_case.context.earliest_execution_time.isoformat().replace(
            "+00:00", "Z"
        ),
        calendar_id=usd_case.context.calendar_id,
    )
    bt01_api = bt01._bt_api()
    binding = bt01_api.SessionClock.bind(context, bundle, envelope)
    events = bt01_api.BacktestRunner().run((binding,))
    euro_case = SimpleNamespace(
        context=context,
        bundle=bundle,
        envelope=envelope,
        binding=binding,
        decision=next(event for event in events if type(event).__name__ == "DecisionEvent"),
        opportunity=next(
            event for event in events if type(event).__name__ == "OpportunityEvent"
        ),
    )
    euro_outcome = bt02_fixtures._outcome(bt02, euro_case)
    assert euro_case.context.base_currency == "EUR"
    assert euro_case.context.run_id == usd_case.context.run_id
    assert euro_case.context.variant_id == usd_case.context.variant_id
    assert euro_case.context.calendar_id == usd_case.context.calendar_id
    assert euro_case.context.decision_time == usd_case.context.decision_time
    assert euro_case.context.earliest_execution_time == usd_case.context.earliest_execution_time
    assert euro_case.envelope.quant.instrument_id == usd_intent.instrument_id
    assert euro_outcome.canonical_bytes() == usd_outcome.canonical_bytes()

    with pytest.raises(bt02.OrderInputError) as rejected_fill:
        bt02_fixtures._validate_fill_context(
            bt02, euro_case, usd_fill, usd_intent, euro_outcome, usd_policy
        )
    assert getattr(
        rejected_fill.value.reason_code,
        "value",
        rejected_fill.value.reason_code,
    ) == "binding_mismatch"

    api = _bt03_api()
    euro_ledger = _new_ledger(api, euro_case, opening_cash=D("1000"))
    before = _snapshot(euro_ledger)
    with pytest.raises((ValueError, TypeError)):
        _fill_event(
            api,
            euro_ledger,
            intent=usd_intent,
            fill=usd_fill,
            case=euro_case,
            outcome=euro_outcome,
            policy=usd_policy,
            event_id="sealed-currency-mismatch",
        )
    assert _snapshot(euro_ledger) == before

    usd_ledger = _new_ledger(api, usd_case, opening_cash=D("1000"))
    usd_event = _fill_event(
        api,
        usd_ledger,
        intent=usd_intent,
        fill=usd_fill,
        case=usd_case,
        outcome=usd_outcome,
        policy=usd_policy,
        event_id="one-covered-position",
    )
    balance = usd_ledger.append(usd_event)
    receipt_cutoff = usd_fill.received_at
    assert receipt_cutoff == datetime(2024, 7, 3, 17, 3, tzinfo=UTC)
    usd_mark = _mark(api, usd_case, usd_outcome)
    usd_nav_policy = _accounting_policy(
        api,
        usd_case,
        usd_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
        session_date=usd_outcome.bar.session_date,
        currency="USD",
        mark_source=usd_outcome.bar.manifest.source,
        mark_revision=usd_outcome.bar.manifest.revision,
    )
    usd_nav = api.NAVCalculator().compute(balance, (usd_mark,), usd_nav_policy)
    assert _result_status(usd_nav) == "available"
    assert usd_nav.value is not None
    assert usd_nav.value > ZERO
    assert usd_nav.run_valid is True

    euro_mark = _mark(api, euro_case, euro_outcome)
    euro_nav_policy = _accounting_policy(
        api,
        euro_case,
        euro_outcome,
        valuation_cutoff=receipt_cutoff,
        archive_cutoff=receipt_cutoff,
        session_date=euro_outcome.bar.session_date,
        currency="USD",
        mark_source=euro_outcome.bar.manifest.source,
        mark_revision=euro_outcome.bar.manifest.revision,
    )
    assert euro_nav_policy.valuation_cutoff >= receipt_cutoff
    assert euro_nav_policy.archive_cutoff >= receipt_cutoff
    euro_nav = api.NAVCalculator().compute(balance, (euro_mark,), euro_nav_policy)
    assert _result_status(euro_nav) == "unavailable"
    assert euro_nav.value is None
    assert euro_nav.run_valid is False

    marks = (
        _mark(api, usd_case, usd_outcome),
        _mark(api, usd_case, usd_outcome),
    )
    duplicate_policy = _accounting_policy(api, usd_case, usd_outcome)
    duplicate = api.NAVCalculator().compute(balance, marks, duplicate_policy)
    assert _result_status(duplicate) == "unavailable"
    assert duplicate.value is None


def test_nav_rejects_wrong_session_instrument_calendar_finality_and_adjustment() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    mark_day = date(2024, 7, 3)
    mark_outcome = bt02_fixtures._outcome(bt02, case, session=mark_day)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    fill = _make_fill(bt02, case, intent=intent, outcome=mark_outcome, policy=policy)
    ledger = _new_ledger(api, case)
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=mark_outcome,
        policy=policy,
        event_id="strict-mark-fill",
    )
    balance = ledger.append(event)
    target_day = date(2024, 7, 5)
    target_close = case.bundle.calendar.session(target_day).close_at

    stale = _nav(
        api,
        balance,
        case,
        mark_outcome,
        session_date=target_day,
        valuation_cutoff=target_close + timedelta(minutes=5),
        archive_cutoff=target_close + timedelta(minutes=5),
    )
    assert _result_status(stale) == "unavailable"

    original = mark_outcome.bar
    invalid_bars = (
        original.model_copy(update={"instrument_id": "inst-market-etf"}),
        original.model_copy(update={"calendar_id": "calendar-other"}),
        bt02_fixtures._make_bar(
            case,
            session=mark_day,
            finality=BarFinality.PRELIMINARY,
        ),
        bt02_fixtures._make_bar(
            case,
            session=mark_day,
            adjustment_basis=AdjustmentBasis.PROVIDER_ADJUSTED,
        ),
    )
    for index, invalid_bar in enumerate(invalid_bars):
        invalid_outcome = bt02.OutcomeEvidence(
            invalid_bar,
            outcome_cutoff=invalid_bar.manifest.available_at,
            archive_cutoff=invalid_bar.manifest.ingested_at,
            replay_policy=case.bundle.replay_policy,
        )
        unavailable = _nav(api, balance, case, invalid_outcome)
        assert _result_status(unavailable) == "unavailable", index
        assert unavailable.value is None
        assert unavailable.run_valid is False


def test_opening_and_resolution_cutoffs_reject_out_of_window_fill_atomically() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)

    late_ledger = _new_ledger(
        api,
        case,
        resolution_cutoff=fill.received_at - timedelta(microseconds=1),
    )
    late_event = _fill_event(
        api,
        late_ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="receipt-after-resolution",
    )
    before = _snapshot(late_ledger)
    _expect_rejection(lambda: late_ledger.append(late_event))
    assert _snapshot(late_ledger) == before

    before_economics = _new_ledger(
        api,
        case,
        opening_time=fill.fill_time + timedelta(microseconds=1),
    )
    before_event = _fill_event(
        api,
        before_economics,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="economic-before-opening",
    )
    before = _snapshot(before_economics)
    _expect_rejection(lambda: before_economics.append(before_event))
    assert _snapshot(before_economics) == before

    cutoff = RESOLUTION_CUTOFF
    future_ledger = _new_ledger(
        api,
        case,
        resolution_cutoff=cutoff,
    )
    future_time = cutoff + timedelta(microseconds=1)
    future_event = _obligation_event(
        api,
        future_ledger,
        event_id="economic-after-resolution",
        kind="receivable_create",
        obligation_id="future-claim",
        amount=D("1"),
        economic_time=future_time,
        observed_at=future_time,
        due_at=future_time,
    )
    before = _snapshot(future_ledger)
    _expect_rejection(lambda: future_ledger.append(future_event))
    assert _snapshot(future_ledger) == before


def test_economic_chronology_cannot_be_reordered_to_hide_an_earlier_event() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    first_day, later_day = date(2024, 7, 3), date(2024, 7, 5)
    first_outcome = bt02_fixtures._outcome(bt02, case, session=first_day)
    later_outcome = bt02_fixtures._outcome(bt02, case, session=later_day)
    first_intent = bt02_fixtures._intent(
        bt02, case, quantity=D("1"), plan_id="plan-chronology-first"
    )
    later_intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("1"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(later_day).close_at,
        plan_id="plan-chronology-later",
    )
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    earlier_fill = _make_fill(
        bt02, case, intent=first_intent, outcome=first_outcome, policy=policy
    )
    later_fill = _make_fill(
        bt02, case, intent=later_intent, outcome=later_outcome, policy=policy
    )
    ledger = _new_ledger(api, case)
    later_event = _fill_event(
        api,
        ledger,
        intent=later_intent,
        fill=later_fill,
        case=case,
        outcome=later_outcome,
        policy=policy,
        event_id="economic-later-first",
    )
    ledger.append(later_event)
    earlier_event = _fill_event(
        api,
        ledger,
        intent=first_intent,
        fill=earlier_fill,
        case=case,
        outcome=first_outcome,
        policy=policy,
        event_id="economic-earlier-second",
    )
    before = _snapshot(ledger)
    _expect_rejection(lambda: ledger.append(earlier_event))
    assert _snapshot(ledger) == before


def test_invalid_source_storage_and_completion_mutation_reject_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("2"))
    policy = _policy(
        bt02,
        half_spread_bps=ZERO,
        slippage_bps=ZERO,
        commission_per_share=D("0"),
        order_minimum=D("0"),
    )
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)

    forged = fill.model_copy(update={"price": D("101")})
    with pytest.raises((ValueError, TypeError)):
        _fill_event(
            api,
            ledger,
            intent=intent,
            fill=forged,
            case=case,
            outcome=outcome,
            policy=policy,
            event_id="rehashed-but-invalid-fill",
        )
    assert ledger.balance().event_count == 0

    from mytradingalpha.contracts.orders import _contract_storage_fingerprint

    assert fill.price == D("100")
    original_fill_bytes = fill.canonical_bytes()
    original_storage = _contract_storage_fingerprint(fill, bt02.Fill)

    captured = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="owned-source-event",
    )
    expected_price = captured.fill.price
    expected_native_price = expected_price.as_tuple()
    expected_bytes = captured.canonical_bytes()
    object.__setattr__(fill, "price", D("100.000"))
    assert fill.canonical_bytes() == original_fill_bytes
    assert _contract_storage_fingerprint(fill, bt02.Fill) != original_storage
    assert captured.fill.price == expected_price
    assert captured.fill.price.as_tuple() == expected_native_price
    assert captured.canonical_bytes() == expected_bytes
    ledger.append(captured)
    before_tamper = _snapshot(ledger)

    returned = ledger.events[0]
    object.__setattr__(returned.fill, "price", D("100.000"))
    assert _snapshot(ledger) == before_tamper
    assert ledger.events[0].fill.price.as_tuple() == expected_native_price

    before_completion = _snapshot(ledger)

    original_validate = bt02.FillModel.validate_fill
    completion_mutation: list[tuple[bytes, tuple[object, ...], bytes, tuple[object, ...]]] = []

    def mutate_during_validation(*args: Any, **kwargs: Any) -> Any:
        candidate = args[0] if args else kwargs["fill"]
        canonical_before = candidate.canonical_bytes()
        storage_before = _contract_storage_fingerprint(candidate, bt02.Fill)
        checked = original_validate(*args, **kwargs)
        object.__setattr__(candidate, "price", D("100.000"))
        canonical_after = candidate.canonical_bytes()
        storage_after = _contract_storage_fingerprint(candidate, bt02.Fill)
        completion_mutation.append(
            (canonical_before, storage_before, canonical_after, storage_after)
        )
        return checked

    second_intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("1"),
        plan_id="plan-completion-seal-independent-fill",
    )
    second_fill = _make_fill(
        bt02, case, intent=second_intent, outcome=outcome, policy=policy
    )
    control_ledger = _new_ledger(api, case)
    control_ledger.append(captured)
    control_event = _fill_event(
        api,
        control_ledger,
        intent=second_intent,
        fill=second_fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="completion-seal-control-fill",
    )
    control_balance = control_ledger.append(control_event)
    assert control_balance.event_count == 2
    assert control_balance.positions == (("inst-survivor", D("3")),)
    assert control_balance.cash == D("1700")

    monkeypatch.setattr(bt02.FillModel, "validate_fill", staticmethod(mutate_during_validation))
    with pytest.raises((ValueError, TypeError)):
        completion_event = api.LedgerEvent.for_fill(
            event_id="completion-seal-race",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            intent=second_intent,
            fill=second_fill,
            binding=case.binding,
            outcome=outcome,
            policy=policy,
        )
        ledger.append(completion_event)
    assert completion_mutation
    assert all(after == before for before, _old, after, _new in completion_mutation)
    assert any(old != new for _before, old, _after, new in completion_mutation)
    assert _snapshot(ledger) == before_completion


def test_unicode_and_escaped_source_bytes_remain_owned_by_fill_event() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    source_bar = bt02_fixtures._make_bar(case)
    terms = 'Terms "東京"\nsource archive'
    locator = 'fixture://bt03/source/"東京"?line=one\ntwo'
    manifest = source_bar.manifest.model_copy(
        update={"source_locator": locator, "terms": terms}
    )
    source_bar = source_bar.model_copy(update={"manifest": manifest})
    outcome = bt02_fixtures._outcome(bt02, case, bar=source_bar)
    original_source_bytes = outcome.canonical_bytes()
    assert "東京".encode() in original_source_bytes
    assert b'\\"' in original_source_bytes
    assert b"\\n" in original_source_bytes

    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"), bar=source_bar)
    policy = _policy(
        bt02,
        half_spread_bps=ZERO,
        slippage_bps=ZERO,
        commission_per_share=ZERO,
        order_minimum=ZERO,
    )
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="unicode-source-event",
    )
    event_bytes = event.canonical_bytes()

    object.__setattr__(source_bar.manifest, "terms", "caller replacement")
    assert outcome.canonical_bytes() == original_source_bytes
    assert ledger.append(event).event_count == 1
    assert event.canonical_bytes() == event_bytes
    assert outcome.canonical_bytes() == original_source_bytes


def test_replay_reproduces_exact_prefix_and_retains_last_valid_prefix_on_damage() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    days = (date(2024, 7, 3), date(2024, 7, 5))
    outcomes = tuple(bt02_fixtures._outcome(bt02, case, session=day) for day in days)
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(days[-1]).close_at,
    )
    policy = _policy(bt02, fixed_share_cap=D("5"))
    result = bt02_fixtures._run(
        bt02, case, (intent,), outcomes, policy, cash=D("2000"), end_session=days[-1]
    )
    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    for index, (fill, outcome) in enumerate(zip(result.fills, outcomes, strict=True)):
        ledger.append(
            _fill_event(
                api,
                ledger,
                intent=intent,
                fill=fill,
                case=case,
                outcome=outcome,
                policy=policy,
                event_id=f"replay-fill-{index + 1}",
            )
        )

    replayed = _new_ledger(api, case, opening_cash=D("2000"))
    replayed.replay(ledger.events)
    assert _snapshot(replayed) == _snapshot(ledger)

    damaged = list(ledger.events)
    object.__setattr__(damaged[1], "previous_hash", "sha256:" + "f" * 64)
    partial = _new_ledger(api, case, opening_cash=D("2000"))
    with pytest.raises((ValueError, TypeError)):
        partial.replay(tuple(damaged))
    assert partial.balance().event_count == 1
    assert partial.events[0].canonical_bytes() == ledger.events[0].canonical_bytes()
    assert partial.balance().cash == D("1499.5")


def test_opening_chronology_and_numeric_policy_fail_closed() -> None:
    api = _bt03_api()
    case = _case()
    _expect_rejection(
        lambda: _new_ledger(
            api,
            case,
            opening_time=RESOLUTION_CUTOFF,
            resolution_cutoff=OPENING_TIME,
        )
    )
    _expect_rejection(lambda: _new_ledger(api, case, opening_cash=1000))
    _expect_rejection(lambda: _new_ledger(api, case, opening_cash="1000"))
    _expect_rejection(lambda: _new_ledger(api, case, opening_cash=D("1E+25")))
    _expect_rejection(lambda: _new_ledger(api, case, start_sequence=True))
    _expect_rejection(lambda: _new_ledger(api, case, start_sequence=1 << 63))

    hostile_exponent = D((0, (1,), 999_999_999))
    _expect_rejection(lambda: _new_ledger(api, case, opening_cash=hostile_exponent))
    accepted_boundary = _new_ledger(api, case, opening_cash=D("1E+24"))
    assert accepted_boundary.balance().cash == D("1E+24")
    lower_exponent_boundary = _new_ledger(api, case, opening_cash=D("1E-24"))
    assert lower_exponent_boundary.balance().cash == D("1E-24")
    _expect_rejection(lambda: _new_ledger(api, case, opening_cash=D("1E-25")))
    _expect_rejection(
        lambda: _new_ledger(api, case, opening_cash=D("1.0000000000000000000000001E24"))
    )


def test_native_identifier_and_money_bounds_are_inclusive_and_one_over_rejects() -> None:
    api = _bt03_api()
    case = _case()
    maximum_money_ledger = _new_ledger(api, case, opening_cash=ZERO)
    maximum_money_event = _obligation_event(
        api,
        maximum_money_ledger,
        event_id="maximum-money-event",
        kind="receivable_create",
        obligation_id="maximum-money-claim",
        amount=D("1E24"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=RESOLUTION_CUTOFF,
    )
    assert maximum_money_ledger.append(maximum_money_event).receivables == D("1E24")

    ledger = _new_ledger(api, case, opening_cash=D("1000"))
    identifier = "i" * 128
    obligation_id = "o" * 128
    smallest_money = D("1E-24")
    minimum_event = api.LedgerEvent.for_obligation(
        event_id=identifier,
        sequence=0,
        previous_hash=_tail(ledger.balance()),
        run_id=case.context.run_id,
        calendar_id=case.bundle.calendar.calendar_id,
        currency="USD",
        kind="receivable_create",
        obligation_id=obligation_id,
        amount=smallest_money,
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=RESOLUTION_CUTOFF,
    )
    minimum_balance = ledger.append(minimum_event)
    assert minimum_balance.receivables == smallest_money
    assert len(minimum_event.event_id.encode("utf-8")) == 128

    before = _snapshot(ledger)
    invalid_factories = (
        lambda: api.LedgerEvent.for_obligation(
            event_id="i" * 129,
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="next-obligation",
            amount=D("1"),
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        ),
        lambda: api.LedgerEvent.for_obligation(
            event_id="next-event-id",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="o" * 129,
            amount=D("1"),
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        ),
        lambda: api.LedgerEvent.for_obligation(
            event_id="money-exponent-underflow",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="underflow-claim",
            amount=D("1E-25"),
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        ),
        lambda: api.LedgerEvent.for_obligation(
            event_id="money-magnitude-overflow",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="overflow-claim",
            amount=D("1.0000000000000000000000001E24"),
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        ),
    )
    for factory in invalid_factories:
        _expect_rejection(factory)
        assert _snapshot(ledger) == before

    largest_reachable_coefficient = D("1" + "0" * 48 + "E-24")
    assert len(largest_reachable_coefficient.as_tuple().digits) == 49
    assert largest_reachable_coefficient == D("1E24")
    # The 100-digit coefficient ceiling is shadowed by the tighter money
    # exponent and magnitude bounds; the longest in-range coefficient is 49.
    coefficient_one_over = D("1" + "0" * 48 + "1E-24")
    assert len(coefficient_one_over.as_tuple().digits) == 50
    coefficient_guard_one_over = D("9" * 101)
    _expect_rejection(
        lambda: api.LedgerEvent.for_obligation(
            event_id="coefficient-one-over",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="coefficient-overflow-claim",
            amount=coefficient_one_over,
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        )
    )
    assert _snapshot(ledger) == before
    _expect_rejection(
        lambda: api.LedgerEvent.for_obligation(
            event_id="coefficient-guard-overflow",
            sequence=ledger.balance().next_sequence,
            previous_hash=_tail(ledger.balance()),
            run_id=case.context.run_id,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id="coefficient-guard-overflow-claim",
            amount=coefficient_guard_one_over,
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=RESOLUTION_CUTOFF,
        )
    )
    assert _snapshot(ledger) == before


def test_new_factories_reject_inherited_source_entry_and_byte_overflow() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=ZERO, order_minimum=ZERO)
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    before = _snapshot(ledger)

    bar_snapshot = object.__getattribute__(outcome, "_bar_snapshot")
    fields_set = object.__getattribute__(bar_snapshot, "__pydantic_fields_set__")
    original_fields = set(fields_set)
    callbacks: list[str] = []

    class HostileKey(str):
        def __hash__(self) -> int:
            callbacks.append("hash")
            return str.__hash__(self)

        def __eq__(self, other: object) -> bool:
            callbacks.append("eq")
            return str.__eq__(self, other)

        def __repr__(self) -> str:
            callbacks.append("repr")
            return "source-key-canary"

        def __str__(self) -> str:
            callbacks.append("str")
            return "source-key-canary"

    padding_count = 64 - len(fields_set)
    fields_set.update(f"bt03-source-padding-{index}" for index in range(padding_count))
    hostile = HostileKey("bt03-source-hostile-key")
    fields_set.add(hostile)
    assert len(fields_set) == 65
    callbacks.clear()
    try:
        with pytest.raises((ValueError, TypeError, OverflowError)):
            _fill_event(
                api,
                ledger,
                intent=intent,
                fill=fill,
                case=case,
                outcome=outcome,
                policy=policy,
                event_id="source-metadata-overflow",
            )
        assert callbacks == []
        assert _snapshot(ledger) == before
    finally:
        fields_set.clear()
        fields_set.update(original_fields)

    binding_context = object.__getattribute__(case.binding, "_context_snapshot")
    original_run_id = object.__getattribute__(binding_context, "run_id")
    object.__setattr__(binding_context, "run_id", "x" * 65_537)
    try:
        with pytest.raises((ValueError, TypeError, OverflowError)):
            _fill_event(
                api,
                ledger,
                intent=intent,
                fill=fill,
                case=case,
                outcome=outcome,
                policy=policy,
                event_id="source-byte-overflow",
            )
        assert _snapshot(ledger) == before
    finally:
        object.__setattr__(binding_context, "run_id", original_run_id)

    bundle_snapshot = object.__getattribute__(case.binding, "_bundle_snapshot")
    original_events = object.__getattribute__(bundle_snapshot, "events")
    assert original_events
    oversized_event = original_events[0].model_copy(update={"body": "x" * 65_000})
    object.__setattr__(bundle_snapshot, "events", (oversized_event,) * 33)
    try:
        with pytest.raises((ValueError, TypeError, OverflowError)):
            _fill_event(
                api,
                ledger,
                intent=intent,
                fill=fill,
                case=case,
                outcome=outcome,
                policy=policy,
                event_id="source-aggregate-byte-overflow",
            )
        assert _snapshot(ledger) == before
    finally:
        object.__setattr__(bundle_snapshot, "events", original_events)


def test_fixed_decimal_policy_ignores_ambient_context_and_traps() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    policy = _policy(bt02, half_spread_bps=D("30"), slippage_bps=D("30"))
    intent = bt02_fixtures._intent(bt02, case, quantity=D("3"))
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)

    ordinary = _new_ledger(api, case, opening_cash=D("2000"))
    ordinary_event = _fill_event(
        api,
        ordinary,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="ambient-context-fill",
    )
    ordinary.append(ordinary_event)

    unusual = _new_ledger(api, case, opening_cash=D("2000"))
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_DOWN
        ambient.traps[Inexact] = True
        ambient.traps[Rounded] = True
        unusual_event = _fill_event(
            api,
            unusual,
            intent=intent,
            fill=fill,
            case=case,
            outcome=outcome,
            policy=policy,
            event_id="ambient-context-fill",
        )
        unusual.append(unusual_event)
        assert _snapshot(unusual) == _snapshot(ordinary)


def test_hostile_inputs_do_not_run_callbacks_or_leak_canary_diagnostics() -> None:
    api = _bt03_api()
    case = _case()
    ledger = _new_ledger(api, case)
    callbacks: list[str] = []

    class Opaque:
        def __getattribute__(self, name: str) -> Any:
            if name not in {"__class__", "__slots__"}:
                callbacks.append(f"attribute:{name}")
            raise AssertionError("opaque protocol executed")

        def __iter__(self):
            callbacks.append("iter")
            raise AssertionError("opaque iterator executed")

        def __deepcopy__(self, memo: dict[int, object]) -> Any:
            callbacks.append("deepcopy")
            raise AssertionError("opaque copy executed")

        def __repr__(self) -> str:
            callbacks.append("repr")
            return "bt03-canary-secret"

        def __str__(self) -> str:
            callbacks.append("str")
            return "bt03-canary-secret"

    opaque = Opaque()
    _expect_rejection(
        lambda: api.Ledger(
            run_id=opaque,
            calendar_id=case.bundle.calendar.calendar_id,
            currency="USD",
            opening_cash=D("100"),
            opening_time=OPENING_TIME,
            resolution_cutoff=RESOLUTION_CUTOFF,
        )
    )
    _expect_rejection(lambda: ledger.append(opaque))
    _expect_rejection(lambda: ledger.replay(opaque))
    _expect_rejection(lambda: ledger.replay((opaque,)))
    with pytest.raises((ValueError, TypeError)):
        api.LedgerEvent.for_fill(
            event_id="bad-event",
            sequence=0,
            previous_hash=opaque,
            intent=opaque,
            fill=opaque,
            binding=opaque,
            outcome=opaque,
            policy=opaque,
        )
    _expect_rejection(lambda: api.NAVCalculator().compute(opaque, opaque, opaque))
    _expect_rejection(lambda: api.EligibleMark(binding=opaque, outcome=opaque))
    _expect_rejection(
        lambda: api.AccountingPolicy(
            binding=opaque,
            session_date=date(2024, 7, 3),
            valuation_cutoff=EVENT_OBSERVED_AT,
            archive_cutoff=EVENT_OBSERVED_AT,
            currency="USD",
            mark_source="synthetic-source",
            mark_revision=0,
        )
    )
    _expect_rejection(lambda: api.AccountingInvariant.check(opaque, opaque, opaque))
    assert callbacks == []

    canary = "bt03-canary-secret"

    def malformed_obligation(event_id: str, obligation_id: str) -> BaseException:
        return _expect_rejection(
            lambda: api.LedgerEvent.for_obligation(
                event_id=event_id,
                sequence=0,
                previous_hash="sha256:" + "0" * 64,
                run_id=case.context.run_id,
                calendar_id=case.bundle.calendar.calendar_id,
                currency="USD",
                kind="receivable_create",
                obligation_id=obligation_id,
                amount=D("1"),
                economic_time=EVENT_ECONOMIC_TIME,
                observed_at=EVENT_OBSERVED_AT,
                due_at=EVENT_OBSERVED_AT,
            )
        )

    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        direct = malformed_obligation(f"Authorization: Bearer {canary}", "claim-secret")
        encoded = malformed_obligation(f"Authorization%3A%20Bearer%20{canary}", "claim-secret")
        nested_direct = malformed_obligation(
            "secret-bearing-event", f"claim:Authorization: Bearer {canary}"
        )
        nested_encoded = malformed_obligation(
            "secret-bearing-event", f"claim:Authorization%3A%20Bearer%20{canary}"
        )
    for error in (direct, encoded, nested_direct, nested_encoded):
        exposed = [str(error), repr(error), repr(error.args)]
        for attr in ("__cause__", "__context__"):
            chained = getattr(error, attr, None)
            if chained is not None:
                exposed.extend((str(chained), repr(chained)))
        notes = getattr(error, "__notes__", ())
        if type(notes) in (tuple, list):
            exposed.extend(str(note) for note in notes)
        structured = getattr(error, "errors", None)
        if callable(structured):
            exposed.append(repr(structured()))
        assert all(canary not in text for text in exposed)
    assert observed == []
    assert all(canary not in str(warning.message) for warning in observed)


def test_overlapping_append_and_replay_publish_one_complete_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=ZERO, order_minimum=ZERO)
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="overlap-fill-event",
    )

    validation_entered = Event()
    release_validation = Event()
    replay_entered = Event()
    replay_finished = Event()
    validation_lock = Lock()
    validation_count = 0
    errors: list[BaseException] = []
    results: dict[str, Any] = {}
    original_validate = bt02.FillModel.validate_fill
    original_replay = api.Ledger.replay

    def observe_validation(*args: Any, **kwargs: Any) -> Any:
        nonlocal validation_count
        with validation_lock:
            validation_count += 1
            first_validation = validation_count == 1
        if first_validation:
            validation_entered.set()
            if not release_validation.wait(5):
                raise TimeoutError("test did not release the bounded fill validation pause")
        return original_validate(*args, **kwargs)

    def observe_replay(self: Any, events: tuple[Any, ...]) -> Any:
        replay_entered.set()
        try:
            return original_replay(self, events)
        finally:
            replay_finished.set()

    monkeypatch.setattr(bt02.FillModel, "validate_fill", staticmethod(observe_validation))
    monkeypatch.setattr(api.Ledger, "replay", observe_replay)

    def append_first() -> None:
        try:
            results["append"] = ledger.append(event)
        except BaseException as error:
            errors.append(error)

    def replay_second() -> None:
        try:
            results["replay"] = ledger.replay((event,))
        except BaseException as error:
            errors.append(error)
        finally:
            replay_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(append_first)
        assert validation_entered.wait(5), "append did not reach contextual fill validation"
        second = pool.submit(replay_second)
        try:
            assert replay_entered.wait(5), "the overlapping replay did not start"
            assert not replay_finished.wait(0.05), "replay completed before the in-flight append was released"
        finally:
            release_validation.set()
        first.result(timeout=10)
        second.result(timeout=10)

    assert errors == []
    assert results.keys() == {"append", "replay"}
    assert all(result.event_count == 1 for result in results.values())
    result = ledger.balance()
    assert result.event_count == 1
    assert result.cash == D("1900")
    assert result.positions == (("inst-survivor", D("1")),)
    assert ledger.events[0].event_id == "overlap-fill-event"
    assert ledger.events[0].canonical_bytes() == event.canonical_bytes()
    assert _snapshot(ledger)[0] == result


def test_same_thread_reentrant_public_mutation_rejects_before_nested_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=ZERO, order_minimum=ZERO)
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    outer_event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="outer-reentrant-fill",
    )
    nested_event = _obligation_event(
        api,
        ledger,
        event_id="nested-reentrant-claim",
        kind="receivable_create",
        obligation_id="nested-reentrant-claim-id",
        amount=D("1"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=EVENT_OBSERVED_AT,
    )

    validation_entered = Event()
    outer_finished = Event()
    original_validate = bt02.FillModel.validate_fill
    nested_errors: list[BaseException] = []
    nested_results: list[Any] = []
    outer_results: list[Any] = []
    outer_errors: list[BaseException] = []
    reentry_attempted = False

    def reenter_during_validation(*args: Any, **kwargs: Any) -> Any:
        nonlocal reentry_attempted
        validation_entered.set()
        if not reentry_attempted:
            reentry_attempted = True
            try:
                nested_results.append(ledger.append(nested_event))
            except BaseException as error:
                nested_errors.append(error)
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(
        bt02.FillModel, "validate_fill", staticmethod(reenter_during_validation)
    )

    def append_outer() -> None:
        try:
            outer_results.append(ledger.append(outer_event))
        except BaseException as error:
            outer_errors.append(error)
        finally:
            outer_finished.set()

    thread = Thread(target=append_outer, daemon=True)
    thread.start()
    assert validation_entered.wait(5), "outer append did not reach contextual fill validation"
    assert outer_finished.wait(5), "same-thread reentry did not return within the bounded interval"
    thread.join(5)
    assert not thread.is_alive()
    assert outer_errors == []
    assert len(nested_errors) == 1
    assert nested_results == []
    assert len(str(nested_errors[0])) <= 256
    assert "nested-reentrant-claim" not in str(nested_errors[0])
    assert len(outer_results) == 1
    assert outer_results[0].event_count == 1
    assert ledger.balance().event_count == 1
    assert tuple(event.event_id for event in ledger.events) == ("outer-reentrant-fill",)
    assert ledger.balance().cash == D("1900")


def test_append_and_replay_are_pure_under_armed_external_side_effect_observers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="pure-side-effect-fill",
    )
    attempts: list[str] = []

    def deny(name: str) -> Callable[..., Any]:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            attempts.append(name)
            raise AssertionError(f"unexpected side effect: {name}")

        return blocked

    monkeypatch.setattr(builtins, "open", deny("builtins.open"))
    monkeypatch.setattr(pathlib.Path, "open", deny("Path.open"))
    monkeypatch.setattr(socket, "socket", deny("socket.socket"))
    monkeypatch.setattr(socket, "create_connection", deny("socket.create_connection"))
    monkeypatch.setattr(urllib.request, "urlopen", deny("urlopen"))
    monkeypatch.setattr(subprocess, "Popen", deny("subprocess.Popen"))
    monkeypatch.setattr(subprocess, "run", deny("subprocess.run"))
    monkeypatch.setattr(os, "getenv", deny("os.getenv"))
    monkeypatch.setattr(os, "system", deny("os.system"))
    monkeypatch.setattr(zoneinfo, "ZoneInfo", deny("ZoneInfo"))

    balance = ledger.append(event)
    api.AccountingInvariant.check(_new_ledger(api, case).balance(), event, balance)
    replayed = _new_ledger(api, case)
    replayed.replay(ledger.events)
    replayed.balance()
    _nav(api, balance, case, outcome)

    malformed = api.LedgerEvent.for_obligation
    with pytest.raises((ValueError, TypeError)):
        malformed(
            event_id="bad-secret-event",
            sequence=1,
            previous_hash=_tail(balance),
            run_id=balance.run_id,
            calendar_id=balance.calendar_id,
            currency="EUR",
            kind="receivable_create",
            obligation_id="bad-currency-claim",
            amount=D("1"),
            economic_time=outcome.bar.manifest.event_time,
            observed_at=outcome.bar.manifest.ingested_at,
            due_at=outcome.bar.manifest.event_time,
        )
    assert attempts == []


def test_calendar_receipt_order_is_preserved_without_rewriting_economic_time() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    day = case.binding.next_session.session_date
    close = case.bundle.calendar.session(day).close_at
    late_receipt = bt02_fixtures._outcome(
        bt02, case, available_offset_minutes=5, ingestion_offset_minutes=7
    )
    earlier_receipt = bt02_fixtures._outcome(
        bt02,
        case,
        available_offset_minutes=1,
        ingestion_offset_minutes=3,
        source="synthetic-market-earlier-receipt-v1",
    )
    first_intent = bt02_fixtures._intent(
        bt02, case, quantity=D("1"), plan_id="plan-late-receipt"
    )
    second_intent = bt02_fixtures._intent(
        bt02,
        case,
        bar=earlier_receipt.bar,
        quantity=D("1"),
        plan_id="plan-earlier-receipt",
    )
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    first_fill = _make_fill(
        bt02, case, intent=first_intent, outcome=late_receipt, policy=policy
    )
    second_fill = _make_fill(
        bt02, case, intent=second_intent, outcome=earlier_receipt, policy=policy
    )
    assert first_fill.fill_time == second_fill.fill_time == close
    assert first_fill.received_at > second_fill.received_at
    ledger = _new_ledger(api, case, opening_cash=D("1000"))
    first = _fill_event(
        api,
        ledger,
        intent=first_intent,
        fill=first_fill,
        case=case,
        outcome=late_receipt,
        policy=policy,
        event_id="later-observation-first",
    )
    ledger.append(first)
    second = _fill_event(
        api,
        ledger,
        intent=second_intent,
        fill=second_fill,
        case=case,
        outcome=earlier_receipt,
        policy=policy,
        event_id="earlier-observation-second",
    )
    after = ledger.append(second)
    assert after.latest_economic_time == close
    assert after.latest_observation_time == first_fill.received_at
    assert after.positions == (("inst-survivor", D("2")),)


def test_resource_limits_reject_overlength_replay_before_state_changes() -> None:
    api = _bt03_api()
    case = _case()
    at_capacity = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    events = _obligation_chain(api, at_capacity, 4096)
    final = at_capacity.replay(events)
    assert final.event_count == 4096
    assert final.next_sequence == 4096
    assert final.cash == D("4195")
    assert final.receivables == D("0")

    before = _snapshot(at_capacity)
    retry_balance = at_capacity.append(events[0])
    assert retry_balance == before[0]
    assert _snapshot(at_capacity) == before

    one_over_ledger = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    one_over = _obligation_chain(api, one_over_ledger, 4097)
    error = _expect_rejection(lambda: one_over_ledger.replay(one_over))
    assert _result_reason(error) == "resource_limit"
    assert one_over_ledger.balance().event_count == 0


def test_distinct_obligation_cap_includes_fully_settled_identities() -> None:
    api = _bt03_api()
    case = _case()
    ledger = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    due = EVENT_ECONOMIC_TIME + timedelta(days=1)
    events: list[Any] = []
    previous_hash = ledger.balance().genesis_hash

    for index in range(256):
        event = api.LedgerEvent.for_obligation(
            event_id=f"obligation-cap-create-{index:03d}",
            sequence=len(events),
            previous_hash=previous_hash,
            run_id=ledger.balance().run_id,
            calendar_id=ledger.balance().calendar_id,
            currency="USD",
            kind="receivable_create",
            obligation_id=f"obligation-cap-id-{index:03d}",
            amount=D("1"),
            economic_time=EVENT_ECONOMIC_TIME,
            observed_at=EVENT_OBSERVED_AT,
            due_at=due,
        )
        events.append(event)
        previous_hash = _prefix_hash(previous_hash, event.canonical_bytes())

    for index in range(256):
        event = api.LedgerEvent.for_obligation(
            event_id=f"obligation-cap-settle-{index:03d}",
            sequence=len(events),
            previous_hash=previous_hash,
            run_id=ledger.balance().run_id,
            calendar_id=ledger.balance().calendar_id,
            currency="USD",
            kind="receivable_settle",
            obligation_id=f"obligation-cap-id-{index:03d}",
            amount=D("1"),
            economic_time=due,
            observed_at=due,
            due_at=due,
        )
        events.append(event)
        previous_hash = _prefix_hash(previous_hash, event.canonical_bytes())

    final = ledger.replay(tuple(events))
    assert final.event_count == 512
    assert final.receivables == ZERO
    assert final.cash == D("356")
    assert final.recognized_income == D("256")

    one_over = api.LedgerEvent.for_obligation(
        event_id="obligation-cap-settled-one-over",
        sequence=final.next_sequence,
        previous_hash=_tail(final),
        run_id=final.run_id,
        calendar_id=final.calendar_id,
        currency="USD",
        kind="receivable_create",
        obligation_id="obligation-cap-id-256",
        amount=D("1"),
        economic_time=due,
        observed_at=due,
        due_at=due,
    )
    before = _snapshot(ledger)
    error = _expect_rejection(lambda: ledger.append(one_over))
    assert _result_reason(error) == "resource_limit"
    assert _snapshot(ledger) == before


def test_nav_mark_count_boundary_is_checked_before_duplicate_coverage() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=ZERO, order_minimum=ZERO)
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    ledger.append(
        _fill_event(
            api,
            ledger,
            intent=intent,
            fill=fill,
            case=case,
            outcome=outcome,
            policy=policy,
            event_id="mark-cap-position-fill",
        )
    )
    balance = ledger.balance()
    mark = _mark(api, case, outcome)
    accounting_policy = _accounting_policy(
        api,
        case,
        outcome,
        valuation_cutoff=fill.received_at,
        archive_cutoff=fill.received_at,
    )
    before = _snapshot(ledger)

    try:
        at_limit = api.NAVCalculator().compute(balance, (mark,) * 256, accounting_policy)
    except (ValueError, TypeError, OverflowError) as error:
        assert _result_reason(error) != "resource_limit"
    else:
        assert _result_status(at_limit) == "unavailable"
        assert at_limit.value is None
        assert _result_reason(at_limit) != "resource_limit"

    try:
        api.NAVCalculator().compute(balance, (mark,) * 257, accounting_policy)
    except (ValueError, TypeError, OverflowError) as error:
        assert _result_reason(error) == "resource_limit"
    else:
        pytest.fail("a 257th eligible-mark record must exceed the declared item limit")
    assert _snapshot(ledger) == before


def test_late_or_future_fill_and_non_gtc_later_attempts_are_rejected_atomically() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case(extended=True)
    first_day, later_day = date(2024, 7, 3), date(2024, 7, 5)
    first = bt02_fixtures._outcome(bt02, case, session=first_day)
    later = bt02_fixtures._outcome(bt02, case, session=later_day)
    intent = bt02_fixtures._intent(
        bt02,
        case,
        quantity=D("10"),
        time_in_force="day",
        expires_at=case.bundle.calendar.session(later_day).close_at,
    )
    policy = _policy(bt02, fixed_share_cap=D("5"))
    first_fill = _make_fill(
        bt02, case, intent=intent, outcome=first, policy=policy, cap=D("5")
    )
    ledger = _new_ledger(
        api,
        case,
        opening_cash=D("2000"),
        resolution_cutoff=case.bundle.calendar.session(later_day).close_at + timedelta(hours=1),
    )
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=first_fill,
        case=case,
        outcome=first,
        policy=policy,
        event_id="day-terminal-partial",
    )
    ledger.append(event)
    before = _snapshot(ledger)

    # BT-02 validates a single fill; the ledger must preserve its terminal
    # DAY semantics across accepted events and reject a later fabricated fill.
    with pytest.raises((ValueError, TypeError)):
        bt02_fixtures._simulate_direct(
            bt02,
            case,
            intent,
            later,
            remaining=D("5"),
            cumulative=D("5"),
            cash=ledger.balance().cash,
            shares=D("0"),
            cap=D("5"),
            policy=policy,
        )
    assert _snapshot(ledger) == before


def test_invariant_checker_rejects_forged_transition_and_has_fixed_diagnostics() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    intent = bt02_fixtures._intent(bt02, case, quantity=D("1"))
    policy = _policy(bt02, commission_per_share=D("0"), order_minimum=D("0"))
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    ledger = _new_ledger(api, case)
    before = ledger.balance()
    event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="invariant-good-fill",
    )
    after = ledger.append(event)
    assert api.AccountingInvariant.check(before, event, after) is None

    forged_after = copy.deepcopy(after)
    object.__setattr__(forged_after, "cash", after.cash + D("1"))
    error = _expect_rejection(lambda: api.AccountingInvariant.check(before, event, forged_after))
    assert "invariant-good-fill" not in str(error)
    assert "inst-survivor" not in str(error)
    assert _snapshot(ledger)[0] == after


def test_genuine_event_retained_charge_cannot_be_understated() -> None:
    api = _bt03_api()
    case = _case()
    ledger = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    event = _obligation_event(
        api,
        ledger,
        event_id="retained-charge-create",
        kind="receivable_create",
        obligation_id="retained-charge-claim",
        amount=D("3"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=EVENT_OBSERVED_AT + timedelta(days=1),
    )
    valid_retry = _obligation_event(
        api,
        ledger,
        event_id="retained-charge-create",
        kind="receivable_create",
        obligation_id="retained-charge-claim",
        amount=D("3"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=EVENT_OBSERVED_AT + timedelta(days=1),
    )
    event_bytes = event.canonical_bytes()
    retained_charge = event._retained_size
    assert type(retained_charge) is int
    assert retained_charge > len(event_bytes)
    assert valid_retry.canonical_bytes() == event_bytes

    accepted = ledger.append(event)
    assert accepted.event_count == 1
    assert accepted.cash == D("100")
    assert accepted.receivables == D("3")
    accepted_snapshot = _snapshot(ledger)
    assert ledger.append(valid_retry) == accepted
    assert _snapshot(ledger) == accepted_snapshot
    assert ledger.events[0]._retained_size == retained_charge

    object.__setattr__(event, "_retained_size", len(event_bytes))
    _expect_rejection(lambda: event.canonical_bytes())
    assert _snapshot(ledger) == accepted_snapshot
    assert ledger.events[0]._retained_size == retained_charge
    _expect_rejection(lambda: ledger.append(event))
    assert _snapshot(ledger) == accepted_snapshot
    assert ledger.events[0]._retained_size == retained_charge

    append_ledger = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    append_before = _snapshot(append_ledger)
    _expect_rejection(lambda: append_ledger.append(event))
    assert _snapshot(append_ledger) == append_before

    replay_ledger = _new_ledger(
        api,
        case,
        opening_cash=D("100"),
        opening_time=OPENING_TIME,
        resolution_cutoff=RESOLUTION_CUTOFF,
    )
    replay_before = _snapshot(replay_ledger)
    _expect_rejection(lambda: replay_ledger.replay((event,)))
    assert _snapshot(replay_ledger) == replay_before


def test_genuine_balance_rejects_nested_hostiles_before_protocols() -> None:
    api = _bt03_api()
    bt02 = bt02_fixtures._bt02_api()
    case = _case()
    outcome = bt02_fixtures._outcome(bt02, case)
    ledger = _new_ledger(api, case, opening_cash=D("2000"))
    before = ledger.balance()
    obligation = _obligation_event(
        api,
        ledger,
        event_id="balance-hostile-claim-create",
        kind="receivable_create",
        obligation_id="balance-hostile-claim",
        amount=D("10"),
        economic_time=EVENT_ECONOMIC_TIME,
        observed_at=EVENT_OBSERVED_AT,
        due_at=case.bundle.calendar.session(case.binding.next_session.session_date).close_at,
    )
    after_obligation = ledger.append(obligation)
    assert api.AccountingInvariant.check(before, obligation, after_obligation) is None

    intent = bt02_fixtures._intent(
        bt02, case, bar=outcome.bar, quantity=D("1"), plan_id="balance-hostile-fill"
    )
    policy = _policy(bt02, commission_per_share=ZERO, order_minimum=ZERO)
    fill = _make_fill(bt02, case, intent=intent, outcome=outcome, policy=policy)
    fill_event = _fill_event(
        api,
        ledger,
        intent=intent,
        fill=fill,
        case=case,
        outcome=outcome,
        policy=policy,
        event_id="balance-hostile-fill-event",
    )
    genuine_balance = ledger.append(fill_event)
    nav_policy = _accounting_policy(
        api,
        case,
        outcome,
        valuation_cutoff=fill.received_at,
        archive_cutoff=fill.received_at,
    )
    mark = _mark(api, case, outcome)
    good_nav = api.NAVCalculator().compute(genuine_balance, (mark,), nav_policy)
    assert _result_status(good_nav) == "available"
    assert good_nav.value == D("2010")

    owner_snapshot = _snapshot(ledger)
    canary = "bt03-balance-canary-secret"
    callbacks: list[str] = []

    def invoke(name: str) -> None:
        callbacks.append(name)
        raise RuntimeError(canary)

    class HostileDecimal(D):
        def as_tuple(self) -> Any:
            invoke("decimal.as_tuple")

        def __format__(self, format_spec: str) -> str:
            invoke("decimal.format")

        def __repr__(self) -> str:
            invoke("decimal.repr")

        def __str__(self) -> str:
            invoke("decimal.str")

    class HostileIterable:
        def __iter__(self) -> Any:
            invoke("iterable.iter")

        def __eq__(self, other: object) -> bool:
            invoke("iterable.eq")

        def __repr__(self) -> str:
            invoke("iterable.repr")

        def __str__(self) -> str:
            invoke("iterable.str")

    class HostileText(str):
        def __eq__(self, other: object) -> bool:
            invoke("text.eq")

        def __hash__(self) -> int:
            invoke("text.hash")

        def __repr__(self) -> str:
            invoke("text.repr")

        def __str__(self) -> str:
            invoke("text.str")

    def tamper(balance: Any, field: str, value: object) -> Any:
        candidate = copy.deepcopy(balance)
        assert type(candidate) is api.LedgerBalance
        assert candidate is not balance
        object.__setattr__(candidate, field, value)
        return candidate

    def reject_without_protocol(action: Callable[[], object]) -> BaseException:
        error = _expect_rejection(action)
        exposed: list[str] = []
        pending = [error]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if id(current) in seen:
                continue
            seen.add(id(current))
            exposed.extend((str(current), repr(current), repr(current.args)))
            notes = getattr(current, "__notes__", ())
            if type(notes) in (tuple, list):
                exposed.extend(str(note) for note in notes)
            for attribute in ("__cause__", "__context__"):
                chained = getattr(current, attribute, None)
                if chained is not None:
                    pending.append(chained)
        assert all(canary not in text for text in exposed)
        assert callbacks == []
        return error

    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")

        hostile_decimal = tamper(genuine_balance, "cash", HostileDecimal("1900"))
        reject_without_protocol(lambda: hostile_decimal.canonical_bytes())

        hostile_positions = tamper(genuine_balance, "positions", HostileIterable())
        reject_without_protocol(lambda: hostile_positions == genuine_balance)

        hostile_obligations = tamper(genuine_balance, "obligations", HostileIterable())
        reject_without_protocol(lambda: hostile_obligations.canonical_bytes())

        hostile_position_id = tamper(
            genuine_balance,
            "positions",
            ((HostileText("inst-survivor"), D("1")),),
        )
        reject_without_protocol(
            lambda: api.NAVCalculator().compute(hostile_position_id, (mark,), nav_policy)
        )

        hostile_prefix = tamper(
            genuine_balance,
            "prefix_hashes",
            (HostileText(genuine_balance.prefix_hashes[-1]),),
        )
        reject_without_protocol(lambda: hostile_prefix.canonical_bytes())
        reject_without_protocol(lambda: hostile_prefix == genuine_balance)
        reject_without_protocol(lambda: genuine_balance == hostile_prefix)

        saved_witness = genuine_balance._witness
        assert type(saved_witness) is tuple
        assert type(saved_witness[0]) is tuple
        assert len(saved_witness[0]) > 0
        hostile_witness = (
            (HostileIterable(),) + saved_witness[0][1:],
        ) + saved_witness[1:]
        hostile_saved_witness = tamper(genuine_balance, "_witness", hostile_witness)
        assert hostile_saved_witness.prefix_hashes == genuine_balance.prefix_hashes
        assert hostile_saved_witness._prefix_witness is hostile_saved_witness.prefix_hashes
        reject_without_protocol(lambda: hostile_saved_witness.canonical_bytes())
        reject_without_protocol(lambda: hostile_saved_witness == genuine_balance)
        reject_without_protocol(lambda: genuine_balance == hostile_saved_witness)
        reject_without_protocol(
            lambda: api.NAVCalculator().compute(hostile_saved_witness, (mark,), nav_policy)
        )
        reject_without_protocol(
            lambda: api.AccountingInvariant.check(after_obligation, fill_event, hostile_saved_witness)
        )

        pathological_exponent = tamper(
            after_obligation,
            "cash",
            D((0, (1,), 999_999_999)),
        )
        reject_without_protocol(
            lambda: api.AccountingInvariant.check(before, obligation, pathological_exponent)
        )
        reject_without_protocol(lambda: pathological_exponent.canonical_bytes())

    assert observed == []
    assert _snapshot(ledger) == owner_snapshot


def test_returned_balance_nested_obligation_mutation_is_isolated() -> None:
    api = _bt03_api()

    expected_ledger, expected_event = _golden_ledger(api)
    expected_balance = expected_ledger.append(expected_event)
    expected_snapshot = _snapshot(expected_ledger)
    expected_balance_bytes = expected_balance.canonical_bytes()
    expected_event_bytes = tuple(event.canonical_bytes() for event in expected_ledger.events)
    assert expected_balance.event_count == 1
    assert expected_balance.obligations[0].amount_remaining == D("3")

    ledger, event = _golden_ledger(api)
    accepted_balance = ledger.append(event)
    assert accepted_balance.canonical_bytes() == expected_balance_bytes
    assert _snapshot(ledger) == expected_snapshot

    returned_balance = ledger.balance()
    assert returned_balance.canonical_bytes() == expected_balance_bytes
    deep_copy = copy.deepcopy(returned_balance)
    object.__setattr__(deep_copy.obligations[0], "amount_remaining", D("2"))
    _expect_rejection(lambda: deep_copy.canonical_bytes())
    assert returned_balance.canonical_bytes() == expected_balance_bytes

    object.__setattr__(returned_balance.obligations[0], "amount_remaining", D("2"))
    _expect_rejection(lambda: returned_balance.canonical_bytes())
    _expect_rejection(lambda: returned_balance == expected_balance)

    current = ledger.balance()
    assert current.canonical_bytes() == expected_balance_bytes
    assert current == expected_balance
    assert tuple(item.canonical_bytes() for item in ledger.events) == expected_event_bytes
    assert _snapshot(ledger) == expected_snapshot


def test_balance_rejects_rewritten_earlier_prefix_with_unchanged_tail() -> None:
    api = _bt03_api()
    ledger, create_event = _golden_ledger(api)
    after_create = ledger.append(create_event)
    due_at = datetime(2024, 7, 2, 0, 0, tzinfo=UTC)
    settle_event = _obligation_event(
        api,
        ledger,
        event_id="claim-settle-partial-1",
        kind="receivable_settle",
        obligation_id="claim-1",
        amount=D("1"),
        economic_time=due_at,
        observed_at=due_at,
        due_at=due_at,
    )
    after_settlement = ledger.append(settle_event)
    assert api.AccountingInvariant.check(after_create, settle_event, after_settlement) is None
    assert after_settlement.event_count == 2
    assert len(after_settlement.prefix_hashes) == 2
    assert after_settlement.receivables == D("2")

    owner_snapshot = _snapshot(ledger)
    owner_bytes = after_settlement.canonical_bytes()
    original_prefixes = after_settlement.prefix_hashes
    altered_head = "sha256:" + "0" * 64
    assert altered_head != original_prefixes[0]
    altered_prefixes = (altered_head, original_prefixes[-1])
    assert len(altered_prefixes) == len(original_prefixes)
    assert altered_prefixes[-1] == original_prefixes[-1]

    tampered = copy.deepcopy(after_settlement)
    object.__setattr__(tampered, "prefix_hashes", altered_prefixes)
    object.__setattr__(tampered, "_prefix_witness", altered_prefixes)
    assert tampered.event_count == after_settlement.event_count
    assert tampered.prefix_hashes[-1] == after_settlement.prefix_hashes[-1]

    _expect_rejection(lambda: tampered.canonical_bytes())
    _expect_rejection(lambda: tampered == after_settlement)
    _expect_rejection(
        lambda: api.AccountingInvariant.check(after_create, settle_event, tampered)
    )

    current = ledger.balance()
    assert current.canonical_bytes() == owner_bytes
    assert current == after_settlement
    assert _snapshot(ledger) == owner_snapshot
