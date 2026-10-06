---
name: tdd
description: Use focused test-first development while following the repository's authoritative RED, GREEN, and commit evidence procedure.
---

# TDD

For executable changes, follow `.agents/skills/tdd-red-green-evidence/SKILL.md`. That repository skill controls the RED commit, focused failure, GREEN implementation, lease checkpoints, commit, and push.

1. Trace the intended behavior to an observable contract and choose the narrowest deterministic test.
2. Add only the focused test support needed to express the active JIT. Run it before implementation and confirm it fails for the expected missing or incorrect behavior.
3. Commit and push the dedicated tests-only RED when the repository procedure requires it.
4. Implement the smallest compatible change. Preserve the existing safety, data, and side-effect boundaries.
5. Run the focused test and applicable checks. Report exact commands and results.

Do not manufacture a failure, weaken an existing assertion, or add a test that only mirrors implementation details. If no practical deterministic test exists, use the closest repository-approved verification and explain the evidence gap.
