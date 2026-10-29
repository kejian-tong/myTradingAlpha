# Productionization Agent State

Bounded snapshot, not a chronological log. GitHub/current `main` is authoritative. This is a premerge
reconciliation snapshot; resolve the current PR head/status and gates from GitHub before resuming.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `8b1138841719c19bb74b4ed1176c78af8bcc469c`
- `last_reconciled_main_tree`: `4b1b4d9a3e74d1ad4a47e18c3fcaba32af0a1035`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-EFF-04 / PR #109
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `autonomy_mode`: human-authorized HARNESS-EFF-04 only; later slices require separate authorization
- `next_dependency`: BT-06 informational only; refreshed main, fresh Master and separate authorization required

## Current maintenance

HARNESS-EFF-04 owns remaining Harness remediation and security maintenance only.
Current follow-up closes newly surfaced langgraph/sdk GHSA-3fx2-cqw9-xr3c using minimum patches,
manifest floor and offline URL-path regressions. Their introduction is not attributed to PR108.
Master owns state facts and leases. High initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max;
separate reviewer_high / GPT-6.1 Sol / xhigh; Master/boundary_reviewer / GPT-6.1 Sol / xhigh.
Configured routes are not authenticated runtime identity. Routing and safety gates are unchanged.

Resolve RED/GREEN, leases, full validation, approval and Master gate from this PR conversation;
no future approval/merge is asserted here. New commits stale affected proof. Scope is security maintenance;
no later phase starts. Full local/CI and exact-head review remain mandatory. Host enforcement, actual bills
and controlled cost savings remain external prerequisites.

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

- `harness_reconciled_through`: PR #108 / merge `8b1138841719c19bb74b4ed1176c78af8bcc469c`

[HARNESS-EFF-04 / PR #108](https://github.com/kejian-tong/myTradingAlpha/pull/108) added bounded callback-safe
analysis, dated credit estimates, prospective native compaction and seven security patches.
Base `4dbecb231457fe4820623677eb9e4b2e0621cd2b`; approved source
`e5460b09928632b4658f721a0ab119a690f05e75`; tree `4b1b4d9a3e74d1ad4a47e18c3fcaba32af0a1035`; merge/tree match reconciled main above.
Historical high initial `luna_sol_high`, same configured writer/reviewer routes as current maintenance.
PR-source local and CI full each 5548 passed, 4 skipped, 69 subtests. Foundation aggregation succeeded4s.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489107034),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489455137),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489599975).
Its12 scoped alerts are fixed; dependency-graph refresh surfaced alerts15/16.
PR107/HARNESS-EFF-03 validation ownership and prior context/accounting remain in immutable history.

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

[Immutable prior snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/8b1138841719c19bb74b4ed1176c78af8bcc469c/docs/productionization/AGENT_STATE.md)
retains PR105 and prior BT01–04, SIG and Harness recovery references/routes through immutable links.
Its superseded status is historical, not current authority. Load that history only for a specific
question; current GitHub/PR evidence wins. Use [context policy](CONTEXT_MANAGEMENT.md),
[compaction policy](AGENT_STATE_COMPACTION.md) and [validation policy](VALIDATION_EFFICIENCY.md).
