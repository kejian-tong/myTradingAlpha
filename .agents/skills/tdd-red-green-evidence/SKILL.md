---
name: tdd-red-green-evidence
description: Produce auditable RED to GREEN to REFACTOR evidence for one myTradingAlpha roadmap implementation or repair without widening scope.
---

# TDD RED-GREEN Evidence

Use after the JIT contract for executable behavior. Root/scoped instructions define safety and scope.

## Writer lease

The Master acquires the repository-global lease before a fresh writer starts. The writer receives only the
issued tuple and records applicable `writer_start`, `before_red`, `before_green`, `before_commit`, and
`before_push` checkpoints. The writer never acquires or releases the lease. Checkpoints are cooperative
declarations, not runtime identity/order attestation; `writer_start` is first and later checkpoints cannot
regress. Ambiguous or exhausted state fails closed.

## RED

1. Add only focused tests, fixtures, or deterministic test harness needed for the active contract.
2. Run the focused command and confirm the expected missing/incorrect behavior, not collection, syntax,
   dependency, network, or unrelated environment failure.
3. Commit and push a dedicated tests-only RED commit before production implementation.
4. Record SHA, exact command, exit status, and concise expected failure.

Do not weaken assertions to manufacture RED. Migrate an absence assertion only when the current slice owns
that behavior and preserve later-slice guards.

## GREEN and REFACTOR

Implement the minimum compatible behavior required by the JIT, preserve side-effect boundaries and single
writer ownership, then run focused and applicable validation. Refactor only inside the JIT; no cleanup,
dependency upgrade, or later-roadmap behavior. A repair uses focused repair RED -> GREEN and makes prior
affected exact head evidence stale.

Return RED/implementation SHAs, commands/results, changed files, invariant coverage, evidence gaps, and
focused/full validation. Docs-only/Harness-only work may state TDD not applicable only with a concrete
reason; never create a meaningless failing test.
