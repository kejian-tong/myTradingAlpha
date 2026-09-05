# Hybrid Concurrent Agent Execution Protocol

Status: execution-harness policy. This document supplements root `AGENTS.md` and
`AGENT_AUDIT_PROTOCOL.md`. It does **not** change production architecture, roadmap dependencies, or the
47 implementation PR definitions.

## 1. Goal

Use Codex concurrency where work is genuinely independent while preserving deterministic ownership of
production changes.

The default operating principle is:

> **Parallel reads and independent review; serialized production writes.**

This protocol improves pre-flight discovery and review coverage without allowing multiple agents to
race on the same implementation branch or weaken exact-head auditability.

## 2. Non-negotiable ownership rules

For one active roadmap PR:

- the master/orchestrator remains the decision owner and final merge gate;
- at most **one production-code writer** may be active at a time;
- RED, GREEN, REFACTOR, and each repair cycle are owned by one named implementer/repair implementer;
- read-only specialists may run concurrently when their questions are independent;
- the controlling reviewer follows the recorded route using `reviewer_high` or `reviewer_xhigh`;
- specialist reviews add evidence; they do not replace the controlling independent-review artifact;
- no agent may start a dependency-ordered later roadmap PR before the current PR is merged;
- no concurrency rule waives paper/live or other explicit human promotion gates.

Do not parallelize two production writers against the same PR merely to increase throughput. If a
future task is truly decomposable into isolated worktrees and disjoint write ownership, that requires an
explicit JIT decision by the master; it is not the default roadmap workflow.

## 3. Concurrency budget

Project config currently uses:

```toml
[agents]
enabled = true
max_concurrent_threads_per_session = 4
```

Treat this as a **concurrently open spawned-thread guardrail**, not a total-per-PR or lifetime spawn cap.
The master/root context is separate from these spawned-agent slots.

The harness does not impose a numeric maximum on cumulative implement/review/repair cycles. Continue
only while each cycle produces new evidence toward closure. Existing `AGENTS.md` stop conditions still
apply; repeated repair is not permission to lower tests, ignore findings, or force a PASS.

When a subagent's result has been collected and no follow-up is expected, close that completed thread so
it does not occupy a concurrency slot unnecessarily.

## 4. Named specialist roles

| Role | Route | Mode | Primary purpose |
| --- | --- | --- | --- |
| `code_explorer` | GPT-5.6 Luna / max | read-only | current code paths, symbols, interfaces, doc/code drift |
| `test_auditor` | GPT-5.6 Luna / max | read-only | TDD contract, tests, negative cases, validation and CI |
| `boundary_reviewer` | GPT-5.6 Sol / high | read-only | architecture, scope, compatibility, security and side-effect boundaries |

Writer and controlling-review routes:

- `normal_implementer` — Luna/max;
- `high_implementer` — Sol/high;
- `critical_implementer` — Sol/xhigh;
- `reviewer_high` — Sol/high;
- `reviewer_xhigh` — Sol/xhigh (critical/adjudication role);
- hardest route: `critical_implementer` — Sol/xhigh plus fresh `reviewer_xhigh` — Sol/xhigh;

Normal and high share the initial Luna/max writer plus Sol/high reviewer. For high work,
implementation-only escalation replaces the writer with `high_implementer`; review-only escalation
retains the Luna writer and replaces the reviewer with `reviewer_xhigh`; both changes select the
difficult route. Normal does not escalate without reclassification evidence.

Select the least expensive adequate route under AGENTS.md Section 5.2.1. Review-only escalation
retains the existing implementer. Keep normal/high/critical risk classification and its gates. A
replacement writer never runs alongside the previous writer. The concurrency budget is unchanged.

## 5. Phase A — concurrent pre-flight before JIT

After reconciling current `main`/GitHub and selecting the next dependency-valid PR, the master may spawn
up to three independent read-only specialist lanes concurrently:

1. `code_explorer` — map current implementation reality and doc/code drift;
2. `test_auditor` — map existing test/CI evidence and propose the smallest observable RED contract;
3. `boundary_reviewer` — identify architecture/scope/security/compatibility constraints.

Use only lanes that have material independent work. Do not spawn agents merely to fill available slots.
For a tiny docs-only PR, one or zero specialist lanes may be sufficient.

All pre-flight lanes inspect the same reconciled base SHA. The master waits for the required lanes,
deduplicates/conflict-checks their evidence, resolves ordinary differences through repository evidence,
and then writes the controlling JIT Implementation Spec / Scope Contract.

If specialist reports reveal a material architecture conflict that the approved docs/current code do
not resolve, follow the existing stop condition instead of letting agents vote on a redesign.

## 6. Phase B — serialized TDD implementation

