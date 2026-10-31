# Productionization Agent State

Bounded operational snapshot; GitHub and current `main` are authoritative. Resolve any active head or gate from its PR evidence.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f`
- `last_reconciled_main_tree`: `f6a105adbe0d93917cf1a426a55b18ee5a7791a8`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-PSTACK-01536 / PR #112
- `current_phase`: bounded Harness pstack 0.15.36 synchronization; pre-merge
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `last_completed_maintenance_pr`: HARNESS-EFF-06 / PR #111 / merge `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f`
- `harness_reconciled_through`: PR #111 / merge `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f`
- `authorization`: weekly bounded pstack compatibility sync only; later roadmap slices require separate authorization
- `next_dependency`: PR #112 exact-head validation, independent review, required CI and Master gate; no result asserted

## Current maintenance

PR #112 updates the bounded compatible pstack adaptation to canonical version `0.15.36`, commit `4dd1d05818d19792e7cd6e818f1667f95f7e1dbe`, subtree `4719e1c4b4c43bac85d4206a8b41dd2899769c1c`. Its exact-base JIT and all 464 path dispositions are in the PR. Only `interrogate` receives a local skill adaptation. Its reproducible-evidence guidance preserves unexecuted material policy/security risks and the existing review gates. RED and correction history is recorded in the PR; neither validation nor approval of its final head is asserted here. The canonical source and separately frozen user fork remain distinct.

The sync changes no trading algorithm, product dependency, runtime configuration, broker behavior, credential handling, PAPER/live approval, promotion or deployment boundary. BT-06/Phase04+ is not authorized. The Master owns the scope, one-writer leases and merge decision; only the existing named repository roles and gates apply.

## Completed maintenance and roadmap references

Current reconciliation records last_completed_maintenance_pr: HARNESS-EFF-06 / PR #111 / merge `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f`.

HARNESS-EFF-06 / PR #111 refreshed on base `5647d9283b22150c1400584d8fbef7c74c6c9338` and merged at `342b31134e2c9302b5ccb4ea91cd7bc08d17cc8f`. It added verified two-runner CI partitioning and full-collection receipts. Its public final gate and completion record report 5,748 passed, 4 skipped, and 69 subtests on reviewed head `f5c5ea41382bbf3c33e1f2d5b3dc0df9185ba059` ([gate](https://github.com/kejian-tong/myTradingAlpha/pull/111#issuecomment-6540633425)). Its merge is the current main; PR #112 has its own validation gates.

HARNESS-EFF-05: PR #110 / merge `5647d9283b22150c1400584d8fbef7c74c6c9338`; recovery references, compaction and usage accounting remain linked from that PR. BT-05 / PR #104 merged at `b12bef51acd2b1ef6d6db01dede959f1dd67130f`; it added offline manifested replay/checkpointing only. Prior PR108/109 evidence remains in their GitHub PR histories.

## Boundaries and assurance

- Phase 03 remains `insufficient_evidence` until all six separately merged slices. No live broker write before Phase 09.
- SIG-04 validates caller-supplied candidates only. SIG-05 adds only in-memory deterministic shadow envelopes and authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior.
- Explicit human PAPER/live/promotion gates remain mandatory and unexercised by this maintenance sync.
- Current PR review, full local and exact-head CI, writer lifecycle and Master gate remain mandatory. BLOCKER/HIGH, dirty/stale isolation, observed mutation, missing role, or required-CI failure blocks merge.
- Host-origin assurance absence is supplemental; configured read-only intent does not authenticate runtime isolation. Writer leases are cooperative.
- Apps/Memories remain disabled; rules, permissions, OTEL, repository plugins and MCP are watch-only.

[Immutable cold snapshot (merge `300605dcbed7aff113d81fd7d709ebbabe01e61c`)](https://github.com/kejian-tong/myTradingAlpha/blob/300605dcbed7aff113d81fd7d709ebbabe01e61c/docs/productionization/AGENT_STATE.md) retains prior BT01–04, SIG and Harness recovery references/routes. Its status is historical. Use [context management](CONTEXT_MANAGEMENT.md), [state compaction](AGENT_STATE_COMPACTION.md), and [validation efficiency](VALIDATION_EFFICIENCY.md) for their respective procedures.
