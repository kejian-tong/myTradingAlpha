# Codex Harness Telemetry

Status: execution-harness observability policy. Telemetry is advisory evidence for tuning the harness;
it does not authorize implementation, review, merge, or paper/live promotion.

## Storage and exact-head safety

Use `scripts/harness_telemetry.py`. Records are written beneath the repository Git common directory at
`codex-harness/telemetry.jsonl`, not into the checked-out source tree. This is intentional: observing the
harness must not dirty a candidate worktree, create a new source commit, or invalidate exact-head review.

Do not commit raw telemetry by default. Publish only deliberately summarized, non-sensitive benchmark
results through a reviewed harness PR when they change policy.

## Automatic lifecycle observations

The trusted project hooks call `scripts/codex_telemetry_hook.py` for three documented Codex lifecycle
events:

- `SubagentStart` records `agent_spawn`, role/agent type, and the active model only when Codex exposes it;
- `SubagentStop` records `agent_stop` with the same narrow role/model boundary;
- `PostCompact` records `context_compaction` and the documented `manual` or `auto` trigger.

These hooks are asynchronous, best-effort, and fail open. They do not parse transcripts or store session
IDs, agent IDs, prompts, assistant messages, permission state, tool inputs, source snippets, or secrets.
A missing lifecycle record is an observability gap, not proof that the event did not happen.

## What to record

Record only facts exposed by the runtime or directly observed by the master:

- agent spawn/stop and observed peak active agents;
- role and phase completion duration when measured;
- review round and BLOCKER/HIGH count;
- exact-head invalidations and CI reruns;
- context compaction and its documented trigger when the runtime reports them;
- model/effort and input/cached/output token counts only when those values are actually exposed.

Never estimate hidden token counts, reasoning tokens, credits, model routes, latency, or concurrency and
store the estimate as observed telemetry. Unknown stays unknown.

Do not store prompts, source snippets, credentials, secrets, broker/account identifiers, model chain of
thought, raw review prose, user data, or environment variables. The recorder rejects arbitrary fields to
keep the schema narrow.

## Example

```bash
python scripts/harness_telemetry.py record --json \
  '{"event":"agent_spawn","role":"code_explorer","active_agents":2,"model":"gpt-5.6-luna","effort":"max"}'
python scripts/harness_telemetry.py summary
```

## Tuning decisions

Use telemetry over a meaningful recent sample rather than a single PR. In particular, keep the six-thread
concurrency cap unless repeated evidence shows materially independent lanes waiting because all six spawned
slots are occupied. A suggested trigger for considering 6 -> 8 is at least three affected PRs in a recent
10-PR sample; a cap increase still requires a separate reviewed harness change.

Model-routing benchmark policy is separate: correctness/safety eligibility comes before cost/latency.
Telemetry supplies measured latency/token observations to that benchmark when available; it does not by
itself select a model.
