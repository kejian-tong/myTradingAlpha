# Agent State Compaction Policy

Status: execution-harness maintainability policy. `AGENT_STATE.md` is current operational recovery
state, not the long-term home for complete PR/audit transcripts. GitHub/current `main` remains
authoritative.

## Objective

Keep fresh-master recovery efficient without deleting durable evidence. After the current owner of
`AGENT_STATE.md` yields the file, normal reconciliation should target a current snapshot of at most
12 KiB. The offline harness enforces a temporary absolute ceiling of 64 KiB so state cannot grow
without bound while an already-active roadmap PR still owns a larger transition record.

The 12 KiB target is a maintainability objective, not permission to discard unresolved blockers,
current authorization boundaries, exact SHAs, or evidence needed to recover the active task.

## Current snapshot belongs in `AGENT_STATE.md`

Retain only facts needed to resume current work safely:

- schema version and last reconciled `main` SHA;
- current/last-completed/next dependency-valid roadmap IDs;
- current phase, stop boundary and autonomy status;
- current requested/configured model routes and material escalation reason;
- active PR/base/head/merge status and exact blocking findings;
- latest relevant RED/GREEN, review, CI and master-gate references;
- unresolved evidence gaps and explicit human gates.

Prefer references to durable GitHub PR comments, workflow runs and immutable commit SHAs over repeating
long chronological prose already available there.

## Historical evidence belongs outside the current snapshot

Closed remediation narratives, superseded review rounds, resolved repair chronology and prior phase
recovery detail may be summarized or moved under `docs/productionization/history/` when that history is
still useful in-repo. GitHub PR conversations, commits and workflow records remain the primary durable
evidence and must not be rewritten merely to make the current state file smaller.

Archives are not automatically loaded as current execution instructions. A future master reads them only
when a specific recovery/audit question requires that history.

## Ownership and conflict avoidance

Before compacting, check current GitHub and active PR scope. If another active roadmap/maintenance PR
explicitly owns `AGENT_STATE.md`, do **not** create a competing state rewrite from a harness-maintenance
branch. Install or update the compaction policy/guard separately, then compact during the next normal
owner-controlled state reconciliation after that PR merges/closes or otherwise yields ownership.

As of the PR introducing this policy, SIG-02 PR #45 is active and owns `AGENT_STATE.md`; therefore that
PR deliberately does not rewrite the state file.

## Compaction procedure

1. Reconcile the state file against current GitHub/main first; never compact stale assumptions as truth.
2. Identify material current facts using the current-snapshot list above.
3. Preserve immutable GitHub references for historical claims before removing duplicated narrative.
4. Move only useful closed history to a clearly dated/topic-named file under `history/`; do not create an
   archive merely to duplicate GitHub.
5. Re-read the compacted snapshot as a fresh master would. It must still identify the exact active state,
   blockers, routes, next allowed action and stop boundary without relying on chat memory.
6. Run the offline harness validator and productionization tests before merge.

Compaction is a context-efficiency optimization. It never changes production architecture, authorization,
review requirements, paper/live gates, or the meaning of historical evidence.
