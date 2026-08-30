# Phase 07 — Broker, OMS, Paper, and Reconciliation Design

Status: planned. This phase exercises order lifecycle and paper operations while keeping live-broker writes unavailable.

## Goals

- Implement shared `OrderIntent`, `OrderEvent`, and `Fill` lifecycle contracts.
- Make validation, risk approval, submission, acknowledgement, fills, and unknown states explicit and idempotent.
- Provide a local deterministic `PaperBroker` and an isolated external PAPER adapter path with reconciliation.

## Scope

OMS state machine, outbox, stable client/fill IDs, local paper simulator, external PAPER endpoint submit/cancel/query behind `paper_write_enabled=false`, broker snapshot reconciliation, scheduler, and human approvals.

## Non-goals

No live-broker write before Phase 09, no unattended automation, no credential access from Research Graph/LLM, and no claim that paper operation proves alpha.

## Dependencies

Depends on Phase 04 approved risk decisions, Phase 05 cost/fill contracts, and Phase 06 experiment/gate evidence. Current repository has no broker integration; relevant reporting/CLI seams are [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py), [`cli/main.py`](../../../../cli/main.py), and [`trading_graph.py`](../../../../tradingagents/graph/trading_graph.py#L350-L500).

## Components and dataflow

```text
TargetPortfolio -> RiskEngine -> RiskDecision -> OrderIntent(proposed)
  -> validated -> approved -> submitting -> submitted
  -> acknowledged -> partial/filled/cancelled/rejected/expired
  -> outbox -> PaperBroker or approved external PAPER endpoint
  -> broker snapshot/fills -> Reconciliation -> Ledger/alerts
```

An unknown acknowledgement pauses the intent and queries the endpoint; no blind resubmit is allowed. Risk validation and human approval occur before submission. Paper endpoint writes are an external side effect and require explicit approval; `paper_broker_egress` is enabled only for that approved endpoint, while `live_broker_egress` and `live_write_enabled` remain disabled.

## Current integration points

- [`TradingAgentsGraph.propagate`](../../../../tradingagents/graph/trading_graph.py#L350-L500) produces research decisions but has no order lifecycle.
- [`AgentState`](../../../../tradingagents/agents/utils/agent_states.py#L47-L76) has no orders/fills/NAV and must not become the OMS store.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) writes report artifacts; OMS events require a separate append-only store.
- [`cli/main.py`](../../../../cli/main.py) can host an additive paper scheduler/approval command but cannot receive broker secrets in graph state.

## Interfaces and invariants

Order states are `proposed`, `validated`, `approved`, `submitting`, `submitted`, `acknowledged`, `partial`, `filled`, `cancelled`, `rejected`, `expired`, and `unknown`. Required transitions include `proposed → validated → approved → submitting → submitted → acknowledged/rejected/expired/unknown`; `acknowledged → filled/partial/cancelled/rejected/expired`; and `partial → filled/cancelled/rejected`. A risk decision and approval are required before `submitting`. Stable client/fill IDs and an outbox make retries idempotent. Unknown acknowledgement enters query-only pause. `paper_write_enabled` defaults false; `live_write_enabled` is unavailable until Phase 09.

## Decisions and alternatives

- Use one OMS state machine for local paper and future live, not separate semantics.
- Keep a deterministic local `PaperBroker` for tests and an external PAPER adapter for approved endpoint integration.
- Use an outbox plus append-only event log rather than direct request/retry loops.
- Reconcile local cash, positions, open orders, fills, and broker snapshot hash before resuming after uncertainty.

## Failure, security, and observability

Invalid transitions, duplicate/conflicting events, timeout, unknown ACK, endpoint mismatch, and reconciliation deltas pause or halt the affected scope. Paper credentials are isolated to the adapter process and redacted; the Research Graph and LLM never see them. Observe state transition latency, outbox depth, acknowledgement age, fill/partial rates, unknown count, reconciliation deltas, and approval IDs.

## Migration and rollback

Run local paper first, then an approved external PAPER endpoint in shadow or constrained mode. Existing graph output remains available. Disable dispatcher or `paper_write_enabled` to stop paper writes; preserve outbox/events and reconcile before resume. `live_write_enabled` is not enabled by this phase.

## Acceptance and gate

Pass requires exhaustive lifecycle tests, risk/approval ordering, idempotent restart, unknown-ACK pause/query, local paper parity, external PAPER fake/sandbox evidence, and reconciliation tests. `fail` or `insufficient_evidence` blocks Phase 08; no mandatory gate waiver exists.
