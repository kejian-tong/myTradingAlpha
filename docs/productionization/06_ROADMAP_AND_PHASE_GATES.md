# Roadmap and Phase Gates

## Sequencing rule

The implementation order is fixed:

`00 foundation → 01 point-in-time data → 02 evidence/agent boundary → 03 backtest/ledger → 04 portfolio/risk → 05 execution cost/liquidity → 06 experiment/alpha validation → 07 broker/OMS/paper/reconciliation → 08 8–12 week forward paper gate → 09 tiny live pilot`.

Each phase is additive and independently rollbackable. A phase gate is evidence that the scoped behavior works; it is not a claim that later phases are ready.

## Phase map

| Phase | Goal | Depends on | Exit gate |
| --- | --- | --- | --- |
| 00 Foundation | Package boundary, config, IDs, CI/docs baseline | Current repo baseline | Imports, schema lint, no dependency inversion, reproducible dev check |
| 01 PIT data | Capture, normalize, archive, calendar, universe, EvidenceBundle | 00 | Cutoff/revision/delisting tests and sealed bundle replay with network denied |
| 02 Evidence/agent boundary | Adapt Research Graph to read-only evidence and bounded overlay | 01 | Overlay cannot increase quant influence or create weights/orders; missing evidence is explicit |
| 03 Backtest/ledger | Deterministic clock, fills, costs, corporate actions, NAV | 01, 02 contracts | Golden ledgers, fee-once invariant, repeat replay, baseline reports |
| 04 Portfolio/risk | Rule allocator then optional optimizer; deterministic risk/halts | 02, 03 | Long-only constraints, fail-closed rejects, persistent halt restart test |
| 05 Execution/cost/liquidity | Cost/slippage/impact and capacity model | 03, 04 | Stress scenarios, no double costs, capacity and liquidity reports |
| 06 Experiment/alpha | Variants, seeds, walk-forward, stats, sealed holdout | 03–05 | Required variant matrix, 10/30 seed policy, reports and statistical controls |
| 07 OMS/paper/reconciliation | Shared OMS lifecycle, paper adapter, broker boundary, reconciliation | 04, 05, 06 | State-machine tests, idempotency, unknown-ACK pause, `live_write_enabled` false |
| 08 Forward paper gate | 8–12 week operational run and promotion decision | 07 | Complete daily evidence, no unexplained breaks, signed gate record |
| 09 Live pilot | L0/L1/L2 tiny live workflow under explicit approval | 08 | L0 first, human approvals, rollback drill, no unapproved automation |

## Phase-level gate requirements

### 00 Foundation

Goal: make ownership and interfaces explicit without changing current production behavior. Scope includes `mytradingalpha/` skeleton, schema versioning, config validation, and documentation. Non-goals are broker access, data backfill, and portfolio decisions. Gate evidence is an import/type/test job and dependency-direction check.

### 01 Point-in-time data

Goal: make historical inputs immutable and availability-aware. Scope includes vendor captures, revisions, ALFRED-style vintage fields where available, calendars, corporate actions, delisted names, and bundle hashes. Non-goals are live execution and LLM changes. Gate evidence includes future-data fixtures, unavailable-vs-degraded reason codes, and network-denied replay.

### 02 Evidence and agent boundary

Goal: preserve the useful Research Graph while limiting its authority. Scope includes a read-only evidence adapter, ResearchNote, QuantSignal, LLMOverlay, and SignalEnvelope. Non-goals are weights, orders, credentials, and optimizer logic. Gate evidence proves the overlay's allowed actions and abstain semantics.

### 03 Backtest and ledger

Goal: create a deterministic event-driven simulator and append-only accounting. Scope includes clock, order/fill events, costs, corporate actions, NAV, benchmark, and reports. Non-goals are broker writes. Gate evidence is golden scenario plus repeated hash-identical output.

### 04 Portfolio and risk

Goal: produce numeric portfolios and hard controls. Scope begins with a rule allocator; an optimizer is optional only after baseline. Risk is deterministic, shared, independent, fail-closed, and persistent. Non-goals are LLM risk authorization and live deployment.

### 05 Execution cost and liquidity

Goal: model what a small allowlist can actually trade. Scope includes spread, slippage, impact, partial fills, ADV participation, and capacity stress. Non-goals are broker credentials. Gate evidence compares gross/net results and shows fees are posted once.

### 06 Experiment and alpha validation

Goal: separate a reproducible experiment from a favorable narrative. Scope includes required variants, seed manifests, walk-forward purge/embargo, sealed holdout, bootstrap, DSR/PBO, and result governance. Non-goals are live promotion. Gate evidence is complete and reviewable.

### 07 OMS, paper, and reconciliation

Goal: exercise shared intent/event/fill contracts without assuming a broker is safe. Scope includes OMS state machine, paper adapter, broker interface, outbox, stable IDs, reconciliation, and approval records. Non-goals are broker writes before Phase 09. Gate evidence includes unknown-ACK handling and restart idempotency.

### 08 Forward paper gate

Goal: prove operational reliability over 8–12 weeks. Scope includes daily scheduler, captured bundles, paper fills, reconciliation, alerts, incident review, and a signed gate decision. Non-goal is claiming durable alpha from a short paper period.

### 09 Live pilot

Goal: test an explicitly approved tiny live scope. Scope starts at L0 read-only, then L1 one/few symbols human approved, then L2 small allowlist. Non-goals are unapproved automation, leverage, broad universe, and unattended scaling. Gate evidence includes credential separation, rollback, kill switch, and approval history.

## Cross-phase invariants

- `knowledge_cutoff <= decision_time < earliest_execution_time`.
- Historical mode reads only immutable EvidenceBundle and has no network path.
- LLM overlay can attenuate or veto, never increase quant influence or create weights/orders.
- Quant-only and Quant+LLM are separate preregistered variants.
- Risk is deterministic, shared, independent, fail-closed, and persistent on hard failure.
- Fees are represented once in ledger cash flows and never double-counted in NAV.
- Risk validation and human approval precede submission; unknown broker acknowledgement pauses and queries, with no blind resubmission.
- No live-capable PR before Phase 09; broker write is false by default before explicit approval.

## Rough schedule (non-binding)

For one engineer, a practical first slice is two weeks: establish Phase 00 interfaces and config; implement a minimal Phase 01 bundle fixture; add one Phase 02 adapter path; and produce one offline replay report. A broader MVP may take several months depending on data contracts and review capacity. These are non-binding estimates, not delivery commitments. See each phase implementation and [`07_PR_IMPLEMENTATION_PLAN.md`](07_PR_IMPLEMENTATION_PLAN.md) for work packages.

## Promotion language

Use “implemented and locally validated” only for executed checks, “backtest evidence available” only for sealed reports, “paper operational gate passed” only for a signed 8–12 week record, and “live pilot approved” only after explicit Phase 09 authorization. Never call the current baseline or an intermediate phase paper-ready or live-ready.
