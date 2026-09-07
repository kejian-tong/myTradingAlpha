---
name: jit-scope-contract
description: Build the exact just-in-time implementation scope contract for one authorized myTradingAlpha productionization PR from the reconciled current repository and preflight risk evidence.
---

# JIT Scope Contract

Use after `productionization-preflight` and before GREEN production implementation.

## Required fields

Create a durable contract tied to the exact current base SHA with:

- PR ID/title, phase, base SHA, and prerequisite merge SHAs;
- applicable root/scoped `AGENTS.md`, Codex role/config, architecture/design/implementation sources;
- current-state findings and material doc/code drift;
- exact existing/new files and symbols expected;
- interfaces, schemas, invariants, and observable behavior;
- explicit failure/error semantics;
- security, network, persistence, credential, and external-side-effect boundaries;
- backward-compatibility requirements;
- explicit non-goals and later-slice deferrals;
- migration and rollback;
- ordered implementation steps;
- smallest RED test/fixture plan and expected failure;
- minimum GREEN behavior and refactor boundary;
- exact focused/full validation commands;
- acceptance matrix mapping requirement -> evidence -> expected verdict;
- `normal|high|critical` classification, named implementer/reviewer, configured routes, and evidence-based
  escalation triggers;
- the complete preflight `risk_profile` using the reviewed seven tags;
- whether adversarial boundary preflight was mandatory and, when required, the exact base SHA and
  `boundary_reviewer` evidence used;
- for every true risk tag, an adversarial contract matrix entry mapping concrete attack/failure cases ->
  invariant -> RED/validation evidence -> expected closure verdict.

## Adversarial closure rule

A true preflight tag is not a narrative warning. Before GREEN begins, its material attack/failure cases
must be represented by the JIT acceptance matrix and the smallest meaningful RED/negative validation
plan. Examples include hostile object/callback and malformed-wire probes for `untrusted_input`,
Unicode/escaping/hash determinism for `serialization_canonicalization`, encoded/nested confidentiality
cases for `secret_redaction`, cutoff/chronology mismatches for `temporal_provenance`, bounded-work cases
for `resource_complexity`, retry/race/state-transition cases for `concurrency_idempotency`, and denied or
mocked side-effect boundaries for `external_side_effect`.

If the mandatory boundary review reports a material BLOCKER/HIGH that cannot be represented and closed
within the authorized architecture/scope, stop for resolution. Do not postpone a known preflight
BLOCKER/HIGH until the final review simply because implementation has not begun.

## Rules

Use actual current files/APIs rather than copying stale proposed filenames mechanically. Resolve ordinary
drift with the smallest backward-compatible implementation that preserves approved architecture. Stop
for human resolution when a material architecture conflict cannot be resolved without redesign.

Persist the JIT in the PR body or another durable GitHub PR-conversation artifact before GREEN begins.
Do not pre-generate static JIT files for future roadmap slices.

For docs-only/harness-only changes, reduce the contract proportionally but keep scope, non-goals,
validation, compatibility, rollback, and why executable RED is not applicable. Risk tags may all be false
for genuinely non-executable documentation-only work, but the decision must follow the actual touched
surfaces rather than the PR label.

The JIT grants no authority beyond the user-authorized task and cannot waive any paper/live gate.
