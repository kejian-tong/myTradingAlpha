# Productionization Agent Runtime and Audit Protocol

Status: execution harness policy. This document does **not** change the approved productionization
architecture or the 47 roadmap PR definitions.

This protocol supplements root `AGENTS.md`. It applies prospectively to fresh roadmap-agent spawns made
after this policy is present in the trusted project checkout. A roadmap PR whose implementer/reviewer
was already running before this policy landed may finish under the prior harness; do not rewrite its
history merely to retrofit this protocol.

## 1. Codex configuration basis

Codex supports project-scoped configuration in `.codex/config.toml` and project-scoped custom agents in
`.codex/agents/*.toml`.

Official references:

- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/config-file/config-reference

For a named custom agent, the custom agent file's `model` and `model_reasoning_effort` are the routing
configuration of record. Codex documentation specifies that values set in the custom agent file take
precedence over the previously resolved spawn/default/parent values.

Therefore, when the master successfully spawns the required named project agent, record its route as
**configured actual** with the agent name and config path. UI/runtime telemetry may be recorded as an
additional observation when exposed, but lack of UI telemetry does not turn a successfully loaded named
custom-agent configuration into `unknown`.

Do not infer configured actual routing when a generic/default agent was used.

## 2. Required named roles

| Complexity | Implementer | Independent reviewer | Configured route |
| --- | --- | --- | --- |
| `normal` | `normal_implementer` | `reviewer_high` | Luna/max implementation; Sol/high review |
| `high` | `high_implementer` | `reviewer_high` | Sol/high implementation and review; Sol/xhigh review escalation when needed |
| `critical` | `critical_implementer` | `reviewer_xhigh` | Sol/xhigh implementation and review |
| existing class + `model_tier: astra_high` | `astra_high_implementer` | `reviewer_astra_high` | Astra/high implementation and independent review |
| existing class + `model_tier: astra_xhigh` | `astra_xhigh_implementer` | `reviewer_astra_xhigh` | Astra/xhigh implementation and independent review |

`gpt-5.6-sol` is the default Master and demanding-work model ID. The Master uses Sol/xhigh (Extra
High); `reviewer_high` and the boundary reviewer use Sol/high, while `reviewer_xhigh` uses Sol/xhigh.
The normal implementer, code explorer, and test auditor retain `gpt-5.6-luna` / max. GPT-6 Astra is
available through explicit high and xhigh tiers. Historical records retain the routes actually
used.

Use the least expensive adequate tier and normally escalate review in this order:
`reviewer_high -> reviewer_xhigh -> reviewer_astra_high -> reviewer_astra_xhigh`.
Record every Astra-tier reason and affected role in the JIT/state before spawning. A review-only
escalation leaves the implementer unchanged. An Astra implementer requires an independent reviewer at
the same or stronger Astra tier. Preserve the underlying normal/high/critical safety class, one writer,
and all stop conditions; escalation is not permission to choose a new architecture or pass a human
gate. See AGENTS.md Section 5.2.1.

This model/configuration upgrade applies after merge, checkout refresh, and fresh session loading.
Already running agents retain their loaded routes. A paused roadmap PR may resume on new routes after
its stop conditions are resolved; the harness PR does not depend on that blocked PR merging first.
Successful TOML validation alone is not evidence that a new named role was loaded by the runtime.

Model and configuration references:

- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/api/docs/models/gpt-6-astra
- https://learn.chatgpt.com/docs/agent-configuration/subagents

If a required named role cannot be spawned with its project configuration, do not silently substitute a
generic worker and then claim the intended route. Record `insufficient_evidence` and stop before merge.

## 3. Just-in-time PR Implementation Spec / Scope Contract

Stable architecture is defined up front; exact implementation mechanics are resolved **just in time**
from the actual current repository. Before GREEN production implementation for every fresh roadmap PR,
the master must instantiate the structure in:

- `docs/productionization/PR_IMPLEMENTATION_SPEC_TEMPLATE.md`

The JIT spec must be based on the exact current `main` SHA after prerequisites are merged and must
reconcile older proposed filenames/APIs against current code. It must not blindly copy stale examples
from architecture documents.

The completed JIT spec must contain, at minimum:

- roadmap PR ID/title, phase, base SHA, prerequisite merge SHAs;
- applicable `AGENTS.md`, Codex config/agent config, architecture/design/implementation sources;
- current-state findings and material doc/code drift;
- exact existing files/symbols to modify and exact new files/symbols to add;
- interfaces/schemas/invariants and observable behavioral contract;
- explicit failure/error semantics;
- security/network/persistence/external-side-effect boundaries;
- backward compatibility requirements;
- explicit non-goals and deferred later-PR work;
- migration and rollback;
- ordered implementation steps;
- RED test/fixture plan and expected failures;
- GREEN implementation plan and refactor boundary;
- exact validation commands;
- acceptance matrix;
- complexity classification, named implementer/reviewer roles, configured routes, and escalation triggers.

Persist the completed JIT spec in the PR body or as a durable GitHub PR-conversation artifact before
GREEN implementation begins. A separate committed per-PR implementation-spec file is not required
unless the roadmap explicitly asks for one.

Do **not** pre-generate 47 static copies. Future implementation details must remain adaptable to the
repository that exists when each PR starts. If a material architecture conflict cannot be resolved by
the smallest backward-compatible implementation that preserves the approved invariant, stop and
request human resolution rather than guessing.

For docs-only/harness-only work where no GREEN production implementation exists, the JIT spec may be
proportionally smaller but must still document scope, non-goals, validation, rollback, and why executable
RED evidence is not applicable.

## 4. Auditable test-first evidence

