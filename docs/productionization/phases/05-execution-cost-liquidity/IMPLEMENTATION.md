# Phase 05 — Execution Cost and Liquidity Implementation

Commands are planned until exact output is recorded.

## Ordered PR/work packages

1. **EXC-01** — spread and slippage model.
2. **EXC-02** — PIT liquidity and market impact.
3. **EXC-03** — partial fills and capacity.
4. **EXC-04** — base/stress cost scenario reports.

## Exact existing files to touch

- [`tradingagents/dataflows/stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py) only through a read-only bar/volume adapter.
- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only to preserve current research return behavior.
- [`pyproject.toml`](../../../../pyproject.toml) only for approved testing tooling; do not treat Backtrader as a substitute implementation.

## Proposed files, classes, and APIs

- Extend the BT-02 `mytradingalpha/backtest/costs/__init__.py` facade; preserve its CostModel import.
- `mytradingalpha/backtest/costs/spread_slippage.py`: `SpreadSlippage.quote()`.
- `mytradingalpha/backtest/costs/commission.py`: `CommissionPolicy.quote()`.
- `mytradingalpha/backtest/costs/impact.py`: `ImpactModel.quote()`.
- `mytradingalpha/data/liquidity.py`: `LiquidityRepository.as_of()`.
- `mytradingalpha/backtest/partial_fills.py`: `PartialFillModel.fill()`.
- `mytradingalpha/backtest/capacity.py`: `CapacityModel.check()`.
- `mytradingalpha/experiments/cost_scenarios.py`: `CostScenarioRunner.run()`.

## Schema and pseudocode

```text
market = liquidity.as_of(instrument, knowledge_cutoff)
if market missing/stale: reject with DATA_LIQUIDITY_UNAVAILABLE
if calibration outside validity range: reject or use a preregistered conservative stress policy
fill_qty = min(abs(intent.quantity), remaining_session_capacity)
if fill_qty <= 0: record unfilled; do not divide by quantity or invent a fill
# Determine capacity before quoting impact, and consume it across prior fills in this session.
impact_total = eta * sigma * mid * fill_qty * sqrt(fill_qty / ADV)
price_friction_per_share = full_spread_per_share / 2 + slippage_per_share + impact_total / fill_qty
execution_price = mid + side_sign * price_friction_per_share
if execution_price <= 0 or any required value is invalid: reject
explicit_fee = cumulative_fee_after_fill - cumulative_fee_already_posted
cash_delta = -side_sign * fill_qty * execution_price - explicit_fee
append fill-notional and incremental explicit-fee events atomically and idempotently
cost_breakdown = total-currency components; attribution only, never another cash debit
record residual intent/capacity rejection without forcing fills
```

Use the [shared accounting units and fee-once rule](../../03_CONTRACTS_AND_SCHEMAS.md#fill-accounting-units-and-fee-once-rule). The report carries gross return, each total-currency cost component, net return, turnover, participation, capacity, and artifact hash. The same fill/cost event stream is accepted by the Phase 03 ledger.

## Red-green-refactor

1. Red: add tests for negative cost, stale/missing ADV, monotonic square-root impact, calibration out-of-range, partial fill residuals, shared buy/sell/2–3–5 fee-once goldens, cumulative fee allocation, fee double-count, and base/stress divergence.
2. Green: implement explicit cost components, liquidity selector, partial fills, capacity check, and scenario runner.
3. Refactor: share Decimal arithmetic and cost event serialization with `mytradingalpha.backtest` without changing current graph code.

## Exact tests and fixtures

- `tests/productionization/costs/test_spread_slippage.py`: side/price/session, invalid input, deterministic output.
- `tests/productionization/costs/test_impact_liquidity.py`: ADV as-of, stale volume, monotonic square-root participation impact, calibration validity range, missing data.
- `tests/productionization/costs/test_partial_capacity.py`: partial fill, cancellation residual, capacity breach, idempotent event.
- `tests/productionization/costs/test_scenarios.py`: base/stress report, gross/net cost, turnover, capacity, fee-once.
- `tests/productionization/fixtures/costs/{base,stress,thin-volume,partial-fill}.json`.

## Validation commands

```bash
python -m pytest -q tests/productionization/costs tests/productionization/backtest/test_ledger_nav.py
ruff check .
python scripts/check_dependency_direction.py
```

Commands are planned; record exact fixture/policy hashes and any skipped optional integration.

## Migration and compatibility

Cost models are opt-in to simulator/paper paths. Existing raw return/reflection code is not retrofitted to claim net performance. A changed policy produces a new replay artifact. Rollback selects the previous approved model and replays retained events; no fills or ledger entries are overwritten.

## Definition of done

- All EXC PRs pass deterministic focused tests.
- Cost components, liquidity, participation, partial fills, and capacity are explicit.
- Simulator and paper contracts can consume identical cost/fill events.
- Reports distinguish gross/net and charge fees once.
- Gate evidence is `pass`; otherwise `fail` or `insufficient_evidence` blocks Phase 06/07.

## Evidence and rollback

Evidence includes cost-policy hashes, synthetic liquidity fixtures, fill traces, stress reports, and fee-once assertions. Rollback disables the new model or selects the prior policy and returns to explicit no-trade on missing inputs. No live external side effect occurs in this phase.
