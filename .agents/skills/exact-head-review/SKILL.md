---
name: exact-head-review
description: Independently review one exact myTradingAlpha PR head, verify RED/TDD evidence and acceptance criteria, and produce a durable structured verdict.
---

# Exact-Head Independent Review

Use only in a fresh reviewer context different from the implementer. Review repository/diff evidence,
not the implementer's summary.

## Review procedure

1. Fetch current main and PR; record exact base and head SHAs.
2. Read applicable root/scoped `AGENTS.md`, JIT contract, roadmap/phase docs, and relevant state entry.
3. Inspect every changed filename and the complete final diff.
4. Verify the dedicated RED history: base-to-RED should contain only appropriate tests/fixtures/test
   harness; reproduce the recorded focused RED failure in an isolated non-destructive worktree when
   practical.
5. Inspect focused tests and material existing regressions for negative cases, determinism, tautology,
   missing boundaries, and validation/CI coverage.
6. Trace applicable architecture, compatibility, temporal, numerical, accounting, idempotency,
   reconciliation, credential, security, persistence/network, and paper/live invariants.
7. Compare final diff with the durable JIT contract and identify scope leakage or undocumented deviation.
8. Inspect required CI/check evidence for the exact head; never reuse green checks from an older SHA.

## Findings and verdict

Classify findings `BLOCKER`, `HIGH`, `MEDIUM`, `LOW`, or `NIT`. Any unresolved BLOCKER/HIGH means
`REQUEST CHANGES`. Do not repair code in the controlling review context.

Return a structured artifact containing:

- PR ID/number and exact reviewed base/head;
- reviewer role/config and configured model/effort;
- JIT artifact reference;
- RED evidence `PASS|FAIL|INSUFFICIENT_EVIDENCE`;
- findings with file/evidence references;
- acceptance matrix;
- scope-leak and safety-gate verdicts;
- final `APPROVE|REQUEST CHANGES`.

The master must persist the artifact in the GitHub PR conversation before merge. A later commit makes the
approval stale and requires fresh exact-head review. Reviewer approval never authorizes merge by itself.
