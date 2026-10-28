# Agent State Compaction Policy

Status: execution-harness maintainability policy. `AGENT_STATE.md` is current operational recovery
state, not the long-term home for complete PR/audit transcripts. GitHub/current `main` remains
authoritative.

## Objective

Keep fresh-Master recovery efficient without deleting durable evidence. When the verified owner has the
file, normal reconciliation targets a current snapshot of at most 6 KiB. The offline harness enforces a
hard ceiling of 12 KiB measured in original UTF-8 bytes.

Neither budget permits discarding unresolved blockers, current authorization boundaries, exact SHAs, or
evidence needed to recover the active task. See [`CONTEXT_MANAGEMENT.md`](CONTEXT_MANAGEMENT.md) for task
summary and source-window budgets.

## Current snapshot belongs in `AGENT_STATE.md`

Retain only facts needed to resume current work safely:

- schema version and last reconciled `main` SHA/tree;
- current and last-completed PR/base/source/tree/merge identities;
- current/next dependency-valid roadmap IDs, phase, stop boundary, and authorization status;
- current requested/configured routes and material escalation reason;
- pending review, CI, and Master-gate status, with durable references;
- unresolved evidence gaps, blockers, and explicit human gates.

Prefer durable GitHub PR comments, workflow runs, and immutable commits over repeating chronology already
available there. Never claim future review, CI, or merge outcomes.

## Historical evidence stays recoverable

Closed remediation narratives, superseded review rounds, resolved repair chronology, and prior phase
recovery detail may be summarized or retained in the immutable PR/commit records they describe. GitHub PR
conversations, commits, and workflow records remain primary evidence. Cold history is not current
execution authority; load it only for a specific recovery question. Do not create an archive merely to
duplicate durable evidence.

## Ownership and conflict avoidance

Before compacting, verify current GitHub/main and active PR ownership. If another active roadmap or
maintenance PR explicitly owns `AGENT_STATE.md`, do **not** create a competing state rewrite from a
harness-maintenance branch. Reconcile after that owner merges, closes, or yields the file. Preserve
current blockers, authorization/stop boundaries, exact recovery SHAs, and surviving decision context.
The Master owns reconciliation facts and supplies approved state text; writers do not invent status or
authorization.

## Compaction procedure

1. Reconcile the state file against current GitHub/main; do not compact stale assumptions as truth.
2. Retain the current recovery facts listed above and remove only duplicated closed chronology.
3. Preserve immutable GitHub or commit references before removing historical detail.
4. Re-read the compacted snapshot as a fresh Master would; it must identify current state, blockers, and
   the next allowed action without chat memory.
5. Run the offline harness validator and applicable productionization tests.

Compaction is a context-efficiency optimization. It never changes production architecture, authorization,
review requirements, paper/live gates, or the meaning of historical evidence.
