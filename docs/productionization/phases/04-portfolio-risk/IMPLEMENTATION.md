# Phase 04 — Portfolio and Risk Implementation

Commands are planned until exact implementation output is recorded.

## Ordered PR/work packages

1. **RSK-01** — snapshot and target contracts.
2. **RSK-02** — deterministic rule allocator.
3. **RSK-03** — risk estimates and constraints.
4. **RSK-04** — shared `RiskEngine` and persistent halts.
5. **RSK-05** — optional constrained optimizer behind a separate variant.

## Exact existing files to touch

- [`tradingagents/agents/utils/agent_states.py`](../../../../tradingagents/agents/utils/agent_states.py) only for read-only context extraction; do not add portfolio/order authority.
- [`tradingagents/agents/schemas.py`](../../../../tradingagents/agents/schemas.py) only for compatibility with current rating/prose output.
- [`tradingagents/graph/signal_processing.py`](../../../../tradingagents/graph/signal_processing.py) only to keep the current string API.
- [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py) only for an additive opt-in bridge.

## Proposed files, classes, and APIs

- `mytradingalpha/contracts/portfolio.py`: shared PortfolioSnapshot/TargetPortfolio, first introduced by RSK-01.
- `mytradingalpha/portfolio/snapshot.py`: `SnapshotStore.latest()`, consuming the shared snapshot.
- `mytradingalpha/portfolio/target.py`: target validation helpers, not another wire class.
- `mytradingalpha/portfolio/allocator.py`: `RuleAllocator.allocate()`.
- `mytradingalpha/portfolio/policies.py`: `AllocationPolicy`.
- `mytradingalpha/risk/estimates.py`: `RiskEstimator.volatility/covariance/liquidity()`.
- `mytradingalpha/risk/constraints.py`: `ConstraintSet.check()`.
- `mytradingalpha/risk/exposure.py`: `ExposureCalculator.compute()`.
- `mytradingalpha/risk/engine.py`: `RiskEngine.evaluate()`.
- `mytradingalpha/risk/halts.py`: `PersistentHaltStore.activate/clear()`.
- `mytradingalpha/contracts/risk.py`: shared RiskDecision introduced by RSK-04.
- `mytradingalpha/risk/decisions.py`: ResizeLineage/decision helpers consuming that shared type.
- `mytradingalpha/portfolio/optimizer.py`: `ConstrainedOptimizer.optimize()`.

## Schema and pseudocode

```text
eligible signals -> deterministic score ordering -> RuleAllocator
  -> non-negative target weights + explicit cash -> validate target
  -> RiskEngine.evaluate(snapshot, target, policy)
     approved: create no order here; hand off to execution boundary
     resize: create constrained target with prior_decision_id -> revalidate
     rejected/halted: no intent; persist reason and halt when required

on risk exception or missing required observation:
  persist fail-closed decision -> activate persistent halt if policy requires

optional optimizer:
  maximize mu^T w - lambda_r w^T Sigma w
    - lambda_turnover ||w-w0||_1 - lambda_impact Impact(delta)
  subject to long-only/cash/name/sector/volatility/turnover/ADV constraints
  -> independent post-solve validation -> RiskEngine.evaluate()
```

The optimizer may produce only a candidate target; the same `RiskEngine` re-evaluates it. If solver timeout or infeasibility occurs, return rejected/insufficient evidence rather than silently using an unregistered alternative.

## Red-green-refactor

1. Red: add failures for negative weights, weights not summing to 1, stale marks, concentration/capacity breaches, resize without revalidation, optimizer constraint/objective mismatch, post-solve mutation, halt lost on restart, and LLM-provided constraint mutation.
2. Green: implement snapshot/target, rule allocation, estimates/constraints, persistent `RiskEngine`, then optional optimizer.
3. Refactor: centralize Decimal/tolerance handling, reason codes, and decision lineage; keep risk independent from graph code.

## Exact tests and fixtures

- `tests/productionization/portfolio/test_snapshot_target.py`: cash/positions/NAV, weight sum, allowlist, long-only schema.
- `tests/productionization/portfolio/test_rule_allocator.py`: deterministic score mapping, empty/zero scores, cash reserve, turnover cap.
- `tests/productionization/risk/test_estimates_constraints.py`: stale/missing prices, covariance edge cases, concentration, ADV, exposure.
- `tests/productionization/risk/test_engine_halts.py`: approve/reject/resize/revalidation, policy error, persistent halt restart/clear authorization.
- `tests/productionization/portfolio/test_optimizer.py`: objective terms, long-only/cash/name/sector/volatility/turnover/ADV constraints, post-solve validation, feasible/infeasible, timeout, same RiskEngine, rule comparison.
- `tests/productionization/fixtures/risk/` contains synthetic prices/volumes and no fixed live limits or credentials.

## Validation commands

```bash
python -m pytest -q tests/productionization/portfolio tests/productionization/risk
python -m pytest -q tests/test_signal_processing.py tests/test_structured_agents.py
ruff check .
python scripts/check_dependency_direction.py
```

Commands are planned; implementation reports must include policy and fixture hashes.

## Migration and compatibility

Current `PortfolioDecision` and `SignalProcessor` remain the research interface. New numeric targets are emitted as shadow artifacts first and are not added to `AgentState`. Rule allocation is the default production variant; optimizer is opt-in and separately identified. Disable the new path to return to cash/no-trade without changing existing reports.

## Definition of done

- Required baseline RSK-01 through RSK-04 passes focused tests and deterministic repeat checks.
- RSK-05 is optional and not a baseline exit prerequisite. Record `not_applicable` as criterion metadata for a preregistered rule-only configuration, never label an unimplemented optimizer PASS. Once an optimizer variant is selected, all RSK-05 tests and independent post-solve/risk checks are mandatory; failure is no-trade with no dynamic fallback. GateEvidence statuses remain pass/fail/insufficient_evidence.
- Rule allocator emits valid long-only targets with explicit cash.
- Risk handles approve, reject, resize/revalidation, and persistent halt correctly.
- Optimizer cannot bypass constraints or risk and is off by default.
- Gate evidence is `pass`; `fail` or `insufficient_evidence` blocks Phase 05/07.

## Evidence and rollback

Evidence includes target/decision hashes, property-test output, restart logs, constraint fixtures, and reviewer sign-off. Rollback disables allocator/optimizer consumers, returns to cash/no-trade, and preserves prior decisions and halt records. No broker or external endpoint side effect is authorized in this phase.
