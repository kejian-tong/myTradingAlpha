"""BT-02 RED contracts for precommitted simulation fills and explicit costs.

The BT-02 surface is imported inside each test body so this module collects on
the BT-01 base and reports an explicit missing-contract RED.
"""

from __future__ import annotations

import base64
import builtins
import hashlib
import importlib
import json
import os
import socket
import subprocess
import sys
import urllib.request
import warnings
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, Inexact, InvalidOperation, Rounded, localcontext
from itertools import product
from pathlib import Path
from threading import Event, Thread
from types import FrameType, SimpleNamespace
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mytradingalpha.data.bars import AdjustmentBasis, BarFinality, DailyBar
from mytradingalpha.data.calendar import TradingCalendar
from mytradingalpha.data.provenance import SourceManifest
from tests.productionization.backtest import test_clock_events as bt01_fixtures
from tests.productionization.quant import test_signal as quant_fixtures

D = Decimal
ZERO = Decimal("0")
ONE = Decimal("1")
TEN = Decimal("10")
HUNDRED = Decimal("100")
CAP_DEFAULT = Decimal("100")
CASH_DEFAULT = Decimal("2000")
RATE_DEFAULT = Decimal("30")
COMMISSION_DEFAULT = Decimal("0.1")
INTENT_DOMAIN = b"mytradingalpha:bt02:intent:v1\0"
FILL_DOMAIN = b"mytradingalpha:bt02:fill:v1\0"
EXPECTED_GOLDEN_INTENT_ID = (
    "bt02-intent:1648d776e9052bb30afd9b2fbea72da1689097908e2595e9e59dafc6a47b75f1"
)
EXPECTED_GOLDEN_INTENT_HASH = (
    "sha256:47dbaa460993de9b91e277b813d24edea0393d3913879754b069a6b10ef0f1bf"
)
EXPECTED_GOLDEN_FILL_ID = (
    "bt02-fill:7a1bf97d40b89c743c82372fe9bf7296c4198b288c33e310a928e5163097d570"
)
EXPECTED_GOLDEN_INTENT_JSON = "".join(
    (
        '{"calendar_id":"calendar-golden","created_at":"2024-07-02T20:00:00Z",',
        '"currency":"USD","decision_event_id":"bt01-event:',
        "a" * 64,
        '","decision_time":"2024-07-02T20:00:00Z",',
        '"earliest_submit_time":"2024-07-03T13:30:00Z",',
        '"envelope_id":"signal-envelope:',
        "b" * 64,
        '","execution_authority":"simulation_only",',
        '"expires_at":"2024-07-03T17:00:00Z",',
        '"first_session_date":"2024-07-03","instrument_id":"inst-golden",',
        '"limit_price":null,"order_type":"market","outcome_revision":0,',
        '"outcome_source":"synthetic-market-v1","plan_id":"plan-golden",',
        '"quantity":"10","risk_decision_id":"risk-golden",',
        '"risk_policy_version":"risk-policy-v1","run_id":"run-bt02-golden",',
        '"schema_version":"v1","side":"buy","source_fingerprint":"sha256:',
        "c" * 64,
        '","time_in_force":"day","variant_id":"variant-golden"}',
    )
)
EXPECTED_GOLDEN_INTENT_FULL_JSON = EXPECTED_GOLDEN_INTENT_JSON.replace(
    '"limit_price":', f'"intent_id":"{EXPECTED_GOLDEN_INTENT_ID}","limit_price":', 1
)
EXPECTED_GOLDEN_FILL_JSON = "".join(
    (
        '{"bar_id":"bar-golden-2024-07-03-r0","calendar_id":"calendar-golden",',
        '"cost_breakdown":{"adv":null,"adv_status":"unavailable",',
        '"capacity":null,"capacity_status":"unavailable",',
        '"commission_per_share":"0.1","half_spread_bps":"30",',
        '"impact":null,"impact_status":"unavailable",',
        '"order_minimum":"0.2","slippage":"0.6","slippage_bps":"30",',
        '"spread":"0.6"},"cost_policy_hash":"sha256:',
        "d" * 64,
        '","cost_policy_version":"golden-cost-v1",',
        '"cumulative_quantity_after":"2","cumulative_quantity_before":"0",',
        '"currency":"USD","decision_event_id":"bt01-event:',
        "a" * 64,
        '","envelope_id":"signal-envelope:',
        "b" * 64,
        '","execution_authority":"simulation_only","fee":"0.2",',
        '"fee_policy_id":"bt02-usd-cumulative-v1",',
        '"fill_time":"2024-07-03T17:00:00Z","instrument_id":"inst-golden",',
        '"intent_hash":"sha256:47dbaa460993de9b91e277b813d24edea0393d3913879754b069a6b10ef0f1bf",',
        '"intent_id":"bt02-intent:1648d776e9052bb30afd9b2fbea72da1689097908e2595e9e59dafc6a47b75f1",',
        '"liquidity":"simulated",',
        '"manifest_id":"manifest-golden-2024-07-03-r0",',
        '"outcome_hash":"sha256:',
        "f" * 64,
        '","outcome_revision":0,"outcome_source":"synthetic-market-v1",',
        '"price":"100.6","quantity":"2",',
        '"received_at":"2024-07-03T17:03:00Z","reference_price":"100",',
        '"run_id":"run-bt02-golden","schema_version":"v1",',
        '"session_date":"2024-07-03","side":"buy",',
        '"source_checksum":"sha256:',
        "e" * 64,
        '","source_fingerprint":"sha256:',
        "c" * 64,
        '","variant_id":"variant-golden"}',
    )
)
EXPECTED_GOLDEN_FILL_FULL_JSON = EXPECTED_GOLDEN_FILL_JSON.replace(
    '"fill_time":', f'"fill_id":"{EXPECTED_GOLDEN_FILL_ID}","fill_time":', 1
)


def _bt02_api() -> SimpleNamespace:
    """Load the exact first-use contract and simulator API at test execution."""

    try:
        contracts = importlib.import_module("mytradingalpha.contracts.orders")
        costs = importlib.import_module("mytradingalpha.backtest.costs")
        fills = importlib.import_module("mytradingalpha.backtest.fills")
        orders = importlib.import_module("mytradingalpha.backtest.orders")
        return SimpleNamespace(
            OrderInputError=contracts.OrderInputError,
            OrderIntent=contracts.OrderIntent,
            CostBreakdown=contracts.CostBreakdown,
            Fill=contracts.Fill,
            build_order_intent=contracts.build_order_intent,
            build_fill=contracts.build_fill,
            CostPolicy=costs.CostPolicy,
            CostQuote=costs.CostQuote,
            CostModel=costs.CostModel,
            OutcomeEvidence=fills.OutcomeEvidence,
            FillDecision=fills.FillDecision,
            SimulationResult=fills.SimulationResult,
            FillModel=fills.FillModel,
            Simulator=fills.Simulator,
            SimOrder=orders.SimOrder,
            OrderBook=orders.OrderBook,
        )
    except ModuleNotFoundError as exc:
        if not (exc.name or "").startswith("mytradingalpha"):
            raise
        pytest.fail(f"BT-02 RED: order, fill, and cost contract is missing ({exc.name})")
    except AttributeError as exc:
        pytest.fail(f"BT-02 RED: order, fill, and cost API is incomplete ({exc})")


def _case(*, no_trade: bool = False, run_id: str | None = None) -> SimpleNamespace:
    if no_trade:
        context, bundle, envelope = bt01_fixtures._research_inputs()
        from mytradingalpha.quant.envelope import combine_quant_overlay
        from mytradingalpha.quant.variants import VariantRegistry
        from tests.productionization.research import test_overlay as research_fixtures

        no_trade_overlay = research_fixtures._load_sig04().LLMOverlay.model_validate(
            research_fixtures._candidate(
                envelope.note,
                envelope.quant,
                multiplier="0",
            )
        )
        registry = VariantRegistry().register(context.variant_id, kind="quant_llm")
        envelope = combine_quant_overlay(
            envelope.quant,
            context=context,
            registry=registry,
            note=envelope.note,
            overlay=no_trade_overlay,
        )
    else:
        context, bundle, envelope = bt01_fixtures._quant_only_inputs(
            run_id=run_id or "run-bt02-fixture"
        )
    bt01 = bt01_fixtures._bt_api()
    binding = bt01.SessionClock.bind(context, bundle, envelope)
    decision, opportunity = bt01.BacktestRunner().run((binding,))
    return SimpleNamespace(
        context=context,
        bundle=bundle,
        envelope=envelope,
        binding=binding,
        decision=decision,
        opportunity=opportunity,
    )


def _case_for_bundle(
    *,
    bundle: Any,
    run_id: str,
    variant_id: str,
    decision_time: str,
    earliest_execution_time: str,
) -> SimpleNamespace:
    context, selected_bundle, envelope = bt01_fixtures._quant_only_inputs(
        bundle=bundle,
        decision_time=decision_time,
        earliest_execution_time=earliest_execution_time,
        run_id=run_id,
        variant_id=variant_id,
    )
    bt01 = bt01_fixtures._bt_api()
    binding = bt01.SessionClock.bind(context, selected_bundle, envelope)
    events = bt01.BacktestRunner().run((binding,))
    decision = next(event for event in events if type(event).__name__ == "DecisionEvent")
    opportunity = next(event for event in events if type(event).__name__ == "OpportunityEvent")
    return SimpleNamespace(
        context=context,
        bundle=selected_bundle,
        envelope=envelope,
        binding=binding,
        decision=decision,
        opportunity=opportunity,
    )


def _case_with_five_future_sessions() -> SimpleNamespace:
    calendar_payload = quant_fixtures._calendar().model_dump(mode="python")
    ranges = [dict(item) for item in calendar_payload["coverage_ranges"]]
    for coverage_range in ranges:
        if coverage_range["start"] == date(2024, 6, 28):
            coverage_range["end"] = date(2024, 7, 10)
    schedule = [dict(item) for item in calendar_payload["schedule"]]
    for session_date in (date(2024, 7, 8), date(2024, 7, 9), date(2024, 7, 10)):
        schedule.append(
            {
                "schema_version": "v1",
                "calendar_id": calendar_payload["calendar_id"],
                "session_date": session_date,
                "open_at": datetime.combine(
                    session_date, datetime.min.time(), tzinfo=timezone.utc
                ).replace(hour=13, minute=30),
                "close_at": datetime.combine(
                    session_date, datetime.min.time(), tzinfo=timezone.utc
                ).replace(hour=20),
                "session_type": "regular",
            }
        )
    closures = [dict(item) for item in calendar_payload["closures"]]
    for closure_date in (date(2024, 7, 6), date(2024, 7, 7)):
        closures.append(
            {
                "schema_version": "v1",
                "calendar_id": calendar_payload["calendar_id"],
                "date": closure_date,
                "reason": "weekend",
            }
        )
    calendar_payload.update(
        coverage_ranges=tuple(ranges),
        schedule=tuple(sorted(schedule, key=lambda item: item["session_date"])),
        closures=tuple(sorted(closures, key=lambda item: item["date"])),
        replay_evidence=None,
    )
    calendar = TradingCalendar.model_validate(calendar_payload)
    bundle = quant_fixtures._bundle(
        calendar=calendar,
        cutoff=bt01_fixtures.PRE_CLOSE_CUTOFF,
    )
    context, bundle, envelope = bt01_fixtures._quant_only_inputs(
        bundle=bundle,
        run_id="run-bt02-five-partials",
        earliest_execution_time="2024-07-03T13:30:00Z",
    )
    bt01 = bt01_fixtures._bt_api()
    binding = bt01.SessionClock.bind(context, bundle, envelope)
    decision, opportunity = bt01.BacktestRunner().run((binding,))
    return SimpleNamespace(
        context=context,
        bundle=bundle,
        envelope=envelope,
        binding=binding,
        decision=decision,
        opportunity=opportunity,
    )


def _make_bar(
    case: SimpleNamespace,
    *,
    price: Decimal = HUNDRED,
    session: date | None = None,
    source: str = "synthetic-market-v1",
    revision: int = 0,
    available_offset_minutes: int = 1,
    ingestion_offset_minutes: int = 3,
    finality: BarFinality = BarFinality.FINAL,
    adjustment_basis: AdjustmentBasis = AdjustmentBasis.UNADJUSTED,
) -> DailyBar:
    selected_session = session or case.binding.next_session.session_date
    close = case.bundle.calendar.session(selected_session).close_at
    available_at = close + timedelta(minutes=available_offset_minutes)
    fetched_at = available_at + timedelta(minutes=1)
    ingested_at = max(
        fetched_at,
        close + timedelta(minutes=ingestion_offset_minutes),
    )
    manifest = SourceManifest(
        schema_version="v1",
        manifest_id=f"{source}-{selected_session.isoformat()}-r{revision}",
        source=source,
        source_locator=f"fixture://bt02/bars/{source}/{selected_session.isoformat()}/r{revision}",
        fetched_at=fetched_at,
        event_time=close,
        published_at=None,
        available_at=available_at,
        ingested_at=ingested_at,
        checksum="sha256:" + hashlib.sha256(
            f"{source}:{selected_session.isoformat()}:r{revision}".encode()
        ).hexdigest(),
        terms="synthetic BT-02 fixture",
        revision=revision,
    )
    version = (
        "vendor-adjusted-v1"
        if adjustment_basis is AdjustmentBasis.PROVIDER_ADJUSTED
        else None
    )
    return DailyBar(
        schema_version="v1",
        bar_id=(
            f"bar-inst-survivor-{source}-{selected_session.isoformat()}-"
            f"{adjustment_basis.value}-{version or 'none'}-r{revision}"
        ),
        instrument_id="inst-survivor",
        calendar_id=case.bundle.calendar.calendar_id,
        session_date=selected_session,
        interval="1d",
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1_000_000,
        adjustment_basis=adjustment_basis,
        adjustment_version=version,
        finality=finality,
        manifest=manifest,
    )


def _outcome(
    api: SimpleNamespace,
    case: SimpleNamespace,
    *,
    bar: DailyBar | None = None,
    price: Decimal = HUNDRED,
    session: date | None = None,
    source: str = "synthetic-market-v1",
    revision: int = 0,
    outcome_cutoff: datetime | None = None,
    archive_cutoff: datetime | None = None,
    available_offset_minutes: int = 1,
    ingestion_offset_minutes: int = 3,
) -> Any:
    captured_bar = bar or _make_bar(
        case,
        price=price,
        session=session,
        source=source,
        revision=revision,
        available_offset_minutes=available_offset_minutes,
        ingestion_offset_minutes=ingestion_offset_minutes,
    )
    close = case.bundle.calendar.session(captured_bar.session_date).close_at
    return api.OutcomeEvidence(
        captured_bar,
        outcome_cutoff=outcome_cutoff or close + timedelta(hours=1),
        archive_cutoff=archive_cutoff or close + timedelta(hours=1),
        replay_policy=case.bundle.replay_policy,
    )


