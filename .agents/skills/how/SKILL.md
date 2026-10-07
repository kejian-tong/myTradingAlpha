---
name: how
description: Explain how repository code works, including call flow, ownership, data movement, and failure boundaries.
---

# How

Use this skill to explain current repository behavior before or during an authorized change.

1. State the question and the bounded part of the system you will inspect.
2. Read the current source, tests, configuration, and docs that describe that path.
3. Trace the entry point through the important calls, data shapes, owners, and errors.
4. Separate observed behavior from inference. Cite paths and symbols so a reader can verify each claim.
5. Stop when the question is answered. Name any gap that the repository cannot resolve.

Use read-only inspection for a walkthrough. Do not edit files, create a worktree, start an agent, or run external services for an explanation. If the user also requested a change, carry the findings into the authorized implementation workflow and repository TDD procedure.
