---
name: figure-it-out
description: Build a bounded and verifiable work sequence when no narrower repository workflow covers a multi-step task.
---

# Figure it out

Use this skill when a task spans several dependent steps and no narrower repository skill already defines the workflow.

1. Read the active user request, root and scoped instructions, current JIT, and relevant project docs.
2. State the completion condition as an observable result. List scope, dependencies, risks, non-goals, and required approvals.
3. Order the work so each step ends in a useful check. Put the highest-risk unknown early.
4. Keep the plan in the repository artifact authorized for the task, such as its JIT or implementation plan. Do not create a separate private decision log.
5. Complete each step only after its check passes. If evidence contradicts the plan, stop and resolve the design or authorization conflict before continuing.
6. Verify the final artifact directly. Report what passed, what failed, and what remains open.

The repository's TDD, writer-lease, review, CI, safety, and merge procedures remain authoritative. This skill creates no new authority and does not authorize later roadmap work.