def _policy(
    api: SimpleNamespace,
    *,
    half_spread_bps: Decimal = RATE_DEFAULT,
    slippage_bps: Decimal = RATE_DEFAULT,
    commission_per_share: Decimal = COMMISSION_DEFAULT,
    order_minimum: Decimal = ONE,
    fixed_share_cap: Decimal = CAP_DEFAULT,
    lot_size: Decimal = ONE,
    **updates: object,
) -> Any:
    fields: dict[str, object] = {
        "schema_version": "v1",
        "policy_version": "bt02-fixture-policy-v1",
        "numeric_policy_version": "bt02-decimal-v1",
        "fee_policy_id": "bt02-usd-cumulative-v1",
        "currency": "USD",
        "half_spread_bps": half_spread_bps,
        "slippage_bps": slippage_bps,
        "commission_per_share": commission_per_share,
        "order_minimum": order_minimum,
        "fixed_share_cap": fixed_share_cap,
        "lot_size": lot_size,
    }
    fields.update(updates)
    return api.CostPolicy(**fields)


def _intent(
    api: SimpleNamespace,
    case: SimpleNamespace,
    *,
    bar: DailyBar | None = None,
    side: str = "buy",
    quantity: Decimal = TEN,
    order_type: str = "market",
    limit_price: Decimal | None = None,
    time_in_force: str = "day",
    earliest_submit_time: datetime | None = None,
    expires_at: datetime | None = None,
    created_at: datetime | None = None,
    **updates: object,
) -> Any:
    selected_bar = bar or _make_bar(case)
    fields: dict[str, object] = {
        "schema_version": "v1",
        "run_id": case.context.run_id,
        "instrument_id": case.envelope.quant.instrument_id,
        "calendar_id": case.bundle.calendar.calendar_id,
        "variant_id": case.context.variant_id,
        "decision_event_id": case.decision.event_id,
        "envelope_id": case.envelope.envelope_id,
        "source_fingerprint": case.decision.source_fingerprint,
        "currency": "USD",
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "limit_price": limit_price,
        "first_session_date": case.binding.next_session.session_date,
        "decision_time": case.context.decision_time,
        "created_at": created_at or case.context.decision_time,
        "earliest_submit_time": earliest_submit_time or case.context.earliest_execution_time,
        "expires_at": expires_at or case.binding.next_session.close_at,
        "time_in_force": time_in_force,
        "plan_id": "plan-bt02-fixture",
        "risk_decision_id": "risk-bt02-fixture",
        "risk_policy_version": "risk-policy-bt02-fixture-v1",
        "outcome_source": selected_bar.manifest.source,
        "outcome_revision": selected_bar.manifest.revision,
        "execution_authority": "simulation_only",
    }
    fields.update(updates)
    return api.build_order_intent(**fields)


def _quote(
    api: SimpleNamespace,
    policy: Any,
    *,
    price: Decimal = HUNDRED,
    side: str = "buy",
    quantity: Decimal = TEN,
    cumulative: Decimal | None = None,
) -> Any:
    return api.CostModel().quote(
        reference_price=price,
        side=side,
        filled_quantity=quantity,
        cumulative_quantity=cumulative if cumulative is not None else quantity,
        policy=policy,
    )


def _simulate_direct(
    api: SimpleNamespace,
    case: SimpleNamespace,
    intent: Any,
    outcome: Any,
    policy: Any,
    *,
    cash: Decimal = CASH_DEFAULT,
    shares: Decimal = TEN,
    cap: Decimal = CAP_DEFAULT,
    remaining: Decimal | None = None,
    cumulative: Decimal = ZERO,
) -> Any:
    return api.FillModel().simulate(
        intent,
        outcome,
        remaining_quantity=remaining if remaining is not None else intent.quantity,
        cash_available=cash,
        shares_available=shares,
        cap_remaining=cap,
        policy=policy,
        binding=case.binding,
        session_date=outcome.bar.session_date,
        cumulative_quantity=cumulative,
    )


def _validate_fill_context(
    api: SimpleNamespace,
    case: SimpleNamespace,
    fill: Any,
    intent: Any,
    outcome: Any,
    policy: Any,
    *,
    remaining: Decimal | None = None,
    cumulative: Decimal = ZERO,
) -> Any:
    return api.FillModel().validate_fill(
        fill,
        intent,
        outcome,
        policy,
        binding=case.binding,
        session_date=outcome.bar.session_date,
        remaining_quantity=remaining if remaining is not None else intent.quantity,
        cumulative_quantity=cumulative,
    )


def _run(
    api: SimpleNamespace,
    case: SimpleNamespace,
    intents: tuple[Any, ...],
    outcomes: tuple[Any, ...],
    policy: Any,
    *,
    cash: Decimal = CASH_DEFAULT,
    holdings: tuple[tuple[str, Decimal], ...] = (),
    end_session: date | None = None,
) -> Any:
    return api.Simulator().run(
        (case.binding,),
        intents,
        outcomes,
        policy,
        initial_cash=cash,
        initial_holdings=holdings,
        end_session=end_session or case.binding.next_session.session_date,
    )


def _assert_order_error(api: SimpleNamespace, reason: str, action: Any) -> None:
    with pytest.raises(api.OrderInputError) as captured:
        action()
    actual = getattr(captured.value.reason_code, "value", captured.value.reason_code)
    assert actual == reason
    assert len(str(captured.value)) <= 256


def _assert_order_error_one_of(
    api: SimpleNamespace, reasons: set[str], action: Any
) -> None:
    with pytest.raises(api.OrderInputError) as captured:
        action()
    actual = getattr(captured.value.reason_code, "value", captured.value.reason_code)
    assert actual in reasons
    assert len(str(captured.value)) <= 256


def _status(value: Any) -> str:
    status = getattr(value.status, "value", value.status)
    return str(status)


def _golden_intent_fields() -> dict[str, object]:
    return {
        "schema_version": "v1",
        "run_id": "run-bt02-golden",
        "instrument_id": "inst-golden",
        "calendar_id": "calendar-golden",
        "variant_id": "variant-golden",
        "decision_event_id": "bt01-event:" + "a" * 64,
        "envelope_id": "signal-envelope:" + "b" * 64,
        "source_fingerprint": "sha256:" + "c" * 64,
        "currency": "USD",
        "side": "buy",
        "quantity": D("10.000000"),
        "order_type": "market",
        "limit_price": None,
        "first_session_date": date(2024, 7, 3),
        "decision_time": datetime(2024, 7, 2, 20, tzinfo=timezone.utc),
        "created_at": datetime(2024, 7, 2, 20, tzinfo=timezone.utc),
        "earliest_submit_time": datetime(2024, 7, 3, 13, 30, tzinfo=timezone.utc),
        "expires_at": datetime(2024, 7, 3, 17, tzinfo=timezone.utc),
        "time_in_force": "day",
        "plan_id": "plan-golden",
        "risk_decision_id": "risk-golden",
        "risk_policy_version": "risk-policy-v1",
        "outcome_source": "synthetic-market-v1",
        "outcome_revision": 0,
        "execution_authority": "simulation_only",
    }


def _golden_fill_fields(api: SimpleNamespace) -> dict[str, object]:
    cost = api.CostBreakdown(
        half_spread_bps=D("30"),
        slippage_bps=D("30"),
        commission_per_share=D("0.1"),
        order_minimum=D("0.2"),
        spread=D("0.6"),
        slippage=D("0.6"),
        impact=None,
        impact_status="unavailable",
        adv=None,
        adv_status="unavailable",
        capacity=None,
        capacity_status="unavailable",
    )
    return {
        "schema_version": "v1",
        "intent_id": EXPECTED_GOLDEN_INTENT_ID,
        "intent_hash": EXPECTED_GOLDEN_INTENT_HASH,
        "run_id": "run-bt02-golden",
        "instrument_id": "inst-golden",
        "calendar_id": "calendar-golden",
        "variant_id": "variant-golden",
        "decision_event_id": "bt01-event:" + "a" * 64,
        "envelope_id": "signal-envelope:" + "b" * 64,
        "source_fingerprint": "sha256:" + "c" * 64,
        "currency": "USD",
        "side": "buy",
        "quantity": D("2"),
        "cumulative_quantity_before": D("0"),
        "cumulative_quantity_after": D("2"),
        "price": D("100.6"),
        "reference_price": D("100"),
        "fee": D("0.2"),
        "cost_breakdown": cost,
        "cost_policy_version": "golden-cost-v1",
        "cost_policy_hash": "sha256:" + "d" * 64,
        "fee_policy_id": "bt02-usd-cumulative-v1",
        "bar_id": "bar-golden-2024-07-03-r0",
        "manifest_id": "manifest-golden-2024-07-03-r0",
        "outcome_source": "synthetic-market-v1",
        "outcome_revision": 0,
        "source_checksum": "sha256:" + "e" * 64,
        "outcome_hash": "sha256:" + "f" * 64,
        "session_date": date(2024, 7, 3),
        "fill_time": datetime(2024, 7, 3, 17, tzinfo=timezone.utc),
        "received_at": datetime(2024, 7, 3, 17, 3, tzinfo=timezone.utc),
        "execution_authority": "simulation_only",
        "liquidity": "simulated",
    }


def test_bt02_first_use_surface_is_available_with_stable_owners() -> None:
    api = _bt02_api()
    assert api.OrderInputError
    assert api.OrderIntent
    assert api.CostBreakdown
    assert api.Fill
    assert api.CostPolicy
    assert api.CostQuote
    assert api.CostModel
    assert api.OutcomeEvidence
    assert api.FillDecision
    assert api.SimulationResult
    assert api.FillModel
    assert api.Simulator
    assert api.SimOrder
    assert api.OrderBook
    assert callable(api.FillModel.validate_fill)


def test_adverse_buy_and_sell_quotes_pin_price_fee_and_attribution() -> None:
    api = _bt02_api()
    policy = _policy(api)
    buy = _quote(api, policy, side="buy")
    sell = _quote(api, policy, side="sell")

    assert buy.price == D("100.6")
    assert sell.price == D("99.4")
    assert buy.fee == sell.fee == D("1.00")
    assert buy.cost_breakdown.spread == sell.cost_breakdown.spread == D("3.0")
    assert buy.cost_breakdown.slippage == sell.cost_breakdown.slippage == D("3.0")
    assert buy.cost_breakdown.impact is None
    assert buy.policy_version == policy.policy_version
    assert buy.policy_hash == policy.policy_hash


@pytest.mark.parametrize(
    ("side", "cash", "holdings", "expected_cash", "expected_delta", "expected_price"),
    (
        ("buy", D("2000"), (), D("993"), D("-1007"), D("100.6")),
        ("sell", D("0"), (("inst-survivor", D("10")),), D("993"), D("993"), D("99.4")),
    ),
)
def test_fill_cash_delta_posts_adverse_price_and_fee_once(
    side: str,
    cash: Decimal,
    holdings: tuple[tuple[str, Decimal], ...],
    expected_cash: Decimal,
    expected_delta: Decimal,
    expected_price: Decimal,
) -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case)
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar, side=side)
    policy = _policy(api)

    result = _run(api, case, (intent,), (outcome,), policy, cash=cash, holdings=holdings)
    fill = result.fills[0]
    assert fill.price == expected_price
    assert fill.fee == D("1.00")
    assert result.cash == expected_cash
    assert result.cash - cash == expected_delta
    assert result.accounting_basis == "retrospective_simulation"
    assert fill.cost_breakdown.spread + fill.cost_breakdown.slippage == D("6.0")
    assert not {
        "broker_order_id",
        "approval_id",
        "dispatch_id",
        "acknowledgement_id",
    } & set(fill.model_dump(mode="json"))


def test_limit_equality_is_marketable_and_friction_is_never_clipped() -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    policy = _policy(api)

    buy_equal = _intent(
        api, case, order_type="limit", limit_price=D("100.6"), side="buy"
    )
    buy_roomy = _intent(api, case, order_type="limit", limit_price=D("110"), side="buy")
    sell_equal = _intent(
        api, case, order_type="limit", limit_price=D("99.4"), side="sell"
    )
    sell_roomy = _intent(api, case, order_type="limit", limit_price=D("90"), side="sell")

    for intent, expected in (
        (buy_equal, D("100.6")),
        (buy_roomy, D("100.6")),
        (sell_equal, D("99.4")),
        (sell_roomy, D("99.4")),
    ):
        decision = _simulate_direct(api, case, intent, outcome, policy)
        assert _status(decision) == "filled"
        assert decision.fill.price == expected

    for intent in (
        _intent(api, case, order_type="limit", limit_price=D("100.59"), side="buy"),
        _intent(api, case, order_type="limit", limit_price=D("99.41"), side="sell"),
    ):
        decision = _simulate_direct(api, case, intent, outcome, policy)
        assert _status(decision) == "no_fill"
        assert decision.fill is None


def test_next_early_close_is_economic_time_and_late_resolution_is_receipt_time() -> None:
    api = _bt02_api()
    case = _case()
    assert case.binding.next_session.session_type.value == "early_close"
    outcome = _outcome(api, case)
    intent = _intent(api, case)
    result = _run(api, case, (intent,), (outcome,), _policy(api))
    fill = result.fills[0]

    assert fill.session_date == date(2024, 7, 3)
    assert fill.fill_time == case.binding.next_session.close_at
    assert fill.received_at == outcome.bar.manifest.ingested_at
    assert fill.received_at > fill.fill_time
    assert case.decision.economic_time < fill.fill_time
    assert case.decision.observed_at < fill.received_at


@pytest.mark.parametrize(
    ("submit_point", "expiry_delta", "expected"),
    (
        ("minimum", timedelta(0), "filled"),
        ("close", timedelta(0), "filled"),
        ("after_close", timedelta(hours=1), "no_fill"),
        ("minimum", -timedelta(microseconds=1), "no_fill"),
        ("before_minimum", timedelta(0), "invalid"),
    ),
)
def test_submit_and_expiry_equality_and_microsecond_edges(
    submit_point: str, expiry_delta: timedelta, expected: str
) -> None:
    api = _bt02_api()
    case = _case()
    close = case.binding.next_session.close_at
    outcome = _outcome(api, case)
    earliest = {
        "minimum": case.context.earliest_execution_time,
        "close": close,
        "after_close": close + timedelta(microseconds=1),
        "before_minimum": case.context.earliest_execution_time
        - timedelta(microseconds=1),
    }[submit_point]
    expiry = close + expiry_delta
    intent = _intent(
        api,
        case,
        earliest_submit_time=earliest,
        expires_at=expiry,
    )
    if expected == "invalid":
        _assert_order_error(
            api,
            "intent_invalid",
            lambda: _simulate_direct(api, case, intent, outcome, _policy(api)),
        )
    else:
        decision = _simulate_direct(api, case, intent, outcome, _policy(api))
        assert _status(decision) == expected


