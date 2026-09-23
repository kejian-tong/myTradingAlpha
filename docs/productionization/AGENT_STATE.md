# Productionization Agent State

This is the bounded operational recovery snapshot, not a chronological log. GitHub/current `main` is authoritative;
immutable detail remains in commits, pull requests, and workflow runs.

## Current control state

- `schema_version`: 2
- `last_reconciled_main_sha`: `49d5980b640638ed687b6c7771f5f28367072c9a`
- `last_reconciled_main_tree`: `3b3a70802603d4cd717c62e5c46089319c5ffa0f`
- `roadmap_status`: `sig_03_green_pending_review`
- `current_pr_id`: `SIG-03` / PR #87
- `current_phase`: Phase 02 — Evidence and Agent Boundary
- `last_completed_roadmap_pr`: `SIG-02` / PR #45 / merge
  `376c9c044722ee37f3fa36691b576420e3b6253d`
- `autonomy_mode`: enabled only for authorized SIG-03 implementation
- `active_writer`: none
- `last_writer_route`: `high_implementer`
- `merge`: pending independent exact-head review, required CI, and Master gate

SIG-03 is the only active roadmap slice. Base is `49d5980b640638ed687b6c7771f5f28367072c9a`; the JIT
contract is persisted in PR #87. RED commits are `03c29a17c9517766fbdaaf2636cd5b172c5b359a`,
`01957a598e46ff264552b764393ea8adba050149`, `367dfd3da3bd289c1d7c87d4a03c5f4011ef3a2c`,
`161ce9c9659f5129953f28563e1a5e3e712ad8d8`, `b0d18f6dc206b09d109f8b2a2a97bf33b91c403a`,
`7c299aca51177d2cfeb6f9b783c40d8e5e56ab2a`, `ef531bcb2fae13d7e6aa86ed10fc1ab8a19e2488`,
`b71ffa0ad3b3b1cee7d72a50e11c416ddc78d524`, `201a9fa3375b5bf8421fc59e028db928508eefc5`,
`0d674c230f208ec5eb8c1dda1a8e984a5969daf0`, and `c3e15354a19bc9a2dec84a458df62d7c2cd6669b`.
Round-one controlling review on `649d7615f72a8a6712083266043741d260c6b98e` returned REQUEST CHANGES.
The first repair RED is `077997894df8ccd6d01f431fb5bedb6816a6c8a7`; Round-two controlling review
returned REQUEST CHANGES. Its focused RED is `3b8a6a0f38932defed36825b2ccafc30c1ff1af3`; the second-cycle
GREEN head is `d0d325dd3b401dda7b0f720443775b81eeb9bf6a`. Round-three controlling review returned REQUEST
CHANGES on that head. The Round-three repair RED is `5d6a2c6d74cb6a1af604941725491ab49335bb53`;
the consolidated Round-three GREEN head is `6d5e1628bae41c65c979cd855f968ebcc864ade8`. Round-four
controlling review returned REQUEST CHANGES on that head. The Round-four repair RED is
`d6f37bd36bf8192d5f6de4d68c3a61ec7d35a24a`; the Round-four final semantic GREEN is implemented with
head `0f48225c2fc7f3f96197cf0d2082c5826aa9dea6`. Round-five controlling review returned REQUEST
CHANGES on that head. The Round-five architectural RED is `7dc44cda4f91663690446a0281199470a9e701a1`;
the architectural GREEN head is `9122f99c20d783691084139891bd8d3b07d5626e`. Round-six controlling
review returned REQUEST CHANGES on that head. The Round-six final-contract RED is
`62fb66468c2d73faf731e0860e2842ceaf3e8684`; the final-contract GREEN head is
`6b9673011f5f04c11a39169bfe75ea632ac91d3f`. Round-seven controlling review returned REQUEST CHANGES
on that head. Round-seven RED evidence is `9db53e8c79cb040f946f9c2a915061db401fd8c0`,
`10f622a8642ee12082beb946674dc930b6aa95ef`, and `da115b0432ac6790c996dfe547c74b9607b49287`;
the tests-only safe-label compatibility guard is `3d62828c9587508de83f641e9fcbedc91fac315f`.
Round-seven GREEN was produced and durable lease release is recorded in PR evidence. Round-eight repair started from candidate
`95ca3698ebc014860fb82bd450f8792f3d7a6703`; its tests-only commits are
`f8ff012c2b6425fac086dac2df5b900ec1d07c5a`, `de40e2ea920848bef83364b333e22cdae4379822`,
and `ff3a5fa7429aa6b5b6ecb25126c57d78d2c976f3`. Round-eight GREEN was produced and durable lease
release is recorded in PR evidence. Round-nine repair started from candidate
`78db7ced724d85a8e8dc9867388526285df2e009`; its tests-only RED is
`a5e4b7820357c19f0bcb25b06c26791bb40f06c3`. The bounded GREEN candidate was produced and durable
lease release is recorded in PR evidence. Round-ten repair started from candidate
`e2bbdb4dc9f4fba89bee0b23368d760a7d9a9d57`; its tests-only RED is
`c7687d570d5be5cda3dec018bdb441752f4bd79e`; its tests-only measurement guard is
`7fc83c4e460342e68820519534b79c97aa165397`. The bounded GREEN candidate was produced; durable lease
release is recorded in PR evidence. Independent review, required CI, and merge
remain pending. Round-eleven repair started from candidate
`2962fa991bd7a68fb86234c7ce8f53b4bb79fdad`; its tests-only RED is
`9c974ac81599948d0f1335b4a066590cc1ff2b51`; supplemental hash-cap RED evidence is
`159d4684b68e66728bc48bcc275ddbc2a3bcb751` and
`5e84436e09c1c7c83b22d08f9f4c4495b5f3b67d`. The bounded request-context and defensive-hash GREEN
candidate was produced, including intrinsic public-hash and defensive-copy collection caps; durable
Round-eleven lease release is recorded in PR evidence. Round-twelve repair started from candidate
`ae5fe31237d4595368889a79417d3802ead22121`; its tests-only RED is
`3f42e26438b1945a9a0c75a0528ece3aac1f9ad1` and its contiguous golden baseline is
`a4f463902474f94cd9ac394003e3dce1f2d878c0`. The bounded caller-context isolation and
verified-calendar continuity GREEN candidate was produced; durable Round-twelve lease release is
recorded in PR evidence. Round-thirteen repair started from candidate
`69692b488dfc6254a0b9107635b5eb83b7485f1d`; its tests-only RED is
`791ece8993b7e13dc779b441f9c5aa048fd5605e`. The bounded caller-context work isolation,
pre-materialization cardinality, and FeatureSet reason-semantics GREEN candidate was produced; durable
Round-thirteen lease release is recorded in PR evidence. Round-fourteen repair started from candidate
`1cd6edd141f4c35f47d3c24d3a39009b0a6922be`; its tests-only RED is
`61248a21924ff3ff48f2f3eb33b3373ffb28f7a4`. The bounded nested-model storage, saturating Decimal
arithmetic, and bundle-text bounds GREEN candidate was produced; durable Round-fourteen lease release
is recorded in PR evidence. Round-fifteen repair started from candidate
`a7a7b6a1c70d079d9867817df6c3ccbdf21a61d1`; its tests-only RED is
`367ed11e5d5924b8eb8494eccd51775921e7953f`. The bounded bundle Decimal exponent and
arithmetic-exception GREEN candidate was produced; durable Round-fifteen lease release will be recorded
in PR evidence before fresh review.
No SIG-04 or later roadmap implementation, portfolio/risk/order/broker/PAPER/live
action, credential, deployment, or
promotion action is authorized. Explicit human PAPER/live promotion gates remain mandatory and unexercised.

## SIG-02 recovery reference

PR #45 implemented the deterministic Evidence tools and `ResearchNote` boundary over sealed evidence.
The final reviewed source head was `de51698180ff6873c7512c70828add3c55728fb9`; its source tree was
`ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`. The merge commit was
`376c9c044722ee37f3fa36691b576420e3b6253d` with resulting tree
`ef87b5e4c5b9778bbbcdde74d6db5b53b802865c`. No provider, network, ordinary-graph fallback, broker,
PAPER/live, or promotion behavior was introduced.

## Current harness policy

- `harness_reconciled_through`: `HARNESS-AUD-21` / PR #86 / merge
  `49d5980b640638ed687b6c7771f5f28367072c9a`
- `active_harness_pr`: none; HARNESS-AUD-21 / PR #86 merged as the verified base
  `49d5980b640638ed687b6c7771f5f28367072c9a`. Its read-only review-assurance policy is active.

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
