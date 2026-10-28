# Productionization Agent State

Bounded snapshot, not a chronological log. GitHub/current `main` is authoritative. This is a premerge
reconciliation snapshot; resolve the current PR head/status and gates from GitHub before resuming.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `6de97229c19e9f57d536fc8e59c45411bb39abc5`
- `last_reconciled_main_tree`: `c61da75328298fbd79aa3b299aca4cd26164f08c`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-EFF-02 / PR #106
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `autonomy_mode`: human-authorized HARNESS-EFF-02 only; later slices require separate authorization
- `next_dependency`: BT-06 informational only; refreshed main, fresh Master and separate authorization required

## Current maintenance

HARNESS-EFF-02 owns context/state compaction only. Master owns reconciliation facts and writer leases.
High initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max; separate reviewer_high /
GPT-6.1 Sol / xhigh; Master and boundary_reviewer / GPT-6.1 Sol / xhigh. These are configured routes,
not authenticated runtime identity. Routing and CI are unchanged.

At this snapshot, this PR's RED/GREEN, released lease, full validation, independent approval and Master
merge gate must be resolved from its conversation; no future approval/merge is asserted here. There are
no inherited material blockers from closed PR104/105. A new commit invalidates affected review and CI.

## Last completed roadmap

[BT-05 / PR #104](https://github.com/kejian-tong/myTradingAlpha/pull/104) merged. Base
`3d9e049b2fa2c54b55ac66d1c3000480cd3254bd`; approved source
`f1e4507f0508e822464878508219eeacf5a8eb45`; tree `eb1fc414d070d9fec1f71bb95f7742be9fbf29ee`;
merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`. Offline manifested replay/checkpointing only.
Historical hardest `sol_xhigh_sol_xhigh`: critical_implementer / reviewer_xhigh, GPT-6.1 Sol / xhigh.
Original RED `41d6801bd3854b9ee54d3bf8bb996e2e3b195463`; complete repair/lease history remains in PR104.
Recorded final local/CI: 5286 passed, 4 skipped, 69 subtests; Foundation: 4710 passed, 2 skipped.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418127493),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418203129),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418296352).
The human clock waiver removed only the 20s computation condition; synchronization, resource, security,
financial and publication checks remain. No general timing waiver or financial authority follows.

## Last completed Harness

- `harness_reconciled_through`: PR #105 / merge `6de97229c19e9f57d536fc8e59c45411bb39abc5`

[HARNESS-EFF-01 / PR #105](https://github.com/kejian-tong/myTradingAlpha/pull/105): explicit inclusive
v2 accounting and bounded observations, legacy semantics retained. Base `b12bef51acd2b1ef6d6db01dede959f1dd67130f`;
approved source `643a3187d4d4e22dc570f6c74589424b8a37912e`; tree matches reconciled main above.
Historical initial normal_implementer/GPT-6 Luna/max escalated to high_implementer/GPT-6.1 Sol/xhigh;
reviewer_high/GPT-6.1 Sol/xhigh, existing `sol_high_sol_high` route. Recorded 261 focused and 5474 full
passes, 4 skips, 69 subtests; required CI and Foundation passed. Native Windows storage is not claimed.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/105#issuecomment-6443992835),
[Master gate](https://github.com/kejian-tong/myTradingAlpha/pull/105#issuecomment-6444042267),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/105#issuecomment-6444089249).

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

[Immutable precompaction snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/6de97229c19e9f57d536fc8e59c45411bb39abc5/docs/productionization/AGENT_STATE.md)
retains prior BT01–04, SIG and Harness recovery references/routes. Its superseded status is historical,
not current authority. Load that history only for a specific question; current GitHub/PR evidence wins.
Use [context policy](CONTEXT_MANAGEMENT.md) and [compaction policy](AGENT_STATE_COMPACTION.md) for recovery.