@pytest.mark.parametrize(
    ("tif", "quantity", "cap", "expected_fills", "expected_status"),
    (
        ("day", D("5"), D("2"), 1, "expired"),
        ("ioc", D("5"), D("2"), 1, "cancelled"),
        ("fok", D("5"), D("2"), 0, "cancelled"),
        ("fok", D("1.5"), D("10"), 0, "cancelled"),
        ("fok", D("2"), D("2"), 1, "filled"),
    ),
)
def test_day_ioc_fok_and_off_lot_fok_are_explicit(
    tif: str,
    quantity: Decimal,
    cap: Decimal,
    expected_fills: int,
    expected_status: str,
) -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    intent = _intent(api, case, quantity=quantity, time_in_force=tif)
    result = _run(
        api,
        case,
        (intent,),
        (outcome,),
        _policy(api, fixed_share_cap=cap),
    )

    assert len(result.fills) == expected_fills
    assert _status(result.orders[0]) == expected_status
    if tif == "fok" and (quantity == D("1.5") or cap < quantity):
        assert result.cash == D("2000")
        assert result.holdings == ()


def test_gtc_retries_only_on_verified_sessions_and_resets_session_cap() -> None:
    api = _bt02_api()
    case = _case()
    first = _outcome(api, case, price=D("90"))
    second_day = date(2024, 7, 5)
    second = _outcome(api, case, price=D("90"), session=second_day)
    intent = _intent(
        api,
        case,
        quantity=D("4"),
        order_type="limit",
        limit_price=D("99"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(second_day).close_at,
    )
    policy = _policy(api, fixed_share_cap=D("2"))

    result = _run(
        api,
        case,
        (intent,),
        (second, first),
        policy,
        end_session=second_day,
    )

    assert tuple(fill.session_date for fill in result.fills) == (
        case.binding.next_session.session_date,
        second_day,
    )
    assert tuple(fill.quantity for fill in result.fills) == (D("2"), D("2"))
    assert result.orders[0].cumulative_quantity == D("4")
    assert _status(result.orders[0]) == "filled"


def test_gtc_retries_after_a_nonmarketable_early_close() -> None:
    api = _bt02_api()
    case = _case()
    first = _outcome(api, case, price=D("100"))
    second_day = date(2024, 7, 5)
    second = _outcome(api, case, price=D("90"), session=second_day)
    intent = _intent(
        api,
        case,
        quantity=D("4"),
        order_type="limit",
        limit_price=D("99"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(second_day).close_at,
    )
    result = _run(
        api,
        case,
        (intent,),
        (first, second),
        _policy(api),
        end_session=second_day,
    )
    assert len(result.fills) == 1
    assert result.fills[0].session_date == second_day
    assert result.fills[0].price == D("90.54")
    assert _status(result.orders[0]) == "filled"


@pytest.mark.parametrize(
    ("partial_count", "cap", "expected_quantities"),
    (
        (2, D("5"), (D("5"), D("5"))),
        (3, D("4"), (D("4"), D("4"), D("2"))),
        (5, D("2"), (D("2"), D("2"), D("2"), D("2"), D("2"))),
    ),
)
def test_simulator_fee_once_golden_counts_two_three_and_five_partials(
    partial_count: int,
    cap: Decimal,
    expected_quantities: tuple[Decimal, ...],
) -> None:
    api = _bt02_api()
    case = _case_with_five_future_sessions()
    session_dates = (
        date(2024, 7, 3),
        date(2024, 7, 5),
        date(2024, 7, 8),
        date(2024, 7, 9),
        date(2024, 7, 10),
    )
    outcomes = tuple(_outcome(api, case, session=day) for day in session_dates)
    intent = _intent(
        api,
        case,
        quantity=D("10"),
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(session_dates[-1]).close_at,
    )
    result = _run(
        api,
        case,
        (intent,),
        outcomes,
        _policy(
            api,
            half_spread_bps=D("0"),
            slippage_bps=D("0"),
            commission_per_share=D("0.1"),
            order_minimum=D("0.2"),
            fixed_share_cap=cap,
        ),
        cash=D("2000"),
        end_session=session_dates[-1],
    )

    assert len(result.fills) == partial_count
    assert tuple(fill.quantity for fill in result.fills) == expected_quantities
    assert sum((fill.fee for fill in result.fills), D("0")) == D("1.00")
    assert result.cash == D("999")
    assert result.holdings == (("inst-survivor", D("10")),)
    assert _status(result.orders[0]) == "filled"


def test_missing_first_eligible_outcome_is_not_skipped_or_filled_for_free() -> None:
    api = _bt02_api()
    case = _case()
    second_day = date(2024, 7, 5)
    late = _outcome(api, case, session=second_day)
    intent = _intent(
        api,
        case,
        time_in_force="gtc",
        expires_at=case.bundle.calendar.session(second_day).close_at,
    )
    _assert_order_error(
        api,
        "outcome_unavailable",
        lambda: _run(
            api,
            case,
            (intent,),
            (late,),
            _policy(api),
            end_session=second_day,
        ),
    )


def test_order_expired_before_attempt_needs_no_outcome_evidence() -> None:
    api = _bt02_api()
    case = _case()
    close = case.binding.next_session.close_at
    intent = _intent(
        api,
        case,
        expires_at=close - timedelta(microseconds=1),
    )
    result = _run(api, case, (intent,), (), _policy(api))
    assert result.fills == ()
    assert _status(result.orders[0]) == "expired"
    assert result.cash == D("2000")


def test_fixed_quantity_cash_holdings_lot_and_zero_cap_never_infer_or_short() -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)

    no_cash = _run(
        api,
        case,
        (_intent(api, case, quantity=D("10")),),
        (outcome,),
        _policy(api, fixed_share_cap=D("0")),
        cash=D("2000"),
    )
    assert no_cash.fills == ()
    assert no_cash.cash == D("2000")
    assert no_cash.holdings == ()

    short_attempt = _run(
        api,
        case,
        (_intent(api, case, side="sell", quantity=D("1")),),
        (outcome,),
        _policy(api),
        cash=D("0"),
    )
    assert short_attempt.fills == ()
    assert short_attempt.holdings == ()
    assert short_attempt.cash == D("0")

    cash_limited = _run(
        api,
        case,
        (_intent(api, case, quantity=D("10")),),
        (outcome,),
        _policy(api),
        cash=D("1006"),
    )
    assert cash_limited.fills[0].quantity == D("9")
    assert cash_limited.cash >= D("0")


def test_partial_quantity_respects_fractional_lot_and_share_cap() -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case, price=D("1"))
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar, quantity=D("2"))
    result = _run(
        api,
        case,
        (intent,),
        (outcome,),
        _policy(
            api,
            half_spread_bps=D("0"),
            slippage_bps=D("0"),
            commission_per_share=D("0"),
            order_minimum=D("0"),
            fixed_share_cap=D("1.3"),
            lot_size=D("0.5"),
        ),
    )
    assert tuple(fill.quantity for fill in result.fills) == (D("1.0"),)
    assert result.holdings == (("inst-survivor", D("1.0")),)


def test_fixed_share_cap_competition_is_canonical_across_input_order() -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    buy = _intent(api, case, side="buy", quantity=D("2"))
    sell = _intent(api, case, side="sell", quantity=D("2"))
    intents = tuple(sorted((buy, sell), key=lambda item: item.intent_id))
    policy = _policy(api, fixed_share_cap=D("3"))
    holdings = (("inst-survivor", D("2")),)

    forward = _run(api, case, intents, (outcome,), policy, holdings=holdings)
    reverse = _run(api, case, tuple(reversed(intents)), (outcome,), policy, holdings=holdings)

    assert tuple(fill.fill_id for fill in forward.fills) == tuple(
        fill.fill_id for fill in reverse.fills
    )
    assert tuple(fill.quantity for fill in forward.fills) == (D("2"), D("1"))
    assert forward.cash == reverse.cash
    assert forward.holdings == reverse.holdings
    assert forward.orders == reverse.orders


def test_cumulative_fee_allocations_pin_two_three_five_and_cent_residuals() -> None:
    api = _bt02_api()
    low_minimum = _policy(
        api,
        commission_per_share=D("0.1"),
        order_minimum=D("0.2"),
    )
    fees = tuple(
        _quote(api, low_minimum, quantity=quantity, cumulative=cumulative).fee
        for quantity, cumulative in ((D("2"), D("2")), (D("3"), D("5")), (D("5"), D("10")))
    )
    assert fees == (D("0.20"), D("0.30"), D("0.50"))
    assert sum(fees, D("0")) == D("1.00")

    minimum_policy = _policy(api, commission_per_share=D("0.1"), order_minimum=D("1"))
    minimum_fees = tuple(
        _quote(api, minimum_policy, quantity=quantity, cumulative=cumulative).fee
        for quantity, cumulative in ((D("2"), D("2")), (D("3"), D("5")), (D("5"), D("10")))
    )
    assert minimum_fees == (D("1.00"), D("0.00"), D("0.00"))

    half_cent = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("0.005"),
        order_minimum=D("0"),
    )
    rounded = tuple(
        _quote(api, half_cent, quantity=quantity, cumulative=cumulative).fee
        for quantity, cumulative in ((D("1"), D("1")), (D("1"), D("2")), (D("1"), D("3")))
    )
    assert rounded == (D("0.00"), D("0.01"), D("0.01"))


def test_prior_minimum_charge_partial_is_not_charged_again_on_a_sale() -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case, price=D("1"))
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar, side="sell", quantity=D("10"))
    policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("0.1"),
        order_minimum=D("2"),
    )

    decision = _simulate_direct(
        api,
        case,
        intent,
        outcome,
        policy,
        cash=D("0"),
        shares=D("8"),
        cap=D("3"),
        remaining=D("8"),
        cumulative=D("2"),
    )
    assert _status(decision) == "filled"
    assert decision.fill.cumulative_quantity_before == D("2")
    assert decision.fill.cumulative_quantity_after == D("5")
    assert decision.fill.fee == D("0.00")
    assert decision.fill.quantity == D("3")


@pytest.mark.parametrize(
    ("cash", "minimum", "commission", "shares", "expected_quantity"),
    (
        (D("0"), D("2"), D("0"), D("2"), D("2")),
        (D("0"), D("2"), D("0"), D("1"), D("0")),
        (D("1"), D("0"), D("2"), D("2"), D("1")),
        (D("10"), D("0"), D("2"), D("100"), D("10")),
    ),
)
def test_conservative_sale_fee_bounds_pin_m3_policy(
    cash: Decimal,
    minimum: Decimal,
    commission: Decimal,
    shares: Decimal,
    expected_quantity: Decimal,
) -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case, price=D("1"))
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar, side="sell", quantity=shares)
    policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=commission,
        order_minimum=minimum,
    )
    result = _run(
        api,
        case,
        (intent,),
        (outcome,),
        policy,
        cash=cash,
        holdings=(("inst-survivor", shares),),
    )
    if expected_quantity == 0:
        assert result.fills == ()
    else:
        assert sum((fill.quantity for fill in result.fills), D("0")) == expected_quantity
    assert result.cash >= D("0")
    assert all(quantity >= D("0") for _, quantity in result.holdings)


def test_sale_cent_rounding_uses_the_fixed_half_cent_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case, price=D("1"))
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar, side="sell", quantity=D("200"))
    policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("1.004"),
        order_minimum=D("0"),
        fixed_share_cap=D("200"),
        lot_size=D("0.001"),
    )
    original_quote = api.CostModel().quote
    quote_calls = 0

    def counted_quote(*args: Any, **kwargs: Any) -> Any:
        nonlocal quote_calls
        quote_calls += 1
        return original_quote(*args, **kwargs)

    monkeypatch.setattr(api.CostModel, "quote", staticmethod(counted_quote))
    decision = _simulate_direct(
        api,
        case,
        intent,
        outcome,
        policy,
        cash=D("0.4005"),
        shares=D("200"),
        cap=D("200"),
    )

    assert _status(decision) == "filled"
    assert decision.fill.quantity == D("98.875")
    assert D("0.4005") + decision.fill.quantity - decision.fill.fee >= D("0")
    assert quote_calls <= 3


@pytest.mark.parametrize(
    "updates",
    (
        {"half_spread_bps": None},
        {"slippage_bps": D("-0.1")},
        {"commission_per_share": D("NaN")},
        {"order_minimum": D("Infinity")},
        {"currency": "EUR"},
        {"schema_version": "v9"},
        {"numeric_policy_version": "bt02-decimal-v99"},
        {"fee_policy_id": "fee-policy-unknown"},
        {"half_spread_bps": D("9999"), "slippage_bps": D("1")},
    ),
)
def test_cost_policy_rejects_missing_negative_nonfinite_currency_and_unknown_versions(
    updates: dict[str, object],
) -> None:
    api = _bt02_api()
    with pytest.raises((api.OrderInputError, ValidationError)):
        _policy(api, **updates)


def test_explicit_zero_cost_policy_is_valid_and_later_costs_remain_unavailable() -> None:
    api = _bt02_api()
    policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("0"),
        order_minimum=D("0"),
    )
    quote = _quote(api, policy)
    assert quote.price == D("100")
    assert quote.fee == D("0.00")
    for name in ("impact", "adv", "capacity"):
        value = getattr(quote.cost_breakdown, name)
        status = getattr(quote.cost_breakdown, f"{name}_status")
        assert value is None
        assert getattr(status, "value", status) == "unavailable"


def test_cost_policy_canonical_bytes_and_hash_are_pinned_independently() -> None:
    api = _bt02_api()
    policy = _policy(
        api,
        half_spread_bps=D("30"),
        slippage_bps=D("30"),
        commission_per_share=D("0.1"),
        order_minimum=D("0.2"),
        fixed_share_cap=D("10"),
        lot_size=D("1"),
        policy_version="golden-cost-v1",
    )
    expected = (
        b'{"commission_per_share":"0.1","currency":"USD",'
        b'"fee_policy_id":"bt02-usd-cumulative-v1","fixed_share_cap":"10",'
        b'"half_spread_bps":"30","lot_size":"1",'
        b'"numeric_policy_version":"bt02-decimal-v1","order_minimum":"0.2",'
        b'"policy_version":"golden-cost-v1","schema_version":"v1",'
        b'"slippage_bps":"30"}'
    )
    expected_hash = "sha256:1477c8032c08aa92f325c4716080834d945bbdef4b133260e1ed34b54d8ea3b9"
    assert policy.canonical_bytes() == expected
    assert policy.policy_hash == expected_hash


