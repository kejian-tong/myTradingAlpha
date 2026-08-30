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
if calibration outside instrument/venue/time validity range: reject or select approved conservative stress policy
impact_cost = eta * sigma * price * abs(quantity) * sqrt(abs(quantity) / ADV)
execution_price = mid + sign(quantity) * (spread / 2 + slippage + impact_cost / abs(quantity))
cost = spread + slippage + commission + impact_cost
fill_qty = min(intent.qty, participation_limit * ADV)
append fill and one fee/cost cash event
emit residual intent for partial fill or explicit capacity rejection
```

The report carries gross return, each cost component, total net cost, turnover, participation, capacity, and artifact hash. The same fill/cost event stream is accepted by the Phase 03 ledger.

## Red-green-refactor

1. Red: add tests for negative cost, stale/missing ADV, monotonic square-root impact, calibration out-of-range, partial fill residuals, fee double-count, and base/stress divergence.
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
