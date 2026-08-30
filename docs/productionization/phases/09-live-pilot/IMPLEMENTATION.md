# Phase 09 — Live Pilot Implementation

Commands are planned until exact implementation output is recorded. This is the only phase that may introduce an approved live-broker write path, and it remains disabled until explicit authorization.

## Ordered PR/work packages

1. **LIVE-01** — L0 read-only live observation and credential boundary.
2. **LIVE-02** — L1 one/few-symbol human-approved canary.
3. **LIVE-03** — L2 small allowlist controls.
4. **LIVE-04** — later automation approval, kill switch, and incident drill.

## Exact existing files to touch

- [`cli/main.py`](../../../../cli/main.py) only for explicit live-level commands and safe status output.
- [`tradingagents/reporting.py`](../../../../tradingagents/reporting.py) only for evidence links; no credentials or order authority.
- [`tradingagents/graph/setup.py`](../../../../tradingagents/graph/setup.py#L113-L154) only through an adapter; no live write node.
- [`pyproject.toml`](../../../../pyproject.toml) only for an approved broker client with security review.

## Proposed files, classes, and APIs

- `mytradingalpha/ops/live/credentials.py`: `SecretProvider.get_scoped()` and redaction hooks.
- `mytradingalpha/ops/live/l0.py`: `L0Observer.snapshot()`.
- `mytradingalpha/ops/live/approval.py`: `LiveApproval.require()`.
- `mytradingalpha/ops/live/l1.py`: `L1Canary.submit_approved()`.
- `mytradingalpha/ops/live/l2.py`: `L2Canary.submit_batch()`.
- `mytradingalpha/ops/live/limits.py`: `LiveLimitPolicy.validate()`.
- `mytradingalpha/ops/live/automation.py`: `AutomationApproval.require_new_gate()`.
- `mytradingalpha/ops/live/kill_switch.py`: `KillSwitch.pause/cancel/query/plan_flatten()`.
- `mytradingalpha/ops/live/incident.py`: `IncidentCoordinator.open/escalate/close()`.

## Schema and pseudocode

```text
require Phase08 GateEvidence(pass)
L0: read account/data -> record only; never dispatch
L1/L2: validate level + allowlist + RiskDecision + human approval
    -> outbox -> broker submit -> state machine -> reconcile
on unknown ACK/risk/broker/reconcile issue:
    persistent halt -> query/cancel per policy -> human review
emergency:
    assess liquidity, open orders, positions, and reconciliation
    -> human authorizes a policy-compliant plan (may be no action)
    -> execute and reconcile; never unconditional market liquidation
```

All live writes require an explicit feature flag and approval record. No live order is created by an LLM or Research Graph node. Any future automation path must reference a new `GateEvidence` record and remain disabled by default.

## Red-green-refactor

1. Red: add tests for Phase 08 gate prerequisite, credential redaction, L0 no-write, L1/L2 approvals, allowlist escape, risk/reconciliation halt, unknown ACK, and policy-driven emergency plan.
2. Green: implement L0, L1, L2, then new-approval/kill/incident controls.
3. Refactor: isolate secret/broker client process, make level policy immutable per run, and share OMS/reconciliation code with paper.

## Exact tests and fixtures

- `tests/productionization/live/test_credentials_l0.py`: scoped secret, redaction, L0 read-only, no prompt/context leakage.
- `tests/productionization/live/test_l1_canary.py`: one/few-symbol approval, risk decision, submit/ack/fill/reject/unknown, rollback to L0.
- `tests/productionization/live/test_l2_limits.py`: allowlist, batch approval, exposure/turnover/capacity, persistent halt/restart.
- `tests/productionization/live/test_kill_incident.py`: broker outage, unknown ACK, cancel/query, liquidity/open-order/reconcile assessment, human-approved flatten plan or no action.
- `tests/productionization/fixtures/live/{l0,l1,l2,incident}.json` use fake/sandbox responses and no real credentials or fixed live risk limits.

## Validation commands

```bash
python -m pytest -q tests/productionization/live tests/productionization/execution tests/productionization/risk
ruff check .
python scripts/check_dependency_direction.py
```

Any separately approved sandbox validation must state its exact scope and sanitized result. No command should contact a live broker without explicit user/owner approval.

## Migration and compatibility

L0 is additive and read-only. L1/L2 writes are behind a false-by-default flag, scoped credentials, human approval, and Phase 08 gate evidence. Existing Research Graph behavior and paper mode remain available. Revoke the flag/credential to roll back to L0/paper; persist halts and reconcile outstanding orders before any restart.

## Definition of done

- LIVE PRs pass focused fake/sandbox tests and security review.
- L0 is read-only; L1/L2 are allowlisted and human-approved where authorized.
- Deterministic RiskEngine, OMS, outbox, stable IDs, and reconciliation remain in path.
- Kill/emergency handling is policy-driven and requires human/liquidity/open-order/reconcile assessment.
- Later automation has a new approval and remains disabled by default.
- Gate status is `pass`; `fail` or `insufficient_evidence` returns to paper/read-only.

## Evidence and rollback

Evidence includes Phase 08 gate record, level approvals, scoped credential audit, order/event/fill/reconciliation hashes, halt/incident drills, and reviewer sign-off. Rollback revokes write access, pauses/cancels/queries according to policy, reconciles, and returns to paper/L0. It never blindly resubmits or unconditionally liquidates, and it never deletes evidence.