def test_decimal_results_ignore_ambient_precision_rounding_and_traps() -> None:
    api = _bt02_api()
    policy = _policy(api)
    case = _case()
    outcome = _outcome(api, case)
    intent = _intent(api, case)

    with localcontext() as hostile:
        hostile.prec = 3
        hostile.rounding = "ROUND_DOWN"
        hostile.traps[Inexact] = True
        hostile.traps[Rounded] = True
        hostile.traps[InvalidOperation] = True
        quote = _quote(api, policy)
        decision = _simulate_direct(api, case, intent, outcome, policy)

    assert quote.price == D("100.6")
    assert quote.fee == D("1.00")
    assert decision.fill.price == D("100.6")
    assert decision.fill.fee == D("1.00")


def test_hostile_decimal_exponents_signed_zero_and_long_scale_reject_boundedly() -> None:
    api = _bt02_api()
    policy = _policy(api)
    hostile_values = (
        D("1E+999999999"),
        D("1E-999999999"),
        D("-0E+999999999"),
        D("-0E-999999999"),
        D("1." + "0" * 2048),
        D("100.0000001"),
    )
    for value in hostile_values:
        _assert_order_error(
            api,
            "numeric_invalid",
            lambda value=value: _quote(api, policy, price=value),
        )
        with pytest.raises((api.OrderInputError, ValidationError, ValueError, TypeError)):
            _policy(api, half_spread_bps=value)

    calls: list[str] = []

    class DecimalTrap(Decimal):
        def as_tuple(self) -> Any:
            calls.append("as_tuple")
            raise AssertionError("subclass Decimal must be rejected before protocol use")

        def __format__(self, spec: str) -> str:
            calls.append("format")
            raise AssertionError("subclass Decimal must be rejected before formatting")

        def as_integer_ratio(self) -> tuple[int, int]:
            calls.append("integer_ratio")
            raise AssertionError("subclass Decimal must be rejected before ratio work")

    subclass_value = DecimalTrap("100")
    _assert_order_error_one_of(
        api,
        {"input_invalid", "numeric_invalid"},
        lambda: _quote(api, policy, price=subclass_value),
    )
    assert calls == []

    zero_policy = _policy(
        api,
        half_spread_bps=D("-0.000000"),
        slippage_bps=D("0E-6"),
        commission_per_share=D("-0"),
        order_minimum=D("0.000000"),
    )
    zero_bytes = zero_policy.canonical_bytes()
    assert b'"half_spread_bps":"0"' in zero_bytes
    assert b'"slippage_bps":"0"' in zero_bytes
    assert b'"commission_per_share":"0"' in zero_bytes


def test_cost_and_state_bounds_are_inclusive_and_reject_one_over() -> None:
    api = _bt02_api()
    case = _case()
    largest_reference = D("1000000000")
    maximum_policy = _policy(
        api,
        half_spread_bps=D("9999"),
        slippage_bps=D("0"),
        commission_per_share=D("0"),
        order_minimum=D("0"),
        fixed_share_cap=D("1000000000"),
        lot_size=D("0.000001"),
    )
    quote = _quote(
        api,
        maximum_policy,
        price=largest_reference,
        quantity=D("1000000000"),
    )
    assert quote.price == D("1999900000")
    assert quote.price <= D("2000000000")
    precise_policy = _policy(
        api,
        half_spread_bps=D("0.000001"),
        slippage_bps=D("0"),
        commission_per_share=D("0"),
        order_minimum=D("0"),
    )
    precise_quote = _quote(
        api,
        precise_policy,
        price=D("1.000000"),
        quantity=D("1"),
    )
    assert precise_quote.price == D("1.0000000001")
    assert max(0, -precise_quote.price.as_tuple().exponent) <= 16

    bad_reference = _quote
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        bad_reference(
            api,
            maximum_policy,
            price=D("1000000000.000001"),
            quantity=D("1"),
        )

    outcome = _outcome(api, case, price=largest_reference)
    intent = _intent(api, case, quantity=D("1000000000"))
    for prior_shares, expected_holding in (
        (D("0"), D("1000000000")),
        (D("999000000000"), D("1000000000000")),
    ):
        starting_holdings = (
            ()
            if prior_shares == 0
            else (("inst-survivor", prior_shares),)
        )
        below_limit = _run(
            api,
            case,
            (intent,),
            (outcome,),
            maximum_policy,
            cash=D("1000000000000000000000000"),
            holdings=starting_holdings,
        )
        assert below_limit.holdings == (("inst-survivor", expected_holding),)

    at_limit = _run(
        api,
        case,
        (),
        (),
        maximum_policy,
        cash=D("1000000000000000000000000"),
        holdings=(("inst-survivor", D("1000000000000")),),
    )
    assert at_limit.cash == D("1000000000000000000000000")
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        _run(
            api,
            case,
            (),
            (),
            maximum_policy,
            cash=D("1000000000000000000000001"),
            holdings=(("inst-survivor", D("1000000000000")),),
        )

    _assert_order_error(
        api,
        "numeric_invalid",
        lambda: _run(
            api,
            case,
            (intent,),
            (outcome,),
            maximum_policy,
            cash=D("1000000000000000000000000"),
            holdings=(("inst-survivor", D("1000000000000")),),
        ),
    )

    one_share_sale = _intent(api, case, side="sell", quantity=D("1"))
    maximum_cash = D("1000000000000000000000000")
    starting_position = (("inst-survivor", D("1")),)
    _assert_order_error(
        api,
        "numeric_invalid",
        lambda: _run(
            api,
            case,
            (one_share_sale,),
            (outcome,),
            maximum_policy,
            cash=maximum_cash,
            holdings=starting_position,
        ),
    )
    assert starting_position == (("inst-survivor", D("1")),)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("finality", BarFinality.PRELIMINARY),
        ("adjustment_basis", AdjustmentBasis.PROVIDER_ADJUSTED),
        ("instrument_id", "inst-other"),
        ("calendar_id", "calendar-other"),
        ("session_date", date(2024, 7, 5)),
    ),
)
def test_outcome_requires_exact_final_unadjusted_source_and_session(
    field: str, value: object
) -> None:
    api = _bt02_api()
    case = _case()
    source = _make_bar(case)
    if field == "session_date":
        candidate = _make_bar(case, session=value)
    else:
        payload = source.model_dump(mode="python")
        payload[field] = value
        if field == "adjustment_basis":
            payload["adjustment_version"] = "vendor-adjusted-v1"
        candidate = DailyBar.model_validate(payload)
    outcome = _outcome(api, case, bar=candidate)
    intent = _intent(api, case, bar=source)
    _assert_order_error(
        api,
        "outcome_invalid",
        lambda: _simulate_direct(api, case, intent, outcome, _policy(api)),
    )


@pytest.mark.parametrize(
    ("available_offset", "ingestion_offset", "archive_offset"),
    (
        (120, 3, 60),
        (1, 120, 60),
    ),
)
def test_outcome_availability_and_archive_ingestion_cutoffs_fail_closed(
    available_offset: int, ingestion_offset: int, archive_offset: int
) -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(
        case,
        available_offset_minutes=available_offset,
        ingestion_offset_minutes=ingestion_offset,
    )
    close = case.bundle.calendar.session(bar.session_date).close_at
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        _outcome(
            api,
            case,
            bar=bar,
            outcome_cutoff=close + timedelta(minutes=60),
            archive_cutoff=close + timedelta(minutes=archive_offset),
        )


def test_outcome_provenance_text_is_bounded_by_utf8_bytes() -> None:
    api = _bt02_api()
    case = _case()
    base = _make_bar(case)
    for field in ("source_locator", "terms"):
        manifest = base.manifest.model_dump(mode="python")
        manifest[field] = "é" * 64
        exact = DailyBar.model_validate(
            {**base.model_dump(mode="python"), "manifest": manifest}
        )
        outcome = _outcome(api, case, bar=exact)
        assert len(getattr(outcome.bar.manifest, field).encode("utf-8")) == 128

        manifest[field] = "é" * 64 + "a"
        over = DailyBar.model_validate(
            {**base.model_dump(mode="python"), "manifest": manifest}
        )
        with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
            _outcome(api, case, bar=over)


def test_outcome_revision_source_selector_and_duplicate_slots_are_enforced() -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case, revision=1)
    outcome = _outcome(api, case, bar=bar)
    stale_selector = _intent(api, case, bar=bar, outcome_revision=0)
    _assert_order_error(
        api,
        "outcome_invalid",
        lambda: _simulate_direct(api, case, stale_selector, outcome, _policy(api)),
    )

    intent = _intent(api, case, bar=bar)
    with pytest.raises(api.OrderInputError) as duplicate:
        _run(api, case, (intent,), (outcome, outcome), _policy(api))
    assert getattr(duplicate.value.reason_code, "value", duplicate.value.reason_code) in {
        "duplicate_outcome",
        "outcome_invalid",
    }


def test_fill_model_refuses_direct_unsealed_daily_bar_ingress() -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case)
    intent = _intent(api, case, bar=bar)
    _assert_order_error(
        api,
        "outcome_invalid",
        lambda: api.FillModel().simulate(
            intent,
            bar,
            remaining_quantity=intent.quantity,
            cash_available=D("2000"),
            shares_available=D("10"),
            cap_remaining=D("100"),
            policy=_policy(api),
            binding=case.binding,
            session_date=bar.session_date,
            cumulative_quantity=D("0"),
        ),
    )


def test_no_trade_binding_cannot_be_promoted_into_a_test_intent() -> None:
    api = _bt02_api()
    case = _case(no_trade=True)
    outcome = _outcome(api, case)
    assert case.envelope.no_trade is True
    intent = _intent(api, case, bar=outcome.bar)
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _run(api, case, (intent,), (outcome,), _policy(api)),
    )


def test_empty_intents_on_valid_no_trade_binding_are_a_pure_noop() -> None:
    api = _bt02_api()
    case = _case(no_trade=True)
    result = _run(
        api,
        case,
        (),
        (),
        _policy(api),
        cash=D("1234.50"),
        holdings=(("inst-survivor", D("3")),),
    )
    assert result.fills == ()
    assert result.cash == D("1234.50")
    assert result.holdings == (("inst-survivor", D("3")),)


def test_order_builder_requires_exact_lineage_and_precommitted_time() -> None:
    api = _bt02_api()
    case = _case()
    fields = {
        "created_at": case.binding.next_session.open_at,
        "decision_event_id": "bt01-event:" + "a" * 64,
        "outcome_source": "synthetic-market-v1",
    }
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _intent(api, case, **fields),
    )
    wrong_run = _intent(api, case, run_id="run-another-cohort")
    outcome = _outcome(api, case)
    _assert_order_error(
        api,
        "binding_mismatch",
        lambda: _simulate_direct(api, case, wrong_run, outcome, _policy(api)),
    )


def test_order_builder_rejects_inconsistent_type_limit_tif_and_authority_fields() -> None:
    api = _bt02_api()
    invalid_updates = (
        {"schema_version": "v9"},
        {"currency": "EUR"},
        {"side": "short"},
        {"order_type": "market", "limit_price": D("100")},
        {"order_type": "limit", "limit_price": None},
        {"order_type": "limit", "limit_price": D("0")},
        {"time_in_force": "fill_or_kill"},
        {"outcome_revision": True},
        {"execution_authority": "broker_dispatch"},
        {
            "expires_at": datetime(2024, 7, 3, 13, 29, tzinfo=timezone.utc),
            "earliest_submit_time": datetime(2024, 7, 3, 13, 30, tzinfo=timezone.utc),
        },
    )
    for update in invalid_updates:
        fields = _golden_intent_fields()
        fields.update(update)
        with pytest.raises((api.OrderInputError, ValidationError, ValueError, TypeError)):
            api.build_order_intent(**fields)


def test_json_ingress_unknown_fields_and_type_adapter_bypass_are_rejected() -> None:
    api = _bt02_api()
    fields = _golden_intent_fields()
    intent = api.build_order_intent(**fields)
    payload = intent.model_dump(mode="python")
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        api.OrderIntent.model_validate({**payload, "surprise": "no"})

    encoded = json.dumps(intent.model_dump(mode="json"))
    for decoder in (
        api.OrderIntent.model_validate_json,
        TypeAdapter(api.OrderIntent).validate_json,
    ):
        with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
            decoder(encoded)

    for bad in (True, 1.0, float("nan"), "1.0"):
        invalid = dict(payload)
        invalid["quantity"] = bad
        invalid.pop("intent_id")
        with pytest.raises((api.OrderInputError, ValidationError, ValueError, TypeError)):
            api.build_order_intent(**invalid)


def test_type_adapter_serialization_rejects_forged_models_without_callbacks() -> None:
    api = _bt02_api()
    valid = api.build_order_intent(**_golden_intent_fields())
    assert api.OrderIntent.model_validate(valid).canonical_bytes() == valid.canonical_bytes()
    assert TypeAdapter(api.OrderIntent).validate_python(valid).canonical_bytes() == valid.canonical_bytes()
    policy = _policy(api)
    assert api.CostPolicy.model_validate(policy).canonical_bytes() == policy.canonical_bytes()
    assert TypeAdapter(api.CostPolicy).validate_python(policy).canonical_bytes() == policy.canonical_bytes()
    fill = api.build_fill(**_golden_fill_fields(api))
    assert api.Fill.model_validate(fill).canonical_bytes() == fill.canonical_bytes()
    assert api.CostBreakdown.model_validate(fill.cost_breakdown).model_dump(mode="python") == fill.cost_breakdown.model_dump(mode="python")
    assert TypeAdapter(api.Fill).validate_python(fill).canonical_bytes() == fill.canonical_bytes()
    assert TypeAdapter(api.CostBreakdown).validate_python(fill.cost_breakdown).model_dump(mode="python") == fill.cost_breakdown.model_dump(mode="python")
    calls: list[str] = []

    class ReprTrap:
        def __repr__(self) -> str:
            calls.append("repr")
            return "BT02_SERIALIZER_CANARY"

    forged = valid.model_copy(update={"quantity": ReprTrap()})
    adapter = TypeAdapter(api.OrderIntent)
    for serialize in (adapter.dump_python, adapter.dump_json):
        calls.clear()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ValueError) as error:
                serialize(forged)
        assert calls == []
        assert caught == []
        _assert_no_secret_echo(error.value, "BT02_SERIALIZER_CANARY", "BT02_SERIALIZER_CANARY")


