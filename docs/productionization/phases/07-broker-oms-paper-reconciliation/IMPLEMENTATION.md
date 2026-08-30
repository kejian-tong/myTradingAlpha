# Phase 07 — Broker, OMS, Paper, and Reconciliation Implementation

Commands are planned until exact implementation output is recorded. External PAPER writes require explicit approval and a sandbox or approved paper account; no live write is permitted.

## Ordered PR/work packages

1. **OMS-01** — lifecycle states and transition machine.
2. **OMS-02** — outbox, stable IDs, and idempotency.
3. **OMS-03** — local deterministic `PaperBroker`.
4. **OMS-04** — broker query plus approved external PAPER endpoint adapter.
5. **OMS-05** — reconciliation engine and broker snapshots.
6. **OMS-06** — scheduler, approvals, alerts, and runbook integration.

## Exact existing files to touch

- [`tradingagents/graph/trading_graph.py`](../../../../tradingagents/graph/trading_graph.py) only through a read-only decision adapter.
- [`tradingagents/agents/utils/agent_states.py`](../../../../tradingagents/agents/utils/agent_states.py) only for extraction; do not add OMS fields.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) only for additive links to event artifacts.
- [`cli/main.py`](../../../../cli/main.py) only for an additive paper command or scheduler hook; no secret logging.
- [`pyproject.toml`](../../../../pyproject.toml) only for approved client/test dependencies.

## Proposed files, classes, and APIs

- `mytradingalpha/execution/orders.py`: `OrderIntent`, `OrderAggregate`.
- `mytradingalpha/execution/events.py`: `OrderEvent`, `Fill`, `TransitionEvent`.
- `mytradingalpha/execution/state_machine.py`: `OrderStateMachine.apply()`.
- `mytradingalpha/execution/identity.py`: `ClientOrderIdFactory`, `FillIdFactory`.
- `mytradingalpha/execution/outbox.py`: `Outbox.append/claim/ack()`.
- `mytradingalpha/execution/paper.py`: `PaperBroker.submit/cancel/query()`.
- `mytradingalpha/execution/broker.py`: `BrokerAdapter.get_orders/get_fills/get_positions/submit_paper/cancel_paper`.
- `mytradingalpha/execution/reconciliation.py`: `ReconciliationEngine.compare()`.
- `mytradingalpha/execution/broker_snapshot.py`: `BrokerSnapshot.capture()`.
- `mytradingalpha/ops/scheduler.py`: `CloseScheduler.run_once()`.
- `mytradingalpha/ops/approval.py`: `ApprovalService.require()`.
- `mytradingalpha/ops/alerts.py`: `AlertRouter.emit()`.

## Schema and pseudocode

```text
intent(proposed)
 -> validate target/risk decision and policy
 -> require human approval for PAPER endpoint
 -> outbox append(client_order_id)
 -> transition submitting -> submitted
 -> endpoint result:
      ack -> acknowledged; fills -> partial/filled
      reject/expire/cancel -> terminal state
      timeout/unknown -> unknown + query-only pause
 -> reconcile broker snapshot with local ledger
```

`submit_paper` checks `mode=forward_paper`, `paper_write_enabled=true`, approved endpoint identity, and a valid approval record. A live endpoint method is not exposed in Phase 07 and `live_write_enabled` remains false. Duplicate client IDs return the existing aggregate; a conflicting payload halts.

## Red-green-refactor

1. Red: add tests for every state transition, skipped approval/risk, duplicate/conflicting IDs, timeout/unknown ACK, partial fills, paper flag default false, and reconciliation deltas.
2. Green: implement state machine, outbox/IDs, local paper, broker query/PAPER adapter, reconciliation, and scheduler in order.
3. Refactor: centralize event serialization and reason codes, keep credential process boundaries explicit, and test local/external paper contract parity.

## Exact tests and fixtures

- `tests/productionization/execution/test_state_machine.py`: all 12 statuses, valid/invalid transitions, risk/approval ordering.
- `tests/productionization/execution/test_outbox_ids.py`: duplicate/conflicting intent, restart, timeout, stable client/fill IDs.
- `tests/productionization/execution/test_paper_broker.py`: deterministic submit/cancel/query, partial fills, cost/ledger parity.
- `tests/productionization/execution/test_paper_endpoint.py`: fake/sandbox PAPER submit/cancel/query, default-false flag, credential redaction, live-write denial.
- `tests/productionization/execution/test_reconciliation.py`: matched state, missing/extra fill, cash/position/open-order delta, unknown order, restart.
- `tests/productionization/ops/test_scheduler_approval.py`: close schedule, missed session, approval expiry, alerts, duplicate run.
- Fixtures under `tests/productionization/fixtures/oms/` contain fake endpoint responses and no real secrets.

## Validation commands

```bash
python -m pytest -q tests/productionization/execution tests/productionization/ops
python -m pytest -q tests/test_reporting.py tests/test_checkpoint_resume.py
ruff check .
python scripts/check_dependency_direction.py
```

An approved sandbox command, if used, must be recorded with endpoint identity and sanitized output; never report a live broker call as a test.

## Migration and compatibility

OMS events are new append-only artifacts and do not alter current reports or memory logs. Local PaperBroker is the default test target. External PAPER adapter remains disabled until approval and `paper_write_enabled=true`; live broker methods are absent/denied and `live_write_enabled` remains false. Disable dispatcher and retain outbox/events to roll back, then reconcile before resuming.

## Definition of done

- All OMS PRs pass lifecycle, idempotency, paper, approval, and reconciliation tests.
- The full state machine includes proposed/validated/approved/submitting before submitted and unknown-ACK pause/query.
- Local paper and approved external PAPER paths share contracts; live broker write remains unavailable.
- Scheduler and alerts are dry-run verified; no credentials enter graph/logs.
- Gate status is `pass`; `fail` or `insufficient_evidence` blocks Phase 08.

## Evidence and rollback

Evidence includes transition tables, event/outbox hashes, fake/sandbox PAPER records, approval IDs, reconciliation snapshots, and test output. External PAPER side effects are stopped by disabling the flag/dispatcher; unresolved events remain paused for manual review. Rollback never blind-resubmits, deletes event history, or enables a live endpoint.
