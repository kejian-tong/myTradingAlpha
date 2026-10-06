---
name: why
description: Explain why repository behavior or design exists using source history, tests, docs, and authorized PR evidence.
---

# Why

Use this skill to investigate the motivation behind a repository design or behavior. Use repository evidence only, including authorized Git and PR records for this repository.

1. Identify the code, test, or design decision in question.
2. Read the current implementation and the constraints recorded in nearby docs and tests.
3. Use `git log`, `git blame`, commit messages, and authorized PR discussion when they can establish the change history.
4. Label direct evidence separately from inference. A commit that changed code does not prove why it changed unless its record says so.
5. Report unresolved questions as unknown. Do not search external chat, ticket systems, observability tools, or analytics sources through this skill.

Keep the answer bounded to the question. Cite repository paths, symbols, commit SHAs, or the relevant PR record.
