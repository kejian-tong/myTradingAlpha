---
name: exact-head-review
description: Independently review one exact myTradingAlpha PR head, verify RED/TDD evidence and acceptance criteria, and produce a durable structured verdict.
---

# Exact Head Independent Review

Use a fresh reviewer context different from the implementer. Inspect repository/diff evidence, not
summaries. Do not edit files, repair, commit, push, merge, or delegate; only the Master may make the final
merge decision.

## Isolation requirement

Use a detached isolated Git worktree for RED replay and final validation. Allocate a session-specific
`allowed_root` and pass it to `scripts/review_worktree.py create --sha <full-sha> --path <temporary-path>
--allowed-root <session-specific-root>` and the matching `remove`. The worktree is read/execute-only: it
does not authorize edits, a writer, commit, push, repair, merge, or delegation. Record exact candidate SHA
and cleanliness before and after review. Any mutation, SHA drift, unexpected ref movement, or unclean state
is a blocking finding; preserve the worktree for human recovery.

If marker, registration, HEAD, or cleanliness validation fails, fail closed and preserve the directory and
registration for human recovery. Do not use force or automatic pruning. If equivalent non-destructive
isolation cannot be established, return `INSUFFICIENT_EVIDENCE` and preserve the directory for manual recovery.

Missing host-origin sandbox/profile/approval evidence or a complete tool inventory is supplemental
disclosure and does not itself block review. Never present configuration, model prose, caller JSON, hooks,
telemetry, or an offline verifier as authenticated runtime identity or isolation. A missing required role,
observed mutation, contradictory runtime evidence, stale head, dirty isolation, unresolved BLOCKER/HIGH,
required CI failure, or human paper/live/promotion gate remains fail-closed.

## Review procedure

1. Fetch current main/PR and record exact base/head SHAs.
2. Read applicable root/scoped instructions, JIT, roadmap/phase docs, and state evidence.
3. Inspect every changed filename and the complete final diff.
4. Verify base-to-RED is test/fixture-only and reproduce its focused failure in isolated evidence space.
5. Validate the exact final head in the same isolation model and re-check SHA and cleanliness afterward.
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
