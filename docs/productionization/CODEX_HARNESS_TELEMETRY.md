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

Use `scripts/harness_telemetry.py`. Legacy lifecycle records remain in
`codex-harness/telemetry.jsonl`; explicit v2 usage observations use the separate
`codex-harness/telemetry-v2.jsonl` stream. Both are written beneath the canonical repository Git common
directory, not into the checked-out source tree. This is intentional: observing the harness must not dirty
a candidate worktree, create a new source commit, or invalidate exact-head review.

The recorder sanitizes inherited Git path redirects before resolving that directory. It retains opened
directory descriptors for every ancestor and uses no-follow, descriptor-relative operations beneath them.
Git-common discovery retains the originally inspected device, inode and file type through canonicalization;
the final opened common descriptor must match before any telemetry descendants are accessed.
Stream validation and append share one opened regular inode; entry identity, size, ancestor identity and
link count are checked before mutation. Multiply linked writable streams are rejected. Cooperating
appends use a per-stream lock with a one-second acquisition deadline checked on every retry, including a
disappearing lock. Read-only contention inspection may retry a regular zero-link snapshot after release;
ownership still requires a fresh exclusive open, and mutable evidence still requires exactly one link.
A partial tail or unresolved contention is an explicit failure. Existing unsafe or
oversized evidence is left untouched; there is no stale-lock recovery, migration or truncation.

Secure storage requires POSIX no-follow directory opens, descriptor-relative open/stat/mkdir/unlink/rmdir,
and descriptor-based directory scanning. Unsupported platforms, including native Windows Python without
these primitives, receive a bounded sanitized manual error; lifecycle hooks return silently with success.
There is no path-based write fallback. Importlib, direct CLI and unrelated-CWD runpy loading remain
supported. A runpy command-shape test on POSIX verifies loading, not Windows storage confinement.

### Legacy lifecycle stream and explicit usage v2

The legacy stream keeps its historical row shape and summary keys. Legacy token fields retain their
original meaning; missing cached-token fields are incomplete evidence, not an observed zero. The summary
reports `legacy_token_accounting_complete` alongside the compatibility totals. V2 usage totals are
returned separately under `usage_v2`; they are never added to legacy totals.
Legacy additive duration, blocking-finding and input/cache/output totals also use checked signed 64-bit
arithmetic. Overflow rejects the summary without modifying the evidence stream.
Legacy `pr_id` metadata accepts the bounded FND/PIT/SIG/BT/RSK/EXC/EXP/OMS/FWD/LIVE roadmap families,
numeric PR references and reviewed Harness identifiers. Metadata acceptance grants no execution authority.

V2 records use `schema_version=2`, `event=usage_observation`, `observed_at_ms`, and a nested `usage` object.
The usage object has a pseudonymous 64-hex `observation_ref`, non-negative `revision`, asserted
`source_kind`, `usage_scope`, `aggregation_scope`, and seven required nullable counts: input, cached input,
cache writes, both cache-write TTL components, output, and reasoning output. Null means unknown. Input
includes cached reads and writes; reasoning output is already included in output. A revision replaces its
prior snapshot. Retries of the same revision and content count once even if the observation time or key
order differs. Rebinding its source, scope, aggregation, or approved outer attribution is rejected.

Summaries partition request, turn, agent, and task usage. They count only exclusive observations and show
observed subtotals separately from complete totals; exclusions or unknown required counts make complete
totals unavailable. The 272,000-token exposure count applies only to known exclusive request-scoped input.
`over_limit_count` reports that observed subtotal and is null when there are no eligible known requests.
`request_scoped_records` and `non_request_records` disclose coverage among the latest snapshots.
`complete_over_limit_count` is null when request data is absent, unknown or excluded, or when non-request
aggregate scopes are present. `unknown_count` counts only unknown or excluded request rows; aggregate
usage never supplies an inferred request count or an observed zero exceedance count.

The benchmark derives cost estimates from caller-asserted usage and an explicitly selected dated pricing
surface; those calculations are not telemetry observations or account bills. The current
`work_codex_standard_2026_10_28` surface cites the [ChatGPT Work pricing page](https://learn.chatgpt.com/docs/pricing)
and reports subscription credits only. Current-card Enterprise USD means and completeness remain unknown
and incomplete. Do not infer realized charges from credits, API rates, model routes or telemetry gaps.

This is a schema example using illustrative caller-reported values, not an observed runtime measurement:

```json
{
  "schema_version": 2,
  "event": "usage_observation",
  "observed_at_ms": 0,
  "role": "normal_implementer",
  "model": "gpt-6-luna",
  "effort": "max",
  "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pr_ref": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "usage": {
    "observation_ref": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "revision": 0,
    "source_kind": "caller_report",
    "usage_scope": "task",
    "aggregation_scope": "exclusive",
    "input_tokens": 100,
    "cached_input_tokens": 20,
    "cache_write_tokens": 0,
    "cache_write_30m_tokens": 0,
    "cache_write_12h_tokens": 0,
    "output_tokens": 30,
    "reasoning_output_tokens": 10
  }
}
```

JSON records are limited to 16,384 bytes, each stream to 16,777,216 bytes and 10,000 nonblank records.
Metadata labels are limited to 128 UTF-8 bytes, and token measurements and derived arithmetic use the
non-negative signed 64-bit range. Diagnostics do not include untrusted values.

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

Each hook event is limited to 65,536 bytes. Per-agent scratch files are limited to 4,096 bytes and each
session may have at most 64 agent files. The bridge reads and cleans only bounded, regular files beneath
the canonical runtime directory; cleanup does not recurse. A symlink, special file, oversized state, or
unsafe directory is left untouched and causes the hook to fail open silently.

A process-shared lock in the runtime parent serializes each session's entire count/create/read/remove
transaction. It remains outside the removable session directory, so stop and SessionEnd removal cannot
split serialization from a later recreation. Count plus creation is atomic, duplicate starts preserve
the original start time, and acquisition has the same bounded deadline as stream locking. Session locks
are released before durable stream recording; a failed observation remains an observability gap.

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
  '{"event":"agent_stop","role":"code_explorer","active_agents":1,"duration_ms":12500,"model":"gpt-6-luna"}'
python scripts/harness_telemetry.py summary
```

## Tuning decisions

The current cap is eight concurrently open spawned-agent threads, raised from the previous six-thread cap
by a reviewed Harness policy change. Treat it as a maximum rather than a target, and close completed lanes
promptly. Use a meaningful recent sample to assess future concurrency changes; any further adjustment
requires a separate reviewed Harness change. Production writes remain serialized under one active writer
per PR.

Model-routing benchmark policy is separate: correctness/safety eligibility comes before cost/latency.
Measured `duration_ms`, active concurrency and observed token counts make routing/concurrency decisions
better grounded, but telemetry does not by itself select a model or authorize a policy change.
