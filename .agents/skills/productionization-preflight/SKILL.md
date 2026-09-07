---
name: productionization-preflight
description: Reconcile GitHub, main, roadmap state, current code, applicable instructions, and adversarial risk tags before a myTradingAlpha productionization PR or bounded remediation task.
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
9. Build an explicit boolean `risk_profile` for the authorized scope using exactly these tags:
   `untrusted_input`, `serialization_canonicalization`, `secret_redaction`, `temporal_provenance`,
   `resource_complexity`, `concurrency_idempotency`, and `external_side_effect`. A tag is true when the
   proposed change creates, modifies, validates, serializes, transports, or relies on that risk surface;
   do not set tags false merely because the intended implementation is small.
10. If **any** risk tag is true, the Master must run a fresh read-only `boundary_reviewer` against the same
    reconciled base SHA **before RED/GREEN implementation**. The specialist must return a compact
    adversarial contract matrix mapping each true tag to concrete attack/failure cases, invariants, and
    required closure evidence. Incorporate material findings into the JIT and RED plan. An unavailable
    required boundary reviewer is `insufficient_evidence`; do not proceed as if the mandatory preflight
    occurred.
11. `code_explorer` and `test_auditor` remain optional preflight lanes when materially useful. They may run
    in parallel with the mandatory boundary lane when their work is independent. Specialists add evidence;
    they do not replace the controlling exact-head reviewer.
12. Classify the task `normal`, `high`, or `critical` from the resulting correctness/safety risk and select
    the least expensive adequate named production route under root policy. The risk tags inform but do not
    mechanically determine the class; document the evidence-based mapping.

## Adversarial tag intent

- `untrusted_input`: hostile/unknown external or caller-controlled values, subclass/callback/object-shape
  attacks, parser/validator boundaries, injection or malformed wire data.
- `serialization_canonicalization`: canonical bytes/hashes, schema/wire compatibility, Unicode/escaping,
  deterministic ordering, mutable-after-hash or representation ambiguity.
- `secret_redaction`: credentials/tokens/private identifiers, logging/rendering/derived artifacts,
  escaped/encoded/nested secret representations or confidentiality boundaries.
- `temporal_provenance`: availability/ingestion/event/publication timestamps, knowledge cutoffs, revision
  lineage, source manifests, replay/PIT eligibility or chronology.
- `resource_complexity`: adversarial CPU/memory/input-size behavior, recursion, pathological matching,
  bounded work, amplification or denial-of-service surfaces.
- `concurrency_idempotency`: races, retries, duplicate work, state transitions, exactly-once/idempotent
  semantics, unknown acknowledgement or reconciliation.
- `external_side_effect`: network/persistence/provider/broker/file/process writes, credentials, deployment,
  PAPER/live behavior or any action whose consequences escape the candidate's pure in-memory boundary.

## Output

Return a compact preflight record containing base SHA, applicable instructions/docs, current-state drift,
relevant paths/symbols, prerequisites, the complete `risk_profile`, boundary-review requirement/result,
adversarial matrix reference when required, risk class, requested named routes, validation surfaces,
blockers, and whether it is safe to proceed to the JIT scope contract.

Do not edit production code during this skill. If an unresolved architecture conflict, missing prerequisite,
unavailable required role, mandatory adversarial finding, or human gate blocks the task, return
`insufficient_evidence`/blocked rather than inventing a resolution.