After the JIT spec is durable:

1. spawn exactly one named implementer appropriate to the classified complexity;
2. create durable test-only RED evidence where executable TDD applies;
3. perform minimum GREEN implementation;
4. REFACTOR only within the JIT boundary;
5. run required local validation;
6. freeze an exact candidate PR head for independent review.

Read-only specialists may answer narrowly scoped questions during implementation, but they must not
write production code or become a second implementer.

## 7. Phase C — concurrent exact-head review

Once a candidate PR head is frozen, review lanes may run concurrently **against the same exact SHA**.

Required lane:

- controlling reviewer named by the complexity and recorded model tier.

Default specialist lanes when material to the PR:

- `test_auditor` for RED/TDD/test/CI quality;
- `boundary_reviewer` for architecture/scope/security/compatibility boundaries.

`code_explorer` is normally a pre-flight role and should not be spawned again unless the final diff
requires fresh call-path/current-state tracing.

The master collects all lane results and performs triage. Specialist findings use the same severity
vocabulary (`BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, `NIT`). An unresolved `BLOCKER` or `HIGH` from **any**
lane blocks merge even if the controlling reviewer otherwise approves.

The durable independent-review artifact required by `AGENT_AUDIT_PROTOCOL.md` is still produced by the
controlling reviewer. Before it is persisted/finalized, the master should provide or reconcile material
specialist findings so the controlling artifact reflects the complete exact-head evidence set.

## 8. Repair and re-review loop

If triage finds a material defect:

1. mark all affected prior exact-head evidence stale after the next commit;
2. classify/escalate complexity from the actual defect, not merely the number of review rounds;
3. spawn **one** appropriate repair implementer;
4. use repair RED -> repair GREEN when the defect is executable/testable;
5. run validation and freeze the new exact head;
6. spawn a fresh controlling reviewer;
7. re-run every specialist lane that found a prior BLOCKER/HIGH or whose boundary was changed by the
   repair;
8. optionally omit unaffected specialist lanes when the master can prove their evidence remains
   irrelevant to the changed surface — but never reuse an old exact-head approval as approval of the
   new SHA.

For ambiguity, advance review only as evidence requires:
`reviewer_high -> reviewer_xhigh`.
Re-review count alone does not make a PR `critical` or justify Astra. Safety classification remains
tied to correctness/external-effect risk under `AGENTS.md`; route escalation requires a separate
recorded reason.

There is no fixed `N` for repair/re-review attempts. Continue only while the scope remains valid and the
system is converging. Stop under the existing autonomous stop conditions when evidence cannot be made
sufficient without redesign, scope leakage, unavailable required roles, unresolved BLOCKER/HIGH, or a
human gate.

## 9. Master synthesis and merge gate

The master does not delegate final ownership. Before merge it must independently confirm:

- the JIT contract matches the final diff;
- the single-writer rule was preserved;
- required RED/GREEN evidence is durable;
- controlling reviewer inspected the exact final head;
- all material specialist BLOCKER/HIGH findings are closed on the exact final head;
- required CI is green for the exact final head;
- architecture/scope/backward compatibility remain valid;
- the required master merge-gate artifact is durable.

Only then may autonomous mode merge an ordinary roadmap PR.

## 10. Recommended lifecycle

```text
                          MASTER / Sol xhigh
                               |
              +----------------+----------------+
              |                |                |
              v                v                v
        code_explorer      test_auditor   boundary_reviewer
         read-only          read-only         read-only
              |                |                |
              +----------------+----------------+
                               |
                    Master synthesizes JIT
                               |
                               v
                       ONE IMPLEMENTER
                    RED -> GREEN -> REFACTOR
                               |
                        freeze exact head
                               |
              +----------------+----------------+
              |                |                |
              v                v                v
       controlling         test_auditor   boundary_reviewer
         reviewer           read-only         read-only
              |                |                |
              +----------------+----------------+
                               |
                         Master triage
                         /           \
                   finding           clean
                      |                |
                      v                v
              ONE repair writer   Master gate
              RED -> GREEN            |
                      |             exact CI
                new exact head         |
                      |               MERGE
                fresh re-review
```

This is a hybrid-concurrent workflow, not a multi-writer workflow.

## 11. Activation and migration

This policy is prospective. Running agents keep their loaded routes; prior model/review evidence is
not relabeled. After this independent harness PR merges, refresh the relevant checkout with `main`
and start a **fresh master session** to load the new configuration. A paused PR may resume with new
agents after its stop conditions are resolved; do not require a blocked PR to merge before this
harness update. Verify named-role availability on resume and record actual loading evidence.

No production/runtime migration is involved. Rollback is simply reverting this harness/config change;
production code and roadmap architecture remain unchanged.
