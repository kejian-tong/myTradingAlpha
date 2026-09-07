# Productionization Agent State

This is the compact operational recovery snapshot. GitHub and current `main` are authoritative.
Approved architecture remains in the productionization roadmap and phase documents. Historical detail
removed from this snapshot remains immutable in Git commits, workflow runs and PR conversations.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `acb4f971b584b0ba12d83d9e57c96c85c95da418`
- `last_reconciled_main_tree`: `d16c6643a1cf250fa14f010169b51ff7fdc487cd`
- `roadmap_status`: `sig_02_candidate_pending_final_exact_head_review`
- `current_pr_id`: `SIG-02` / PR #45
- `current_phase`: `02-evidence-agent-boundary`
- `last_completed_roadmap_pr`: `SIG-01` / PR #24 / merge
  `a614b8a27c6a822477235304f4749dc9c8163165`
- `next_pr_id`: `SIG-03` (informational only; not authorized by this task)
- `stop_after_pr_id`: `SIG-02`
- `autonomy_mode`: authorized for SIG-02 implementation, repair, review, exact-head merge and
  post-merge verification only
- `active_writer`: none
- `merge`: pending

The user explicitly prohibited SIG-03, SIG-04, SIG-05, BT-01 and all later work in this task. No model
or provider inference, paid data, deployment, broker, PAPER/live, real order or promotion action is
authorized. Explicit human PAPER/live promotion gates remain mandatory and unexercised.

## Current main reconciliation

The original recovery baseline was PR #44 at
`24dfcd60cda656d9b7b9ce0f6b581764b13dd8a4`. GitHub was reconciled through harness-only PRs #46-#58.
Current `main` is PR #58 at `acb4f971b584b0ba12d83d9e57c96c85c95da418`; its delta from the prior
SIG-02 base adds only execution-harness policy, hooks, telemetry, review-worktree tooling, benchmark/
canary configuration, required CI checks, state-compaction policy/tests, scoped-instruction discovery
and feature-watchlist guardrails. It does not change SIG-02 production contracts or the active Luna/Sol
production route.

PR #45 owns this state file. PR #56 deliberately did not compete for it and requires this owner-controlled
compaction. This snapshot replaces the prior 37 KiB chronology with durable references and stays below
the 12 KiB target in `AGENT_STATE_COMPACTION.md`.

## SIG-02 candidate

- original base: `24dfcd60cda656d9b7b9ce0f6b581764b13dd8a4`
- final integrated base main: `acb4f971b584b0ba12d83d9e57c96c85c95da418`
- latest product repair: `bc792afb9638e7a3a47997d1f97e397a44f38a3a`
  (tree `ade6eb617dc74ef64f228d970f710b445af02705`)
- latest main-integration commit before this compaction:
  `64649885c61a018c0a227bbfbbe01a63d446a373`
  (tree `c7cc27e812f7845a4f7f77c46d36d77a3c130e26`)
- final state-bearing head: authoritative in the PR ref/conversation because this commit cannot embed
  its own SHA
- PR: https://github.com/kejian-tong/myTradingAlpha/pull/45
- JIT: PR body; final amendments/comments `5572425609`, `5572923666`, `5573381099`, `5573635143`
- scope leak: none; the diff contains no Quant, overlay, envelope, backtest, portfolio, risk, OMS,
  broker, PAPER or live implementation

Implemented behavior is a pure sealed EvidenceBundle/cached-response-to-ResearchNote transformation:
domain-qualified typed references, exact bundle/reference integrity, defensive immutable access,
semantic-support separation, exact provenance/cutoff/artifact binding, deterministic bounded canonical
serialization, typed failures, hostile-data redaction and zero provider/network/graph fallback. SIG-01
sealed replay bytes, hashes, UTC cutoff/date semantics and callable/loader/provider denial remain intact.

## Routing and runtime evidence

- complexity: `high`; successive hostile-data confidentiality and bounded-work findings justified the
  difficult route `sol_high_sol_xhigh`
