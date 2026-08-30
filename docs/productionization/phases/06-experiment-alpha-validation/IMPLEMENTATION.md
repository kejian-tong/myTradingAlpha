# Phase 06 — Experiment and Alpha Validation Implementation

Commands are planned until exact implementation output is recorded.

## Ordered PR/work packages

1. **EXP-01** — ExperimentSpec and registry.
2. **EXP-02** — variant matrix and seed runner.
3. **EXP-03** — walk-forward and statistical safeguards.
4. **EXP-04** — alpha report and governance.

## Exact existing files to touch

- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only through a read-only adapter to capture graph outputs.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) only for additive report links; do not reinterpret raw return reflections as alpha.
- [`pyproject.toml`](../../../../pyproject.toml) only for explicitly approved statistical tooling, with lock metadata recorded.

## Proposed files, classes, and APIs

- `mytradingalpha/experiments/spec.py`: immutable `ExperimentSpec` and `validate_preregistration()`.
- `mytradingalpha/experiments/registry.py`: `VariantRegistry.register/resolve()`.
- `mytradingalpha/experiments/matrix.py`: `ExperimentMatrix.required_variants()`.
- `mytradingalpha/experiments/seeds.py`: `SeedPlan.screen/final()`.
- `mytradingalpha/experiments/walk_forward.py`: `WalkForwardSplitter.split()` with purge/embargo.
- `mytradingalpha/experiments/bootstrap.py`: `BlockBootstrap.sample()`.
- `mytradingalpha/experiments/selection.py`: `DeflatedSharpe` and `PBOEstimator`.
- `mytradingalpha/experiments/reports.py`: `AlphaReport.render()`.
- `mytradingalpha/experiments/review.py`: `GateReviewer.record()`.

## Schema and pseudocode

```text
register(spec) before run
  -> freeze variant/universe/bundle/split/cost/seeds/holdout
  -> execute each variant x seed on identical PIT bundles
  -> compute net ledger metrics and operational completeness
  -> split walk-forward with purge + embargo
  -> bootstrap blocks; compute DSR/PBO when trial search applies
  -> keep holdout sealed until preregistered selection and code/config hashes are frozen
  -> after opening, allow read-only audit replay only; any tuning/model/metric/seed change contaminates it and requires a new holdout/experiment
  -> write immutable report + GateEvidence(pass|fail|insufficient_evidence)
```

The final report must include Cash, B&H, trend, Single Agent, No Debate, No Memory, Full Multi-agent, Quant-only, and Quant+LLM. Quant+LLM overlay error/abstain is no trade; it never selects Quant-only inside the same run.

## Red-green-refactor

1. Red: add tests for incomplete variant matrix, fewer seeds, post-registration mutation, overlapping windows, premature holdout access, post-opening write/tuning contamination, serial bootstrap, missing metrics, and forbidden promotion status.
2. Green: implement registry/matrix/seeds, split/statistics, report/governance in order.
3. Refactor: isolate metric formulas and canonical report serialization; preserve failed-run evidence and lock metadata.

## Exact tests and fixtures

- `tests/productionization/experiments/test_spec_registry.py`: preregistration immutability, required fields, variant identity.
- `tests/productionization/experiments/test_matrix_seeds.py`: nine required variants, >=10 screening, >=30 final or preregistered budget, failed-seed retention.
- `tests/productionization/experiments/test_walk_forward.py`: purge/embargo, no overlap, sealed holdout access denial, post-opening read-only audit replay, and contamination requiring a new holdout.
- `tests/productionization/experiments/test_statistics.py`: block bootstrap repeatability, DSR/PBO inputs and trial counts.
- `tests/productionization/experiments/test_reports_gate.py`: median/p5/p95/worst, all risk/trading/relative/capacity metrics, gate statuses.
- `tests/productionization/fixtures/experiments/{matrix,walk-forward,holdout-sealed}.json`.

## Validation commands

```bash
python -m pytest -q tests/productionization/experiments
python -m pytest -q tests/test_reporting.py tests/test_memory_log.py
ruff check .
python scripts/check_dependency_direction.py
```

Commands are planned. Reports must record actual output, environment/lock hash, bundle hash, and reviewer.

## Migration and compatibility

Experiments consume new ledger/bundle artifacts and leave current markdown reports unchanged. Existing graph variants remain available as named adapters. The holdout store is write-once and is not migrated in place. A failed experiment is marked failed; a corrected experiment receives a new ID/spec version.

## Definition of done

- All EXP PRs pass focused deterministic tests.
- Required baselines/ablations, seed thresholds, and cost policies are complete.
- Walk-forward purge/embargo, sealed holdout, block bootstrap, DSR/PBO are evidenced where applicable.
- Reports contain required metrics and no raw close-minus-benchmark alpha claim.
- Gate evidence is `pass`; `fail` or `insufficient_evidence` blocks Phase 07/08.

## Evidence and rollback

Evidence includes preregistration JSON, seed/variant manifests, split diagrams, statistic inputs, report hashes, holdout access logs, and reviewer record. Rollback marks candidate non-promotable and returns operations to prior approved variant; immutable failed artifacts remain available for audit. No broker or live endpoint side effect occurs.
