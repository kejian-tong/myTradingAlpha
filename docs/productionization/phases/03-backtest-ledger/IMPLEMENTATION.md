# Phase 03 — Backtest and Ledger Implementation

Commands are planned until exact execution evidence is recorded.

## Ordered PR/work packages

1. **BT-01** — session clock and event model.
2. **BT-02** — orders, fills, and deterministic cost engine.
3. **BT-03** — append-only ledger and NAV.
4. **BT-04** — corporate actions and benchmark policies.
5. **BT-05** — manifested replay and checkpointing.
6. **BT-06** — metrics and golden reports.

## Exact existing files to touch

- [`tradingagents/dataflows/stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py) only for a read-only bar adapter.
- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only to keep historical replay from invoking current-time memory resolution.
- [`tradingagents/graph/checkpointer.py`](../../../../tradingagents/graph/checkpointer.py) only for compatibility with existing checkpoints; do not treat it as a financial ledger.
- [`pyproject.toml`](../../../../pyproject.toml) only if a newly approved test dependency is required; Backtrader is not the implementation shortcut.

## Proposed files, classes, and APIs

- `mytradingalpha/backtest/clock.py`: `SessionClock.next_event()`.
- `mytradingalpha/backtest/events.py`: `DecisionEvent`, `MarketEvent`, `OrderEvent`, `CorporateActionEvent`.
- `mytradingalpha/backtest/runner.py`: `BacktestRunner.run()`.
- `mytradingalpha/backtest/orders.py`: `SimOrder`, `OrderBook`.
- `mytradingalpha/backtest/fills.py`: `FillModel.simulate()`.
- `mytradingalpha/backtest/costs/__init__.py`: export `CostModel.quote()` from the initial package; EXC extends it without breaking the public import.
- `mytradingalpha/contracts/orders.py`: shared `OrderIntent`/`Fill` first introduced by BT-02; `SimOrder` remains domain-internal. BT-01 simulation events are not OMS wire events.
- `mytradingalpha/backtest/ledger.py`: `Ledger.append/replay/balance()`.
- `mytradingalpha/backtest/nav.py`: `NAVCalculator.compute()`.
- `mytradingalpha/backtest/accounting.py`: `AccountingInvariant.check()`.
- `mytradingalpha/backtest/corporate_actions.py`, `benchmarks.py`.
- `mytradingalpha/backtest/manifest.py`: `ReplayManifest.semantic_hash()`.
- `mytradingalpha/backtest/replay.py`: `ReplayRunner.replay()`.
- `mytradingalpha/backtest/metrics.py`, `reports.py`.

## Schema and pseudocode

```text
decision at session close
  -> clock.next_session(decision_time)
  -> create intent with earliest_submit_time
  -> fill using next-session bar and cost model
  -> append all-in fill notional + incremental explicit fee exactly once (atomic, by fill ID)
  -> cost breakdown/implementation shortfall are attribution, not another debit
  -> derive positions/cash/NAV and metrics

semantic_hash(record):
  canonicalize economic fields and artifact/config/model hashes
  omit run_id, created_at, wall_clock, log sequence unrelated to economics
  hash canonical JSON
```

Use [shared first-use ownership and accounting units](../../03_CONTRACTS_AND_SCHEMAS.md). Simulation-only plan/risk references never authorize broker dispatch; do not implement RSK/OMS early merely to run fill fixtures.

An interrupted run resumes from the last valid event sequence. If a semantic input changes, the manifest hash changes and the prior result is not overwritten.

## Red-green-refactor

1. Red: add failing next-bar, out-of-order, duplicate-fill, insufficient-cash, fee-once, corporate-action, and hash-exclusion tests.
2. Green: implement clock/events, fill/cost, ledger/NAV, action/benchmark, replay manifest, and metrics in that order.
3. Refactor: centralize Decimal arithmetic, immutable event records, and canonical serialization; keep metric definitions explicit.

## Exact tests and fixtures

- `tests/productionization/backtest/test_clock_events.py`: close-to-next-session, holidays, event order, restart sequence.
- `tests/productionization/backtest/test_fills_costs.py`: market/limit, spread/slippage/commission, partial fills, no-cash, deterministic output.
- `tests/productionization/backtest/test_ledger_nav.py`: cash/position balance, fee-once, duplicate event, mark price, negative cash.
- `tests/productionization/backtest/test_actions_benchmarks.py`: split, dividend, delisting, Cash/B&H benchmark.
- `tests/productionization/backtest/test_replay_hash.py`: repeat semantic/economic hash, changed bundle/config invalidation, run ID/wall-clock exclusion.
- `tests/productionization/backtest/test_metrics_reports.py`: median/p5/p95/worst, risk/trading/relative/capacity fields, missing metric rejection.
- Fixtures under `tests/productionization/fixtures/backtest/` include two instruments, one holiday, one split, one dividend, and a partial fill.

## Validation commands

```bash
python -m pytest -q tests/productionization/backtest
python -m pytest -q tests/test_memory_log.py tests/test_date_boundaries.py
ruff check .
python scripts/check_dependency_direction.py
```

Commands are planned. The report must include interpreter, fixture hash, and whether the output hash was compared after removing non-semantic run IDs/wall-clock fields.

## Migration and compatibility

No current memory-log outcome or markdown report is reinterpreted as a ledger event. The new runner consumes explicit bundle/envelope/intent fixtures. Existing checkpoint APIs remain available for graph runs; production replay uses its own manifest and event sequence. A failed new cost/action policy rolls back by selecting the previous version and writing a new derived artifact.

## Definition of done

- All BT PRs pass focused tests and repeat replay.
- The ledger is append-only, NAV balances, and fees are charged once.
- Execution timing, partial fills, actions, benchmarks, and metrics are explicit.
- Canonical semantic/economic hashes exclude non-semantic run IDs and wall clock but retain economic inputs.
- Gate evidence is `pass`; `fail` or `insufficient_evidence` blocks Phase 04/05/06.

## Evidence and rollback

Evidence includes event/fill/ledger fixtures, semantic hash manifests, golden reports, and test output. Rollback disables the new runner or selects the previous version; it replays retained events and never deletes or edits ledger history. This phase has no broker or external endpoint side effect.
