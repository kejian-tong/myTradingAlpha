# Productionization Agent State

Bounded snapshot, not a chronological log; GitHub/current `main` is authoritative. Immutable details: Git/PRs.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `3d9e049b2fa2c54b55ac66d1c3000480cd3254bd`
- `last_reconciled_main_tree`: `72b42554e30deb8f715a3cbaef3bc175537222b3`
- `bt04_roadmap_base_sha`: `7a863c0f04522c6b689a713170c47358e06c02f1`
- `bt04_roadmap_base_tree`: `667f01077881a863f5639b786869238d05955856`
- `roadmap_status`: active BT-05 candidate
- `current_pr_id`: BT-05 / PR #104
- `current_phase`: 03 — Backtest and Ledger
- `last_completed_roadmap_pr`: `BT-04` / PR #100 / merge `9f80cbdf7af9029bbe431acde66ef67b1b60a0ad`
- `autonomy_mode`: human-authorized BT-05 only; later slices require separate authorization
- `next_dependency`: BT-06 requires BT-05 merge, refreshed main, fresh Master and separate authorization
- SIG-04 validates caller-supplied candidates only; no inference
- SIG-05 adds only in-memory deterministic shadow envelopes
- SIG-05 authorizes no portfolio, risk, order, broker, PAPER/live, or promotion behavior

## BT-05 current recovery

- exact base/main and tree above; PR104 only; GitHub head overrides this snapshot.
- Hardest route `sol_xhigh_sol_xhigh`: `critical_implementer` / GPT-6.1 Sol / xhigh; fresh `reviewer_xhigh` / GPT-6.1 Sol / xhigh plus boundary review. Host attestation unavailable.
- Original RED `41d6801bd3854b9ee54d3bf8bb996e2e3b195463`; P1/P2/root/M1/performance/R1/R2 history: PR104. R1/R2 closed:6401678234/6402537952.
- JIT6405736903/6406302176; R3 RED `99c4fd8a5ef5dd32534c3565a4a5a22ce575f2aa`/6405904139:8fail/9controls. All285 old cases/PID fixture/20-second race unchanged; R3/R4 add9/7cases. Codec RED `8ba60ecae8287f00b9a9d0c3ed64dc80403ccf65`/6406469971.
- Uncommitted R3 attempt kept hashes/files/financial checks but cold22.02s failed20s; not accepted. Codec completion retains every admission/source/financial/publication guard; no deadline relaxation.
- Private per-call positive lexemes:256keys/32768UTF8bytes, genuine first/current-validator checks, fresh redaction; insert after both, evict failures, clear/reset finally. PID/thread copies stay cold; defaults unchanged; no global raw/decoded memo.
- Heavy pools64MiB/eight: benchmark16MiB/four, trace48MiB/four; no reducer restoration or omitted link/fsync; schemas/bytes unchanged. Explicit operation limits stay financially cold.
- Exact frozen-head validation, reviews and CI remain pending, including installed orders/manifest/replay bytes. Interrupted/failed/superseded runs are not passes. Lease/commit/review evidence: PR104; Master alone releases after stopped-writer observation and owns merge.
- Phase 03 gate: insufficient_evidence until all six separately merged slices; BT06 needs separate authorization. No PAPER/live operation; explicit human PAPER/live gates remain mandatory and unexercised.

## BT-04 completed recovery

- PR100 source `e774641c1a4a4052bc8fdf40261c7ed37654335a`, merge `9f80cbdf7af9029bbe431acde66ef67b1b60a0ad`; APPROVE6380274387, Master gate6380292548, completion6380324398. Closed RED, rejected-candidate, repair, lease and validation history remains durable in PR100.
- Original roadmap base/tree retained above. Difficult route `sol_high_sol_xhigh`: `high_implementer` / GPT-6.1 Sol / xhigh; `reviewer_xhigh` / GPT-6.1 Sol / xhigh. Master/boundary Sol/xhigh; attestation unavailable.
- Scope: offline actions and independent Cash/B&H; additive ledger/accounting.

## BT-03 completed recovery

- PR99 merge/base above; source `7b4df459cd655e8d7d708e28534e5562b6b76c29`, identical tree above. Final RED `6ff2f9c6ae008bb7363f542b8d20a67ab21adc12`.
- Initial `luna_sol_xhigh` normal_implementer/GPT-6 Luna/max; final difficult `sol_high_sol_xhigh` high_implementer/reviewer_xhigh GPT-6.1 Sol/xhigh. Scope: internal ledger/NAV/accounting only.
- Durable PR99 comments: JIT6094290872, RED6098196615, GREEN/released lease6098830935, material CLOSED6099033623, APPROVE6099410594, Master MERGE6099435193. Writer/reviewer4801passed/4skipped; nine source contexts+Foundation passed.
- Main CI38066050888/CodeQL38066050887 passed; scheduled CodeQL38287873542 also succeeded at the same SHA. PIT05 PR22 and BT01/02 ancestry verified at BT04 preflight.


