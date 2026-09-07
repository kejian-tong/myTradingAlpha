# Codex Hooks Policy

Status: execution-harness policy. These hooks provide fast local feedback and advisory lifecycle
telemetry; they do not replace CI, independent review, exact-head evidence, or the master merge gate.

## Scope

The trusted project hook configuration lives at `.codex/hooks.json`. Codex may require a user to review
or trust project hooks before command hooks execute. A hook that was not loaded or trusted is not merge
evidence and must never be treated as if it ran.

The reviewed v2 hook surface is deliberately narrow:

- `SessionStart` synchronously runs `scripts/codex_hook_guard.py session-start` to validate the
  project-scoped Codex harness before substantial work begins.
- `Stop` synchronously runs `scripts/codex_hook_guard.py stop`, repeating harness consistency and
  `git diff --check` for lightweight whitespace/conflict-marker feedback.
- `SubagentStart` and `SubagentStop` asynchronously run `scripts/codex_telemetry_hook.py`, recording
  only the documented agent type/role and active model when Codex exposes it.
- `PostCompact` asynchronously records only whether compaction was `manual` or `auto`.

The two guard hooks are bounded by a 15-second timeout. The telemetry hooks are best-effort,
asynchronous, bounded by a five-second timeout, and deliberately fail open: observability must never
steer, approve, continue, block, or otherwise change an agentic turn.

The JSON configuration uses the current official hooks.json field names (`timeout`, `commandWindows`,
and `statusMessage`). Do not reintroduce older local aliases such as `timeout_sec`, `command_windows`,
or `status_message` into the JSON hook contract.

## Telemetry data boundary

Lifecycle hook input can contain session/transcript/tool context. The telemetry bridge intentionally
does **not** store transcripts, prompts, tool inputs, assistant messages, credentials, repository source,
or permission decisions. It maps only these observations into the existing Git-common-dir telemetry:

- `SubagentStart` -> `agent_spawn` with role and observed model when available;
- `SubagentStop` -> `agent_stop` with role and observed model when available;
- `PostCompact` -> `context_compaction` with `manual` or `auto` trigger.

Unknown runtime data remains unknown. Do not parse the transcript to infer hidden token counts, reasoning,
agent duration, or model routing. `scripts/harness_telemetry.py` remains the schema owner, and raw
telemetry remains outside the source worktree so observation cannot invalidate an exact candidate head.

## Authority and failure handling

Hook output is supplemental runtime evidence only. The authoritative merge requirements remain:

1. the offline harness validator and contract tests;
2. applicable focused/full validation;
3. exact-head required GitHub CI/checks;
4. fresh independent review against the final head;
5. the master merge gate and every explicit human promotion gate.

If project hooks are unavailable, untrusted, skipped, or behave differently in a particular Codex
surface/worktree, record that limitation rather than claiming a hook passed. Guard-hook failures require
repair of the underlying consistency/diff problem. Telemetry-hook failure is an observability gap, not a
reason to weaken or halt otherwise valid execution.

## Change control

Treat `.codex/hooks.json`, `scripts/codex_hook_guard.py`, `scripts/codex_telemetry_hook.py`, and
`scripts/harness_telemetry.py` as security-sensitive harness surfaces. Changes require a reviewed harness
PR, contract-test coverage, and fresh-session/project-hook loading. Do not place secrets, user-specific
absolute paths, network credentials, broker endpoints, or transcript parsing into hook commands.

Official reference:

- https://developers.openai.com/codex/hooks
