---
name: principles-verification
description: Verify engineering behavior against the real artifact with focused tests and checks that expose observable results.
---

# Verification principles

Apply these principles before reporting a task as complete.

- Inspect or run the real artifact. A successful compile, cached result, or self-report does not prove the intended behavior.
- Test the observable contract with concrete inputs and expected results. A caller can observe return values, errors, readable state, and effects at an external boundary. Private helpers, internal call order, intermediate values, and collaborator choices are implementation details unless the contract exposes them.
- A denied-effect assertion can prove a contract such as "no request is sent" or "no row is written." Pair it with a positive control that demonstrates the test detects the effect when the permitted case should produce it. Assert a stated invariant directly when the invariant itself is the contract.
- Check that a test detects a broken behavior and still passes when internal structure changes but the observable result stays the same. Avoid assertions that only repeat constants or implementation details.
- Break multi-step work into units that each end in a check. Do not build on a failed unit.
- Use deterministic repository tests for contracts and safety boundaries. Do not replace them with live services or unbounded external state.
- Re-run evidence made stale by a later commit. Review and CI must apply to the exact candidate SHA.
- Report the command, exit status, and result. Name missing evidence and unresolved failures.

Follow the repository's TDD and exact-head review skills for their required procedures. This principle does not replace either gate.
