---
name: productionization-preflight
description: Reconcile GitHub, main, roadmap state, current code, applicable instructions, and adversarial risk tags before a myTradingAlpha productionization PR or bounded remediation task.
---

# Productionization Preflight

Use before the JIT scope contract or any productionization edit. This procedure supplies evidence; root
`AGENTS.md` and scoped instructions remain authoritative.

## Procedure

1. Fetch/sync current `main`; record its exact SHA and confirm the worktree/branch will not overwrite
   unrelated changes.
2. Read root `AGENTS.md`, then explicitly read every deeper `AGENTS.md` applicable to an in-scope path that
   is outside the project-root-to-current-working-directory chain. The instruction chain stops at the CWD.
   Opening/editing a file does not by itself prove its instructions loaded.
3. Read and reconcile `docs/productionization/AGENT_STATE.md` with current GitHub PR/merge/check evidence;
   GitHub/current main wins.
4. Confirm the authorized PR or bounded Harness scope; do not infer authority for a later slice.
5. For roadmap work, read its plan row, complete phase DESIGN/IMPLEMENTATION, and applicable appendices.
6. Inspect actual files/symbols/APIs, tests, package/runtime touchpoints, validation, and CI; record drift,
   dependencies, compatibility, side-effect boundaries, non-goals, and rollback.
7. Build a boolean `risk_profile` using exactly these tags: `untrusted_input`,
   `serialization_canonicalization`, `secret_redaction`, `temporal_provenance`, `resource_complexity`,
   `concurrency_idempotency`, and `external_side_effect`. Do not set a tag false merely because the edit
   is small.
8. If **any** risk tag is true, before RED/GREEN implementation the Master runs a fresh read-only
   `boundary_reviewer` on the same base SHA. Its adversarial contract matrix maps each true tag to concrete
   attack/failure cases, invariants, and closure evidence. An unavailable required lane is
   `insufficient_evidence`.
9. Optional `code_explorer`/`test_auditor` lanes may run independently; they add evidence and do not
   replace the controlling reviewer. Classify risk and select the least expensive adequate
   named route under root policy.
10. For a fresh writer, confirm the lease helper/skill comes from trusted refreshed main, the exact lane
    identity, and no previous writer remains active. The Master acquires before the writer; preflight and
    ordinary CI do not authenticate live state.

## Adversarial tag intent

Use the matrix for hostile object/callback or malformed input (`untrusted_input`), canonical bytes,
Unicode, escaping, and mutable-after-hash (`serialization_canonicalization`), encoded/nested secrets
(`secret_redaction`), chronology/cutoff/revision (`temporal_provenance`), bounded work and input size
(`resource_complexity`), races/retries/duplicates/state transitions (`concurrency_idempotency`), and
denied network/persistence/provider/broker/file/process effects (`external_side_effect`).

## Output and stop rule

Return base SHA, instructions/docs, current drift, paths, prerequisites, complete risk profile, boundary
review/matrix reference, class/routes, validation surfaces, lease readiness, blockers, and whether JIT is
safe. If a required role, prerequisite, architecture resolution, adversarial closure, or human gate is
missing, return `insufficient_evidence`/blocked; do not invent a resolution. Shift-left evidence is not a
replacement; do not replace the controlling exact-head reviewer.
