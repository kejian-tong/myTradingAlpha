# Productionization Agent State

This is the compact operational recovery snapshot. GitHub and current `main` are authoritative.
Approved architecture remains in the productionization roadmap and phase documents. Historical detail
removed from this snapshot remains immutable in Git commits, workflow runs and PR conversations.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `6ed694fd6c31af3adc5be6d2ee85d85f54aa408f`
- `last_reconciled_main_tree`: `070179c0e8350e46bad899c0eb3291f9f07fb0cc`
- `roadmap_status`: `sig_02_merged_stopped`
- `current_pr_id`: none
- `current_phase`: none active
- `last_completed_roadmap_pr`: `SIG-02` / PR #45 / merge
  `376c9c044722ee37f3fa36691b576420e3b6253d`
- `next_pr_id`: `SIG-03` (informational only; not authorized by the current harness-maintenance task)
- `stop_after_pr_id`: `SIG-02` (completed historical stop boundary)
- `autonomy_mode`: disabled for roadmap implementation after SIG-02 completion
- `active_writer`: none
- `merge`: merged

No new roadmap slice is active. The current user authorization is limited to bounded Codex-harness
maintenance and does not authorize SIG-03, SIG-04, SIG-05, BT-01 or any later roadmap implementation.
No model/provider inference, paid data, deployment, broker, PAPER/live, real-order or promotion action is
authorized by this state. Explicit human PAPER/live promotion gates remain mandatory and unexercised.

## Latest completed roadmap slice: SIG-02

PR #45 implemented the Evidence tools and `ResearchNote` boundary as a pure, deterministic transformation
of sealed `EvidenceBundle` / cached-response evidence. It added domain-qualified references, exact
bundle/provenance/cutoff/artifact binding, defensive immutable access, bounded canonical serialization,
typed failures, hostile-data redaction and no provider/network/ordinary-graph fallback.

Final immutable evidence:

- final reviewed source head: `de51698180ff6873c7512c70828add3c55728fb9`
- final source tree: `ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`
- merged base main: `acb4f971b584b0ba12d83d9e57c96c85c95da418`
- actual merge commit: `376c9c044722ee37f3fa36691b576420e3b6253d`
- merge parents: `acb4f971b584b0ba12d83d9e57c96c85c95da418`,
  `de51698180ff6873c7512c70828add3c55728fb9`
- merge/resulting-main tree: `ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`
- merge time: `2026-09-07T18:04:30Z`
- final Master merge-gate artifact: PR #45 comment `5574233504`
- post-merge final receipt: PR #45 comment `5574325065`
- main-push CI `34150165313`: PASS
- main-push CodeQL `34150165320`: PASS

The final controlling review used fresh `reviewer_xhigh`, configured `gpt-5.6-sol / xhigh`, on the exact
source head above and returned APPROVE with all prior BLOCKER/HIGH findings closed before the Master
merge gate. The completed SIG-02 task did not authorize or start SIG-03.

## Routing and lessons retained for future work

SIG-02 was classified `high` and ultimately used the difficult production route:

- original implementer: `normal_implementer` / `gpt-5.6-luna / max`
- final repair implementer: `high_implementer` / `gpt-5.6-sol / high`
- final controlling reviewer: `reviewer_xhigh` / `gpt-5.6-sol / xhigh`
- Master: configured/requested `gpt-5.6-sol / xhigh`

Only one production writer ran at a time. Replacements began only after the prior writer stopped. The
SIG-02-only runtime alternative permitting correctly loaded children to expose, but not invoke,
collaboration controls expired after post-merge verification; normal master-only delegation policy now
applies without that exception.

The durable review history in PR #45 shows repeated late discovery of hostile-input, provenance,
redaction, canonicalization and bounded-work defects. Future high/critical work should use that evidence
to shift adversarial boundary analysis earlier during preflight/JIT rather than treating those findings as
a reason to weaken review.

## Prospective harness policy

`HARNESS-V2-COLLAB-COMPAT` / PR #64 candidate is the bounded execution-harness maintenance change based on
reconciled main `6ed694fd6c31af3adc5be6d2ee85d85f54aa408f` and tree
`070179c0e8350e46bad899c0eb3291f9f07fb0cc`. It does not start SIG-03 or any later roadmap slice.

After this policy is merged and a fresh session loads the checkout, collaboration-control visibility in a
non-master V2 child is informational only. The Master remains the only role permitted to invoke controls or
delegate work; any attempted or completed nested delegation, including a runtime-denied/no-op attempt,
blocks progression. All ten non-master roles retain `[agents] enabled = false` and the uniform
no-invocation instruction contract. The offline gate requires complete strict boolean evidence and retains
`telemetry_conflict` as separate blocking evidence. This prospective policy does not rewrite the expired
SIG-02-only exception recorded above or relabel its historical evidence.

## State and recovery policy

This snapshot is intentionally compact and remains below the target in `AGENT_STATE_COMPACTION.md`.
Detailed SIG-02 repair chronology remains in PR #45, its immutable commits/workflows, and the historical
pre-compaction state snapshot. Do not re-expand this file into a chronological log.

A fresh Master must still fetch GitHub/current `main`, reconcile this snapshot, read applicable scoped
instructions and phase documents, and obtain fresh authorization before starting any later roadmap slice.
Harness-only commits may advance `main` after the reconciled roadmap merge without implying that a later
roadmap slice has started.
