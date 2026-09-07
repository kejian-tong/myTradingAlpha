# Productionization Execution Instructions

This file applies to `docs/productionization/**` and supplements the repository root `AGENTS.md`.
The root safety, language, routing, concurrency, and merge rules remain authoritative.

## Authoritative planning sources

For productionization work, use these in order:

1. current GitHub/main and actual repository state for implementation reality;
2. `README.md` and `07_PR_IMPLEMENTATION_PLAN.md` for approved architecture and dependency order;
3. the assigned phase `phases/<phase>/DESIGN.md` and `IMPLEMENTATION.md` in full;
4. `appendices/A_REQUIREMENTS_TRACEABILITY.md` and `appendices/B_TEST_MATRIX.md` when applicable;
5. `AGENT_STATE.md` only as operational memory, never as a replacement for GitHub or approved architecture.

If current code and approved architecture materially conflict, preserve the approved invariant and stop
for human resolution when the smallest backward-compatible implementation cannot resolve the conflict.
Never silently redesign the roadmap.

## One roadmap slice at a time

Default to exactly one roadmap PR ID per implementation session. Do not start a dependency-ordered later
slice before the current slice is merged. Future files, APIs, scripts, schemas, broker capabilities, or
refactors mentioned in phase documents remain deferred unless the active PR requires them.

Before implementation, use the `productionization-preflight` and `jit-scope-contract` repo skills. The
resulting JIT contract must be tied to the exact reconciled base SHA and be durable in the PR conversation
before GREEN implementation begins.

## Durable operational state

`AGENT_STATE.md` is master-owned cross-session memory. At the start of every fresh master session:

- read it completely;
- fetch current main, relevant PRs, and checks;
- reconcile stale fields against GitHub;
- repair only fields proven stale by repository/GitHub evidence;
- continue only from the dependency-valid next PR authorized by the current task.

Keep the ledger concise and evidence-backed. Track at least base/final/merge SHAs, PR ID, complexity,
requested/configured routes, escalation reason, RED evidence when applicable, validation/CI, independent
review, master gate, scope status, blockers, and the informational next dependency-valid PR.

Do not create a state-only PR after each merge merely to update the ledger. When direct post-merge state
updates are blocked or undesirable, reconcile the prior merge in the next authorized normal branch.

## JIT and TDD evidence

Use the `jit-scope-contract` skill to specify exact files/symbols, interfaces, failure semantics,
invariants, security/network/persistence boundaries, compatibility, non-goals, migration/rollback,
validation, complexity, and named routing.

For executable behavior, use the `tdd-red-green-evidence` skill. Preserve durable RED -> GREEN ->
REFACTOR history. A dedicated RED commit must contain only tests/fixtures/test harness needed to express
the current contract. Docs-only/harness-only work may mark RED not applicable with a specific reason.
Never manufacture meaningless failing tests.

## Independent review and exact-head evidence

Use the `exact-head-review` skill for every roadmap implementation PR. A controlling reviewer is always
required and must be a fresh context different from the implementer. Specialist lanes are additional
evidence only.

Review and CI are SHA-specific. Any commit after an approval/check invalidates the affected exact-head
evidence. Re-run the required review/checks against the new final head. Persist the structured independent
review artifact in the PR conversation.

A BLOCKER or HIGH from any material review lane blocks merge until repaired and re-reviewed on the new
exact head. An APPROVE verdict makes the PR eligible for the master gate; it does not authorize merge.

## Master merge gate

Use the `merge-gate` skill before merge. The master must independently verify JIT scope, one-writer
history, RED/GREEN evidence, final-head review, final-head required CI, specialist closure, backward
compatibility, and all safety/promotion gates. Persist the master merge-gate artifact before autonomous
merge.

No execution-harness rule may waive a human paper/live promotion gate or authorize a real broker write.

## Documentation discipline

Repository-authored engineering prose stays English. Preserve immutable historical evidence rather than
rewriting prior review/model claims to match a newer harness. When a harness policy changes, apply it
prospectively to fresh sessions/spawns and leave historical actual routes intact.

Commands in phase implementation documents are plans until execution evidence exists. If a command
belongs to a later slice, record it as deferred/not applicable instead of implementing the later tooling
early.
