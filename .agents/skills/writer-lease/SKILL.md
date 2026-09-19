---
name: writer-lease
description: Acquire, checkpoint, release, and export cooperative repository-global single-writer evidence for one authorized myTradingAlpha productionization or harness PR.
---

# Writer Lease

Use for every fresh implementation or repair writer after the helper is present on refreshed trusted main.
The lease is cooperative structural evidence; it does not authenticate runtime identity, checkpoint order,
or defend against a malicious same-user process.

## Master lifecycle

1. Confirm PR/base/role and no prior writer. Generate pseudonymous 64-lowercase-hex owner/session refs;
   never persist raw IDs, paths, credentials, or transcripts.
2. From trusted main, acquire before the writer starts in a dedicated linked worktree. Supply full
   `branch_ref`; the helper derives `writer_lane_ref` from canonical gitdir relative to the exact common
   directory and persists the lease ID and identity tuple.
3. Give the writer only that tuple. Verify at `writer_start`, applicable RED/GREEN, commit, and push
   boundaries. `writer_start` is first, later checkpoints cannot regress, and omitted non-applicable phases
   are allowed. A checkpoint is a declaration, not host attestation.
4. After independent host observation that the writer stopped, the Master releases with the exact tuple.
   The writer never acquires or releases its own lease.
5. Export and validate canonical bounded evidence, record its digest/reference, and reconcile it with Git
   history and the Master lifecycle.

Any mismatch, malformed/unsafe state, missing or out-of-order event, exhausted capacity, partial transition,
or ambiguous stopped state fails closed. Evidence has bounded archive capacity; no automatic stale-state
recovery is permitted.

## Dedicated lane contract

The exact canonical dedicated linked worktree must have non-detached `HEAD` equal to `branch_ref`, a linked
gitdir canonical under the same common directory, and exactly one matching bounded `git worktree list
--porcelain -z` registration. Verify/release/export re-derive the lane before state access. Candidate HEAD
movement on the same branch is not lane identity. The helper changes no refs, index, config, registered
worktrees, product files, or remote state.

The introducing helper PR records a Master-observed bootstrap limitation because candidate code cannot
authorize its own writer. CI/offline checks inspect checked-in contracts only and never live lease state.
