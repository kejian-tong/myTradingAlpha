# Productionization Agent State

This is the bounded operational recovery snapshot, not a chronological log. GitHub/current `main` is authoritative;
immutable detail remains in commits, pull requests, and workflow runs.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `2cfc175fe5d07190c740821da5bb20e13877d252`
- `last_reconciled_main_tree`: `5ce0ebd88ac1f08e9b4a80238fb87ced0014bb81`
- `roadmap_status`: active BT-01 candidate; SIG-05 / PR #92 merged; BT-02 through BT-06 await dependency gates
- `current_pr_id`: BT-01 / PR #96
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: `SIG-05` / PR #92 / merge
  `d709f16b37e40837c4ee687a6bc03ab92ea55218`
- `autonomy_mode`: human-authorized BT-01 through BT-06 in six independent dependency-ordered PRs and fresh Master sessions; this session owns BT-01 only
- `merge`: PR #92 merged at `d709f16b37e40837c4ee687a6bc03ab92ea55218`; implementation, review,
  and CI records remain in its GitHub conversation
- `next_dependency`: BT-02 is authorized but blocked until BT-01 merges, main is verified, and a fresh Master session starts
- SIG-04 validates caller-supplied candidates only; no inference
- SIG-05 adds only in-memory deterministic shadow envelopes; later roadmap work remains deferred
- SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior; explicit human PAPER/live gates remain mandatory and unexercised

## BT-01 current recovery