For roadmap implementation PRs where tests can express the contract, red-green-refactor must be visible
in Git history rather than only asserted in chat.

### 4.1 RED commit

Before production implementation:

1. add only the focused tests/fixtures/test harness needed to express the assigned PR contract;
2. run the focused test command and confirm the expected failure;
3. create and push a dedicated RED commit;
4. record:
   - RED commit SHA;
   - exact command;
   - exit status;
   - concise expected failure summary.

The RED commit must not contain production implementation that makes the new contract pass.

### 4.2 GREEN implementation

After the RED commit is durable:

1. add the minimum implementation needed to satisfy the tests;
2. run focused validation and the roadmap validation floor;
3. refactor without scope expansion;
4. commit the implementation separately from the RED commit.

The PR body must identify the RED commit and GREEN implementation commit(s).

### 4.3 Independent RED verification

The independent reviewer must verify that:

- `base..RED` contains only appropriate tests/fixtures/test harness changes;
- the observed failure is the expected missing-contract behavior, not an unrelated environment error;
- when feasible, the focused RED command is rerun at the RED commit in an isolated worktree or equivalent
  non-destructive checkout;
- the production implementation appears only after the RED commit.

If the claimed RED evidence cannot be independently established, mark the TDD evidence
`insufficient_evidence` and block the merge until corrected.

Docs-only/harness-only work that has no executable behavior may state `TDD not applicable` with a
specific reason; do not manufacture meaningless failing tests.

## 5. Durable independent-review artifact

A subagent review that exists only in the parent chat is not sufficient durable audit evidence.

For each review pass, the independent reviewer returns a structured artifact to the master. The master
must persist that artifact in the GitHub PR conversation before the merge gate. A native GitHub review
may also be submitted when the available GitHub identity permits it, but the structured PR-conversation
artifact remains required.

Required review artifact fields:

```text
INDEPENDENT AGENT REVIEW
PR ID: <id>
PR: #<n>
reviewed head: <exact SHA>
reviewer role: reviewer_high|reviewer_xhigh|reviewer_astra_high|reviewer_astra_xhigh
reviewer config: .codex/agents/<file>.toml
model tier: luna|sol_high|sol_xhigh|astra_high|astra_xhigh
configured model/effort: <model> / <effort>
JIT implementation spec: <GitHub PR body/comment reference>
RED evidence: PASS|FAIL|INSUFFICIENT_EVIDENCE
findings: BLOCKER/HIGH/MEDIUM/LOW/NIT with file/evidence
acceptance matrix: <requirement -> evidence -> PASS/FAIL>
scope leak: none|<summary>
verdict: APPROVE|REQUEST CHANGES
```

The reviewer must verify that the final diff still matches the JIT implementation spec or that any
deviation is explicitly justified, scope-safe, and reflected in the durable PR artifact.

If any commit changes the PR head after the review — including a state-only/bookkeeping commit — the
review is stale. Run a fresh review or explicit follow-up review against the new exact head and persist
a new artifact before merge.

## 6. Durable master merge-gate artifact

Before autonomous merge, the master must persist a final GitHub PR-conversation artifact tied to the
exact final head.

Required fields:

```text
MASTER MERGE GATE
PR ID: <id>
final head: <exact SHA>
base main: <exact SHA>
complexity: normal|high|critical
model tier: luna|sol_high|sol_xhigh|astra_high|astra_xhigh
JIT implementation spec: <GitHub PR body/comment reference>
implementer role/configured route: <role> / <model> / <effort>
reviewer role/configured route: <role> / <model> / <effort>
RED commit: <SHA-or-N/A>
independent review artifact: <GitHub comment/review reference>
focused validation: PASS|FAIL
full validation: PASS|FAIL
required CI: PASS|FAIL with exact-head evidence
scope: PASS|FAIL
backward compatibility: PASS|FAIL
master verdict: MERGE|DO NOT MERGE
```

The master must independently confirm that the final diff remains within the JIT spec's scope and
approved roadmap slice. The master must not merge until the final-head independent review artifact,
exact-head required CI, and this master-gate artifact all exist and pass.

## 7. Durable ledger fields

On the next normal `AGENT_STATE.md` update, record at least:

- complexity and model tier, including the evidence-based reason and affected roles for every Astra tier;
- named implementer role and config path;
- configured actual implementer model/effort;
- named reviewer role and config path;
- configured actual reviewer model/effort;
- master configured/requested route;
- JIT implementation spec GitHub artifact reference;
- RED commit SHA and RED evidence status when applicable;
- independent-review GitHub artifact reference;
- master-gate GitHub artifact reference;
- exact final head and merge SHA;
- tests/CI/scope verdict;
- next dependency-valid PR.

Do not create a separate state-only PR after every merge solely to update the ledger. If direct
post-merge state updates are blocked by branch policy, reconcile the prior merge in the next roadmap
branch before that branch's production implementation begins, while GitHub remains authoritative.

## 8. Exact-head rule

Review and CI evidence are SHA-specific.

Any new commit after review or CI evidence invalidates the affected exact-head gate. Re-run the reviewer
and required CI as applicable. Never merge based on green checks or an approval artifact from an older
head.

## 9. Merge and safety boundaries

This protocol strengthens execution evidence; it does not weaken any existing stop condition.

In particular:

- unresolved `BLOCKER`/`HIGH` findings block merge;
- attributable required-CI failures block merge;
- scope leakage blocks merge;
- `insufficient_evidence` blocks downstream work where the roadmap defines a gate;
- paper/live promotion and broker-write gates still require the explicit human approval defined by the
  approved productionization docs;
- named model routing never authorizes an agent to self-approve an externally consequential gate.
