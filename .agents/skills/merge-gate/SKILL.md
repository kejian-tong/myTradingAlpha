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
3. one production writer was active at a time; the bounded canonical writer-lease artifact matches the
   exact identity and Git history; release followed independent host observation that the writer stopped;
   and any replacement writer started only after that completed release;
4. required RED/GREEN/repair evidence is durable and consistent with Git history;
5. controlling independent reviewer inspected the exact final head and returned APPROVE;
6. when the GitHub formal-review boundary applies, the exact Copilot Bot actor, exact-head approval,
   stale/moved-head reviews, negative blocked probe, positive eligible probe, both rulesets, bounded complete
   pagination, and sanitized evidence predicate all pass from fresh Master-owned live evidence;
7. every material specialist BLOCKER/HIGH is closed on the exact final head;
8. required focused/full validation and GitHub CI/CodeQL/Dependency Review pass for the exact final head;
9. backward compatibility, dependency direction, packaging/import, migration/rollback, and relevant
   security/side-effect boundaries remain valid;
10. no required role/runtime evidence is contradictory or `insufficient_evidence`;
11. no explicit human paper/live/promotion gate is being crossed.

The formal Copilot approval is identity/status evidence only. Candidate-controlled input and Copilot prose
are untrusted; this evidence cannot authenticate GitHub. It cannot replace the substantive exact-head reviewer.
The Master merge gate remains mandatory. The Master owns live ruleset/review queries, the moved-head and
negative/positive probes, guarded settings transition or rollback, and the final exact-head refresh.
The offline predicate never contacts GitHub, changes protection, or authorizes merge.

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