def test_order_string_and_identifier_bounds_are_inclusive_and_bounded() -> None:
    api = _bt02_api()
    valid = _golden_intent_fields()
    at_limit = dict(valid)
    at_limit["plan_id"] = "p" * 128
    built = api.build_order_intent(**at_limit)
    assert len(built.plan_id.encode("utf-8")) == 128

    for size in (129, 16_385):
        over = dict(valid)
        over["plan_id"] = "p" * size
        with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
            api.build_order_intent(**over)


def test_model_construct_and_model_copy_cannot_bypass_consuming_validation() -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    policy = _policy(api)
    valid = _intent(api, case, bar=outcome.bar)
    forged_copy = valid.model_copy(update={"quantity": D("-1")})
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _simulate_direct(api, case, forged_copy, outcome, policy),
    )

    constructed = api.OrderIntent.model_construct(
        **{**valid.model_dump(mode="python"), "execution_authority": "live"}
    )
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _simulate_direct(api, case, constructed, outcome, policy),
    )


def test_proxy_and_callback_inputs_are_rejected_before_user_protocols() -> None:
    api = _bt02_api()
    case = _case()
    policy = _policy(api)
    intent = _intent(api, case)
    outcome = _outcome(api, case)
    calls: list[str] = []

    class IterableTrap:
        def __iter__(self) -> Any:
            calls.append("iter")
            raise AssertionError("input iterable must not be consumed")

    class TupleTrap(tuple):
        def __iter__(self) -> Any:
            calls.append("tuple-iter")
            raise AssertionError("tuple subclass must not be inspected")

    for overrides in (
        {"intents": IterableTrap()},
        {"outcomes": IterableTrap()},
        {"intents": TupleTrap((intent,))},
    ):
        args = {"intents": (intent,), "outcomes": (outcome,)}
        args.update(overrides)
        with pytest.raises((api.OrderInputError, TypeError, ValueError)):
            api.Simulator().run(
                (case.binding,),
                args["intents"],
                args["outcomes"],
                policy,
                initial_cash=D("2000"),
                initial_holdings=(),
                end_session=case.binding.next_session.session_date,
            )
    assert calls == []


def test_exact_string_decimal_date_timezone_model_key_and_metadata_types() -> None:
    api = _bt02_api()
    case = _case()
    base = _golden_intent_fields()
    calls: list[str] = []

    class StringTrap(str):
        def encode(self, *args: Any, **kwargs: Any) -> bytes:
            del args, kwargs
            calls.append("string-encode")
            raise AssertionError("string subclass protocol invoked")

    class DecimalTrap(Decimal):
        def as_tuple(self) -> Any:
            calls.append("decimal-as-tuple")
            raise AssertionError("Decimal subclass protocol invoked")

        def __format__(self, spec: str) -> str:
            del spec
            calls.append("decimal-format")
            raise AssertionError("Decimal subclass formatting invoked")

        def as_integer_ratio(self) -> tuple[int, int]:
            calls.append("decimal-ratio")
            raise AssertionError("Decimal subclass ratio invoked")

    class DateTrap(date):
        def isoformat(self) -> str:
            calls.append("date-isoformat")
            raise AssertionError("date subclass protocol invoked")

    class TZTrap(tzinfo):
        def utcoffset(self, dt: datetime | None) -> timedelta:
            del dt
            calls.append("timezone-utcoffset")
            raise AssertionError("custom timezone protocol invoked")

        def dst(self, dt: datetime | None) -> timedelta:
            del dt
            calls.append("timezone-dst")
            raise AssertionError("custom timezone protocol invoked")

        def tzname(self, dt: datetime | None) -> str:
            del dt
            calls.append("timezone-name")
            raise AssertionError("custom timezone protocol invoked")

    for field, value in (
        ("run_id", StringTrap("run-string-subclass")),
        ("quantity", DecimalTrap("1")),
        ("first_session_date", DateTrap(2024, 7, 3)),
        (
            "created_at",
            datetime(2024, 7, 2, 20, tzinfo=TZTrap()),
        ),
    ):
        changed = dict(base)
        changed[field] = value
        _assert_order_error_one_of(
            api,
            {"input_invalid", "intent_invalid", "numeric_invalid"},
            lambda changed=changed: api.build_order_intent(**changed),
        )
        assert calls == []

    bar = _make_bar(case)

    class ModelProxy:
        def __getattribute__(self, name: str) -> Any:
            calls.append("model-" + name)
            raise AssertionError("model proxy protocol invoked")

    close = case.bundle.calendar.session(bar.session_date).close_at
    with pytest.raises((api.OrderInputError, ValidationError, TypeError, ValueError)):
        api.OutcomeEvidence(
            ModelProxy(),
            outcome_cutoff=close + timedelta(hours=1),
            archive_cutoff=close + timedelta(hours=1),
            replay_policy=case.bundle.replay_policy,
        )
    assert calls == []

    intent = api.build_order_intent(**base)
    payload = intent.model_dump(mode="python")

    class KeyTrap(str):
        def __hash__(self) -> int:
            calls.append("key-hash")
            return hash(str(self))

        def __eq__(self, other: object) -> bool:
            calls.append("key-equality")
            return str(self) == other

    run_value = payload.pop("run_id")
    dict.__setitem__(payload, KeyTrap("run_id"), run_value)
    calls.clear()
    with pytest.raises((api.OrderInputError, ValidationError, ValueError, TypeError)):
        api.OrderIntent.model_validate(payload)
    assert calls == []

    class ForeignMetadata:
        def __copy__(self) -> object:
            calls.append("metadata-copy")
            return self

        def __deepcopy__(self, memo: object) -> object:
            del memo
            calls.append("metadata-deepcopy")
            return self

        def __iter__(self) -> Any:
            calls.append("metadata-iter")
            raise AssertionError("metadata protocol invoked")

        def __hash__(self) -> int:
            calls.append("metadata-hash")
            return 1

        def __eq__(self, other: object) -> bool:
            del other
            calls.append("metadata-equality")
            return False

    class MetadataSet(set, ForeignMetadata):
        def __copy__(self) -> object:
            return ForeignMetadata.__copy__(self)

        def __iter__(self) -> Any:
            return ForeignMetadata.__iter__(self)

    metadata = MetadataSet(api.OrderIntent.model_fields)
    object.__setattr__(intent, "__pydantic_fields_set__", metadata)
    calls.clear()
    outcome = _outcome(api, case)
    with pytest.raises(api.OrderInputError):
        _simulate_direct(api, case, intent, outcome, _policy(api))
    assert calls == []


def test_malformed_holdings_shapes_primitives_order_and_duplicates_reject() -> None:
    api = _bt02_api()
    case = _case()
    policy = _policy(api)
    malformed = (
        (("inst-z", D("1")), ("inst-a", D("1"))),
        (("inst-a", D("1")), ("inst-a", D("2"))),
        (("inst-survivor", D("-1")),),
        (("inst-survivor", 1.0),),
        (("inst-survivor", True),),
        (("inst-survivor", D("1"), "extra"),),
        (object(),),
    )
    for holdings in malformed:
        _assert_order_error_one_of(
            api,
            {"input_invalid", "numeric_invalid", "resource_limit"},
            lambda holdings=holdings: api.Simulator().run(
                (case.binding,),
                (),
                (),
                policy,
                initial_cash=D("2000"),
                initial_holdings=holdings,
                end_session=case.binding.next_session.session_date,
            ),
        )


def test_redaction_rejects_direct_encoded_secret_in_all_new_string_fields() -> None:
    api = _bt02_api()
    case = _case()
    canary = "secret-canary-BT02-5ac291"
    raw = canary.encode("utf-8")
    fullwidth = canary.translate(
        str.maketrans({chr(code): chr(code + 0xFEE0) for code in range(33, 127)})
    )
    encoded_values = (
        canary,
        "".join(f"%{byte:02X}" for byte in raw),
        "".join(f"\\u{ord(character):04x}" for character in canary),
        base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="),
        raw.hex(),
        fullwidth,
    )
    string_fields = (
        "run_id",
        "instrument_id",
        "calendar_id",
        "variant_id",
        "decision_event_id",
        "envelope_id",
        "source_fingerprint",
        "currency",
        "side",
        "order_type",
        "time_in_force",
        "plan_id",
        "risk_decision_id",
        "risk_policy_version",
        "outcome_source",
        "execution_authority",
    )
    for field in string_fields:
        for encoded in encoded_values:
            changed = _golden_intent_fields()
            changed[field] = encoded
            with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
                api.build_order_intent(**changed)
            _assert_no_secret_echo(error.value, encoded, canary)

    policy_fields = _policy(api).model_dump(mode="python")
    for field in (
        "schema_version",
        "policy_version",
        "numeric_policy_version",
        "fee_policy_id",
        "currency",
    ):
        for encoded in encoded_values:
            changed = dict(policy_fields)
            changed[field] = encoded
            with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
                api.CostPolicy(**changed)
            _assert_no_secret_echo(error.value, encoded, canary)

    fill_fields = _golden_fill_fields(api)
    for field in (
        "schema_version",
        "intent_id",
        "intent_hash",
        "run_id",
        "instrument_id",
        "calendar_id",
        "variant_id",
        "decision_event_id",
        "envelope_id",
        "source_fingerprint",
        "currency",
        "side",
        "cost_policy_version",
        "cost_policy_hash",
        "fee_policy_id",
        "bar_id",
        "manifest_id",
        "outcome_source",
        "source_checksum",
        "outcome_hash",
        "execution_authority",
        "liquidity",
    ):
        for encoded in encoded_values:
            changed = dict(fill_fields)
            changed[field] = encoded
            with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
                api.build_fill(**changed)
            _assert_no_secret_echo(error.value, encoded, canary)

    bar = _make_bar(case)
    for field in (
        "schema_version",
        "manifest_id",
        "source",
        "source_locator",
        "checksum",
        "terms",
    ):
        for encoded in encoded_values:
            manifest = bar.manifest.model_dump(mode="python")
            manifest[field] = encoded
            with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
                hostile_manifest = SourceManifest.model_construct(**manifest)
                bar_fields = bar.model_dump(mode="python")
                bar_fields["manifest"] = hostile_manifest
                changed_bar = DailyBar.model_construct(**bar_fields)
                close = case.bundle.calendar.session(changed_bar.session_date).close_at
                api.OutcomeEvidence(
                    changed_bar,
                    outcome_cutoff=close + timedelta(hours=1),
                    archive_cutoff=close + timedelta(hours=1),
                    replay_policy=case.bundle.replay_policy,
                )
            _assert_no_secret_echo(error.value, encoded, canary)

    for field in (
        "bar_id",
        "instrument_id",
        "calendar_id",
        "interval",
        "adjustment_version",
    ):
        for encoded in encoded_values:
            changed = bar.model_dump(mode="python")
            changed[field] = encoded
            with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
                changed_bar = DailyBar.model_construct(**changed)
                close = case.bundle.calendar.session(changed_bar.session_date).close_at
                api.OutcomeEvidence(
                    changed_bar,
                    outcome_cutoff=close + timedelta(hours=1),
                    archive_cutoff=close + timedelta(hours=1),
                    replay_policy=case.bundle.replay_policy,
                )
            _assert_no_secret_echo(error.value, encoded, canary)

    for encoded in encoded_values:
        valid = api.build_order_intent(**_golden_intent_fields())
        payload = valid.model_dump(mode="python")
        payload[encoded] = canary
        with pytest.raises((api.OrderInputError, ValidationError, ValueError)) as error:
            api.OrderIntent.model_validate(payload)
        _assert_no_secret_echo(error.value, encoded, canary)

    policy = _policy(api)
    outcome = _outcome(api, case, bar=bar)
    valid_fill = api.build_fill(**_golden_fill_fields(api))
    safe_artifacts = (
        valid.model_dump_json(),
        repr(valid),
        policy.canonical_bytes().decode("utf-8"),
        repr(valid_fill),
        outcome.canonical_bytes().decode("utf-8"),
        repr(outcome),
    )
    assert all(canary not in artifact for artifact in safe_artifacts)
    assert outcome.bar.manifest.source_locator not in repr(outcome)
    assert outcome.bar.manifest.terms not in repr(outcome)


def _assert_no_secret_echo(error: BaseException, encoded: str, canary: str) -> None:
    rendered = str(error) + repr(error)
    assert encoded not in rendered
    assert canary not in rendered
    details = getattr(error, "errors", None)
    if callable(details):
        structured = repr(details())
        assert encoded not in structured
        assert canary not in structured


def test_pinned_intent_and_fill_ids_bind_independently_calculated_canonical_bytes() -> None:
    api = _bt02_api()
    expected_intent_bytes = EXPECTED_GOLDEN_INTENT_JSON.encode("utf-8")
    assert hashlib.sha256(INTENT_DOMAIN + expected_intent_bytes).hexdigest() == (
        EXPECTED_GOLDEN_INTENT_ID.removeprefix("bt02-intent:")
    )
    expected_full_intent_bytes = EXPECTED_GOLDEN_INTENT_FULL_JSON.encode("utf-8")
    assert hashlib.sha256(expected_full_intent_bytes).hexdigest() == (
        EXPECTED_GOLDEN_INTENT_HASH.removeprefix("sha256:")
    )
    intent = api.build_order_intent(**_golden_intent_fields())
    assert intent.intent_id == EXPECTED_GOLDEN_INTENT_ID
    assert intent.canonical_bytes() == expected_full_intent_bytes

    expected_fill_bytes = EXPECTED_GOLDEN_FILL_JSON.encode("utf-8")
    assert hashlib.sha256(FILL_DOMAIN + expected_fill_bytes).hexdigest() == (
        EXPECTED_GOLDEN_FILL_ID.removeprefix("bt02-fill:")
    )
    fill = api.build_fill(**_golden_fill_fields(api))
    assert fill.fill_id == EXPECTED_GOLDEN_FILL_ID
    assert fill.intent_hash == EXPECTED_GOLDEN_INTENT_HASH
    assert fill.canonical_bytes() == EXPECTED_GOLDEN_FILL_FULL_JSON.encode("utf-8")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("price", D("100.59")),
        ("fee", D("0.19")),
        ("cumulative_quantity_after", D("3")),
    ),
)
def test_rehashed_fill_with_altered_price_fee_or_cumulative_equation_rejects(
    field: str, value: Decimal
) -> None:
    api = _bt02_api()
    fields = _golden_fill_fields(api)
    fields[field] = value
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        api.build_fill(**fields)


