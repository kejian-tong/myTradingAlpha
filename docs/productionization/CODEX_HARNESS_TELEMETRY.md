# Codex Harness Telemetry

Status: execution-harness observability policy. Telemetry is advisory evidence for tuning the harness;
it does not authorize implementation, review, merge, or paper/live promotion.

## Runtime capability receipts

Lifecycle telemetry and runtime capability receipts answer different questions. The lifecycle bridge
records best-effort observations exposed by Codex hooks; `scripts/runtime_capability_receipt.py` verifies a
bounded, exact-schema receipt supplied by a caller. The receipt verifier is deliberately offline and
structural-only: it checks duplicate-free JSON, repository commit/tree binding, role TOML intent, and
declared effective capabilities, but it cannot authenticate the host runtime, validate digest provenance,
or parse Codex transcripts. A passing receipt therefore never upgrades an unobserved hook event or a
claimed model/sandbox/tool route into authenticated evidence.

Receipts must use `schema_version=1` and `evidence_source=host_runtime`, lowercase SHA-256 digest
references, exact PR/role/config identity, model/effort, an explicit legacy-sandbox or permission-profile
system, sandbox/profile/approval values, and a complete sorted unique bounded tool inventory. The caller
must supply trusted expected PR/base/head values plus the trusted expected role and trusted expected config path
separately. The verifier requires exact receipt equality,
base ancestry, checked-out expected head, matching head tree, and role TOML loaded from that exact Git tree.
Partial/promisor repositories reject before object lookup so verification cannot trigger a lazy fetch. It
rejects unknown or duplicate fields, oversized or invalid Unicode input, role/model/effort drift,
ambiguous or non-read-only local enforcement for a configured read-only role, collaboration controls,
high-capability function gateways, and external App/MCP/connector tools outside a narrow reviewed
read-only allowlist. Canonical bare and namespaced mutation/delegation aliases receive the same rejection;
read-only `list_agents` and `wait_agent` observation controls may remain visible.
Diagnostic output does not echo untrusted receipt keys or values. The verifier performs no network or
write operation and does not persist receipt data to telemetry. Invoke it only as supplemental boundary
evidence; the normal review/CI/merge gates remain required.

Host-origin sandbox/profile/approval facts and the complete tool inventory are supplemental disclosure.
Lifecycle hooks, this telemetry stream, model reports, caller JSON, static configuration, and the offline
receipt verifier cannot authenticate that boundary. Missing host evidence does not itself block review;
contradictory observed evidence or observed mutation remains a blocking finding that telemetry cannot repair.

## Hook runtime manifests

`scripts/hook_runtime_manifest.py` verifies a bounded `hook_runtime_manifest` record as a separate,
structural-only evidence surface. The exact canonical ASCII record binds a pseudonymous `session_ref`,
`pr_id`, `base_sha`, `head_sha`, `tree_sha`, and a SHA-256 `hook_config_digest` computed from the exact
head Git object for `.codex/hooks.json`. It records the declared `evidence_source`, host-reported loaded
and trusted booleans, `evidence_consistent`, and a pseudonymous `host_evidence_ref` when available.

The allowed states are `observed`, `unavailable`, `unknown`, and `contradictory`. Only complete,
consistent host-runtime evidence with loaded and trusted both true may be observed and effective.
Unavailable and contradictory evidence is always ineffective. `caller_declaration` and `none` must carry
null host fields/reference, remain unknown, and can never become effective. The verifier rejects duplicate,
unknown, sensitive, noncanonical, oversized, or Unicode-bearing input, reads the hook configuration only
from the exact Git object, and sanitizes inherited Git redirects with lazy fetching disabled.

A passing manifest is supplemental structural evidence only. It cannot authenticate the declared evidence
origin, host trust, or actual hook loading, and it never replaces required CI, exact-head independent review,
or the Master merge gate. The verifier performs no network, record generation, transcript/prompt/credential
parsing, or file writes.

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
