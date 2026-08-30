# Productionization Agent State

This file is the durable, repository-tracked checkpoint for agent-driven productionization work.
It is operational state, not architecture. The approved architecture remains in
`docs/productionization/README.md`, `docs/productionization/07_PR_IMPLEMENTATION_PLAN.md`, and the
phase DESIGN/IMPLEMENTATION documents.

`AGENTS.md` defines how agents must use and maintain this file.

## State schema

- `schema_version`: 1
- `last_reconciled_main_sha`: `dc9bc864fc5c1188ec4fd180950dd3a52f7bcf3c`
- `roadmap_status`: `not_started`
- `current_pr_id`: `none`
- `next_pr_id`: `FND-01`
- `current_phase`: `00-foundation`
- `autonomy_mode`: `supervised_by_default`
- `last_completed_roadmap_pr`: `none`

The state above must be reconciled against GitHub before every implementation session. GitHub/main
is authoritative if this file is stale.

## Durable architecture memory

Keep these invariants visible across fresh sessions:

- `tradingagents/` remains the upstream-derived Research Graph.
- `mytradingalpha/` is the production-owned namespace introduced incrementally by the roadmap.
- No file under `tradingagents/` may import `mytradingalpha`.
- Only `mytradingalpha.research` may import/adapt `tradingagents`.
- Existing `tradingagents` public imports, CLI behavior, and runtime behavior remain backward
  compatible unless an approved roadmap slice explicitly changes them.
- One dependency-ordered roadmap PR ID is implemented per PR by default.
- Later-slice work must not be pulled forward to satisfy phase-wide examples or planned commands.
- Historical correctness, alpha evidence, paper readiness, and live readiness require their own
  explicit roadmap gates; ordinary green unit tests/CI do not prove them.
- Broker/paper/live side effects remain prohibited until their approved phase and required approval
  gates.

## Roadmap PR ledger

The master/orchestrator owns this ledger. Add one row per roadmap PR. Keep entries concise and based
on evidence, not intent.

| PR ID | Base main SHA | Branch | PR | Head / merge SHA | Tests | CI | Review | Scope leak | Status / next |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| _none yet_ | — | — | — | — | — | — | — | — | Next: FND-01 |

Recommended compact representation in agent summaries:

```text
FND-01
base: <sha>
PR: #<n>
merge: <sha-or-pending>
tests: PASS|FAIL|INSUFFICIENT_EVIDENCE
CI: PASS|FAIL|PENDING
review: APPROVE|REQUEST_CHANGES
scope leak: none|<summary>
next: FND-02|BLOCKED
```

## Harness/bootstrap history

This section tracks non-roadmap repository harness changes so they are not confused with the 47
productionization PR IDs.

| Item | PR | Base SHA | Purpose | Status |
| --- | --- | --- | --- | --- |
| Agent harness bootstrap | #6 | `dc9bc864fc5c1188ec4fd180950dd3a52f7bcf3c` | Add root `AGENTS.md` and durable agent state | open at bootstrap |

## Open blockers and deferred work

- None at bootstrap.
- FND-01 has not started.

Agents should record discovered unrelated technical debt here only when it materially affects a
future slice. Do not use this section as permission to widen the active PR.

## Resume protocol for a fresh master session

On startup:

1. Read root `AGENTS.md` completely.
2. Read this file completely.
3. Fetch current `main`, open roadmap PRs, and relevant CI/check state.
4. Reconcile this file with actual GitHub state; do not trust stale SHA/status fields.
5. If a prior PR merged but its ledger entry still says `pending`, repair the ledger before or as the
   first state update of the next roadmap PR.
6. Read the approved roadmap and the next PR's full phase DESIGN/IMPLEMENTATION documents.
7. Continue from `next_pr_id` only after prerequisites and prior merge evidence are confirmed.

If a session terminates unexpectedly, this file plus GitHub history must be sufficient for a fresh
master to recover without relying on chat memory.

## Autonomous-mode checkpoint rules

Autonomous execution is allowed only when the user explicitly authorizes it for the master session.
When authorized and the environment provides the required GitHub write/merge permissions plus fresh
subagent contexts, the master may implement, independently review, merge, refresh `main`, and proceed
to the next dependency-ordered PR without asking for confirmation after every ordinary code PR.

Autonomous mode does **not** allow the agent to waive roadmap promotion gates or approve its own
real-world trading side effects. The master must stop for explicit human approval when the roadmap
requires promotion/approval for paper or live broker writes, credentials, live pilot levels, or any
other externally consequential gate.

The master must also stop rather than self-override when there is a `BLOCKER`/`HIGH` review finding,
CI failure attributable to the diff, architecture conflict, missing prerequisite, unavailable merge
permission, or insufficient evidence for a blocking gate.

A Codex environment may support fresh subagents but not creation of new user-visible UI threads. Do
not pretend to create a new UI thread when that capability is unavailable. Fresh isolated subagent
contexts satisfy the implementation/review isolation requirement; this durable state file supports
resume from a newly opened master session if the top-level session ends.
