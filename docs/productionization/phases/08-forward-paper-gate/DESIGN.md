# Phase 08 — Forward Paper Gate Design

Status: planned. This phase runs the complete candidate path for 8–12 weeks to test operational reliability before any live pilot.

## Goals

- Capture daily close inputs and run the same evidence, signal, allocation, risk, OMS, paper, and reconciliation path.
- Measure latency, missingness, alerts, approvals, fills, costs, incidents, and rerunability across real sessions.
- Produce a complete `GateEvidence` decision for Phase 09 review.

## Scope

Forward scheduler, daily bundle capture, approved external PAPER endpoint or local paper fallback, ledger/NAV, reconciliation, weekly review, incident records, and promotion decision.

## Non-goals

No live-broker writes, unattended automation, leverage, broad universe, or claim that 8–12 weeks establishes durable alpha. Live promotion is a separate Phase 09 approval.

## Dependencies

Depends on Phase 07 OMS/paper/reconciliation and Phase 06 sealed experiment/gate evidence. Current CLI/report seams are [`cli/main.py`](../../../../cli/main.py), [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py), and graph execution in [`trading_graph.py`](../../../../tradingagents/graph/trading_graph.py#L350-L500).

## Components and dataflow

```text
session calendar -> close capture -> immutable EvidenceBundle
  -> Quant/Research/Overlay -> allocator -> RiskEngine
  -> approved paper intent -> PaperBroker/PAPER endpoint
  -> ledger/NAV -> reconciliation -> daily/weekly GateEvidence inputs
```

Paper endpoint writes are external side effects, allowed only after explicit approval and bounded to paper. Live broker writes remain false. A missed capture or reconciliation mismatch blocks the day's promotion evidence.

## Current integration points

- [`TradingAgentsGraph.propagate`](../../../../tradingagents/graph/trading_graph.py#L350-L500) is the current run entry point but performs current-time memory resolution; forward mode must use the capture/adapter boundary.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) provides report output but not operational SLO, approval, or reconciliation records.
- [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py) is the existing config seam; new scheduler/paper settings are additive and explicit.

## Interfaces and invariants

Each session has a run ID, bundle hash, decision/earliest execution times, variant, target/risk decisions, event/fill/ledger sequence, approval, endpoint mode, reconciliation status, and incident links. Historical replay remains network-free; forward capture may use approved provider/PAPER endpoints. A no-trade/failure is recorded, not counted as a successful fill. Gate statuses are `pass`, `fail`, or `insufficient_evidence`; there is no mandatory live-gate waiver.

## Decisions and alternatives

- Operate 8–12 weeks rather than rely on a single dry run.
- Use local paper fallback when the external PAPER endpoint is unavailable, but record the mode change and do not merge results silently.
- Treat operational completeness as the gate; alpha claims remain tied to Phase 06 sealed statistics.
- Keep a human approval and review trail for every paper write.

## Failure, security, and observability

Missing/stale data, scheduler miss, LLM error/abstain, risk reject, paper endpoint timeout, unknown ACK, or reconciliation mismatch emits a reason code and blocks or pauses according to policy. Paper credentials are isolated/redacted; live credentials are unavailable. Observe session completion, capture delay, decision latency, queue/outbox, fills, costs, reconciliation, incidents, and approvals.

## Migration and rollback

Begin with one or a few symbols and local paper, then approved PAPER endpoint writes. Disable paper writes and scheduler to return to read-only; preserve bundles, events, ledgers, and incident records. A failed gate returns to paper/read-only and cannot auto-promote.

## Acceptance and gate

Pass requires 8–12 weeks of complete session evidence, repeatable captured reruns, no unexplained reconciliation breaks, reviewed risk incidents, approved paper writes only, and signed independent review. `fail` or `insufficient_evidence` blocks live work.
