---
name: merge-gate
description: Perform the final master-owned exact head merge decision for an authorized myTradingAlpha PR after implementation and independent review are complete.
---

# Master Merge Gate

Use only from the Master after the candidate head is frozen and required evidence exists. This procedure
checks authorization; it does not create it.

## Required checks

Verify independently:

1. exact authorized PR/base/head and JIT scope with no later-slice leakage;
2. one production writer, canonical writer-lease identity/lifecycle, dedicated branch/worktree/common
   directory, and release only after host observation that the writer stopped;
3. durable RED/GREEN/repair history and focused/full validation;
4. controlling reviewer APPROVE on the exact final head from a fresh context separate from the writer,
   with detached worktree isolation, before/after SHA and cleanliness evidence, RED replay, and complete
   validation/CI;
5. closure of every material specialist BLOCKER/HIGH and required CI/CodeQL/Dependency Review;
6. compatibility, dependency direction, packaging/import, migration/rollback, security, side-effect, and
   paper and live promotion boundaries;
7. no contradictory required evidence, observed reviewer mutation, stale head, dirty isolation, missing
   required role, or `insufficient_evidence` outside supplemental host-boundary disclosure. Missing
   host-origin sandbox/approval/tool-inventory facts alone do not block.

## Durable artifact

Persist a PR-conversation artifact containing PR ID, final/base, complexity/route, JIT, configured
implementer/reviewer routes, RED evidence, independent review reference, validation/CI, scope/compatibility,
unresolved non-blocking findings, review assurance, and `MERGE|DO NOT MERGE`. The review path records its
independent-review role/reference, exact-head isolation, and any supplemental host-boundary disclosure;
never fabricate reviewer/model fields.

## Decision

Merge only when every check passes, using the permitted method bound to the expected final head SHA. Any
BLOCKER/HIGH, attributable CI failure, stale evidence, scope leak, missing role, architecture/permission
problem, or human promotion gate means `DO NOT MERGE`. After merge, refresh main and reconcile the actual
merge SHA before a separately authorized slice.
