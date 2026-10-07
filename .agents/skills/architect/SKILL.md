---
name: architect
description: Ground and compare viable designs before a material repository change, then record the chosen interfaces and boundaries.
---

# Architect

Use this skill when a change introduces or changes an important interface, data shape, ownership boundary, or multi-module flow.

## Ground the design

Read the affected source, tests, configuration, and architecture docs. Trace current behavior and identify owners, callers, persisted data, side effects, and compatibility constraints. Treat the active JIT contract and repository instructions as fixed design boundaries.

## Compare designs

When more than one design is viable, use `arena` to compare two or three structurally distinct options sequentially in the same context. State the acceptance criteria before comparing. Do not use model panels, agent fan-out, or nested delegation.

Compare each option on:

- the smallest stable public interface;
- clear ownership of data and writes;
- compatibility with current callers and persisted artifacts;
- failure behavior and safety boundaries;
- testability and the amount of new machinery.

## Return a usable sketch

Describe the chosen types, function boundaries, data flow, failure behavior, and migration or rollback path. Mark assumptions and open decisions. Prefer the smallest shape that satisfies the contract. Repository TDD governs implementation, and the Master decides any scope or authorization question.
