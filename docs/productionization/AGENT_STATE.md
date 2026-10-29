# Productionization Agent State

Bounded snapshot, not a chronological log. GitHub/current `main` is authoritative. This is a premerge
reconciliation snapshot; resolve the current PR head/status and gates from GitHub before resuming.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `4dbecb231457fe4820623677eb9e4b2e0621cd2b`
- `last_reconciled_main_tree`: `723d83e0c5fd0052fa3ebe5767432770d47682f8`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-EFF-04 / PR #108
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `autonomy_mode`: human-authorized HARNESS-EFF-04 only; later slices require separate authorization
- `next_dependency`: BT-06 informational only; refreshed main, fresh Master and separate authorization required

## Current maintenance

HARNESS-EFF-04 owns remaining Harness remediation and security maintenance only.
Master owns state facts and leases. High initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max;
separate reviewer_high / GPT-6.1 Sol / xhigh; Master/boundary_reviewer / GPT-6.1 Sol / xhigh.
Configured routes are not authenticated runtime identity. Routing and safety gates are unchanged.

Scope: benchmark admission/dated credits, prospective native compaction, uv/security lock fixes and full
unfiltered durations. No shared fixture cache or production backtest change. Resolve RED/GREEN, released
leases, validation, independent review and Master gate from this PR; no future approval/merge is asserted here.
Full local/CI and exact-head gates remain mandatory. Realized billing, complete request coverage, host
enforcement, Enterprise USD and controlled savings require external evidence; never fabricate missing facts.

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

- `harness_reconciled_through`: PR #107 / merge `4dbecb231457fe4820623677eb9e4b2e0621cd2b`

[HARNESS-EFF-03 / PR #107](https://github.com/kejian-tong/myTradingAlpha/pull/107) deduplicated Foundation
and named validation ownership. Base `e683b10f75b8038e3423de7cbb80ee4fb19e3303`; approved source
`22bded9c1af4f1f5cb6e88b93af05b5e7dd835c0`; merge/tree match reconciled main above.
Historical high initial `luna_sol_high`, same configured writer/reviewer routes as current maintenance.
RED `58c0c680ba658859eae7ea09c6839d8e4fc09792`;72 focused passes;
PR-source local and CI full each 5491 passed, 4 skipped, 69 subtests. Foundation aggregation succeeded4s.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/107#issuecomment-6471350570),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/107#issuecomment-6471376503),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/107#issuecomment-6471442876).
PR106/HARNESS-EFF-02 context policy and PR105 accounting remain in immutable recovery history.

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

[Immutable prior snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/4dbecb231457fe4820623677eb9e4b2e0621cd2b/docs/productionization/AGENT_STATE.md)
retains PR105 and prior BT01–04, SIG and Harness recovery references/routes through immutable links.
Its superseded status is historical, not current authority. Load that history only for a specific
question; current GitHub/PR evidence wins. Use [context policy](CONTEXT_MANAGEMENT.md),
[compaction policy](AGENT_STATE_COMPACTION.md) and [validation policy](VALIDATION_EFFICIENCY.md).
