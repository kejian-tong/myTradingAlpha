# Hybrid Concurrent Agent Execution Protocol

This execution-harness document supplements root `AGENTS.md` and
`AGENT_AUDIT_PROTOCOL.md`. It defines scheduling only; it changes no product architecture, roadmap
dependency, safety gate, model ID, or merge authority.

> Parallel reads and independent review; serialized production writes.

## 1. Ownership rules

For one active PR, the Master/orchestrator owns scope, synthesis, and the final gate. At most one production-code writer
is active. RED, GREEN, REFACTOR, and each repair cycle have one named owner; a
replacement writer never overlaps the prior writer. Read-only specialists may run concurrently only for
independent questions, and a controlling reviewer plus specialists review one frozen exact head. No lane
starts a dependency-ordered later PR before the current PR is merged. Concurrency never waives paper and live
or another explicit human promotion gate.

Master-only delegation is a behavioral policy, not host identity enforcement. A non-master role may expose
runtime collaboration controls despite `[agents] enabled = false`; collaboration-control visibility alone
is non-blocking. Do not invoke collaboration controls or delegate nested work. Any attempted or completed
nested delegation is a blocking policy violation. Runtime-denied or no-op attempts remain blocking. Missing
observation is `insufficient_evidence`; `telemetry_conflict` is separate.

Every read-only lane requires the root native parent-admission sequence and complete host-origin evidence;
an unverified lane is discarded. `DEGRADED_MASTER_REVIEW` is an explicit per-task human-authorized
Harness-only fallback when native-admission is unavailable. It is not independent review and cannot
authorize roadmap/product, broker, paper and live, promotion, externally consequential, or critical-safety
work. See the root and audit protocol for the assurance artifact and safety boundaries.

## 2. Concurrency budget

The project configuration is:

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 6
```

Six is a concurrently open spawned-thread guardrail and burst headroom, not a lifetime or per-PR spawn
cap. The Master context is separate. Spawn only lanes with material independent work and close completed
lanes promptly. There is no fixed numeric limit on cumulative repair/review cycles; every cycle must add
evidence and must not lower tests or ignore findings.

## 3. Phase A — concurrent pre-flight

After reconciling main/GitHub and selecting the authorized PR, the Master may run independent read-only
exploration, test audit, and boundary review lanes. They inspect the same base SHA and report current files,
tests/CI, scope/compatibility risks, and any adversarial contract matrix. The Master resolves conflicts and
persists the JIT scope contract; specialists never decide architecture or authorize progression.

## 4. Phase B — serialized TDD implementation

After the JIT contract is durable:

1. Start exactly one named implementer appropriate to the risk class.
2. Verify the writer lease and dedicated lane at `writer_start`.
3. Create and push test-only RED evidence, then implement minimum GREEN behavior.
4. Refactor only inside the JIT boundary and run the local validation floor.
5. Freeze the candidate exact head for review.

Read-only specialists may answer bounded questions, but never write production code or become a second
implementer. The writer lease and evidence lifecycle are defined by the audit protocol and writer skill.

## 5. Phase C — concurrent exact head review

Once a candidate head is frozen, the controlling reviewer and relevant specialists may review concurrently
against that same full SHA. The Master reconciles findings; specialist evidence never replaces the
controlling review artifact. A new commit makes affected prior review/CI evidence stale.

## 6. Repair and re-review loop

For a material defect, mark affected evidence stale, classify the defect from actual risk, start one repair
writer only after the prior writer stops, and use repair RED -> GREEN when executable. Freeze the new head,
run required validation, start a fresh controlling reviewer, and rerun every lane whose BLOCKER/HIGH or
changed boundary is affected. Never reuse approval from an older head. Stop for unresolved severity,
architecture conflict, unavailable required role, scope leakage, or missing human gate.

## 7. Master synthesis and merge gate

Before merge, the Master independently confirms JIT scope, single-writer history, RED/GREEN evidence, exact
head review, closure of material findings, required CI, compatibility, and safety/promotion boundaries.
The durable Master gate and any degraded assurance artifact follow `AGENT_AUDIT_PROTOCOL.md`; a reviewer
verdict is eligibility evidence, not merge authority.

## 8. Lifecycle and rollback

This is hybrid-concurrent scheduling, not a multi-writer workflow. Read/review lanes can be parallel;
production writes are serialized. The policy is prospective: after this Harness change merges, refresh main
and start a fresh session. Rollback is reverting this policy/configuration change; no product/runtime
migration is involved.
