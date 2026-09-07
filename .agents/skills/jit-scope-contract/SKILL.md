---
name: jit-scope-contract
description: Build the exact just-in-time implementation scope contract for one authorized myTradingAlpha productionization PR from the reconciled current repository.
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
  escalation triggers.

## Rules

Use actual current files/APIs rather than copying stale proposed filenames mechanically. Resolve ordinary
drift with the smallest backward-compatible implementation that preserves approved architecture. Stop
for human resolution when a material architecture conflict cannot be resolved without redesign.

Persist the JIT in the PR body or another durable GitHub PR-conversation artifact before GREEN begins.
Do not pre-generate static JIT files for future roadmap slices.

For docs-only/harness-only changes, reduce the contract proportionally but keep scope, non-goals,
validation, compatibility, rollback, and why executable RED is not applicable.

The JIT grants no authority beyond the user-authorized task and cannot waive any paper/live gate.
