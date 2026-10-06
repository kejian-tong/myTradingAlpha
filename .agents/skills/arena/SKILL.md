---
name: arena
description: Compare distinct design candidates sequentially in the same context and select the option that best meets repository constraints.
---

# Arena

Use this skill when a design fork has multiple viable shapes and the choice can be compared against explicit criteria.

1. State the design question and the artifact to produce.
2. Write three to six concrete criteria from the user request, repository instructions, and current architecture.
3. Draft two or three genuinely distinct candidates sequentially in the same context.
4. Score each candidate against every criterion. Include compatibility, failure behavior, ownership, and implementation cost where they apply.
5. Select the smallest candidate that meets the contract. Carry over a useful detail only when it fits the selected shape.
6. Verify the result against the real source, tests, and JIT scope.

Do not spawn agents, create parallel candidate branches, use a multi-model panel, or describe the comparison as independent review. Keep scratch comparisons in the current context unless the authorized PR explicitly requires a durable design artifact. The controlling repository reviewer remains separate and reviews the exact final head.