- PR: [#96](https://github.com/kejian-tong/myTradingAlpha/pull/96); [exact JIT](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6074014835) and [preflight matrix](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6074015076) are durable in that conversation.
- Base/main: `2cfc175fe5d07190c740821da5bb20e13877d252`; tests-only RED: `5881288a839915e92edb8eca6aefbcdffc995949`.
- Scope: witnessed immutable session binding, deterministic decision/opportunity events and pure runner only. No quantity, intent, fill, cost, ledger, action, persistence or metric behavior.
- Complexity: high; repair route `sol_high_sol_high`; requested/configured repair writer `high_implementer` / GPT-6.1 Sol / xhigh; controlling reviewer `reviewer_high` / GPT-6.1 Sol / xhigh; Master GPT-6.1 Sol / xhigh. Initial `normal_implementer` / GPT-6 Luna / max route `luna_sol_high` remains historical. Escalation follows actual cached-seal, metadata, archive-enum and continuity defects; independent runtime model telemetry unavailable.
- Cooperative writer leases: RED `dbec4adebaf32d786f9d62f8b5e139f1bf33831fc91b00015be2f68c0add6bf2` (released; digest `7b7a6161d46f36129b4314225cbb8ba729f0fc7cd95565a5090477ff6712cee3`); GREEN `ec61f6a55e776593bf8adc50f1dd9497e225f2825ca7727ce890c0fa1ead6118`; dedicated branch `refs/heads/codex/bt-01-clock-events`; canonical identity/lifecycle evidence is bound to the PR conversation.
- Incomplete source checkpoint: `d02bf389c9bad85912a819b966a63efce97e6e47`; its two fixture setup failures and four HIGH defects require bounded repair. [Repair JIT](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6074666364), [independent repair matrix](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6074666541), repair RED `8f776af174a0e7c064705ff8f92eee36f697c1f3`, and actual closure evidence are durable in the PR. Candidate final SHA, actual local validation, lease release/export, exact-head review, CI, Master gate and merge SHA are recorded in the PR conversation as they become available. This snapshot records no BT merge or completed gate prematurely.
- Repair leases: RED `99367a91965ba01d690a8a76b7a52584aafc34bf0a76fb9433da3ec90db3ddd0` (released; digest `8b888e2d3df94e6246d92910d1cf889b72ce2d817ea0ab5f8010d1c2132070cb`); GREEN `5ded33635e9269c5ab274f6c545afccf3f9fde77a6ba119e6a062834890e5fc1`. Serialized high_implementer contexts; exact identity/lifecycle and final closure references are in the PR.
- Pure-refresh closure: additional RED `c408bcfcc407f498b5efed38fd37e1994d72c335`; [architecture amendment](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6075006446). Supplementary RED lease `8469f73433816dc52db8f2800edd8f4ea510efbd6d4ece8ead6ffe3f6b541031` released (digest `31245aec65b2abf87bd75eb2be3317d6211f3b711a6776f8b3db0c80c916a9a0`); final GREEN `8cb289f44c2044fa0fb4484167e610c4e0c92da2decf7158090d5e8fdb6c9d6d`. Prior uncommitted GREEN lease released with valid start/green/release evidence; no overlap.
- Final review H1 repair: [controlling finding](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6075433036), [bounded JIT](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6075535961), and [preflight](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6075536185). H1 RED `fd8b5ac9ac6724e313d9fab9551f7ff23e2dbe7d`; released RED lease `c0ef75a695cddd680b8aa54e6d0130ee26d53b79c14bac2cbe4a7946fdb51bf5` (digest `874c07d5ce5e4799bac83d67d1c88595392b183f8ea578620fb7fb56bde95b99`); GREEN `25c9bdbb6c9577b44c5f0fa32fb655c887bb663ff8be2ac84723c833255a9e02`. New exact-head review/CI/gate supersede the c532 candidate evidence.
- Pstack: how traced sealed source ownership; architect/principles-design/arena chose private defensive snapshots; interrogate incorporated hostile-type, archive-policy and duplicate/overflow cases; TDD and principles-verification require observable fixtures and exact-head checks.
- Phase 03 gate: insufficient_evidence until all six separately merged slices and BT-06 integrated goldens pass. No PAPER/live operation, Phase 04, release, validated-alpha or promotion authorization.

## Phase 03 documentation recovery

PR #95 [documentation reconciliation](https://github.com/kejian-tong/myTradingAlpha/pull/95) merged at
`2cfc175fe5d07190c740821da5bb20e13877d252`; reviewed source `bf7eedbd76ef3b011e5c8edd7422c8ae640f8609`,
tree `5ce0ebd88ac1f08e9b4a80238fb87ced0014bb81`. Controlling review issuecomment-6073548400,
Master gate issuecomment-6073562231, postmerge verification issuecomment-6073618228. Main CI
`37878690925`: PASS; CodeQL `37878690779`: PASS, independently rechecked at BT-01 preflight.

## SIG-03 recovery reference

PR #87 merged at `6de1635a90d6c33aee02079dca5d0932e3a32cec`; its original JIT base was
`49d5980b640638ed687b6c7771f5f28367072c9a`. Its complete RED/GREEN, review, CI, and repair history
remains recoverable in PR #87. SIG-03 owns deterministic `QuantSignal` only; it adds no portfolio,
risk, order, broker, PAPER/live, credential, deployment, or promotion behavior.

## SIG-02 recovery reference

PR #45 implemented the deterministic Evidence tools and `ResearchNote` boundary over sealed evidence.
The final reviewed source head was `de51698180ff6873c7512c70828add3c55728fb9`; its source tree was
`ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`. The merge commit was
`376c9c044722ee37f3fa36691b576420e3b6253d` with resulting tree
`ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`. No provider, network, ordinary-graph fallback, broker,
PAPER/live, or promotion behavior was introduced.

## Current harness policy

- `harness_reconciled_through`: PR #94 / merge `afa7c35b9f8a71170d6a9d14b051d2e83f54fc0f`
- `active_harness_pr`: none
- PR #90 merge `8f76f341bedf086dd4eb69e4229be33127f5028f` completed bounded pstack compatibility replay and preserves PR #88 model routing, PR #86
  read-only review assurance, and all PAPER/live gates.
- PR #88's policy merge `a42ce7a654994d8071824c3aaba4c9e5503a7e9d` remains recoverable in the
  completed Harness sequence below.
- PR #90's RED/GREEN, writer lease, exact-head review, and required-check evidence remain in its PR conversation.
- PR #91's JIT and lease lifecycle remain recoverable in its PR conversation; PR #92 subsequently completed SIG-05.
- PR #92's JIT, RED evidence, writer lease lifecycle, review, and CI remain recoverable in its GitHub
  conversation; it merged at `d709f16b37e40837c4ee687a6bc03ab92ea55218`.
- PR #86's read-only review-assurance policy remains active.
- PR #94 refreshed Master/Sol routes to GPT-6.1 Sol/xhigh and the concurrent spawned-thread guardrail to eight; merge `afa7c35b9f8a71170d6a9d14b051d2e83f54fc0f`. Historical route evidence remains unchanged.

The completed Harness sequence is summarized by theme: #74–#77 covered state reconciliation, benchmark
integrity, network-denial proof, and safe review worktrees; #78–#81 covered degraded assurance, writer-lane
identity, hook manifests, and advisory stop diagnostics; #82–#84 covered Foundation CI deduplication,
runtime-neutral collaboration terminology, and instruction ownership/compaction; #85 completed final state
closeout.

| Harness PR | Exact merge SHA |
| --- | --- |
| PR #74 | `9177e984c533aa26177fe368190d6e3142342760` |
| PR #75 | `436545cfe8a2b4785f5ef81eb6476f4a2477658c` |
| PR #76 | `9a717c85d293256adaa0ccbc6cf8ce84305253a4` |
| PR #77 | `3e43b2f3c75471573fb969ff07550603c679d0e8` |
| PR #78 | `502378aa34c98db8892e0b789608f919589cdeb4` |
| PR #79 | `e138e63823a3c477cbac976ef9a25c1d867c70d6` |
| PR #80 | `c2eb5d2e9e2defb06ba009d0d0d0f42cea8b2467` |
| PR #81 | `0b204cc276de8a4d95f43c8da59415244f9944e0` |
| PR #82 | `ab775c3d3d75e3a8f30c455f35c1d33fd782b389` |
| PR #83 | `f9b6eb12425ef2e5c8933b75ba327adabd7f76af` |
| PR #84 | `14cb132a92f9177f0f22492a4708a6ed8880918a` |
| PR #85 | `93b812e654773aa1ddafe26879fae7fec0a8e4b7` |

- Former automatic-review ruleset `23141241`: observed disabled on 2026-09-19; main-protection required contexts
  remain authoritative.
- Post-#86 main-push CI `35486435734`: PASS; CodeQL `35486435740`: PASS.
- Historical post-SIG-02 checks: CI `35473160937`: PASS; CodeQL `35473160983`: PASS.

## Runtime limitations and watch-only features

- The host permission profile is disabled/unrestricted. Under the PR #86 policy, missing
  host-origin sandbox/approval/tool-inventory facts are supplemental disclosure and do not themselves block
  review.
- A separate controlling review context remains mandatory and uses a detached exact-head worktree with
  before/after SHA and cleanliness evidence; observed mutation, stale/dirty isolation, missing required
  roles, BLOCKER/HIGH findings, and required-CI failures remain blocking.
- Hook load/trust state is unknown and ineffective absent a host report.
- Runtime receipt, offline verifier, and checked-in config do not authenticate host/model/isolation.
- The writer lease is cooperative structural evidence and does not defend against same-user processes.
- Apps and Memories remain disabled by intent. Rules, Permission Profiles, OTel, and repo Plugins remain
  watch-only.
- External-spec official Docs MCP remains configuration intent unless observed at runtime.

The root instructions own the permanent external-agent prohibition. This state records operational facts only
and does not replace the root policy, audit protocol, required CI, exact-head review, or Master merge gate.
