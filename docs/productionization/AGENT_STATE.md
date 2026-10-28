# Productionization Agent State

Bounded snapshot, not a chronological log. GitHub/current `main` is authoritative. This is a premerge
reconciliation snapshot; resolve the current PR head/status and gates from GitHub before resuming.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `e683b10f75b8038e3423de7cbb80ee4fb19e3303`
- `last_reconciled_main_tree`: `7a5214fd01349fbd5a0d3027b8cacd5151e6d6f1`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-EFF-03 / PR #107
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `autonomy_mode`: human-authorized HARNESS-EFF-03 only; later slices require separate authorization
- `next_dependency`: BT-06 informational only; refreshed main, fresh Master and separate authorization required

## Current maintenance

HARNESS-EFF-03 owns validation efficiency and CI deduplication only. Master owns reconciliation facts
and writer leases. High initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max; separate
reviewer_high / GPT-6.1 Sol / xhigh; Master and boundary_reviewer / GPT-6.1 Sol / xhigh. These are
configured routes, not authenticated runtime identity. Routing and safety gates are unchanged.

Complete unfiltered local/CI suites, independent RED/focused review, required checks and exact-head
evidence remain mandatory. Foundation aggregates same-workflow results, not a second test execution.
Resolve this PR's RED/GREEN, released leases, validation, approval and Master gate from its conversation;
no future approval/merge is asserted here. No inherited material blocker remains from closed PR104–106.
A new commit invalidates affected review and CI.

## Last completed roadmap

[BT-05 / PR #104](https://github.com/kejian-tong/myTradingAlpha/pull/104) merged. Base
`3d9e049b2fa2c54b55ac66d1c3000480cd3254bd`; approved source
`f1e4507f0508e822464878508219eeacf5a8eb45`; tree `eb1fc414d070d9fec1f71bb95f7742be9fbf29ee`;
merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`. Offline manifested replay/checkpointing only.
Historical hardest `sol_xhigh_sol_xhigh`: critical_implementer / reviewer_xhigh, GPT-6.1 Sol / xhigh.
Original RED `41d6801bd3854b9ee54d3bf8bb996e2e3b195463`; complete repair/lease history remains in PR104.
Recorded final PR-source local/CI: 5286 passed, 4 skipped, 69 subtests; Foundation: 4710 passed, 2 skipped.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418127493),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418203129),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418296352).
The human clock waiver removed only the 20s computation condition; synchronization, resource, security,
financial and publication checks remain. No general timing waiver or financial authority follows.

## Last completed Harness

- `harness_reconciled_through`: PR #106 / merge `e683b10f75b8038e3423de7cbb80ee4fb19e3303`

[HARNESS-EFF-02 / PR #106](https://github.com/kejian-tong/myTradingAlpha/pull/106) added compact state,
bounded read-only schema3 identity checks and context guidance. Base
`6de97229c19e9f57d536fc8e59c45411bb39abc5`; approved source
`16b479a7cfc9295079df267755323fc046a2d807`; merge/tree match reconciled main above.
Historical high initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max and reviewer_high /
GPT-6.1 Sol / xhigh. Recorded 158 focused and 64 consumer passes; PR-source local and CI full each
5485 passed, 4 skipped, 69 subtests. The former separate Foundation execution passed 4909, skipped 2.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/106#issuecomment-6459590623),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/106#issuecomment-6459625169),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/106#issuecomment-6459699099).
PR105 accounting remains unchanged; usage assertions and static byte reductions do not prove billing.

## Boundaries and recovery

- Phase 03 gate: insufficient_evidence until all six separately merged slices. BT-06/Phase04+ is not authorized.
- SIG-04 validates caller-supplied candidates only; no inference. SIG-05 adds only in-memory deterministic shadow envelopes.
- SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior.
- No PAPER/live operation; explicit human PAPER/live gates remain mandatory and unexercised. No live broker write before Phase 09.
- Separate controlling review uses a detached exact-head worktree and before/after cleanliness. Mutation, stale/dirty isolation, missing roles, BLOCKER/HIGH or required-CI failure blocks merge.
- Host permission profile disabled/unrestricted. Missing host-origin sandbox/approval/tool facts are supplemental disclosure and do not themselves block review.
- Project hook load/trust unknown without a host report; configuration alone is ineffective proof. Runtime receipt, offline verifier and config do not authenticate host/model/isolation.
- Writer leases are cooperative and do not defend against same-user processes. Main-protection required contexts remain authoritative; recheck current GitHub rules.
- Project Apps and Memories disabled: configuration intent. Rules/Permission Profiles/OTel/repo Plugins remain watch-only. External-spec Docs MCP is configuration intent until observed.

[Immutable prior snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/e683b10f75b8038e3423de7cbb80ee4fb19e3303/docs/productionization/AGENT_STATE.md)
retains PR105 and prior BT01–04, SIG and Harness recovery references/routes through immutable links.
Its superseded status is historical, not current authority. Load that history only for a specific
question; current GitHub/PR evidence wins. Use [context policy](CONTEXT_MANAGEMENT.md),
[compaction policy](AGENT_STATE_COMPACTION.md) and [validation policy](VALIDATION_EFFICIENCY.md).
