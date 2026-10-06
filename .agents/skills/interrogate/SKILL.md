---
name: interrogate
description: Apply a supplemental adversarial pass that looks for assumptions, failure cases, scope leaks, and broken safety boundaries.
---

# Interrogate

Use this skill to challenge a design or diff before handing it to the repository's required independent reviewer.

1. State the intended behavior and the in-scope files.
2. Read the actual design, code, tests, and JIT contract.
3. Ask how each key assumption could be false. Check malformed input, failure paths, stale evidence, concurrency, compatibility, and side effects where relevant.
4. Report each finding with a severity, file or contract location, and concrete evidence. Separate a real defect from a question or low-priority concern.
5. Do not edit the implementation or silently apply a proposed repair.

This pass is supplemental. It is not independent review, does not authorize progression, and never replaces `exact-head-review`, RED replay, exact-SHA CI, or the Master merge gate. Do not spawn reviewers or claim model independence.
