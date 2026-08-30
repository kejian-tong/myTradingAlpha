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
| `high` | `high_implementer` | `reviewer_high` | Sol/high implementation and review; reviewer may escalate |
| `critical` | `critical_implementer` | `reviewer_xhigh` | Sol/xhigh implementation and review |

`gpt-5.6` is the Codex/OpenAI alias used by the project configuration for GPT-5.6 Sol. The normal
implementer uses the explicit `gpt-5.6-luna` model ID.

For a high PR whose review remains ambiguous, rerun independent review with `reviewer_xhigh` before the
master gate.

If a required named role cannot be spawned with its project configuration, do not silently substitute a
generic worker and then claim the intended route. Record `insufficient_evidence` and stop before merge.

## 3. Auditable test-first evidence

For roadmap implementation PRs where tests can express the contract, red-green-refactor must be visible
in Git history rather than only asserted in chat.

### 3.1 RED commit

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

### 3.2 GREEN implementation

After the RED commit is durable:

1. add the minimum implementation needed to satisfy the tests;
2. run focused validation and the roadmap validation floor;
3. refactor without scope expansion;
4. commit the implementation separately from the RED commit.

The PR body must identify the RED commit and GREEN implementation commit(s).

### 3.3 Independent RED verification

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

## 4. Durable independent-review artifact

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
reviewer role: reviewer_high|reviewer_xhigh
reviewer config: .codex/agents/<file>.toml
configured model/effort: <model> / <effort>
RED evidence: PASS|FAIL|INSUFFICIENT_EVIDENCE
findings: BLOCKER/HIGH/MEDIUM/LOW/NIT with file/evidence
acceptance matrix: <requirement -> evidence -> PASS/FAIL>
scope leak: none|<summary>
verdict: APPROVE|REQUEST CHANGES
```

If any commit changes the PR head after the review — including a state-only/bookkeeping commit — the
review is stale. Run a fresh review or explicit follow-up review against the new exact head and persist
a new artifact before merge.

## 5. Durable master merge-gate artifact

Before autonomous merge, the master must persist a final GitHub PR-conversation artifact tied to the
exact final head.

Required fields:

```text
MASTER MERGE GATE
PR ID: <id>
final head: <exact SHA>
base main: <exact SHA>
complexity: normal|high|critical
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

The master must not merge until the final-head independent review artifact, exact-head required CI, and
this master-gate artifact all exist and pass.

## 6. Durable ledger fields

On the next normal `AGENT_STATE.md` update, record at least:

- complexity;
- named implementer role and config path;
- configured actual implementer model/effort;
- named reviewer role and config path;
- configured actual reviewer model/effort;
- master configured/requested route;
- RED commit SHA and RED evidence status when applicable;
- independent-review GitHub artifact reference;
- master-gate GitHub artifact reference;
- exact final head and merge SHA;
- tests/CI/scope verdict;
- next dependency-valid PR.

Do not create a separate state-only PR after every merge solely to update the ledger. If direct
post-merge state updates are blocked by branch policy, reconcile the prior merge in the next roadmap
branch before that branch's production implementation begins, while GitHub remains authoritative.

## 7. Exact-head rule

Review and CI evidence are SHA-specific.

Any new commit after review or CI evidence invalidates the affected exact-head gate. Re-run the reviewer
and required CI as applicable. Never merge based on green checks or an approval artifact from an older
head.

## 8. Merge and safety boundaries

This protocol strengthens execution evidence; it does not weaken any existing stop condition.

In particular:

- unresolved `BLOCKER`/`HIGH` findings block merge;
- attributable required-CI failures block merge;
- scope leakage blocks merge;
- `insufficient_evidence` blocks downstream work where the roadmap defines a gate;
- paper/live promotion and broker-write gates still require the explicit human approval defined by the
  approved productionization docs;
- named model routing never authorizes an agent to self-approve an externally consequential gate.