def test_contextual_fill_consumer_rejects_rehashed_links_and_inconsistent_cumulative_state() -> None:
    api = _bt02_api()
    case = _case()
    bar = _make_bar(case)
    outcome = _outcome(api, case, bar=bar)
    intent = _intent(api, case, bar=bar)
    policy = _policy(api)
    original = _simulate_direct(api, case, intent, outcome, policy).fill

    bad_links = (
        ("run_id", "run-other", "binding_mismatch"),
        ("instrument_id", "inst-other", "binding_mismatch"),
        ("calendar_id", "calendar-other", "binding_mismatch"),
        ("variant_id", "variant-other", "binding_mismatch"),
        ("decision_event_id", "bt01-event:" + "9" * 64, "binding_mismatch"),
        ("envelope_id", "signal-envelope:" + "9" * 64, "binding_mismatch"),
        ("source_fingerprint", "sha256:" + "9" * 64, "binding_mismatch"),
        ("intent_id", "bt02-intent:" + "9" * 64, "intent_invalid"),
        ("intent_hash", "sha256:" + "9" * 64, "intent_invalid"),
        ("bar_id", "bar-other", "outcome_invalid"),
        ("manifest_id", "manifest-other", "outcome_invalid"),
        ("outcome_source", "source-other", "outcome_invalid"),
        ("outcome_revision", 1, "outcome_invalid"),
        ("source_checksum", "sha256:" + "9" * 64, "outcome_invalid"),
        ("outcome_hash", "sha256:" + "9" * 64, "outcome_invalid"),
        ("cost_policy_version", "policy-other", "policy_invalid"),
        ("cost_policy_hash", "sha256:" + "9" * 64, "policy_invalid"),
        ("fee_policy_id", "fee-policy-other", "policy_invalid"),
    )
    for field, value, reason in bad_links:
        fields = original.model_dump(mode="python")
        fields.pop("fill_id")
        fields[field] = value
        rehashed_fill = api.build_fill(**fields)
        assert rehashed_fill.fill_id != original.fill_id
        _assert_order_error(
            api,
            reason,
            lambda rehashed_fill=rehashed_fill: _validate_fill_context(
                api, case, rehashed_fill, intent, outcome, policy
            ),
        )

    changed_math = original.model_copy(update={"price": D("101")})
    _assert_order_error(
        api,
        "input_invalid",
        lambda: _validate_fill_context(api, case, changed_math, intent, outcome, policy),
    )
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _validate_fill_context(
            api,
            case,
            original,
            intent,
            outcome,
            policy,
            remaining=D("9"),
        ),
    )
    _assert_order_error(
        api,
        "intent_invalid",
        lambda: _validate_fill_context(
            api,
            case,
            original,
            intent,
            outcome,
            policy,
            remaining=D("8"),
            cumulative=D("2"),
        ),
    )

    authority = _golden_fill_fields(api)
    authority["execution_authority"] = "broker_dispatch"
    with pytest.raises((api.OrderInputError, ValidationError, ValueError)):
        api.build_fill(**authority)


def test_outcome_and_result_are_defensive_and_repeated_runs_are_independent() -> None:
    api = _bt02_api()
    case = _case()
    source = _make_bar(case)
    outcome = _outcome(api, case, bar=source)
    source_close = source.close
    object.__setattr__(source, "close", D("999"))
    assert outcome.bar.close == source_close
    object.__setattr__(source, "close", source_close)
    first_snapshot = outcome.bar
    object.__setattr__(first_snapshot, "close", D("999"))
    assert outcome.bar.close == source.close
    assert outcome.canonical_bytes() == outcome.canonical_bytes()

    intent = _intent(api, case, bar=source)
    policy = _policy(api)
    simulator = api.Simulator()

    def execute(_: int) -> tuple[Any, ...]:
        result = simulator.run(
            (case.binding,),
            (intent,),
            (outcome,),
            policy,
            initial_cash=D("2000"),
            initial_holdings=(),
            end_session=case.binding.next_session.session_date,
        )
        return result.fills, result.cash, result.holdings

    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = tuple(pool.map(execute, range(8)))
    assert all(output == outputs[0] for output in outputs)


@pytest.mark.parametrize("mutation", ("intent_quantity", "model_metadata"))
def test_synchronized_mid_run_mutation_rejects_without_returning_partial_state(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    intent = _intent(api, case)
    policy = _policy(api)
    original_quantity = intent.quantity
    metadata = object.__getattribute__(intent, "__pydantic_fields_set__")
    assert type(metadata) is set
    original_metadata = set(metadata)
    assert len(metadata) <= 64
    paused = Event()
    resume = Event()
    result: list[Any] = []
    errors: list[BaseException] = []
    original_quote = api.CostModel().quote

    def synchronized_quote(*args: Any, **kwargs: Any) -> Any:
        if not paused.is_set():
            paused.set()
            if not resume.wait(5):
                raise TimeoutError("test did not release the bounded quote pause")
        return original_quote(*args, **kwargs)

    def run_simulation() -> None:
        try:
            result.append(_run(api, case, (intent,), (outcome,), policy))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run_simulation, daemon=True)
    with monkeypatch.context() as scoped:
        scoped.setattr(api.CostModel, "quote", staticmethod(synchronized_quote))
        thread.start()
        try:
            assert paused.wait(5), "simulator did not reach its deterministic quote boundary"
            if mutation == "intent_quantity":
                object.__setattr__(intent, "quantity", D("9"))
            else:
                for index in range(257):
                    metadata.add(f"bt02-metadata-growth-{index}")
                assert len(metadata) > 64
            resume.set()
            thread.join(5)
        finally:
            resume.set()
            thread.join(5)
            object.__setattr__(intent, "quantity", original_quantity)
            metadata.clear()
            metadata.update(original_metadata)

    assert not thread.is_alive()
    assert result == []
    assert len(errors) == 1
    assert isinstance(errors[0], api.OrderInputError)
    reason = getattr(errors[0].reason_code, "value", errors[0].reason_code)
    if mutation == "intent_quantity":
        assert reason == "source_changed"
    else:
        assert reason in {"source_changed", "resource_limit", "input_invalid"}
    assert len(str(errors[0])) <= 256


def test_duplicate_intents_and_reordered_valid_inputs_have_explicit_semantics() -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    policy = _policy(api)
    intent = _intent(api, case)
    with pytest.raises(api.OrderInputError) as duplicate:
        _run(api, case, (intent, intent), (outcome,), policy)
    assert getattr(duplicate.value.reason_code, "value", duplicate.value.reason_code) == "duplicate_intent"

    other = _intent(api, case, side="sell", quantity=D("2"))
    intents = tuple(sorted((intent, other), key=lambda item: item.intent_id))
    first = _run(
        api,
        case,
        intents,
        (outcome,),
        _policy(api, fixed_share_cap=D("12")),
        holdings=(("inst-survivor", D("2")),),
    )
    second = _run(
        api,
        case,
        tuple(reversed(intents)),
        (outcome,),
        _policy(api, fixed_share_cap=D("12")),
        holdings=(("inst-survivor", D("2")),),
    )
    assert first.fills == second.fills
    assert first.orders == second.orders


def test_simulator_accepts_distinct_decision_slots_for_the_same_instrument() -> None:
    api = _bt02_api()
    first = _case()
    second = _case_for_bundle(
        bundle=first.bundle,
        run_id=first.context.run_id,
        variant_id=first.context.variant_id,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )
    first_bar = _make_bar(first, session=date(2024, 7, 3))
    second_bar = _make_bar(second, session=date(2024, 7, 5))
    intents = (
        _intent(api, first, bar=first_bar, quantity=D("1")),
        _intent(api, second, bar=second_bar, quantity=D("1")),
    )
    result = api.Simulator().run(
        (first.binding, second.binding),
        intents,
        (
            _outcome(api, first, bar=first_bar),
            _outcome(api, second, bar=second_bar),
        ),
        _policy(api),
        initial_cash=D("2000"),
        initial_holdings=(),
        end_session=date(2024, 7, 5),
    )

    assert tuple(fill.session_date for fill in result.fills) == (
        date(2024, 7, 3),
        date(2024, 7, 5),
    )
    assert tuple(fill.decision_event_id for fill in result.fills) == tuple(
        intent.decision_event_id for intent in intents
    )


def test_simulator_rejects_duplicate_decision_slots() -> None:
    api = _bt02_api()
    case = _case()
    with pytest.raises(api.OrderInputError) as duplicate:
        api.Simulator().run(
            (case.binding, case.binding),
            (),
            (),
            _policy(api),
            initial_cash=D("2000"),
            initial_holdings=(),
            end_session=case.binding.next_session.session_date,
        )
    assert getattr(duplicate.value.reason_code, "value", duplicate.value.reason_code) == "binding_mismatch"


def test_simulator_rejects_same_id_bindings_with_different_calendar_witnesses() -> None:
    api = _bt02_api()
    first = _case()
    calendar_module = importlib.import_module("mytradingalpha.data.calendar")
    calendar_payload = first.bundle.calendar.model_dump(mode="python")
    calendar_payload["replay_evidence"] = None
    calendar_payload["timezone"] = "America/Chicago"
    changed_calendar = TradingCalendar.model_validate(calendar_payload)
    changed_witness = calendar_module.capture_calendar_replay_evidence(changed_calendar)
    changed_calendar = TradingCalendar.model_validate(
        {**changed_calendar.model_dump(mode="python"), "replay_evidence": changed_witness}
    )
    changed_bundle = quant_fixtures._bundle(
        calendar=changed_calendar,
        cutoff=first.bundle.knowledge_cutoff.isoformat(),
    )
    second = _case_for_bundle(
        bundle=changed_bundle,
        run_id=first.context.run_id,
        variant_id=first.context.variant_id,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )

    assert first.bundle.calendar.calendar_id == second.bundle.calendar.calendar_id
    assert first.bundle.calendar.replay_evidence != second.bundle.calendar.replay_evidence
    with pytest.raises(api.OrderInputError) as conflict:
        api.Simulator().run(
            (first.binding, second.binding),
            (),
            (),
            _policy(api),
            initial_cash=D("2000"),
            initial_holdings=(),
            end_session=date(2024, 7, 5),
        )
    assert getattr(conflict.value.reason_code, "value", conflict.value.reason_code) == "binding_mismatch"


def test_cost_quote_search_and_sale_rounding_have_bounded_call_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("0.000001"),
        order_minimum=D("0"),
        fixed_share_cap=D("1000000000"),
        lot_size=D("0.000001"),
    )
    intent = _intent(api, case, quantity=D("1000000000"))
    original_quote = api.CostModel().quote
    quote_calls = 0

    def counted_quote(*args: Any, **kwargs: Any) -> Any:
        nonlocal quote_calls
        quote_calls += 1
        return original_quote(*args, **kwargs)

    monkeypatch.setattr(api.CostModel, "quote", staticmethod(counted_quote))
    decision = _simulate_direct(
        api,
        case,
        intent,
        outcome,
        policy,
        cash=D("1000000000000000000000000"),
        cap=D("1000000000"),
    )
    assert _status(decision) == "filled"
    assert quote_calls <= 64

    sale_policy = _policy(
        api,
        half_spread_bps=D("0"),
        slippage_bps=D("0"),
        commission_per_share=D("2"),
        order_minimum=D("0"),
    )
    sale = _intent(api, case, bar=outcome.bar, side="sell", quantity=D("100"))
    quote_calls = 0
    sale_result = _run(
        api,
        case,
        (sale,),
        (outcome,),
        sale_policy,
        cash=D("10"),
        holdings=(("inst-survivor", D("100")),),
    )
    assert quote_calls <= 3
    assert sale_result.cash >= D("0")


def test_input_collection_and_aggregate_size_limits_fail_before_reduction() -> None:
    api = _bt02_api()
    case = _case()
    intent = _intent(api, case)
    outcome = _outcome(api, case)
    policy = _policy(api)
    with pytest.raises(api.OrderInputError) as oversized:
        api.Simulator().run(
            (case.binding,),
            (intent,) * 257,
            (outcome,),
            policy,
            initial_cash=D("2000"),
            initial_holdings=(),
            end_session=case.binding.next_session.session_date,
        )
    assert getattr(oversized.value.reason_code, "value", oversized.value.reason_code) == "resource_limit"

    with pytest.raises(api.OrderInputError) as over_outcomes:
        api.Simulator().run(
            (case.binding,),
            (intent,),
            (outcome,) * 4097,
            policy,
            initial_cash=D("2000"),
            initial_holdings=(),
            end_session=case.binding.next_session.session_date,
        )
    assert getattr(over_outcomes.value.reason_code, "value", over_outcomes.value.reason_code) == "resource_limit"


