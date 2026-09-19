---
name: exact-head-review
description: Independently review one exact myTradingAlpha PR head, verify RED/TDD evidence and acceptance criteria, and produce a durable structured verdict.
---

# Exact Head Independent Review

For native independent review, use a fresh reviewer context different from the implementer. Inspect
repository/diff evidence, not summaries. The separate `DEGRADED_MASTER_REVIEW` path is Master-owned
Harness-only maintenance and may be used only under its explicit fallback contract.

## Isolation requirement

Default to a detached isolated Git worktree for RED replay and final validation. Allocate a session-specific
`allowed_root` and pass it to `scripts/review_worktree.py create --sha <full-sha> --path <temporary-path>
--allowed-root <session-specific-root>` and the matching `remove`. The worktree is read/execute-only: it
does not authorize a writer, commit, push, repair, or merge.

If marker, registration, HEAD, or cleanliness validation fails, fail closed and preserve the directory and
registration for human recovery. Do not use force or automatic pruning. If equivalent non-destructive
isolation cannot be established, return `INSUFFICIENT_EVIDENCE` and preserve the directory for manual recovery.

## Degraded Harness-only review

Native host-enforced read-only independent review remains preferred and is required for roadmap/product,
broker, paper and live, promotion, externally consequential, and critical-safety work. When native
admission is unavailable, the degraded Master path may be used only for explicitly per-task human-authorized
Harness-only maintenance. It is not an independent reviewer artifact or verdict.

The Master reviews the complete exact head, replays RED, runs complete local validation/required CI,
discloses every missing runtime fact, and refuses on unresolved BLOCKER/HIGH or material uncertainty. It
must not fabricate reviewer, model, isolation, or runtime telemetry. Record separate assurance, authorization,
native-admission limitation, exact head, RED replay, validation/CI, missing evidence, findings, and
`DEGRADED_MASTER_REVIEW|DO NOT MERGE`; this path cannot authorize roadmap/product, broker, paper and live,
promotion, or critical-safety work.

## Review procedure

1. Fetch current main/PR and record exact base/head SHAs.
2. Read applicable root/scoped instructions, JIT, roadmap/phase docs, and state evidence.
3. Inspect every changed filename and the complete final diff.
4. Verify base-to-RED is test/fixture-only and reproduce its focused failure in isolated evidence space.
5. Validate the exact final head in the same isolation model.
6. Inspect tests, determinism, negative cases, regressions, validation/CI, compatibility, security,
   persistence/network, and safety/promotion boundaries.
7. Compare the final diff with JIT scope and identify leakage or undocumented deviation.
8. Reconcile required CI and the bounded canonical writer-lease artifact with Git evidence. Missing or
   ambiguous lifecycle evidence is `INSUFFICIENT_EVIDENCE`.

## Findings and durable verdict

Classify `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, or `NIT`; unresolved BLOCKER/HIGH means `REQUEST CHANGES`.
Return PR/base/head, reviewer role/configured route, isolation, JIT reference, RED verdict, findings,
acceptance matrix, scope/safety verdicts, and `APPROVE|REQUEST CHANGES`. The Master persists the artifact
in the PR conversation; any later commit makes approval stale.
