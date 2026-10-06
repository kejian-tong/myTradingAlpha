---
name: principle-separate-before-serializing-shared-state
description: Avoid shared mutable targets where possible and enforce one-writer ownership when a shared target is required.
---

# Separate before serializing shared state

Concurrent actors that mutate one file, branch, key, or object can lose updates or produce ambiguous state. Instructions alone do not prevent that race.

1. Identify the shared mutable target and the actors that read or write it.
2. Give independent actors separate files, branches, keys, or state directories when the data does not require one shared owner.
3. When one canonical target is a real invariant, serialize writes through the repository's designated owner and mechanism.
4. For this repository, one production writer owns an active PR. The Master controls writer-lease acquisition and release. Follow the lease and review procedures; do not substitute a lock, convention, or skill instruction for them.
5. Merge independent facts only at the authorized review or reporting boundary.