def test_simulator_denies_file_process_environment_network_and_timezone_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    intent = _intent(api, case, bar=outcome.bar)
    policy = _policy(api)
    attempted: list[str] = []

    def denied(name: str) -> Any:
        def fail(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            attempted.append(name)
            raise AssertionError(f"BT-02 attempted forbidden {name} access")

        return fail

    monkeypatch.setattr(builtins, "open", denied("file"))
    monkeypatch.setattr(Path, "open", denied("path"))
    monkeypatch.setattr(subprocess, "Popen", denied("process"))
    monkeypatch.setattr(subprocess, "run", denied("process"))
    monkeypatch.setattr(os, "system", denied("process"))
    monkeypatch.setattr(os, "getenv", denied("environment"))

    class EnvironmentTrap(dict[str, str]):
        def __getitem__(self, key: str) -> str:
            del key
            return denied("environment")()

        def get(self, key: str, default: Any = None) -> Any:
            del key, default
            return denied("environment")()

        def __iter__(self) -> Any:
            return denied("environment")()

        def items(self) -> Any:
            return denied("environment")()

    monkeypatch.setattr(os, "environ", EnvironmentTrap())
    monkeypatch.setattr(socket, "socket", denied("network"))
    monkeypatch.setattr(socket, "create_connection", denied("network"))
    monkeypatch.setattr(urllib.request, "urlopen", denied("network"))
    monkeypatch.setattr(zoneinfo, "ZoneInfo", denied("timezone"))
    calendar_module = importlib.import_module("mytradingalpha.data.calendar")
    monkeypatch.setattr(calendar_module, "ZoneInfo", denied("timezone"))
    monkeypatch.setattr(
        calendar_module,
        "capture_calendar_replay_evidence",
        denied("calendar-capture"),
    )

    result = _run(api, case, (intent,), (outcome,), policy)
    assert result.fills
    assert attempted == []


@pytest.mark.parametrize(
    ("timing", "expected_reason"),
    (
        ("expiry_before_close", "expired"),
        ("submission_after_close", "not_yet_eligible"),
        ("submit_and_expiry_at_close", None),
    ),
)
def test_repair_contextual_fill_checks_rehashed_submit_and_expiry_window(
    timing: str, expected_reason: str | None
) -> None:
    api = _bt02_api()
    case = _case()
    outcome = _outcome(api, case)
    policy = _policy(api)
    original_intent = _intent(api, case, bar=outcome.bar)
    original_fill = _simulate_direct(api, case, original_intent, outcome, policy).fill
    assert original_fill is not None
    close = case.binding.next_session.close_at
    submit = close if timing == "submit_and_expiry_at_close" else case.context.earliest_execution_time
    expiry = close
    if timing == "expiry_before_close":
        expiry -= timedelta(microseconds=1)
    elif timing == "submission_after_close":
        submit = close + timedelta(microseconds=1)
        expiry += timedelta(hours=1)
    changed_intent = _intent(
        api, case, bar=outcome.bar, earliest_submit_time=submit, expires_at=expiry
    )
    fields = original_fill.model_dump(mode="python")
    fields.pop("fill_id")
    fields["intent_id"] = changed_intent.intent_id
    fields["intent_hash"] = "sha256:" + hashlib.sha256(changed_intent.canonical_bytes()).hexdigest()
    rehashed_fill = api.build_fill(**fields)
    assert rehashed_fill.fill_id != original_fill.fill_id
    assert rehashed_fill.intent_id == changed_intent.intent_id
    simulated = _simulate_direct(api, case, changed_intent, outcome, policy)
    if expected_reason is None:
        assert _status(simulated) == "filled"
        accepted = _validate_fill_context(api, case, rehashed_fill, changed_intent, outcome, policy)
        assert accepted.canonical_bytes() == rehashed_fill.canonical_bytes()
    else:
        assert _status(simulated) == "no_fill"
        assert simulated.reason_code == expected_reason
        assert simulated.fill is None
        _assert_order_error(
            api,
            "intent_invalid",
            lambda: _validate_fill_context(api, case, rehashed_fill, changed_intent, outcome, policy),
        )


@pytest.mark.parametrize(
    ("reverse_bindings", "reverse_intents", "reverse_outcomes"),
    tuple(product((False, True), repeat=3)),
)
def test_repair_outcome_prevalidation_is_independent_of_all_collection_permutations(
    reverse_bindings: bool, reverse_intents: bool, reverse_outcomes: bool
) -> None:
    api = _bt02_api()
    first = _case()
    second = _case_for_bundle(
        bundle=first.bundle,
        run_id=first.context.run_id,
        variant_id=first.context.variant_id,
        decision_time="2024-07-03T17:00:00Z",
        earliest_execution_time="2024-07-05T13:30:00Z",
    )
    first_bar = _make_bar(first, session=date(2024, 7, 3))
    second_bar = _make_bar(second, session=date(2024, 7, 5))
    bindings = (first.binding, second.binding)
    intents = (
        _intent(api, first, bar=first_bar, quantity=ONE),
        _intent(api, second, bar=second_bar, quantity=ONE),
    )
    outcomes = (_outcome(api, first, bar=first_bar), _outcome(api, second, bar=second_bar))
    policy = _policy(api)

    def run(bs: tuple[Any, ...], ins: tuple[Any, ...], outs: tuple[Any, ...]) -> Any:
        return api.Simulator().run(
            bs, ins, outs, policy,
            initial_cash=CASH_DEFAULT, initial_holdings=(), end_session=date(2024, 7, 5),
        )

    baseline = run(bindings, intents, outcomes)
    assert tuple(fill.session_date for fill in baseline.fills) == (date(2024, 7, 3), date(2024, 7, 5))
    assert tuple(fill.decision_event_id for fill in baseline.fills) == tuple(
        intent.decision_event_id for intent in intents
    )
    actual = run(
        tuple(reversed(bindings)) if reverse_bindings else bindings,
        tuple(reversed(intents)) if reverse_intents else intents,
        tuple(reversed(outcomes)) if reverse_outcomes else outcomes,
    )
    assert actual.fills == baseline.fills
    assert actual.orders == baseline.orders
    assert actual.cash == baseline.cash
    assert actual.holdings == baseline.holdings
    assert actual.accounting_basis == baseline.accounting_basis


def _assert_public_metadata_race_is_bounded_and_callback_free(
    api: SimpleNamespace,
    *,
    target: Any,
    action: Any,
    expected: Any,
    location: str,
    mutation: str,
) -> None:
    """Pause after metadata capture; mutate data only, with no production patch.

    The trace follows the known contract fingerprint and its owned metadata
    locals rather than fixed line numbers. On the repair parent these pauses
    precede the live rereads at orders.py:856-857 and the nested projection:835.
    """

    calls: list[str] = []

    class HostileMetadata:
        def __init__(self, rank: int) -> None:
            self.rank = rank

        def __hash__(self) -> int:
            calls.append("hash")
            return self.rank

        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            return self is other

        def __lt__(self, other: object) -> bool:
            calls.append("lt")
            return type(other) is HostileMetadata and self.rank < other.rank

        def __repr__(self) -> str:
            calls.append("repr")
            return "<hostile-metadata>"

        def __iter__(self) -> Any:
            calls.append("iter")
            return iter(())

    original = object.__getattribute__(target, "__pydantic_fields_set__")
    assert type(original) is set
    original_contents = set(original)
    hostile = {HostileMetadata(index) for index in range(12)}
    assert len(hostile) == 12
    assert calls == ["hash"] * 12
    calls.clear()  # Fixture construction is outside the consuming API boundary.
    growth = original_contents | {f"metadata-growth-{index}" for index in range(257)}
    paused, resume = Event(), Event()
    results: list[Any] = []
    errors: list[BaseException] = []
    widths: list[int] = []
    trace_restored: list[bool] = []
    contracts_file = importlib.import_module("mytradingalpha.contracts.orders").__file__

    def trace(frame: FrameType, event: str, arg: Any) -> Any:
        if frame.f_code.co_filename != contracts_file:
            return trace
        local_values = frame.f_locals
        metadata = [
            value for name, value in local_values.items()
            if "metadata" in name and type(value) in (tuple, list)
        ]
        widths.extend(len(value) for value in metadata)
        # The typed nested projection has no local for its final metadata tuple.
        if (
            event == "return"
            and frame.f_code.co_name in {"_typed_storage_value", "_contract_storage_fingerprint"}
            and type(arg) is tuple and len(arg) == 3 and type(arg[2]) is tuple
        ):
            widths.append(len(arg[2]))
        ancestors: set[str] = set()
        current: FrameType | None = frame
        while current is not None:
            ancestors.add(current.f_code.co_name)
            current = current.f_back
        if (
            event == "line" and not paused.is_set()
            and any(value is target for value in local_values.values())
            and "_contract_storage_fingerprint" in ancestors
            and "_guard_input" not in ancestors
            and any(
                len(value) == len(original_contents) and all(type(item) is str for item in value)
                for value in metadata
            )
        ):
            paused.set()
            if not resume.wait(5):
                raise TimeoutError("metadata race was not released")
        return trace

    def consume() -> None:
        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            results.append(action())
        except BaseException as error:
            errors.append(error)
        finally:
            sys.settrace(previous)
            trace_restored.append(sys.gettrace() is previous)

    thread = Thread(target=consume, daemon=True)
    thread.start()
    try:
        assert paused.wait(5), "public API did not reach its metadata capture boundary"
        if mutation == "replace_hostile":
            object.__setattr__(target, "__pydantic_fields_set__", hostile)
        else:
            original.clear()
            original.update(growth if mutation == "grow" else hostile)
        resume.set()
        thread.join(5)
        assert not thread.is_alive()
        assert trace_restored == [True]
        print(
            f"metadata race {location}/{mutation}: callbacks={calls}; "
            f"max_snapshot={max(widths)}; results={len(results)}; errors={len(errors)}"
        )
        assert calls == []
        assert widths and max(widths) <= 65
        if errors:
            assert results == []
            assert len(errors) == 1
            assert isinstance(errors[0], api.OrderInputError)
            assert errors[0].reason_code in {"input_invalid", "policy_invalid", "source_changed", "resource_limit"}
            assert len(str(errors[0])) <= 256
        else:
            assert len(results) == 1
            accepted = results[0]
            cost = accepted.cost_breakdown
            owned_metadata = object.__getattribute__(cost, "__pydantic_fields_set__")
            assert type(owned_metadata) is set
            assert set.__len__(owned_metadata) <= 64
            assert all(type(item) is str for item in set.__iter__(owned_metadata))
            if location == "policy":
                assert accepted == expected
            else:
                assert accepted.canonical_bytes() == expected
            assert calls == []
    finally:
        resume.set()
        thread.join(5)
        original.clear()
        original.update(original_contents)
        object.__setattr__(target, "__pydantic_fields_set__", original)
    assert not thread.is_alive()


@pytest.mark.parametrize("location", ("policy", "nested_cost"))
@pytest.mark.parametrize("mutation", ("replace_hostile", "mutate_hostile", "grow"))
def test_repair_public_metadata_races_never_call_protocols_or_expand_snapshots(
    location: str, mutation: str
) -> None:
    api = _bt02_api()
    policy = _policy(api)
    if location == "policy":
        expected = _quote(api, policy)
        target = policy

        def action() -> Any:
            return _quote(api, policy)
    else:
        case = _case()
        outcome = _outcome(api, case)
        intent = _intent(api, case, bar=outcome.bar)
        fill = _simulate_direct(api, case, intent, outcome, policy).fill
        assert fill is not None
        expected = fill.canonical_bytes()
        target = fill.cost_breakdown

        def action() -> Any:
            return _validate_fill_context(api, case, fill, intent, outcome, policy)
    _assert_public_metadata_race_is_bounded_and_callback_free(
        api, target=target, action=action, expected=expected, location=location, mutation=mutation,
    )


@pytest.mark.parametrize("instrument_id", ("é", "inst/path", "inst-stable_1:USD"))
def test_repair_holding_ids_use_ascii_stable_tokens(instrument_id: str) -> None:
    api = _bt02_api()
    case = _case(no_trade=True)
    policy = _policy(api)
    holdings = ((instrument_id, ONE),)
    if instrument_id == "inst-stable_1:USD":
        result = _run(api, case, (), (), policy, holdings=holdings)
        assert result.holdings == holdings
        assert result.cash == CASH_DEFAULT
        assert result.fills == result.orders == ()
    else:
        _assert_order_error(api, "input_invalid", lambda: _run(api, case, (), (), policy, holdings=holdings))


def _repair2_hostile_key(
    native: str, calls: list[str], *, kind: str, throwing: bool,
) -> tuple[Any, list[bool], str]:
    """Build a colliding key; arm callbacks only after constructing fixtures."""

    armed = [False]
    canary = "BT02_REPAIR2_DIAGNOSTIC_CANARY"
    base = str if kind == "str_subclass" else object

    def record(protocol: str) -> None:
        calls.append(protocol)
        if armed[0] and throwing:
            raise RuntimeError(canary)

    class HostileKey(base):
        def __new__(cls) -> Any:
            return str.__new__(cls, native) if base is str else object.__new__(cls)

        def __hash__(self) -> int:
            record("hash")
            return hash(native)

        def __eq__(self, other: object) -> bool:
            record("eq")
            return type(other) is str and native == other

        def __repr__(self) -> str:
            record("repr")
            return canary

        def __str__(self) -> str:
            record("str")
            return canary

        def __iter__(self) -> Any:
            record("iter")
            return iter(())

        def __len__(self) -> int:
            record("len")
            return 0

        def __getitem__(self, index: Any) -> str:
            record("getitem")
            return canary

        def __lt__(self, other: object) -> bool:
            record("lt")
            return False

        def __format__(self, specification: str) -> str:
            record("format")
            return canary

    return HostileKey(), armed, canary


def _repair2_fixed_error(api: SimpleNamespace, error: BaseException) -> None:
    assert type(error) is api.OrderInputError
    assert error.reason_code in {
        "input_invalid", "intent_invalid", "policy_invalid", "outcome_invalid",
        "source_changed", "resource_limit",
    }
    assert str(error) == f"BT-02 input rejected ({error.reason_code})"
    assert len(str(error)) <= 256
    assert error.errors() == [{
        "type": "order_input_error", "loc": (), "msg": str(error), "input": None,
    }]


def _repair2_schema_error(
    api: SimpleNamespace, error: BaseException, calls: list[str], canary: str,
) -> None:
    """Inspect public diagnostics, including their structured representation."""

    assert type(error) is ValidationError
    encoded = base64.b64encode(canary.encode()).decode()
    details = error.errors(include_url=False)
    rendered: list[str] = []
    inspection_errors: list[BaseException] = []
    try:
        rendered.extend((str(error), repr(error), repr(details), repr(error.errors())))
    except BaseException as inspection_error:
        inspection_errors.append(inspection_error)
    print(
        f"schema diagnostics: callbacks={calls}; lines={len(details)}; "
        f"inspection_errors={len(inspection_errors)}"
    )
    assert calls == [], "schema ingress or diagnostic inspection invoked caller protocols"
    assert inspection_errors == []
    assert len(details) == 1
    line = details[0]
    assert set(line) == {"type", "loc", "msg", "input", "ctx"}
    assert line["type"] == "value_error"
    assert line["loc"] == ()
    assert line["input"] is None
    assert line["msg"] == "Value error, BT-02 input rejected (input_invalid)"
    assert set(line["ctx"]) == {"error"}
    cause = line["ctx"]["error"]
    assert type(cause) is api.OrderInputError
    assert cause.reason_code == "input_invalid"
    assert str(cause) == "BT-02 input rejected (input_invalid)"
    assert cause.args == ("BT-02 input rejected (input_invalid)",)
    assert cause.__cause__ is None and cause.__context__ is None
    assert all(canary not in text and encoded not in text for text in rendered)
    assert all(len(text) <= 2048 for text in rendered)
    assert calls == []


def _repair2_data_race(
    *, source: Any, action: Any, mutate: Any, restore: Any, capture: str,
    capture_owner: str | None = None,
) -> tuple[list[Any], list[BaseException], list[int]]:
    """Pause at an owned snapshot shape, never at a fixed source line.

    Both the parent's native-key tuple and a capped key/value-entry tuple are
    recognized. Metadata pauses follow its first bounded capture. The schema
    control pauses at the public outer wrapper before Pydantic's kwargs path.
    Only data changes across threads; source code and functions stay intact.
    """

    files = {
        importlib.import_module(name).__file__
        for name in (
            "mytradingalpha.contracts.orders", "mytradingalpha.backtest.costs",
            "mytradingalpha.backtest.fills",
        )
    }
    helpers = {
        "_owned_mapping", "_policy_payload", "_bar_fields", "_contract_snapshot",
        "validate_fixed", "__init__",
    }
    paused, resume = Event(), Event()
    results: list[Any] = []
    errors: list[BaseException] = []
    widths: list[int] = []
    restored: list[bool] = []
    original_width = dict.__len__(source) if type(source) is dict else set.__len__(source)

    def trace(frame: FrameType, event: str, arg: Any) -> Any:
        if frame.f_code.co_filename not in files or frame.f_code.co_name not in helpers:
            return None
        local_values = frame.f_locals
        snapshots: list[tuple[str, Any]] = []
        for name, value in local_values.items():
            if type(value) not in (tuple, list):
                continue
            pairs = bool(value) and all(type(item) is tuple and len(item) == 2 for item in value)
            if "metadata" in name or "fields_set" in name:
                snapshots.append(("metadata", value))
            elif "keys" in name or pairs:
                snapshots.append(("entries", value))
        widths.extend(len(value) for _, value in snapshots)
        # A model constructor's kwargs dict is consumer-created, unlike the
        # deliberately oversized submitted source. It must also stay bounded.
        if frame.f_code.co_name in {"validate_fixed", "__init__"}:
            widths.extend(
                dict.__len__(value) for value in local_values.values()
                if type(value) is dict and value is not source
            )
        if event == "return" and type(arg) is dict and arg is not source:
            widths.append(dict.__len__(arg))
        reaches_source = any(value is source for value in local_values.values())
        captured = any(kind == capture and len(value) == original_width for kind, value in snapshots)
        outer_schema = capture == "schema" and frame.f_code.co_name == "validate_fixed"
        ancestors: set[str] = set()
        current: FrameType | None = frame
        while current is not None:
            ancestors.add(current.f_code.co_name)
            current = current.f_back
        owned_path = capture_owner is None or capture_owner in ancestors
        if (
            event == "line" and not paused.is_set() and reaches_source and owned_path
            and (captured or outer_schema)
        ):
            paused.set()
            if not resume.wait(10):
                raise TimeoutError("data-only race was not released")
        return trace

    def consume() -> None:
        previous = sys.gettrace()
        try:
            sys.settrace(trace)
            results.append(action())
        except BaseException as error:
            errors.append(error)
        finally:
            sys.settrace(previous)
            restored.append(sys.gettrace() is previous)

    thread = Thread(target=consume, daemon=True)
    thread.start()
    try:
        assert paused.wait(10), "consumer did not reach the semantic capture boundary"
        mutate()
        resume.set()
        thread.join(10)
        assert not thread.is_alive()
        assert restored == [True]
    finally:
        resume.set()
        thread.join(10)
        restore()
    assert not thread.is_alive()
    return results, errors, widths


def _repair2_public_mapping_case(api: SimpleNamespace, location: str) -> SimpleNamespace:
    if location == "intent":
        original = api.build_order_intent(**_golden_intent_fields())
        storage = original.model_dump(mode="python")
        return SimpleNamespace(
            storage=storage, key="quantity", expected=original.canonical_bytes(),
            action=lambda: api.OrderIntent.model_validate(storage), capture_owner="_owned_mapping",
        )
    if location == "policy":
        policy = _policy(api)
        return SimpleNamespace(
            storage=object.__getattribute__(policy, "__dict__"), key="half_spread_bps",
            expected=_quote(api, policy), action=lambda: _quote(api, policy),
            capture_owner="_policy_payload",
        )
    case = _case()
    bar = _make_bar(case)
    target = bar if location == "bar" else bar.manifest
    expected = _outcome(api, case, bar=bar)
    return SimpleNamespace(
        storage=object.__getattribute__(target, "__dict__"),
        key="close" if location == "bar" else "source", target=target, bar=bar,
        expected=object.__getattribute__(expected, "_sealed_bytes"),
        action=lambda: _outcome(api, case, bar=bar), capture_owner="_bar_fields",
    )


def _repair2_assert_before_image(location: str, case: SimpleNamespace, accepted: Any) -> None:
    if location == "intent":
        assert accepted.canonical_bytes() == case.expected
        assert object.__getattribute__(accepted, "__dict__") is not case.storage
        models = (accepted,)
    elif location == "policy":
        assert accepted == case.expected
        models = (accepted.cost_breakdown,)
    else:
        assert object.__getattribute__(accepted, "_sealed_bytes") == case.expected
        owned_bar = accepted.bar
        assert owned_bar is not case.bar
        assert owned_bar.manifest is not case.bar.manifest
        models = (owned_bar, owned_bar.manifest)
    for model in models:
        storage = object.__getattribute__(model, "__dict__")
        metadata = object.__getattribute__(model, "__pydantic_fields_set__")
        assert type(storage) is dict and dict.__len__(storage) <= 64
        assert all(type(key) is str for key in dict.keys(storage))
        assert type(metadata) is set and set.__len__(metadata) <= 64
        assert all(type(item) is str for item in set.__iter__(metadata))


@pytest.mark.parametrize("location", ("intent", "policy", "bar", "manifest"))
@pytest.mark.parametrize("key_kind", ("object", "str_subclass"))
@pytest.mark.parametrize("throwing", (False, True))
def test_repair2_public_key_replacement_owns_values_before_protocols(
    location: str, key_kind: str, throwing: bool,
) -> None:
    api = _bt02_api()
    case = _repair2_public_mapping_case(api, location)
    storage = case.storage
    before = dict(storage)
    calls: list[str] = []
    key, armed, canary = _repair2_hostile_key(case.key, calls, kind=key_kind, throwing=throwing)
    replacement = {key: before[case.key]}
    assert calls == ["hash"]
    calls.clear()
    armed[0] = True

    def mutate() -> None:
        dict.__delitem__(storage, case.key)
        dict.update(storage, replacement)

    def restore() -> None:
        dict.clear(storage)
        dict.update(storage, before)

    results, errors, widths = _repair2_data_race(
        source=storage, action=case.action, mutate=mutate, restore=restore, capture="entries",
        capture_owner=case.capture_owner,
    )
    print(
        f"key race {location}/{key_kind}/{throwing}: callbacks={calls}; "
        f"max_capture={max(widths, default=0)}; results={len(results)}; "
        f"errors={[type(error).__name__ for error in errors]}; "
        f"canary_echo={any(type(error) is RuntimeError and canary in str(error) for error in errors)}"
    )
    assert calls == [], "live caller lookup executed a colliding hostile key"
    assert widths and max(widths) <= 65
    if errors:
        assert results == [] and len(errors) == 1
        _repair2_fixed_error(api, errors[0])
        _assert_no_secret_echo(errors[0], canary, canary)
    else:
        assert len(results) == 1
        _repair2_assert_before_image(location, case, results[0])
    assert calls == []


@pytest.mark.parametrize("location", ("intent", "policy", "bar", "manifest"))
def test_repair2_public_mapping_growth_keeps_all_owned_captures_bounded(location: str) -> None:
    api = _bt02_api()
    case = _repair2_public_mapping_case(api, location)
    storage = case.storage
    before = dict(storage)
    growth = {f"repair2-extra-{index}": None for index in range(257)}

    def restore() -> None:
        dict.clear(storage)
        dict.update(storage, before)

    results, errors, widths = _repair2_data_race(
        source=storage, action=case.action, mutate=lambda: dict.update(storage, growth),
        restore=restore, capture="entries", capture_owner=case.capture_owner,
    )
    print(f"mapping growth {location}: max_capture={max(widths, default=0)}")
    assert widths and max(widths) <= 65
    if errors:
        assert results == [] and len(errors) == 1
        _repair2_fixed_error(api, errors[0])
    else:
        assert len(results) == 1
        _repair2_assert_before_image(location, case, results[0])


@pytest.mark.parametrize("location", ("bar", "manifest"))
@pytest.mark.parametrize("mutation,key_kind", (
    ("grow", "native"), ("replace_hostile", "object"), ("mutate_hostile", "object"),
    ("replace_hostile", "str_subclass"), ("mutate_hostile", "str_subclass"),
))
def test_repair2_outcome_metadata_uses_only_its_first_bounded_capture(
    location: str, mutation: str, key_kind: str,
) -> None:
    api = _bt02_api()
    case = _repair2_public_mapping_case(api, location)
    original = object.__getattribute__(case.target, "__pydantic_fields_set__")
    before = set(original)
    calls: list[str] = []
    hostile, armed, canary = _repair2_hostile_key(
        "repair2-hostile-metadata", calls, kind=key_kind, throwing=True,
    )
    replacement = {hostile}
    growth = before | {f"repair2-metadata-{index}" for index in range(257)}
    assert calls == ["hash"]
    calls.clear()
    armed[0] = True

    def mutate() -> None:
        if mutation == "replace_hostile":
            object.__setattr__(case.target, "__pydantic_fields_set__", replacement)
        else:
            set.clear(original)
            set.update(original, growth if mutation == "grow" else replacement)

    def restore() -> None:
        set.clear(original)
        set.update(original, before)
        object.__setattr__(case.target, "__pydantic_fields_set__", original)

    results, errors, widths = _repair2_data_race(
        source=original, action=case.action, mutate=mutate, restore=restore, capture="metadata",
        capture_owner=case.capture_owner,
    )
    print(
        f"outcome metadata {location}/{mutation}/{key_kind}: callbacks={calls}; "
        f"max_capture={max(widths, default=0)}; results={len(results)}; errors={len(errors)}"
    )
    assert calls == []
    assert widths and max(widths) <= 65
    if errors:
        assert results == [] and len(errors) == 1
        _repair2_fixed_error(api, errors[0])
        _assert_no_secret_echo(errors[0], canary, canary)
    else:
        assert len(results) == 1
        _repair2_assert_before_image(location, case, results[0])
    assert calls == []


def _repair2_adapter_case(api: SimpleNamespace, contract: str) -> SimpleNamespace:
    if contract == "OrderIntent":
        valid = api.build_order_intent(**_golden_intent_fields())
    elif contract == "Fill":
        valid = api.build_fill(**_golden_fill_fields(api))
    elif contract == "CostBreakdown":
        valid = api.build_fill(**_golden_fill_fields(api)).cost_breakdown
    else:
        valid = _policy(api)
    model = type(valid)
    payload = {name: object.__getattribute__(valid, name) for name in model.model_fields}
    adapter = TypeAdapter(model)
    assert type(adapter.validate_python(payload)) is model
    return SimpleNamespace(
        model=model, payload=payload, adapter=adapter,
        key="quantity" if contract in {"OrderIntent", "Fill"} else "half_spread_bps",
    )


@pytest.mark.parametrize("contract", ("OrderIntent", "Fill", "CostBreakdown", "CostPolicy"))
@pytest.mark.parametrize("throwing", (False, True))
def test_repair2_type_adapter_rejects_hostile_string_keys_without_protocols(
    contract: str, throwing: bool,
) -> None:
    api = _bt02_api()
    case = _repair2_adapter_case(api, contract)
    calls: list[str] = []
    key, armed, canary = _repair2_hostile_key(
        case.key, calls, kind="str_subclass", throwing=throwing,
    )
    value = case.payload.pop(case.key)
    replacement = {key: value}
    dict.update(case.payload, replacement)
    assert calls == ["hash"]
    calls.clear()
    armed[0] = True
    errors: list[BaseException] = []
    try:
        case.adapter.validate_python(case.payload)
    except BaseException as error:
        errors.append(error)
    print(
        f"adapter key {contract}/{throwing}: callbacks={calls}; "
        f"errors={[type(error).__name__ for error in errors]}"
    )
    assert calls == []
    assert len(errors) == 1
    _repair2_schema_error(api, errors[0], calls, canary)


@pytest.mark.parametrize("contract", ("OrderIntent", "Fill", "CostBreakdown", "CostPolicy"))
@pytest.mark.parametrize("throwing", (False, True))
def test_repair2_type_adapter_malformed_dict_diagnostics_are_fixed_and_callback_free(
    contract: str, throwing: bool,
) -> None:
    api = _bt02_api()
    case = _repair2_adapter_case(api, contract)
    calls: list[str] = []
    opaque, armed, canary = _repair2_hostile_key(
        "diagnostic-value", calls, kind="object", throwing=throwing,
    )
    encoded = base64.b64encode(canary.encode()).decode()
    case.payload["unexpected"] = {"direct": canary, "encoded": encoded, "opaque": opaque}
    calls.clear()
    armed[0] = True
    with pytest.raises(ValidationError) as captured:
        case.adapter.validate_python(case.payload)
    _repair2_schema_error(api, captured.value, calls, canary)


@pytest.mark.parametrize("contract", ("OrderIntent", "Fill", "CostBreakdown", "CostPolicy"))
@pytest.mark.parametrize("wire_type", ("str", "bytes"))
def test_repair2_type_adapter_denied_json_diagnostics_never_retain_submitted_payload(
    contract: str, wire_type: str,
) -> None:
    api = _bt02_api()
    case = _repair2_adapter_case(api, contract)
    canary = "BT02_REPAIR2_DIAGNOSTIC_CANARY"
    encoded = base64.b64encode(canary.encode()).decode()
    wire = json.dumps({"direct": canary, "encoded": encoded})
    submitted = wire if wire_type == "str" else wire.encode()
    with pytest.raises(ValidationError) as captured:
        case.adapter.validate_json(submitted)
    _repair2_schema_error(api, captured.value, [], canary)


@pytest.mark.parametrize("contract", ("OrderIntent", "Fill", "CostBreakdown", "CostPolicy"))
def test_repair2_type_adapter_outer_growth_is_bounded_before_model_kwargs(contract: str) -> None:
    api = _bt02_api()
    case = _repair2_adapter_case(api, contract)
    before = dict(case.payload)
    growth = {f"repair2-outer-{index}": None for index in range(257)}

    def restore() -> None:
        dict.clear(case.payload)
        dict.update(case.payload, before)

    results, errors, widths = _repair2_data_race(
        source=case.payload, action=lambda: case.adapter.validate_python(case.payload),
        mutate=lambda: dict.update(case.payload, growth), restore=restore, capture="schema",
    )
    print(f"outer adapter growth {contract}: max_capture={max(widths, default=0)}")
    assert max(widths, default=0) <= 65
    assert results == [] and len(errors) == 1
    _repair2_schema_error(api, errors[0], [], "BT02_REPAIR2_DIAGNOSTIC_CANARY")
