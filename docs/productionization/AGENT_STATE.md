# Productionization Agent State

Bounded premerge snapshot, not a chronological log. GitHub/current `main` is authoritative.
Resolve active head, blockers, validation, review and gate from the PR conversation before resuming.

## Current control state

- `schema_version`: 3
- `last_reconciled_main_sha`: `300605dcbed7aff113d81fd7d709ebbabe01e61c`
- `last_reconciled_main_tree`: `67d3c9378a0017cecc02acf85649c93d0bc988d6`
- `roadmap_status`: BT-05 merged; BT-06 not started
- `current_pr_id`: HARNESS-EFF-05 / PR #110
- `current_phase`: bounded Harness maintenance; Phase 03 incomplete
- `last_completed_roadmap_pr`: BT-05 / PR #104 / merge `b12bef51acd2b1ef6d6db01dede959f1dd67130f`
- `harness_reconciled_through`: PR #109 / merge `300605dcbed7aff113d81fd7d709ebbabe01e61c`
- `autonomy_mode`: human-authorized HARNESS-EFF-05 only; later slices require separate authorization
- `next_dependency`: BT-06 informational only; refreshed main, fresh Master and separate authorization required

## Current maintenance

HARNESS-EFF-05 owns native compaction evidence, meaningful-event monitoring, profile-led recovery-test
reference reuse and explicit root/child usage accounting. BT-06/Phase04+ is not authorized.
Routing and safety gates are unchanged. No financial algorithm, dependency, runtime/config precedence,
production phase or broker behavior changes. Full required source/log/review reads override summary budgets.

High initial `luna_sol_high`: normal_implementer / GPT-6 Luna / max; separate reviewer_high /
GPT-6.1 Sol / xhigh; Master / GPT-6.1 Sol / xhigh. Master owns state, scope, sequential writer leases
and merge. Configured intent and observed model/effort are distinct from authenticated runtime identity.
Exact RED/GREEN SHAs, lease exports, findings, full local/CI logs and final gate belong in
[PR #110](https://github.com/kejian-tong/myTradingAlpha/pull/110); no future approval/merge is asserted here.
New commits stale affected evidence. Failed or incomplete runs do not pass.

## Completed recovery anchors

BT-05: Base `3d9e049b2fa2c54b55ac66d1c3000480cd3254bd`; approved source
`f1e4507f0508e822464878508219eeacf5a8eb45`; tree `eb1fc414d070d9fec1f71bb95f7742be9fbf29ee`.
Offline manifested replay/checkpointing only. Historical hardest route; full 5286 passed, 4 skipped,
69 subtests; Foundation: 4710 passed, 2 skipped.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418127493),
[gate](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418203129),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/104#issuecomment-6418296352).
Its human computation-clock waiver changes no synchronization, resource, security, financial or publication gate.

PR109: Base `8b1138841719c19bb74b4ed1176c78af8bcc469c`; approved source
`e721ccad33aa912c473fcce8b74d7f48ba56e904`; tree `67d3c9378a0017cecc02acf85649c93d0bc988d6`;
merge/tree match reconciled main above. Minimum langgraph/sdk security patches and offline URL-path
regressions; high initial route, full local and required CI passed.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/109#issuecomment-6495074222),
[gate](https://github.com/kejian-tong/myTradingAlpha/pull/109#issuecomment-6495090548),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/109#issuecomment-6495208854).

Prior PR108: callback-safe analysis, dated credit estimates, prospective compaction and security patches.
PR-source local and CI full each 5548 passed, 4 skipped, 69 subtests; Foundation aggregation succeeded4s.
[APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489107034),
[gate](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489455137),
[completion](https://github.com/kejian-tong/myTradingAlpha/pull/108#issuecomment-6489599975).

## Boundaries and assurance

- Phase 03 gate: insufficient_evidence until all six separately merged slices. No live broker write before Phase 09.
- SIG-04 validates caller-supplied candidates only; no inference.
- SIG-05 adds only in-memory deterministic shadow envelopes.
- SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior.
- No PAPER/live operation; explicit human PAPER/live gates remain mandatory and unexercised.
- Separate review uses a clean detached exact-head worktree and RED replay. Full local/required CI,
  released writer evidence and Master gate remain mandatory. BLOCKER/HIGH, dirty/stale isolation,
  observed mutation or required-CI failure blocks merge.
- Host-origin assurance absence is supplemental disclosure, not a block alone. Permission profile is
  disabled; observed filesystem is unrestricted. Read-only role configuration expresses intent.
- Hook load/trust unknown without host report; configuration alone is ineffective proof. Runtime receipt
  and offline verifier do not authenticate host/model/isolation. No enforced isolation is claimed.
- Writer leases are cooperative; they cannot constrain malicious same-user processes.
- Apps/Memories disabled; rules, permission profiles, OTEL and repo plugins remain watch-only.
  External-spec/docs MCP settings express configuration intent, not observed host behavior.

[Immutable cold snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/300605dcbed7aff113d81fd7d709ebbabe01e61c/docs/productionization/AGENT_STATE.md)
retains prior BT01–04, SIG and Harness recovery references/routes. Its superseded status is historical,
not current authority. Load that history only for a specific question. Use
[context](CONTEXT_MANAGEMENT.md), [state compaction](AGENT_STATE_COMPACTION.md) and
[validation](VALIDATION_EFFICIENCY.md) policies.