- original implementer: named `normal_implementer`, configured actual `gpt-5.6-luna / max`
- final repair implementer: named `high_implementer`, configured actual `gpt-5.6-sol / high`
- final reviewer: fresh named `reviewer_xhigh`, configured actual `gpt-5.6-sol / xhigh`
- Master: configured/requested `gpt-5.6-sol / xhigh`
- no separate backend model/effort telemetry was exposed; no historical route is relabeled
- GPT-6 remains disabled for production; `astra_canary` is optional shadow-only and cannot work on an
  active PR

The user approved a SIG-02-only runtime alternative in PR comment `5572425609`: correctly loaded named
roles may expose collaboration controls but must not invoke them; the Master remains the sole
orchestrator. Final writers/reviewers reported zero collaboration-tool calls. This exception changes no
configuration or route and expires immediately after SIG-02 post-merge verification.

Only one production writer ran at a time. One stalled writer was terminated before replacement; its
uncommitted test draft was preserved/corrected by the replacement and committed as a dedicated test-only
RED. No production writers overlapped.

## TDD and validation

Initial contract evidence:

- RED `8bca32021f03ecb1e9b34830277b8a6d2febdef6`: expected `12 failed, 55 passed`
- GREEN `28d09cf4bf92d030c3c649ebdc28a3be091ebe2d`

Latest material repair evidence:

- multiline RED `2330475f48b81087082cfec1801874c1b8231f39`: `4 failed, 95 deselected`;
  GREEN/refactor `bce1fd069c28a6aa8453a937ffc24023be07f3ff` /
  `0a842a327f373d2fa2dda0f3266d66b38f2de42c`
- confidentiality RED `d00d81b8ab473ebf33de3a28b291cb2df95c77be`: `14 failed, 104 passed`;
  GREEN `1d751c49795ff612487a6185c56ef2ac36012ca8`
- YAML/source-field RED `62b8cf26f341faf6d26465bedf7e0a0df39394d9`: `7 failed, 121 passed`;
  GREEN `2f3561c045bef70c7babd2349045e2e01060cda3`
- explicit-key work-bound RED `cf7218da99d6c29f1c3188185a51f22545e9adf5`:
  `1 failed, 129 passed`; GREEN `bc792afb9638e7a3a47997d1f97e397a44f38a3a`

All RED commits above are test-only and failed for the intended behavior. Complete superseded repair
chronology remains in the [pre-compaction snapshot](https://github.com/kejian-tong/myTradingAlpha/blob/1192df7031442c189d46e4365b39088d08d9ac51/docs/productionization/AGENT_STATE.md)
and PR #45 conversation.

Latest local validation after integrating PRs #55-#58:

- focused SIG-02: `130 passed`
- data/research regressions: `1120 passed`
- full suite: `2420 passed, 3 skipped, 18 warnings, 69 subtests passed`
- full Ruff, dependency direction, offline harness, lock consistency, Markdown contracts and diff
  check: PASS
- installed-package smoke: previously passed locally and must pass again in exact-head CI

The three skips are the supported Python-version/optional Bedrock/disabled real DeepSeek cases, not
passed integrations. Green software evidence does not prove source authenticity, real inference,
statistical alpha, PAPER readiness or live readiness.

## Review and merge gate

All prior BLOCKER/HIGH findings were repaired through dedicated RED/GREEN cycles. Key durable review
artifacts are PR comments `5566390797`, `5572900008`, `5573371521` and `5573628363`. The most recent
exact-head controlling/boundary approval before current-main integration is comment `5573958340` for
head `1192df7031442c189d46e4365b39088d08d9ac51`; CI `34147150048`, CodeQL `34147150001` and Dependency
Review `34147150107` passed there.

That approval/check evidence is stale after integrating PRs #55-#58 and the compacted state update. Required
next steps are:

1. freeze the new exact PR head/tree and verify current `main` is still `80fa2b9...`;
2. run exact-head Python 3.10-3.14, required harness/Ruff, Foundation, clean-install, CodeQL and
   Dependency Review checks;
3. obtain a fresh isolated controlling `reviewer_xhigh` APPROVE with all prior findings closed;
4. persist the Master MERGE gate and merge with expected-head protection;
5. read back merge parents/tree/time, wait for main-push CI/CodeQL, run proportionate final SIG-02
   verification and stop without starting SIG-03.

Current blocker: none in implementation; only the fresh exact-head evidence above remains pending.
