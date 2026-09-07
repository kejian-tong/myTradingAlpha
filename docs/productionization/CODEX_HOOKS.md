# Codex Hooks Policy

Status: execution-harness policy. These hooks provide fast local feedback; they do not replace the
repository's CI, independent review, exact-head evidence, or master merge gate.

## Scope

The trusted project hook configuration lives at `.codex/hooks.json`. Codex may require a user to review
or trust project hooks before command hooks execute. A hook that was not loaded or trusted is not merge
evidence and must never be treated as if it ran.

The v1 hook surface is deliberately small:

- `SessionStart` runs `scripts/codex_hook_guard.py session-start` to validate the project-scoped Codex
  harness configuration before substantial work begins.
- `Stop` runs `scripts/codex_hook_guard.py stop`, which repeats the harness consistency check and runs
  `git diff --check` for lightweight whitespace/conflict-marker feedback.

Both hooks are synchronous, network-free, read-only with respect to repository contents, and bounded by
a 15-second timeout. They must not run the full test suite, contact external services, mutate Git state,
write operational memory, merge PRs, or make paper/live promotion decisions.

## Authority and failure handling

Hook output is supplemental runtime evidence only. The authoritative merge requirements remain:

1. the offline harness validator and contract tests;
2. applicable focused/full validation;
3. exact-head required GitHub CI/checks;
4. fresh independent review against the final head;
5. the master merge gate and every explicit human promotion gate.

If project hooks are unavailable, untrusted, skipped, or behave differently in a particular Codex
surface/worktree, record that limitation rather than claiming a hook passed. Continue only when the
normal non-hook evidence is sufficient. A hook failure must not be bypassed by weakening the hook;
inspect the underlying validator/diff error and repair the cause.

## Change control

Treat `.codex/hooks.json` and `scripts/codex_hook_guard.py` as security-sensitive harness configuration.
Changes require a reviewed harness PR, contract-test coverage, and fresh-session/project-hook loading.
Do not place secrets, user-specific absolute paths, network credentials, or broker endpoints in hook
commands.

Official references:

- https://developers.openai.com/codex/hooks
- https://developers.openai.com/codex/config
