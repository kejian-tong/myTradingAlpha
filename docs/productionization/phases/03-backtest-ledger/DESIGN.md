# Phase 03 — Backtest and Ledger Design

Status: planned. This phase supplies the deterministic event-driven simulator and append-only accounting that the current repository does not ship.

## Goals

- Model session time, next-session execution, orders, fills, costs, corporate actions, and benchmarks deterministically.
- Maintain cash/positions/NAV through an append-only ledger.
- Produce canonical economic/artifact hashes and report metrics without overstating alpha.

## Scope

Clock/events, simulator fill model, spread/slippage/commission hooks, ledger/NAV, corporate actions, benchmark policies, replay manifests, checkpoints, and golden metric reports.

## Non-goals

No broker endpoint, live credential, forward-paper operation, optimizer, or production promotion. Backtrader dependency remains unused until a separately reviewed integration proves contract parity.

## Dependencies

Depends on Phase 01 EvidenceBundle and Phase 02 signal contracts. Current data/cache behavior is in [`stockstats_utils.py`](../../../../tradingagents/dataflows/stockstats_utils.py#L148-L221); current pending outcome/benchmark logic is in [`trading_graph.py`](../../../../tradingagents/graph/trading_graph.py#L248-L334); declared Backtrader is visible in [`pyproject.toml`](../../../../pyproject.toml).

## Components and dataflow

```text
EvidenceBundle + SignalEnvelope + Snapshot
        -> SessionClock -> DecisionEvent -> Target/intent fixture
        -> deterministic FillModel -> Fill/Cost events -> AppendOnlyLedger
        -> NAV/benchmark/metrics -> canonical report artifact
```

The first executable decision is at the close and the first fill is at the earliest eligible next session. No same-bar fill is inferred unless the order contract explicitly permits it.

## Current integration points

- [`TradingAgentsGraph._fetch_returns`](../../../../tradingagents/graph/trading_graph.py#L248-L294) computes raw and benchmark returns for memory reflection, not portfolio ledger performance.
- [`_resolve_pending_entries`](../../../../tradingagents/graph/trading_graph.py#L296-L334) fetches current outcomes and is excluded from historical replay.
- [`load_ohlcv`](../../../../tradingagents/dataflows/stockstats_utils.py#L148-L221) is a live/cache dataflow, not a sealed event source.
- [`pyproject.toml`](../../../../pyproject.toml) declares Backtrader but no shipped runner/ledger implementation exists.

## Interfaces and invariants

`SessionClock` emits ordered session events. `FillModel` is deterministic for a fixed event stream/config. `Ledger.append()` is immutable and sequence-numbered. `NAV = cash + sum(quantity * mark_price) + receivables - liabilities` after every applied event; all-in fill notional and incremental explicit fees are posted once, atomically, and are not subtracted again in NAV. Price-friction attribution is not an extra cash charge; use the [shared accounting rule](../../03_CONTRACTS_AND_SCHEMAS.md#fill-accounting-units-and-fee-once-rule). Reported alpha is portfolio net return relative to a declared benchmark, not raw close-minus-benchmark. The canonical economic/artifact hash excludes non-semantic run IDs and wall-clock fields while retaining bundle/config/code/model/seed, events, fills, costs, holdings, and metrics.

## Decisions and alternatives

- Build a small contract-first simulator before any Backtrader integration to make time, fills, and accounting testable.
- Use event sourcing/append-only records rather than mutable snapshots as the source of truth; snapshots are derived checkpoints.
- Make costs explicit and versioned rather than relying on provider-adjusted prices or hidden commissions.
- Keep benchmark and portfolio accounting separate so alpha cannot be inferred from a price series alone.

## Failure, security, and observability

Out-of-order events, insufficient cash, invalid prices, duplicate fills, and fee mismatches fail the run. Historical simulation cannot open sockets or read credentials. Observe event sequence, fill decisions, cost components, ledger hash, cash/position balance, rejected events, and replay duration. Preserve failed artifacts for review without logging secrets.

## Migration and rollback

The simulator is a new offline path and does not replace current graph propagation. Existing reports remain available. A model or cost policy change creates a new manifest/artifact; rollback selects the last valid version and replays immutable events. No ledger row is edited or deleted.

## Acceptance and gate

Pass requires golden cash/position/NAV scenarios, next-session timing, partial-fill/cost tests, corporate-action tests, canonical hash repeatability excluding non-semantic fields, and metric reports with explicit gross/net costs. `fail` or `insufficient_evidence` blocks portfolio/paper work.
