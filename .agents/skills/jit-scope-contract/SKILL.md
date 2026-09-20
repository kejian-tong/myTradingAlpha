---
name: jit-scope-contract
description: Build the exact just-in-time implementation scope contract for one authorized myTradingAlpha productionization PR from the reconciled current repository and preflight risk evidence.
---

# JIT Scope Contract

Use after `productionization-preflight` and before GREEN. Persist one contract tied to the exact base SHA;
it narrows work and grants no authority beyond the user-authorized PR.

## Required contract

Record PR/phase/base/prerequisites; applicable root/scoped instructions, role/config, and design sources;
current drift; exact files/symbols; interfaces/invariants and failure semantics; security, network,
persistence, credentials, and external-side-effect boundaries; compatibility; non-goals/later deferrals;
migration/rollback; ordered steps; smallest RED plan and expected failure; minimum GREEN/refactor boundary;
focused/full validation; acceptance matrix; risk class/routes/escalation; complete preflight `risk_profile`;
boundary-review requirement/evidence; writer-lease lifecycle and exact dedicated lane identity; and the
assurance path.

The lane identity includes full `branch_ref`, derived `writer_lane_ref`, canonical gitdir/common-directory
membership, bounded worktree registration, and the rule that moving candidate `HEAD` is not identity. The
assurance path requires a fresh reviewer context separate from the writer, configured read-only intent,
detached exact-head isolation, before/after SHA and cleanliness evidence, RED replay, review freshness,
required CI, and a durable independent-review artifact. Record missing host-origin boundary facts as
supplemental disclosure; they do not themselves block review or replace required evidence.

For every true risk tag, add an adversarial matrix entry mapping attack/failure cases -> invariant ->
RED/validation evidence -> expected closure verdict. In other words, for every true risk tag the matrix
must show closure. Do not postpone a known preflight BLOCKER/HIGH until
final review merely because implementation has not begun.

## Rules

Use actual current files/APIs, resolve ordinary drift with the smallest compatible change, and stop for an
architecture conflict requiring redesign. For docs-only/Harness-only work, reduce the contract
proportionally but retain scope, non-goals, validation, compatibility, rollback, and why executable RED is
not applicable. Risk tags may be false only when the touched surface truly has no such risk.

The JIT cannot waive paper and live approval, fabricate runtime telemetry, authorize roadmap/product,
broker, promotion, or other externally consequential work. A material adversarial BLOCKER/HIGH that cannot
be closed inside scope blocks GREEN.
