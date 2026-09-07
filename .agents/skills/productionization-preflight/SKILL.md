---
name: productionization-preflight
description: Reconcile GitHub, main, roadmap state, current code, and applicable instructions before a myTradingAlpha productionization PR or bounded remediation task.
---

# Productionization Preflight

Use this skill before writing a JIT scope contract or editing productionization code.

## Procedure

1. Fetch/sync current `main`; record its exact SHA and verify the active worktree/branch will not overwrite
   unrelated user changes.
2. Read the applicable instruction chain. Codex automatically discovers project instructions only along
   the project-root-to-current-working-directory chain and stops at the CWD. Always read root `AGENTS.md`;
   then explicitly read every deeper `AGENTS.md` applicable to any in-scope path that is not already on
   the discovered CWD chain. Opening or editing a file does not by itself prove its nested instructions
   were automatically loaded.
3. Read `docs/productionization/AGENT_STATE.md` completely and reconcile it against current GitHub PR,
   merge, and CI/check evidence. GitHub/current main wins on conflict.
4. Identify the explicitly authorized roadmap PR ID or bounded maintenance scope. Do not infer authority
   to start a later roadmap slice.
5. For roadmap work, read the assigned row in `07_PR_IMPLEMENTATION_PLAN.md`, the complete relevant phase
   `DESIGN.md` and `IMPLEMENTATION.md`, and applicable traceability/test appendices.
6. Inspect actual current files, symbols, interfaces, package/import behavior, tests, validation scripts,
   and CI surfaces touched by the proposed slice.
7. Reconcile doc assumptions with current implementation reality. Record drift rather than silently
   redesigning architecture.
8. Identify dependencies/prerequisites, compatibility constraints, side-effect boundaries, explicit
   non-goals, and later-slice deferrals.
9. Classify the task `normal`, `high`, or `critical` from actual correctness/safety risk and select the
   least expensive adequate named route under root policy.
10. When materially useful, have the master run independent read-only `code_explorer`, `test_auditor`,
    and `boundary_reviewer` lanes against the same reconciled base SHA and synthesize their evidence.

## Output

Return a compact preflight record containing base SHA, applicable instructions/docs, current-state drift,
relevant paths/symbols, prerequisites, risk class, requested named routes, validation surfaces, blockers,
and whether it is safe to proceed to the JIT scope contract.

Do not edit production code during this skill. If an unresolved architecture conflict, missing prerequisite,
unavailable required role, or human gate blocks the task, return `insufficient_evidence`/blocked rather
than inventing a resolution.