## BT-02 completed recovery

- [PR #97](https://github.com/kejian-tong/myTradingAlpha/pull/97). Base/main: `a713fbb48324ad9da45e254268b9cfe30b0a634b`. Merge `7b818c3f78916375ef80d1a5c65d24a95b5423d5`; source `60878adab64c138ccad5cf571a648e6cd909b3d9`; identical tree `d89d1321aa62864ba7a2362a3794259831435ae7`.
- Critical implementation escalation route `sol_high_sol_xhigh`: `high_implementer` / GPT-6.1 Sol / xhigh; controlling `reviewer_xhigh` / GPT-6.1 Sol / xhigh. Initial route `luna_sol_xhigh`, `normal_implementer` / GPT-6 Luna / max remains historical.
- Scope: shared simulation-only intent/fill contracts, internal deterministic order/fill simulator and stable cost facade.
- H1-H5/M1/M2/schema closed; PR97 durable comments: APPROVE6092025678, closure6092025513, Master6092102850, leases6091815683, postmerge6092297315. RED/JIT/floor/CI detail remains immutable in PR97; merged tree/ancestry/checks verified at BT03 preflight.

## BT-01 completed recovery

- PR: [#96](https://github.com/kejian-tong/myTradingAlpha/pull/96); merge/main `a713fbb48324ad9da45e254268b9cfe30b0a634b`, reviewed source `0b3eee8a98f365c3c3b55c35cd584db617c4d3ff`, identical tree `9fc6e587ca34a297d3183288763f91a933ae054c`. Original Base/main: `2cfc175fe5d07190c740821da5bb20e13877d252`; original RED `5881288a839915e92edb8eca6aefbcdffc995949`; final H3 RED `02805808a8e530f189f557f2bf27e710b4e6b41e`.
- Scope: witnessed immutable session binding, deterministic decision/opportunity events and pure runner only. No quantity, intent, fill, cost, ledger, action, persistence or metric behavior.
- Final high implementation escalation route `sol_high_sol_high`: `high_implementer` / GPT-6.1 Sol / xhigh; controlling `reviewer_high` / GPT-6.1 Sol / xhigh. Initial route `luna_sol_high`: `normal_implementer` / GPT-6 Luna / max remains historical. Independent runtime telemetry is unavailable; observed host unrestricted, no authenticated isolation claimed.
- Durable PR96 comments: APPROVE6077723821, material6077677736, Master6077744423, leases6077509103, postmerge6077864574. All eight HIGH groups and M0 closed; exact repair/JIT/RED history remains immutable in Git/PR #96.

- PR96 validation detail remains in its durable artifacts; main CI `37908220659` and CodeQL `37908220735` passed.

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

- `harness_reconciled_through`: PR #103 / merge `3d9e049b2fa2c54b55ac66d1c3000480cd3254bd`
- `active_harness_pr`: none
- PR #103 source `c2d5e38c793430f27a136f78cb3d8bdcacf0e22a`; six disjoint pstack files.
- PR #101 merged bounded pstack 0.15.25 at `7a98e9eb689ed4a44c23e9ccf1c1c04e0a9c0911`; PR #102 refreshed provenance at `28dcae6ceea84b04df405ea25e77e408d2d88b27`. Current skills are authoritative prospectively; prior route/RED/review evidence remains immutable.
- [PR #98](https://github.com/kejian-tong/myTradingAlpha/pull/98) raised lease archive64 to6400, preserving all evidence. Source `2f1a0644f328a8a0bfb89c95bb5f91776b977be2`, merge tree `d7b159ae4eb6d1caf2632014fc37006b00e4a5de`. Durable TDD/CI/APPROVE/Master gate/postmerge facts remain in PR98. Human-authorized unleased test-only RED applied solely to this prerequisite; GREEN used a genuine old-helper lease. Merge `e0025b3990334d48664a4caf3bef6839421ef586`.
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

- Permission profile disabled/unrestricted. Missing host-origin sandbox/approval/tool-inventory facts are supplemental disclosure, not a review block (PR86).
- Separate controlling review: detached exact-head worktree, before/after SHA/cleanliness. Mutation, stale/dirty isolation, missing roles, BLOCKER/HIGH or required-CI failure blocks.
- Hook load/trust unknown, ineffective without a host report. Runtime receipt, offline verifier and config do not authenticate host/model/isolation.
- Cooperative writer leases do not defend against same-user processes.
- Apps and Memories disabled; Rules/Permission Profiles/OTel/repo Plugins watch-only.
- External-spec Docs MCP: configuration intent until observed.

Root policy owns external-agent prohibitions, safety, review/CI and merges. This state is operational memory.
