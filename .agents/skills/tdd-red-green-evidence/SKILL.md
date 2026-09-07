---
name: tdd-red-green-evidence
description: Produce auditable RED to GREEN to REFACTOR evidence for one myTradingAlpha roadmap implementation or repair without widening scope.
---

# TDD RED-GREEN Evidence

Use for executable roadmap behavior after the JIT contract is durable.

## RED

1. Add only the smallest focused tests, fixtures, or deterministic test harness needed to express the
   active contract and required failure modes.
2. Run the focused command and verify it fails for the expected missing/incorrect behavior, not collection,
   syntax, dependency installation, network, or unrelated environment failure.
3. Commit and push a dedicated RED commit before production implementation.
4. Record RED SHA, exact command, exit status, and concise expected failure.

Do not weaken existing assertions to force RED. When a current roadmap slice legitimately supersedes an
absence assertion, migrate only the exact current-slice prohibition and preserve later-slice guards.

## GREEN

Implement the minimum production behavior required by the JIT and RED tests. Preserve compatibility,
side-effect boundaries, and one-writer ownership. Run the focused command and applicable validation floor.
Commit implementation separately from RED.

## REFACTOR

Simplify only within the approved JIT boundary. Do not add future abstractions, unrelated cleanup,
dependency upgrades, or later-roadmap behavior.

## Repair loop

For a material review defect, create a focused repair RED when executable, then repair GREEN. Any commit
changes the exact head, so prior review/CI evidence must be treated as stale and rerun according to the
review protocol.

## Output

Return RED and implementation/repair SHAs, exact commands/results, changed files, invariant coverage,
remaining evidence gaps, and whether focused/full validation passed.

Docs-only/harness-only work with no executable contract may state `TDD not applicable` with a specific
reason; never create a meaningless failing test solely to satisfy ceremony.
