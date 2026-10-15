---
name: principles-design
description: Use first-principles reasoning and distinct alternatives when a repository change has multiple viable designs.
---

# Design principles

Apply these principles when a new requirement changes an existing design or when more than one architecture can meet the contract.

- Ground the design in current source, tests, callers, persisted data, and repository constraints.
- Ask what shape you would choose if the new requirement had been present from the start. Propagate the answer through the interfaces and their callers.
- Compare structurally distinct candidates when the choice is not dictated by the contract. A small variation of one candidate is not a separate design.
- Prefer clear ownership and a small stable interface over scattered rules and hidden state.
- Preserve compatibility unless the active scope explicitly permits a change.
- Treat repeated special cases, routine casts, and growing workarounds as evidence that the design may be wrong. Reconsider the shape before adding another exception.
- Choose the smallest design that satisfies the observable requirements.

Use `architect` to apply these principles to a material design decision. Use `arena` for sequential comparison in the same context.
