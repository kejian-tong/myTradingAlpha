# Phase 09 — Live Pilot Design

Status: planned and approval-gated. This phase is the first point at which a live-broker write could be considered.

## Goals

- Start with L0 live read-only observation, then L1 one/few symbols with human approval, then L2 small allowlist under explicit limits.
- Keep deterministic risk, reconciliation, stable IDs, outbox, and kill/rollback controls in the live path.
- Require a new approval for any later automation or scope expansion.

## Scope

Credential isolation, live-read adapter, human approvals, tiny allowlist, policy-versioned limits, `live_write_enabled`, incident drills, persistent halt, and policy-driven emergency handling.

## Non-goals

No unapproved automation, leverage, broad universe, unattended scaling, unconditional market liquidation, or claim that a successful tiny pilot proves durable alpha.

## Dependencies

Requires a `pass` Phase 08 gate with complete 8–12 week paper evidence, Phase 07 OMS/reconciliation, Phase 04 risk, and Phase 06 experiment evidence. Current project has no broker integration; [`trading_graph.py`](../../../../tradingagents/graph/trading_graph.py#L350-L500) and [`cli/main.py`](../../../../cli/main.py) are adapter/command seams only.

## Components and dataflow

```text
live read-only account/data -> bundle/context -> quant/research/overlay
  -> allocator -> RiskEngine -> human approval -> outbox -> broker write
  -> order events/fills -> ledger -> reconciliation -> halt/rollback controls
```

L0 stops before outbox dispatch. L1 permits approved intents for one/few symbols. L2 permits approved batches for a small allowlist. Any unknown acknowledgement, risk breach, credential issue, or reconciliation mismatch pauses and may persistently halt.

## Current integration points

- [`cli/main.py`](../../../../cli/main.py) is the only plausible command entry point; current code has no broker credentials or write path.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) can link to live evidence but is not an OMS or audit ledger.
- [`tradingagents/graph/setup.py`](../../../../tradingagents/graph/setup.py#L113-L154) defines the Research Graph; live permission must remain outside graph nodes.

## Interfaces and invariants

Live write requires `GateEvidence=pass`, mode/level approval, approved instrument/quantity, valid `RiskDecision`, human approval, outbox record, and `live_write_enabled=true`. Credentials are not stored in context, prompts, logs, or artifacts. The same OMS transitions and reconciliation apply. A persistent halt survives restart. Emergency handling is policy-driven: first pause/cancel/query/reconcile; any flattening decision requires human authorization, current liquidity/open-order assessment, and a reconciled execution plan. It must not unconditionally send market liquidation.

## Decisions and alternatives

- L0/L1/L2 staged canary rather than immediate automation.
- Human approval for L1/L2; later automation is a new approval, not a config flip.
- Reuse paper/live contracts and deterministic RiskEngine; do not create a less-tested live path.
- Prefer pause and reconcile over blind resubmit or unconditional emergency liquidation.

## Failure, security, and observability

Broker outage, unknown ACK, reject, partial fill, stale quote, risk breach, credential failure, or reconciliation delta triggers alert and pause/halt policy. Secrets use a dedicated secret store/process boundary with rotation and least privilege. Observe approval, level, exposure, order states, broker latency, unknown age, fill/cost, reconciliation, halt, and incident metrics; redact identifiers as required.

## Migration and rollback

Start at L0 and return to Phase 08 paper/read-only on any failed check. L1/L2 require explicit promotion records and can be disabled by revoking the write flag/credential. Persistent halts and outbox/events remain for reconciliation. Scope expansion or automation requires a new gate; no rollback deletes history.

## Acceptance and gate

Pass requires L0 observation, L1 human-approved fake/sandbox/live-pilot evidence as authorized, L2 allowlist checks if approved, incident/kill/reconciliation drills, and reviewer authorization. `fail` or `insufficient_evidence` returns to paper/read-only; no mandatory live gate waiver exists.
