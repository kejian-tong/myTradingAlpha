# Phase 04 — Portfolio and Risk Design

Status: planned. This phase turns signals into numeric targets and applies deterministic controls before any intent is created.

## Goals

- Ship a transparent rule allocator before an optional constrained optimizer.
- Represent cash, positions, exposure, concentration, turnover, liquidity, and constraints numerically.
- Enforce a shared deterministic `RiskEngine` that is independent of LangGraph, fail-closed, and persistent on hard failure.

## Scope

`PortfolioSnapshot`, `TargetPortfolio`, rule allocation, risk estimates, constraints, pre/post-trade checks, `RiskDecision` with approved/resize/rejected/halted, persistent halts, and policy-versioned observability.

## Non-goals

No LLM-generated weights, order creation, broker write, live pilot, or fixed live risk numbers. The optimizer is optional and cannot bypass the rule baseline or `RiskEngine`.

## Dependencies

Depends on Phase 02 `SignalEnvelope` and Phase 03 ledger/NAV/cost contracts. Current evidence is [`agent_states.py`](../../../../tradingagents/agents/utils/agent_states.py#L47-L76), [`schemas.py`](../../../../tradingagents/agents/schemas.py#L188-L223), and [`signal_processing.py`](../../../../tradingagents/graph/signal_processing.py#L20-L30).

## Components and dataflow

```text
PortfolioSnapshot + SignalEnvelope + PIT risk observations
  -> RuleAllocator -> TargetPortfolio
  -> estimates/constraints -> RiskEngine
  -> approved target OR resize -> revalidate -> OrderIntent boundary
  -> rejected/halted with persistent reason code
```

The LLM overlay is never an authority for weights or limits. A resize creates a new constrained target and requires a second risk evaluation referencing the prior decision.

## Current integration points

- [`AgentState`](../../../../tradingagents/agents/utils/agent_states.py#L47-L76) has reports and debate state but no cash/position/order/fill/NAV fields.
- [`TraderProposal`](../../../../tradingagents/agents/schemas.py#L121-L180) stores `position_sizing` as a string.
- [`PortfolioDecision`](../../../../tradingagents/agents/schemas.py#L188-L223) stores rating and prose rather than numeric target weights.
- [`SignalProcessor`](../../../../tradingagents/graph/signal_processing.py#L20-L30) parses a five-tier rating; it does not allocate a portfolio.

## Interfaces and invariants

`RuleAllocator.allocate()` consumes eligible signals and a snapshot and produces non-negative weights summing with cash to 1, limited to the approved allowlist and leverage policy. The optional optimizer objective is `mu^T w - lambda_r w^T Sigma w - lambda_turnover ||w-w0||_1 - lambda_impact Impact(delta)`. Its constraints include long-only `w_i >= 0`, explicit cash, per-name and sector bounds, volatility bound, turnover bound, ADV participation bound, and total-weight equality; an independent post-solve validator rechecks every constraint before the RiskEngine. `RiskEngine.evaluate()` is deterministic for a policy/snapshot/target hash. Missing/stale prices, invalid constraints, exposure/concentration/turnover/capacity violations, and active persistent halts yield rejected or halted. `RESIZE` must carry allowed weights, `prior_decision_id`, and `revalidation_required=true`; no intent is approved until the resized target passes again. Risk decisions are independent of LLM output and remain fail-closed on service errors.

## Decisions and alternatives

- Rule allocator first: transparent and easy to audit; optimizer later only as an experiment variant. The optimizer objective and constraints are explicit, and an independent post-solve validation is mandatory.
- Risk outside LangGraph: an LLM cannot prompt-inject its way past deterministic limits.
- Persistent halt store rather than process-local flags: restart must not clear a hard stop.
- No hard-coded risk percentages in documentation; deployment policy is configuration plus approval.

## Failure, security, and observability

Invalid target or policy stops intent creation. A stale snapshot, missing liquidity, solver timeout, or risk service error rejects/halt rather than assuming safety. Risk config is access-controlled and versioned; LLM and research processes cannot write it. Emit target hash, policy version, exposure/concentration, decision, reason codes, resize lineage, halt state, and evaluation latency without credentials.

## Migration and rollback

Run allocator/risk in shadow mode beside current rating decisions. Use cash/no-trade when the new path is disabled or fails. Roll back by selecting the previous approved policy or clearing only an authorized non-hard error; persistent hard halts require an explicit reviewed clear event. Existing graph reports are not rewritten.

## Acceptance and gate

Pass requires rule allocation golden/property tests, risk reject/resize/revalidation tests, persistent halt restart tests, and proof that no LLM field can alter constraints or create an intent. `fail` or `insufficient_evidence` blocks execution work.
