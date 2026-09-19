---
name: writer-lease
description: Acquire, checkpoint, release, and export cooperative repository-global one-writer evidence for one authorized myTradingAlpha productionization or harness PR.
---

# Writer Lease

Use this skill for every fresh implementation or repair writer after the helper is present on refreshed,
trusted `main`. The lease is cooperative structural evidence. It does not authenticate a runtime identity,
prove that a declared checkpoint happened in real-world order, or defend against a malicious same-user
process that rewrites Git metadata.

## Master procedure

1. Confirm the exact authorized PR ID, base SHA, named writer role, and that no prior writer remains active.
   Generate pseudonymous 64-lowercase-hex `owner_ref` and `session_ref`
   correlation values; never store raw agent/session IDs, paths, credentials, or transcripts.
2. From trusted `main`, call `scripts/writer_lease.py acquire` before the writer starts from a dedicated
   linked worktree. Supply the exact full `branch_ref`; the helper derives the canonical 64-hex
   `writer_lane_ref` from the linked gitdir relative to the exact Git common directory and persists only
   that digest. Persist the returned `lease_id` and identity tuple. Acquisition is intentionally non-idempotent.
3. Give the writer only the tuple needed for its lane, including exact `branch_ref` and `writer_lane_ref`.
   Require `verify` at `writer_start` and at each
   applicable boundary: `before_red`, `before_green`, `before_commit`, and `before_push`. An exact repeated
   verification is idempotent. `writer_start` must be first; later checkpoints never regress, while
   non-applicable intermediate phases may be omitted. A checkpoint is a declaration, not host attestation.
4. Interrupt or wait for the writer to stop and obtain independent host observation of that stopped state.
   Only then may the Master call `release` with the exact tuple. Candidate code cannot authenticate this
   prerequisite, and the writer must never release its own lease.
5. Call `export`, validate the canonical evidence with `validate`, record its SHA-256 digest, and persist the
   bounded artifact or digest/reference in the PR conversation. The merge gate must compare this evidence
   with the Master-owned writer lifecycle and exact Git history.

Any mismatch, malformed or unsafe state, missing/out-of-order event, per-lease event exhaustion, fixed
completed-archive capacity exhaustion, partial transition, or ambiguous stopped state fails closed. Completed
evidence is retained for at most 64 archived leases plus the current lane; there is no rotation or automatic
stale-state action. After independently proving
the writer is stopped, the Master may quarantine the dedicated state directory manually for human recovery;
never let candidate code decide that an existing lease is stale.

## Bootstrap and isolation

The PR that first introduces this helper cannot use candidate code to authorize its own writer; record the
Master-observed single-writer bootstrap limitation. Ordinary CI and the offline harness checker validate
only checked-in contracts and must not read live lease state. The lease requires an exact canonical
dedicated linked worktree: non-detached `HEAD` must equal `branch_ref`, the linked gitdir must be canonical
under the same common directory, and exactly one bounded `git worktree list --porcelain -z` registration
must match. Verify, release, and export re-derive and match the lane before state access; candidate `HEAD`
movement on the same branch is not identity. The lease writes only under the verified Git common directory
and never changes refs, index, config, registered worktrees, product behavior, or remote state.
