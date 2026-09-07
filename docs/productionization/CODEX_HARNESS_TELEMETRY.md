# Codex Harness Telemetry

Status: execution-harness observability policy. Telemetry is advisory evidence for tuning the harness;
it does not authorize implementation, review, merge, or paper/live promotion.

## Storage and exact-head safety

Use `scripts/harness_telemetry.py`. Durable records are written beneath the repository Git common
directory at `codex-harness/telemetry.jsonl`, not into the checked-out source tree. This is intentional:
observing the harness must not dirty a candidate worktree, create a new source commit, or invalidate
exact-head review.

Do not commit raw telemetry by default. Publish only deliberately summarized, non-sensitive benchmark
results through a reviewed harness PR when they change policy.

## Automatic lifecycle observations

The trusted project hooks call `scripts/codex_telemetry_hook.py` for four documented Codex lifecycle
events:

- `SubagentStart` records `agent_spawn`, role/agent type, active model when exposed, and the observed
  active-agent count after the start;
- `SubagentStop` records `agent_stop`, role/model, the observed active-agent count after the stop, and
  `duration_ms` when a matching start observation exists;
- `PostCompact` records `context_compaction` and the documented `manual` or `auto` trigger;
- `SessionEnd` writes no durable event; it synchronously removes only that session's ephemeral correlation
  state.

Start/stop/compaction telemetry hooks are asynchronous, best-effort, and fail open. SessionEnd cleanup is
a bounded synchronous best-effort cleanup and also fails open. A missing lifecycle record is an
observability gap, not proof that the event did not happen.

## Ephemeral correlation boundary

Measuring duration and concurrency requires correlating the documented lifecycle identifiers, but raw
`session_id` and `agent_id` must not become durable Harness telemetry. The bridge therefore:

1. hashes each session/agent identifier with SHA-256;
2. uses only those hashes as names beneath `codex-harness/runtime/` in the Git common directory;
3. stores only start time, role and observed model in the per-agent ephemeral JSON file;
4. removes the agent file at `SubagentStop`; and
5. removes the remaining hashed session directory at `SessionEnd`.

Raw session/agent identifiers, transcripts, prompts, assistant messages and tool inputs are not written to
these files or to `telemetry.jsonl`. Runtime correlation state is operational scratch data, not durable
evidence and must never be committed. If the runtime omits the required identifier or a start record is
missing, the bridge keeps the basic stop observation but leaves unavailable duration/concurrency fields
unknown rather than inventing them.

Because asynchronous start/stop hooks can overlap, active-agent counts are direct observations of the
hashed per-agent files visible when each hook runs. They are suitable for recent-sample peak/concurrency
tuning, not a claim of nanosecond-perfect distributed tracing.

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
thought, raw review prose, user data, environment variables, raw session IDs or raw agent IDs. The
recorder rejects arbitrary fields to keep the durable schema narrow.

## Example

```bash
python scripts/harness_telemetry.py record --json \
  '{"event":"agent_stop","role":"code_explorer","active_agents":1,"duration_ms":12500,"model":"gpt-5.6-luna"}'
python scripts/harness_telemetry.py summary
```

## Tuning decisions

Use telemetry over a meaningful recent sample rather than a single PR. In particular, keep the six-thread
concurrency cap unless repeated evidence shows materially independent lanes waiting because all six spawned
slots are occupied. A suggested trigger for considering 6 -> 8 is at least three affected PRs in a recent
10-PR sample; a cap increase still requires a separate reviewed harness change.

Model-routing benchmark policy is separate: correctness/safety eligibility comes before cost/latency.
Measured `duration_ms`, active concurrency and observed token counts make routing/concurrency decisions
better grounded, but telemetry does not by itself select a model or authorize a policy change.
