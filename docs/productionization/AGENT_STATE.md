# Productionization Agent State

This is the bounded operational recovery snapshot, not a chronological log. GitHub/current `main` is authoritative;
immutable detail remains in commits, pull requests, and workflow runs.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `a713fbb48324ad9da45e254268b9cfe30b0a634b`
- `last_reconciled_main_tree`: `9fc6e587ca34a297d3183288763f91a933ae054c`
- `roadmap_status`: active BT-02 candidate; BT-01 / PR #96 merged; BT-03 through BT-06 await dependency gates
- `current_pr_id`: BT-02 / PR #97
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: `BT-01` / PR #96 / merge
  `a713fbb48324ad9da45e254268b9cfe30b0a634b`
- `autonomy_mode`: human-authorized BT-01 through BT-06 in six independent dependency-ordered PRs and fresh Master sessions; this session owns BT-02 only
- `merge`: PR #96 merged at `a713fbb48324ad9da45e254268b9cfe30b0a634b`; implementation, review,
  and CI records remain in its GitHub conversation
- `next_dependency`: BT-03 is authorized but blocked until BT-02 merges, main is verified, and a fresh Master session starts
- SIG-04 validates caller-supplied candidates only; no inference
- SIG-05 adds only in-memory deterministic shadow envelopes; later roadmap work remains deferred
- SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior; explicit human PAPER/live gates remain mandatory and unexercised

## BT-02 current recovery

- PR: [#97](https://github.com/kejian-tong/myTradingAlpha/pull/97); exact-base [JIT](https://github.com/kejian-tong/myTradingAlpha/pull/97#issuecomment-6078584355). Base/main: `a713fbb48324ad9da45e254268b9cfe30b0a634b`. Dedicated RED `00d4418afde9ad31900d76926e817235ab77992d`; current candidate/review/CI/lease evidence is recorded in the PR conversation as available; no future merge or approval is claimed here.
- Complexity critical; implementation escalation route `sol_high_sol_xhigh`: `high_implementer` / GPT-6.1 Sol / xhigh and controlling `reviewer_xhigh` / GPT-6.1 Sol / xhigh. Initial route `luna_sol_xhigh`, `normal_implementer` / GPT-6 Luna / max remains historical. Master same configured Sol/xhigh; runtime telemetry/isolation attestation unavailable.
- Scope: shared simulation-only intent/fill contracts, internal deterministic order/fill simulator and stable cost facade, plus this normal-branch state reconciliation and narrow operational-test migrations. Precommitted fixture intents, witnessed next-session final close, later receipt, adverse spread/slippage, cumulative USD fees and fixed-share cap/lot/TIF only. No ledger, NAV, actions, persistence, RSK allocation, OMS, broker or later-slice behavior.
- Writer lane: `refs/heads/codex/bt-02-fills-costs`; derived lane `de0c924e2a3882ee1ec48329eecfdf79f5e50b391a26e4f159aefc59d48d3f57`. Separate RED/GREEN leases acquired by Master from trusted main; monotonically ordered checkpoints and host-stopped observation precede release/export. Canonical artifacts and actual validation belong to the PR conversation. Cooperative evidence is not runtime authentication.
- H5 repair parent `c33bec3614087d2cf9baf56ef3f95ecd757b2346`; RED `fac3218821e0a7148432d2ba8aa6b7ce6e9e875a`. Parent controlling/material `6091388117` / `6091388325`; scope/preflight `6091428485` / `6091428664`; diagnostic clarification `6091524595`, all in PR #97. H1-H4/M1/M2/schema diagnostics closed at the parent; H5 needs fresh exact-head closure. Prior repair/JIT/RED and lifecycle evidence remains immutable in Git/PR #97. Final validation/review/CI/Master gate are pending; no approval claimed.
- Phase 03 gate: insufficient_evidence until all six separately merged slices and BT-06 integrated goldens pass. No PAPER/live operation, Phase 04, release, validated-alpha or promotion authorization; explicit human PAPER/live gates remain mandatory and unexercised.

## BT-01 completed recovery

- PR: [#96](https://github.com/kejian-tong/myTradingAlpha/pull/96); merge/main `a713fbb48324ad9da45e254268b9cfe30b0a634b`, reviewed source `0b3eee8a98f365c3c3b55c35cd584db617c4d3ff`, identical tree `9fc6e587ca34a297d3183288763f91a933ae054c`. Original Base/main: `2cfc175fe5d07190c740821da5bb20e13877d252`; original RED `5881288a839915e92edb8eca6aefbcdffc995949`; final H3 RED `02805808a8e530f189f557f2bf27e710b4e6b41e`.
- Scope: witnessed immutable session binding, deterministic decision/opportunity events and pure runner only. No quantity, intent, fill, cost, ledger, action, persistence or metric behavior.
- Final high implementation escalation route `sol_high_sol_high`: `high_implementer` / GPT-6.1 Sol / xhigh; controlling `reviewer_high` / GPT-6.1 Sol / xhigh. Initial route `luna_sol_high`: `normal_implementer` / GPT-6 Luna / max remains historical. Independent runtime telemetry is unavailable; observed host unrestricted, no authenticated isolation claimed.
- Durable [controlling APPROVE](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6077723821), [material closure](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6077677736), [Master MERGE gate](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6077744423), [sixteen closed writer lifecycles](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6077509103), and [postmerge verification](https://github.com/kejian-tong/myTradingAlpha/pull/96#issuecomment-6077864574). All eight HIGH groups and M0 closed. Exact repair/JIT/RED history remains immutable in Git/PR #96.
- Final independent validation: 85 clock, 22 state/package, 1817 PIT/SIG/research, 3206 productionization with two skips, 3782 full with four skips/18 warnings/69 subtests. Ruff, four validators, diff, network canary and rebuilt noneditable 18+3 installed origins/exact source passed; skips are not passes.
- All nine app-15368 source contexts passed at the reviewed source: CI `37906143567`, CodeQL `37906143593`, Dependency Review `37906143519`. Exact merge main CI `37908220659` and CodeQL `37908220735` passed all eight applicable main-push contexts plus Foundation contract/docs/lock. Merge tree matches reviewed tree and SIG-05 prerequisite remains an ancestor, independently reverified at BT-02 preflight.
- Preserved ownership/purity boundary: exact typed captured graphs, bounded 65-entry metadata/raw snapshots, early witness denial and owned bundle/calendar/witness guard before inherited validation; pure getters/reducer do not revalidate through environment-dependent PIT paths. Actual canonical source bytes/fingerprints and retained ingress/completion checks remain required. BT-02 consumes these unchanged guarantees.
- Cleanup completed per durable postmerge evidence; immutable writer/review recovery remains in PR96. Repository-global lease capacity64 fails closed; inspect before every acquisition, preserve evidence and never bypass policy.

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
