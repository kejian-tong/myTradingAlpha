---
name: principles-verification
description: Verify engineering behavior against the real artifact with focused tests and checks that expose observable results.
---

# Verification principles

Apply these principles before reporting a task as complete.

- Inspect or run the real artifact. A successful compile, cached result, or self-report does not prove the intended behavior.
- Test observable behavior with concrete inputs and expected results. Avoid assertions that merely repeat a constant or mirror an implementation detail.
- Break multi-step work into units that each end in a check. Do not build on a failed unit.
- Use deterministic repository tests for contracts and safety boundaries. Do not replace them with live services or unbounded external state.
- Re-run evidence made stale by a later commit. Review and CI must apply to the exact candidate SHA.
- Report the command, exit status, and result. Name missing evidence and unresolved failures.

Follow the repository's TDD and exact-head review skills for their required procedures. This principle does not replace either gate.
