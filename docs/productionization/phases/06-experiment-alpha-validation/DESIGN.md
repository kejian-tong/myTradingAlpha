# Phase 06 — Experiment and Alpha Validation Design

Status: planned. This phase establishes whether any observed result is reproducible, implementable, and statistically credible.

## Goals

- Register variants, seeds, data snapshots, costs, split policy, and holdout before execution.
- Compare required baselines and ablations under identical conditions.
- Use walk-forward purge/embargo, sealed holdout, block bootstrap, DSR, and PBO where applicable.

## Scope

`ExperimentSpec`, variant registry, seed runner, required matrix, walk-forward evaluator, metrics/statistics, sealed holdout access, result governance, and `GateEvidence` reports.

## Non-goals

No live promotion, broker writes, post-hoc tuning, dynamic Quant-only fallback, or claim that paper results establish durable alpha.

## Dependencies

Depends on Phase 03 ledger/metrics, Phase 04 targets/risk, and Phase 05 costs/capacity. Current project has tests and reporting but no shipped experiment runner; current graph outputs are in [`trading_graph.py`](../../../../tradingagents/graph/trading_graph.py#L350-L500).

## Components and dataflow

```text
preregistered ExperimentSpec -> variant/seed matrix -> PIT bundle replay
  -> ledger/cost/risk metrics -> walk-forward + bootstrap/DSR/PBO
  -> sealed holdout (opened only after preregistered selection is frozen)
  -> read-only audit replay -> immutable report -> GateEvidence
```

Quant-only and Quant+LLM are separate variants. Quant+LLM uses an optional overlay with attenuate/veto/abstain; failure/abstain is no trade. It never switches dynamically to Quant-only.

## Current integration points

- [`TradingAgentsGraph.propagate`](../../../../tradingagents/graph/trading_graph.py#L350-L500) runs a research graph but does not register seed/data/cost manifests.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) writes reports but does not calculate portfolio alpha/capacity metrics.
- [`pyproject.toml`](../../../../pyproject.toml) exposes open dependency lower bounds; future experiment artifacts must record environment/lock metadata.

## Interfaces and invariants

`ExperimentSpec` is immutable after preregistration. Screening has at least 10 seeds; final has at least 30 unless a budget is preregistered before inspection. Required rows are Cash, B&H, trend, Single Agent, No Debate, No Memory, Full Multi-agent, Quant-only, Quant+LLM. Walk-forward windows enforce purge/embargo; holdout remains sealed. Reports show median/p5/p95/worst and required risk/trading/relative/capacity measures. Gate status is `pass`, `fail`, or `insufficient_evidence`; no mandatory live gate waiver.

## Decisions and alternatives

- Compare a broad ablation matrix instead of a single favorable run.
- Use block bootstrap to retain serial dependence; DSR/PBO guard multiple testing.
- Keep holdout sealed and access-controlled until preregistered selection is frozen; after opening, allow read-only audit replay only. Any tuning/model/metric/seed change contaminates the holdout and requires a new holdout/experiment.
- Treat 8–12 week forward paper as operational evidence, not a replacement for alpha validation.

## Failure, security, and observability

Missing seed, bundle, metric, cost, or split evidence fails the experiment. Holdout access and preregistration are write-once/audit-logged. No credentials or raw sensitive payloads enter reports. Observe run completeness, failed seeds, data gaps, metric distributions, trial count, bootstrap seed, DSR/PBO inputs, and reviewer identity.

## Migration and rollback

Run experiments from immutable bundles and existing graph adapters; do not rewrite current reports. A failed or contaminated run is marked failed and retained. Roll back by excluding the candidate from promotion and rerunning a new versioned experiment; never alter a sealed holdout or delete failed seeds.

## Acceptance and gate

Pass requires all required variants, seed policy, cutoff-safe walk-forward, sealed holdout, statistics, costs, capacity, and complete reviewer evidence. `fail` or `insufficient_evidence` blocks forward-paper promotion.
