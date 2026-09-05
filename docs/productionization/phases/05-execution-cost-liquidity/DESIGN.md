# Phase 05 — Execution Cost and Liquidity Design

Status: planned. This phase makes simulated and paper results sensitive to spread, slippage, impact, partial fills, and capacity.

## Goals

- Apply explicit, versioned cost assumptions to every fill.
- Use point-in-time liquidity and participation limits to avoid impossible fills.
- Report gross/net performance and capacity stress without double-counting fees.

## Scope

Spread/slippage, commissions, market impact, ADV/participation, partial-fill behavior, capacity scenarios, stress reports, and compatibility with Phase 03 ledger and Phase 07 paper contracts.

## Non-goals

No live broker submission, credential handling, optimizer design, or claim that a cost model is calibrated for all markets. No fixed live risk limits.

## Dependencies

Depends on Phase 03 `FillModel`/ledger/NAV and Phase 04 target/risk contracts, with PIT liquidity from Phase 01. Current bar inputs come from [`stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py#L148-L221); current graph has no order/cost model.

## Components and dataflow

```text
PIT bars/volume + target intent
  -> spread/slippage -> impact/participation -> fill quantity/price
  -> cost events -> shared ledger -> base/stress capacity report
```

Every cost component is explicit and versioned. The same cost model feeds simulator and paper adapter so comparison is meaningful.

## Current integration points

- [`load_ohlcv`](../../../../tradingagents/dataflows/stockstats_utils.py#L148-L221) provides cached price/volume but not an archival liquidity contract.
- [`TradingAgentsGraph`](../../../../tradingagents/graph/trading_graph.py#L248-L334) computes raw/benchmark returns but has no order cost or fill lifecycle.
- Backtrader is only a declared dependency in [`pyproject.toml`](../../../../pyproject.toml), not an implemented cost engine.

## Interfaces and invariants

`CostModel.quote(intent, market)` returns non-negative spread, slippage, commission, and impact. A default square-root impact cost is `impact_cost = eta * sigma * price * abs(quantity) * sqrt(abs(quantity) / ADV)` within a calibrated instrument/venue/time validity range; execution price composes mid plus side-signed half-spread, slippage, and impact per share. `LiquidityModel` requires an as-of ADV/volume and rejects stale/missing required data. Participation and capacity constraints can reduce quantity or reject the intent. Partial fills append incremental events. All-in fill price includes price friction; only incremental explicit fees additionally debit cash. Cost breakdown and implementation shortfall are attribution only, never a second debit. Per-share quotes are converted to total-currency attribution after capacity determines actual fill quantity; use the [shared units](../../03_CONTRACTS_AND_SCHEMAS.md#fill-accounting-units-and-fee-once-rule). A missing or out-of-range calibration is explicit unavailable or a documented conservative stress rule, never silently free.

## Decisions and alternatives

- Use transparent parametric base/stress models before calibration to a broker. Calibrate `eta`, volatility, and spread assumptions by instrument/venue/time range; out-of-range observations fail closed or select an explicitly conservative stress policy.
- Use deterministic fills before stochastic impact; any stochastic mode is a separately seeded experiment.
- Share cost/FillModel with paper endpoint to reduce simulator-to-paper divergence.
- Treat capacity as a report and a gate, not a hidden denominator adjustment.

## Failure, security, and observability

Negative/invalid cost, missing volume, stale quote, or participation overflow rejects/reduces according to policy and emits reason codes. Cost configs are versioned and reviewable; no provider credentials are required. Observe each cost component, fill quantity, participation, residual quantity, rejected intents, and stress scenario hash.

## Migration and rollback

Introduce models behind the simulator/paper feature flag. Existing research return reports stay unchanged. Roll back by selecting the last approved cost policy and replaying immutable events; never edit a filled price or subtract a fee a second time.

## Acceptance and gate

Pass requires deterministic base/stress cost fixtures, monotonic impact, partial-fill ledger parity, capacity rejection, and a fee-once report. `fail` or `insufficient_evidence` blocks experiment/paper promotion.
