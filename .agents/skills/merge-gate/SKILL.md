---
name: merge-gate
description: Perform the final master-owned exact-head merge decision for an authorized myTradingAlpha PR after implementation and independent review are complete.
---

# Master Merge Gate

Use only from the master/orchestrator after the candidate head is frozen and all required evidence has
been collected. This skill does not create authorization; it checks an already authorized merge scope.

## Required checks

Verify independently:

1. final base/head SHAs and the exact authorized PR/scope;
2. durable JIT contract matches the final diff and no later roadmap slice leaked in;
3. one production writer was active at a time and any replacement writer started only after the prior
   writer stopped;
4. required RED/GREEN/repair evidence is durable and consistent with Git history;
5. controlling independent reviewer inspected the exact final head and returned APPROVE;
6. every material specialist BLOCKER/HIGH is closed on the exact final head;
7. required focused/full validation and GitHub CI/CodeQL/Dependency Review pass for the exact final head;
8. backward compatibility, dependency direction, packaging/import, migration/rollback, and relevant
   security/side-effect boundaries remain valid;
9. no required role/runtime evidence is contradictory or `insufficient_evidence`;
10. no explicit human paper/live/promotion gate is being crossed.

## Durable artifact

Before autonomous merge, persist a GitHub PR-conversation artifact containing PR ID, final head/base,
complexity/route, JIT reference, implementer/reviewer configured routes, RED evidence, independent review
reference, validation/CI, scope/compatibility, unresolved non-blocking findings, and final
`MERGE|DO NOT MERGE` verdict.

## Decision

Merge only when every required item passes. Use the repository's permitted merge method and bind the
operation to the expected final head SHA so a moved head cannot be merged accidentally.

If any BLOCKER/HIGH, attributable required-CI failure, stale approval/check, scope leak, missing role,
architecture conflict, permission problem, or human promotion gate remains, return `DO NOT MERGE` and
stop rather than weakening the gate.

After merge, refresh main and reconcile the actual merge SHA before beginning any separately authorized
next roadmap slice.
