# Phase 08 — Forward Paper Gate Implementation

Commands are planned until exact implementation output is recorded. Approved external PAPER writes may occur during operation; live broker writes remain unavailable.

## Ordered PR/work packages

1. **FWD-01** — paper environment and daily capture.
2. **FWD-02** — 8–12 week operations and reviews.
3. **FWD-03** — gate evidence and promotion review.

## Exact existing files to touch

- [`cli/main.py`](../../../../cli/main.py) for additive forward command/scheduler invocation.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) for links to daily evidence, without changing report semantics.
- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only through the forward adapter.
- [`tradingagents/default_config.py`](../../../../tradingagents/default_config.py) only for additive mode/config bridge.

## Proposed files, classes, and APIs

- `mytradingalpha/ops/forward/capture.py`: `CloseCapture.capture_session()`.
- `mytradingalpha/ops/forward/environment.py`: `PaperEnvironment.validate()`.
- `mytradingalpha/ops/forward/daily_run.py`: `ForwardRunner.run_session()`.
- `mytradingalpha/ops/forward/weekly_review.py`: `WeeklyReview.summarize()`.
- `mytradingalpha/ops/forward/incidents.py`: `IncidentLog.open/close()`.
- `mytradingalpha/ops/gates.py`: `GateEvaluator.evaluate()`.
- `mytradingalpha/ops/promotion.py`: `PromotionReview.record()`.

## Schema and pseudocode

```text
for each eligible session:
  capture -> seal EvidenceBundle -> run candidate -> require risk + approval
  -> submit to local or approved PAPER endpoint
  -> collect events/fills -> append ledger -> reconcile
  -> record daily completeness/latency/incidents

after 8-12 weeks:
  verify all required sessions and no unexplained breaks
  -> attach experiment/gate artifacts -> reviewer decision
  -> pass|fail|insufficient_evidence; never auto-promote
```

An endpoint outage may switch to local paper only with a new mode record; results from distinct paper modes are not silently pooled.

## Red-green-refactor

1. Red: add tests for capture cutoff, missed session, approved PAPER write, live-write denial, endpoint timeout, unknown ACK, reconciliation mismatch, incomplete weeks, and gate status.
2. Green: implement daily environment/runner, weekly/incident records, and gate evaluator.
3. Refactor: make session artifacts immutable, separate operational from alpha metrics, and centralize promotion policy.

## Exact tests and fixtures

- `tests/productionization/forward/test_capture_environment.py`: close capture, bundle hash, mode isolation, paper endpoint sandbox, live-write denial.
- `tests/productionization/forward/test_daily_runner.py`: one session, duplicate/missed session, approval expiry, endpoint timeout, restart.
- `tests/productionization/forward/test_reviews_incidents.py`: weekly completeness, incident open/close, reconciliation/risk escalation.
- `tests/productionization/forward/test_gate_promotion.py`: 8–12 week fixture, missing session, unexplained delta, reviewer authorization, pass/fail/insufficient evidence.
- `tests/productionization/fixtures/forward/{session-calendar,week-complete,week-incomplete,paper-sandbox}.json`.

## Validation commands

```bash
python -m pytest -q tests/productionization/forward
python -m pytest -q tests/productionization/execution tests/productionization/risk
ruff check .
python scripts/check_dependency_direction.py
```

Commands are planned; any approved PAPER sandbox run must record sanitized endpoint/result evidence and no live credentials.

## Migration and compatibility

Forward artifacts are additive and keyed by bundle/run/ledger hashes. Existing graph reports remain readable. Start with local paper, enable external PAPER only after approval, and keep live flag false. A failed gate disables paper writes/scheduler and returns to read-only; no artifact is edited to manufacture completeness.

## Definition of done

- All FWD PRs pass focused tests and a simulated 8–12 week run.
- Each session has bundle, decision, risk, approval, event/fill, ledger, reconciliation, and incident evidence.
- External PAPER side effects are bounded and approved; live write remains unavailable.
- Gate evaluator emits only pass/fail/insufficient_evidence and blocks promotion on incomplete evidence.
- Independent reviewer signs the final `GateEvidence` record.

## Evidence and rollback

Evidence includes daily bundle/ledger hashes, approval logs, PAPER endpoint records, reconciliation snapshots, SLO/incident summaries, and reviewer decision. Rollback disables scheduler and `paper_write_enabled`, returns to local/read-only, and preserves all evidence for investigation. `live_write_enabled` remains false; no live broker action is performed.
